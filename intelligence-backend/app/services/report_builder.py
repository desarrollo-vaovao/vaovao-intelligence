"""
report_builder — une las piezas del motor de reportes.

Toma un activo comercial de la base y un rango de fechas; pide los datos a
Meta (meta_api) y los arma en la estructura que espera pdf_generator. Es el
"pegamento" entre traer datos y dibujarlos.

Un reporte es siempre de UN activo comercial: los activos de un mismo cliente
pueden ser marcas sin relación entre sí, y mezclarlas en un PDF no sirve.
"""
from datetime import date

from app.models import AdAccount
from app.services import meta_api, pdf_generator, perf

_MESES = ["ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]

CURRENCY_SYMBOLS = {"USD": "$", "GTQ": "Q"}


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


async def build_report_data(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD",
                            country_code: str | None = None) -> dict:
    """
    Construye el diccionario que pdf_generator sabe dibujar, para UN activo
    comercial.
    `tokens` es una lista de candidatos en orden de preferencia (p. ej. el
    Facebook personal del usuario y, de respaldo, el token central de la
    organización): si el primero no tiene acceso a la cuenta, se reintenta con
    el siguiente antes de fallar.
    Si `country_code` se proporciona (ej. "GT", "US"), solo incluye anuncios
    pautados para ese país y recalcula el gasto total en consecuencia.
    Lanza meta_api.MetaApiError si ningún token puede leer la cuenta.
    """
    data = await meta_api.get_account_data_with_fallback(
        tokens, account.meta_ad_account_id, date_from.isoformat(), date_to.isoformat()
    )
    campaigns, filtered_spend = _filter_campaigns_by_country(data["campaigns"], country_code)
    return {
        "client_name": account.label,
        "period": format_period(date_from, date_to),
        "campaigns": campaigns,
        "total_spend": filtered_spend if country_code else data["total_spend"],
        "budget": budget,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "country_code": country_code,
    }


async def build_pdf(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD",
                    country_code: str | None = None) -> tuple[bytes, str]:
    """
    Genera el PDF completo. Devuelve (bytes_del_pdf, nombre_de_archivo).

    El total que se registra aquí es el techo de lo que puede sentir el
    usuario del lado del servidor: si la suma de las fases (ver app/services/
    perf.py) no lo explica, el tiempo que falta está en el sondeo del
    frontend o en la red, no acá.

    Si `country_code` se proporciona (ej. "GT", "US"), el reporte solo incluye
    anuncios pautados para ese país.
    """
    async with perf.aphase(f"REPORTE · total ({account.label})") as info:
        report_data = await build_report_data(account, tokens, date_from, date_to, budget, currency, country_code)
        info["campañas"] = len(report_data["campaigns"])
        pdf_bytes = await pdf_generator.generate_pdf(report_data)

    slug = "".join(ch if ch.isalnum() else "-" for ch in account.label.lower()).strip("-")
    country_suffix = f"-{country_code}" if country_code else ""
    filename = f"reporte-{slug}{country_suffix}-{date_from.isoformat()}-a-{date_to.isoformat()}.pdf"
    return pdf_bytes, filename
