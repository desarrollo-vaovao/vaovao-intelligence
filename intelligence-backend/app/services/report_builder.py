"""
report_builder — une las piezas del motor de reportes.

Toma un activo comercial de la base y un rango de fechas; pide los datos a
Meta (meta_api) y los arma en la estructura que espera pdf_generator. Es el
"pegamento" entre traer datos y dibujarlos.

Un reporte es siempre de UN activo comercial: los activos de un mismo cliente
pueden ser marcas sin relación entre sí, y mezclarlas en un PDF no sirve.
"""
import logging
from datetime import date

from app.models import AdAccount
from app.schemas import ATTRIBUTION_WINDOWS
from app.services import meta_api, pdf_generator, perf

log = logging.getLogger(__name__)

_MESES = ["ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]

CURRENCY_SYMBOLS = {"USD": "$", "GTQ": "Q"}

# Respaldo cuando la organización todavía no configuró su propio tipo de
# cambio (Ajustes > General). Aproximado, NO una tasa oficial — existe
# solo para que un reporte no falle por faltar ese dato; en cuanto el
# owner/admin lo configure, ese valor gana siempre.
DEFAULT_EXCHANGE_RATE_USD_GTQ = 7.75

# Campos monetarios dentro de un dict "insights" de Meta (campaña o
# anuncio). El resto de insights (impresiones, clics, alcance, CTR,
# conversaciones...) NO son dinero y no se tocan.
_MONEY_FIELDS_INSIGHTS = ("spend", "cpm", "cpc")


def _exchange_factor(source_currency: str, target_currency: str, rate: float) -> float | None:
    """Factor por el que multiplicar un monto en `source_currency` para
    obtenerlo en `target_currency`. None si el par no se sabe convertir
    (hoy solo se soporta USD<->GTQ; cualquier otra moneda de origen se
    deja tal cual en vez de arriesgar una conversión incorrecta)."""
    if source_currency == target_currency:
        return 1.0
    if source_currency == "USD" and target_currency == "GTQ":
        return rate
    if source_currency == "GTQ" and target_currency == "USD":
        return 1.0 / rate
    return None


def _convert_money(campaigns: list[dict], total_spend: float, factor: float) -> tuple[list[dict], float]:
    """Aplica `factor` a todo monto en dólares/quetzales dentro de
    `campaigns` (spend a nivel de campaña, y spend/cpm/cpc dentro de cada
    `insights`, tanto de la campaña como de cada anuncio) y a `total_spend`.

    NO toca `budget`: ese lo escribe la persona directamente en la moneda
    que ya tiene seleccionada en el formulario, así que convertirlo de
    nuevo lo dejaría mal (doble conversión).
    """
    def convert_insights(ins: dict | None) -> dict | None:
        if not ins:
            return ins
        out = dict(ins)
        for field in _MONEY_FIELDS_INSIGHTS:
            value = out.get(field)
            if value is not None:
                try:
                    out[field] = float(value) * factor
                except (TypeError, ValueError):
                    pass
        return out

    def convert_entry(entry: dict) -> dict:
        # OJO: pdf_generator lee insights con `entry.get("insights", {})`,
        # y ese default solo aplica si la CLAVE falta — si aquí se le
        # asignara `None` a una campaña/anuncio que nunca tuvo insights,
        # ese `.get(..., {})` devolvería None igual (la clave ya existe) y
        # reventaría con AttributeError más abajo. Por eso la clave se
        # toca únicamente cuando ya existía en el original.
        out = dict(entry)
        if "insights" in out:
            out["insights"] = convert_insights(out["insights"])
        return out

    converted = []
    for campaign in campaigns:
        c = convert_entry(campaign)
        if c.get("spend") is not None:
            c["spend"] = float(c["spend"]) * factor
        if "ads" in c:
            c["ads"] = [convert_entry(ad) for ad in (c["ads"] or [])]
        converted.append(c)

    return converted, total_spend * factor


def _aggregate_platform_breakdown(rows: list[dict], country_code: str | None) -> list[dict]:
    """
    Junta las filas plataforma×país que devuelve Meta (ver
    meta_api.get_platform_breakdown) en una lista de plataformas con sus
    totales, filtrando por país si el reporte tiene ese filtro activo.

    Plataformas sin gasto en el período no aparecen — no tiene sentido
    mostrar una fila en cero en un resumen que es, precisamente, sobre en
    qué se fue el gasto.
    """
    totals: dict[str, dict] = {}
    for row in rows:
        platform = row.get("publisher_platform")
        if platform not in meta_api.PLATFORM_LABELS:
            continue
        if country_code and row.get("country") != country_code:
            continue
        bucket = totals.setdefault(platform, {"spend": 0.0, "impressions": 0, "reach": 0, "clicks": 0})
        bucket["spend"] += float(row.get("spend") or 0)
        bucket["impressions"] += int(float(row.get("impressions") or 0))
        bucket["reach"] += int(float(row.get("reach") or 0))
        bucket["clicks"] += int(float(row.get("clicks") or 0))

    return [
        {"platform": platform, "label": meta_api.PLATFORM_LABELS[platform], **values}
        for platform, values in sorted(totals.items(), key=lambda kv: kv[1]["spend"], reverse=True)
        if values["spend"] > 0
    ]


def _convert_platform_breakdown(breakdown: list[dict], factor: float) -> list[dict]:
    """Aplica el mismo factor de cambio que _convert_money, solo a `spend`
    (impressions/reach/clicks no son dinero)."""
    return [{**row, "spend": row["spend"] * factor} for row in breakdown]


def format_period(date_from: date, date_to: date) -> str:
    """Ej.: '1 – 15 jun 2026' o '20 may – 5 jun 2026' si cruza meses."""
    if date_from.month == date_to.month and date_from.year == date_to.year:
        return f"{date_from.day} – {date_to.day} {_MESES[date_to.month - 1]} {date_to.year}"
    return (f"{date_from.day} {_MESES[date_from.month - 1]} – "
            f"{date_to.day} {_MESES[date_to.month - 1]} {date_to.year}")


def _filter_campaigns_by_country(campaigns: list[dict], country_code: str | None) -> tuple[list[dict], float]:
    """
    Filtra campañas y anuncios por país. Si country_code es None, devuelve todo.
    Devuelve (campañas_filtradas, gasto_total_filtrado).

    Nota: El gasto se distribuye entre los anuncios de una campaña, así que
    el total filtrado es la suma del gasto de las campañas que tienen al
    menos un anuncio en el país seleccionado.
    """
    if not country_code:
        total = sum(c.get("spend", 0) for c in campaigns)
        return campaigns, float(total or 0)

    filtered = []
    filtered_spend = 0.0
    for campaign in campaigns:
        ads = campaign.get("ads", [])
        filtered_ads = [ad for ad in ads if country_code in ad.get("countries", [])]
        if filtered_ads:
            filtered_campaign = campaign.copy()
            filtered_campaign["ads"] = filtered_ads
            filtered.append(filtered_campaign)
            filtered_spend += float(campaign.get("spend", 0) or 0)

    return filtered, filtered_spend


def _apply_customization(campaigns: list[dict], campaign_metrics: dict[str, list[str]] | None,
                         campaign_comments: dict[str, str] | None) -> list[dict]:
    """Adjunta selected_metrics/comment a cada campaña, buscando por su id de
    Meta (clave de ambos dicts, como string — ver GET /reports/campaigns).
    Campañas sin entrada en ninguno de los dos quedan intactas: su render
    sigue usando el set automático de metrics_by_objective."""
    campaign_metrics = campaign_metrics or {}
    campaign_comments = campaign_comments or {}
    out = []
    for c in campaigns:
        cid = str(c.get("id"))
        entry = dict(c)
        if cid in campaign_metrics:
            entry["selected_metrics"] = campaign_metrics[cid]
        if cid in campaign_comments:
            entry["comment"] = campaign_comments[cid]
        out.append(entry)
    return out


async def build_report_data(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD",
                            country_code: str | None = None,
                            source_currency: str = "USD",
                            exchange_rate: float | None = None,
                            attribution_window: str | None = None,
                            campaign_metrics: dict[str, list[str]] | None = None,
                            campaign_comments: dict[str, str] | None = None,
                            general_comment: str | None = None) -> dict:
    """
    Construye el diccionario que pdf_generator sabe dibujar, para UN activo
    comercial.
    `tokens` es una lista de candidatos en orden de preferencia (p. ej. el
    Facebook personal del usuario y, de respaldo, el token central de la
    organización): si el primero no tiene acceso a la cuenta, se reintenta con
    el siguiente antes de fallar.
    Si `country_code` se proporciona (ej. "GT", "US"), solo incluye anuncios
    pautados para ese país y recalcula el gasto total en consecuencia.

    `source_currency` es la moneda en la que ESTA cuenta reporta en Meta
    (account.native_currency, resuelto por quien llama). Si no coincide con
    `currency` (lo que la persona pidió ver), se convierte con
    `exchange_rate` — ver `_exchange_factor`. Si `exchange_rate` es None se
    usa `DEFAULT_EXCHANGE_RATE_USD_GTQ` como respaldo.

    `attribution_window` es la preferencia de la organización (Ajustes >
    Preferencias de reporte, ver schemas.ATTRIBUTION_WINDOWS). None = se
    deja que Meta use el default de esta cuenta publicitaria puntual, igual
    que antes de que existiera esta preferencia.

    Lanza meta_api.MetaApiError si ningún token puede leer la cuenta.
    """
    data = await meta_api.get_account_data_with_fallback(
        tokens, account.meta_ad_account_id, date_from.isoformat(), date_to.isoformat(),
        ATTRIBUTION_WINDOWS.get(attribution_window),
    )
    campaigns, filtered_spend = _filter_campaigns_by_country(data["campaigns"], country_code)
    total_spend = filtered_spend if country_code else data["total_spend"]

    factor = _exchange_factor(
        source_currency, currency, exchange_rate or DEFAULT_EXCHANGE_RATE_USD_GTQ
    )
    if factor is not None and factor != 1.0:
        campaigns, total_spend = _convert_money(campaigns, total_spend, factor)

    if campaign_metrics or campaign_comments:
        campaigns = _apply_customization(campaigns, campaign_metrics, campaign_comments)

    platform_breakdown: list[dict] = []
    if total_spend:
        # No tiene sentido pedirle este desglose a Meta a una cuenta sin
        # gasto en el período — solo devolvería filas vacías. Un fallo acá
        # (ej. rate limit puntual) no debe tirar el reporte completo, que ya
        # tiene los datos que sí importan: el resumen Facebook/Instagram es
        # un extra, no el corazón del reporte.
        try:
            raw_breakdown = await meta_api.get_platform_breakdown_with_fallback(
                tokens, account.meta_ad_account_id, date_from.isoformat(), date_to.isoformat(),
            )
            platform_breakdown = _aggregate_platform_breakdown(raw_breakdown, country_code)
            if factor is not None and factor != 1.0:
                platform_breakdown = _convert_platform_breakdown(platform_breakdown, factor)
        except meta_api.MetaApiError as e:
            log.warning("No se pudo traer el desglose Facebook/Instagram de %s: %s",
                       account.meta_ad_account_id, e)
            platform_breakdown = []

    return {
        "client_name": account.label,
        "period": format_period(date_from, date_to),
        "campaigns": campaigns,
        "total_spend": total_spend,
        "budget": budget,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "country_code": country_code,
        "general_comment": general_comment,
        "platform_breakdown": platform_breakdown,
    }


async def build_pdf(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD",
                    country_code: str | None = None,
                    source_currency: str = "USD",
                    exchange_rate: float | None = None,
                    attribution_window: str | None = None,
                    campaign_metrics: dict[str, list[str]] | None = None,
                    campaign_comments: dict[str, str] | None = None,
                    general_comment: str | None = None) -> tuple[bytes, str]:
    """
    Genera el PDF completo. Devuelve (bytes_del_pdf, nombre_de_archivo).

    El total que se registra aquí es el techo de lo que puede sentir el
    usuario del lado del servidor: si la suma de las fases (ver app/services/
    perf.py) no lo explica, el tiempo que falta está en el sondeo del
    frontend o en la red, no acá.

    Si `country_code` se proporciona (ej. "GT", "US"), el reporte solo incluye
    anuncios pautados para ese país. `attribution_window`, ver
    build_report_data.
    """
    async with perf.aphase(f"REPORTE · total ({account.label})") as info:
        report_data = await build_report_data(
            account, tokens, date_from, date_to, budget, currency, country_code,
            source_currency, exchange_rate, attribution_window,
            campaign_metrics, campaign_comments, general_comment,
        )
        info["campañas"] = len(report_data["campaigns"])
        pdf_bytes = await pdf_generator.generate_pdf(report_data)

    slug = "".join(ch if ch.isalnum() else "-" for ch in account.label.lower()).strip("-")
    country_suffix = f"-{country_code}" if country_code else ""
    filename = f"reporte-{slug}{country_suffix}-{date_from.isoformat()}-a-{date_to.isoformat()}.pdf"
    return pdf_bytes, filename
