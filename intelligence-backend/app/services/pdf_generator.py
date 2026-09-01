"""
pdf_generator — arma el reporte en PDF a partir de los datos de Meta.
Port a Python de reportTemplate.js + pdfGenerator.js (reportería Node).

Mantiene el MISMO diseño aprobado: horizontal, Poppins, header negro con logo
VAOVAO, pleca con gradiente de Meta, resumen de inversión, tabla de campañas y
tarjetas de performance. Usa Playwright (mismo motor Chromium que Puppeteer) para
que el PDF salga idéntico al de la reportería original.

Consume la estructura que produce meta_api.get_account_data():
    campaign = {name, objective, insights{}, ads[], spend}
    ad       = {name, image_url, insights{}}
"""
import asyncio
import html
from datetime import datetime

from app.services import assets, browser_pool, perf

# ── Formateadores ─────────────────────────────────────────────
def fmt_number(n) -> str:
    if not n:
        return "—"
    try:
        return f"{float(n):,.0f}"
    except (TypeError, ValueError):
        return "—"


def fmt_currency(n, symbol: str = "$") -> str:
    if not n:
        return "—"
    try:
        return f"{symbol}{float(n):,.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_percent(n) -> str:
    if not n:
        return "—"
    try:
        return f"{float(n):.2f}%"
    except (TypeError, ValueError):
        return "—"


_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

def _today_es() -> str:
    d = datetime.now()
    return f"{d.day:02d} {_MESES[d.month - 1]} {d.year}"


# ── Etiquetas y estilos por objetivo ──────────────────────────
OBJECTIVE_LABELS = {
    "LINK_CLICKS": "Tráfico", "TRAFFIC": "Tráfico", "MESSAGES": "Mensajes",
    "POST_ENGAGEMENT": "Interacción", "PAGE_LIKES": "Seguidores", "REACH": "Alcance",
    "BRAND_AWARENESS": "Reconocimiento", "VIDEO_VIEWS": "Vistas de video",
    "LEAD_GENERATION": "Leads", "CONVERSIONS": "Conversiones",
    # Taxonomía nueva de Meta (ODAX) — reemplazó a los objetivos de arriba,
    # pero varias cuentas siguen devolviendo la vieja según cuándo se creó
    # la campaña. Sin esto, el badge del PDF mostraba el código crudo de la
    # API (ej. "OUTCOME_ENGAGEMENT") en vez de una etiqueta traducida.
    "OUTCOME_AWARENESS": "Reconocimiento", "OUTCOME_TRAFFIC": "Tráfico",
    "OUTCOME_ENGAGEMENT": "Interacción", "OUTCOME_LEADS": "Leads",
    "OUTCOME_SALES": "Ventas", "OUTCOME_APP_PROMOTION": "Promoción de app",
}

OBJECTIVE_BADGES = {
    "TRAFFIC": "background:#E6F1FB;color:#185FA5", "LINK_CLICKS": "background:#E6F1FB;color:#185FA5",
    "MESSAGES": "background:#E1F5EE;color:#0F6E56", "POST_ENGAGEMENT": "background:#FAEEDA;color:#854F0B",
    "PAGE_LIKES": "background:#EEEDFE;color:#3C3489", "REACH": "background:#FCEBEB;color:#A32D2D",
    "BRAND_AWARENESS": "background:#FCEBEB;color:#A32D2D", "LEAD_GENERATION": "background:#EAF3DE;color:#3B6D11",
    "CONVERSIONS": "background:#EAF3DE;color:#3B6D11",
    # Mismos colores que su equivalente de la taxonomía vieja (ver
    # OBJECTIVE_LABELS) para que un reporte con campañas de ambas
    # generaciones no se vea inconsistente.
    "OUTCOME_AWARENESS": "background:#FCEBEB;color:#A32D2D", "OUTCOME_TRAFFIC": "background:#E6F1FB;color:#185FA5",
    "OUTCOME_ENGAGEMENT": "background:#FAEEDA;color:#854F0B", "OUTCOME_LEADS": "background:#EAF3DE;color:#3B6D11",
    "OUTCOME_SALES": "background:#EAF3DE;color:#3B6D11", "OUTCOME_APP_PROMOTION": "background:#EEEDFE;color:#3C3489",
}


def objective_label(obj: str) -> str:
    return OBJECTIVE_LABELS.get(obj, obj or "—")


def objective_badge(obj: str) -> str:
    return OBJECTIVE_BADGES.get(obj, "background:#F1EFE8;color:#5F5E5A")


def _find_like(insights: dict):
    for a in (insights.get("actions") or []):
        if a.get("action_type") == "like":
            return a.get("value")
    return None


def _cost_per(insights: dict, count_field: str, currency_symbol: str) -> str:
    spend = insights.get("spend")
    count = insights.get(count_field)
    if spend and count:
        try:
            return fmt_currency(float(spend) / float(count), currency_symbol)
        except (TypeError, ValueError, ZeroDivisionError):
            return "—"
    return "—"


def _cost_per_follower(insights: dict, currency_symbol: str) -> str:
    spend = insights.get("spend")
    likes = _find_like(insights)
    if spend and likes:
        try:
            return fmt_currency(float(spend) / float(likes), currency_symbol)
        except (TypeError, ValueError, ZeroDivisionError):
            return "—"
    return "—"


# Catálogo de TODAS las métricas que un reporte puede mostrar, sin importar
# el objetivo de la campaña — la base del "mostrar/ocultar por campaña" que
# elige quien arma el reporte (ver metrics_for_campaign). Cada entrada sabe
# extraer y formatear su propio valor desde `insights`; una clave que no
# aplica al objetivo real de la campaña simplemente no tiene el dato y se
# muestra "—", igual que ya pasaba con campos ausentes antes de este catálogo.
METRIC_REGISTRY: dict[str, dict] = {
    "impressions": {
        "label": "Impresiones",
        "value": lambda ins, cur: fmt_number(ins.get("impressions")),
    },
    "reach": {
        "label": "Alcance",
        "value": lambda ins, cur: fmt_number(ins.get("reach")),
    },
    "frequency": {
        "label": "Frecuencia",
        "value": lambda ins, cur: (
            f"{float(ins['frequency']):.2f}" if ins.get("frequency") else "—"
        ),
    },
    "clicks": {
        "label": "Clics",
        "value": lambda ins, cur: fmt_number(ins.get("clicks")),
    },
    "ctr": {
        "label": "CTR",
        "value": lambda ins, cur: fmt_percent(ins.get("ctr")),
    },
    "cpc": {
        "label": "CPC",
        "value": lambda ins, cur: fmt_currency(ins.get("cpc"), cur),
    },
    "cpm": {
        "label": "CPM",
        "value": lambda ins, cur: fmt_currency(ins.get("cpm"), cur),
    },
    "conversations": {
        "label": "Conversaciones",
        "value": lambda ins, cur: fmt_number(ins.get("messaging_conversation_started_7d")),
    },
    "cost_per_conversation": {
        "label": "Costo / conv.",
        "value": lambda ins, cur: _cost_per(ins, "messaging_conversation_started_7d", cur),
    },
    "engagement": {
        "label": "Interacciones",
        "value": lambda ins, cur: fmt_number(ins.get("post_engagement")),
    },
    "cost_per_engagement": {
        "label": "Costo / int.",
        "value": lambda ins, cur: _cost_per(ins, "post_engagement", cur),
    },
    "followers": {
        "label": "Seguidores",
        "value": lambda ins, cur: fmt_number(_find_like(ins)),
    },
    "cost_per_follower": {
        "label": "Costo / seg.",
        "value": lambda ins, cur: _cost_per_follower(ins, cur),
    },
}

# El set automático por objetivo, expresado como claves de METRIC_REGISTRY —
# única fuente de verdad tanto para metrics_by_objective (comportamiento de
# siempre) como para el `default_metrics` que ve el panel de personalización
# del frontend (GET /reports/campaigns/{account_id}).
OBJECTIVE_DEFAULT_METRIC_KEYS: dict[str, list[str]] = {
    "MESSAGES": ["impressions", "conversations", "cost_per_conversation"],
    "POST_ENGAGEMENT": ["impressions", "engagement", "cost_per_engagement"],
    "PAGE_LIKES": ["impressions", "followers", "cost_per_follower"],
    "REACH": ["impressions", "reach", "frequency", "cpm"],
    "BRAND_AWARENESS": ["impressions", "reach", "frequency", "cpm"],
    "DEFAULT": ["impressions", "clicks", "ctr", "cpc"],
}


def default_metric_keys(objective: str | None) -> list[str]:
    """Claves de METRIC_REGISTRY que se mostrarían para este objetivo si
    nadie personaliza nada — el mismo set que ya se calculaba antes de este
    cambio, ahora expuesto como claves en vez de solo como render final."""
    obj = (objective or "").upper()
    return OBJECTIVE_DEFAULT_METRIC_KEYS.get(obj, OBJECTIVE_DEFAULT_METRIC_KEYS["DEFAULT"])


def _resolve_metrics(keys: list[str], insights: dict, currency_symbol: str) -> list[dict]:
    out = []
    for key in keys:
        entry = METRIC_REGISTRY.get(key)
        if entry is None:
            continue
        out.append({"label": entry["label"], "value": entry["value"](insights, currency_symbol)})
    return out


def metrics_by_objective(objective: str, insights: dict, currency_symbol: str = "$") -> list[dict]:
    return _resolve_metrics(default_metric_keys(objective), insights, currency_symbol)


def metrics_for_campaign(campaign: dict, currency_symbol: str = "$",
                         selected_keys: list[str] | None = None) -> list[dict]:
    """
    Métricas a mostrar en la tarjeta de esta campaña. Con `selected_keys`
    (lista de claves de METRIC_REGISTRY elegidas a mano) se usa exactamente
    esa selección, sin importar el objetivo — es el mecanismo de
    "mostrar/ocultar por campaña" del panel de personalización. Sin
    `selected_keys` (None) cae en el set automático de siempre
    (`default_metric_keys`) — comportamiento idéntico al de antes de que
    existiera esta función.
    """
    insights = campaign.get("insights") or {}
    keys = selected_keys if selected_keys is not None else default_metric_keys(campaign.get("objective"))
    return _resolve_metrics(keys, insights, currency_symbol)


def ad_main_metric(objective: str, ins: dict) -> str:
    obj = (objective or "").upper()
    if obj == "MESSAGES":
        return f"{fmt_number(ins.get('messaging_conversation_started_7d'))} conv."
    if obj == "POST_ENGAGEMENT":
        return f"{fmt_number(ins.get('post_engagement'))} int."
    if obj == "PAGE_LIKES":
        return f"{fmt_number(_find_like(ins))} seg."
    return f"{fmt_number(ins.get('clicks'))} clics"


def ad_cost_metric(objective: str, ins: dict, currency_symbol: str = "$") -> str:
    obj = (objective or "").upper()
    if obj == "MESSAGES" and ins.get("spend") and ins.get("messaging_conversation_started_7d"):
        return fmt_currency(float(ins["spend"]) / float(ins["messaging_conversation_started_7d"]), currency_symbol)
    return fmt_currency(ins.get("cpc"), currency_symbol)


# ── Render de una tarjeta de campaña ──────────────────────────
def render_campaign_card(campaign: dict, currency_symbol: str = "$") -> str:
    selected_metrics = campaign.get("selected_metrics")
    metrics = metrics_for_campaign(campaign, currency_symbol, selected_metrics)
    ads = campaign.get("ads") or []
    best_ad = ads[0] if ads else None
    other_ads = ads[1:4]

    img = (
        f'<img src="{best_ad["image_url"]}" style="width:100%;height:100%;object-fit:cover;" />'
        if best_ad and best_ad.get("image_url")
        else '<span style="font-size:10px;color:#aaa;text-align:center;line-height:1.3;">Sin<br>imagen</span>'
    )

    metrics_html = "".join(
        f'<div><div style="font-size:9px;color:#888;margin-bottom:1px;">{m["label"]}</div>'
        f'<div style="font-size:14px;font-weight:600;color:#111;">{m["value"]}</div></div>'
        for m in metrics
    )

    best_html = ""
    if best_ad:
        best_html = (
            f'<div style="display:flex;justify-content:space-between;font-size:10px;padding:2px 0;">'
            f'<span style="color:#833AB4;font-weight:500;">● {best_ad.get("name","")}</span>'
            f'<span style="color:#aaa;display:flex;gap:8px;">'
            f'<span>{ad_main_metric(campaign.get("objective"), best_ad.get("insights", {}))}</span>'
            f'<span>{ad_cost_metric(campaign.get("objective"), best_ad.get("insights", {}), currency_symbol)}</span>'
            f'</span></div>'
        )

    others_html = "".join(
        f'<div style="display:flex;justify-content:space-between;font-size:10px;padding:2px 0;">'
        f'<span style="color:#888;">○ {ad.get("name","")}</span>'
        f'<span style="color:#aaa;display:flex;gap:8px;">'
        f'<span>{ad_main_metric(campaign.get("objective"), ad.get("insights", {}))}</span>'
        f'<span>{ad_cost_metric(campaign.get("objective"), ad.get("insights", {}), currency_symbol)}</span>'
        f'</span></div>'
        for ad in other_ads
    )

    ads_section = ""
    if ads:
        ads_section = (
            '<div style="border-top:0.5px solid #e0e0e0;padding-top:7px;">'
            '<div style="font-size:9px;color:#aaa;margin-bottom:4px;">Anuncios</div>'
            f'{best_html}{others_html}</div>'
        )

    comment = (campaign.get("comment") or "").strip()
    comment_section = ""
    if comment:
        comment_section = (
            '<div style="border-top:0.5px solid #e0e0e0;padding-top:7px;margin-top:7px;">'
            '<div style="font-size:9px;color:#aaa;margin-bottom:3px;">Observaciones</div>'
            f'<div style="font-size:10px;color:#333;line-height:1.4;white-space:pre-wrap;">{html.escape(comment)}</div></div>'
        )

    return f"""
    <div style="border:0.5px solid #e0e0e0;border-radius:10px;overflow:hidden;break-inside:avoid;">
      <div style="background:#111;color:#fff;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:11px;font-weight:500;">{campaign.get("name","")}</span>
        <span style="display:inline-block;padding:2px 7px;border-radius:99px;font-size:9px;font-weight:500;{objective_badge(campaign.get("objective"))}">{objective_label(campaign.get("objective"))}</span>
      </div>
      <div style="padding:10px 12px;display:flex;gap:12px;">
        <div style="width:72px;height:72px;background:#f5f5f5;border-radius:8px;flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center;">{img}</div>
        <div style="flex:1;">
          <div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap;">{metrics_html}</div>
          {ads_section}
          {comment_section}
        </div>
      </div>
    </div>
    """


_PLATFORM_DOT_COLOR = {
    "facebook": "#1877F2",
    "instagram": "#E1306C",
    "audience_network": "#8A8D91",
    "messenger": "#00B2FF",
}


def _platform_breakdown_block(platform_breakdown: list[dict], total_spend: float, currency_symbol: str) -> str:
    """
    Sección "Facebook vs Instagram" al final del reporte: en qué plataforma
    de publicación se fue el gasto, no por campaña sino de toda la cuenta
    en el período (ver report_builder._aggregate_platform_breakdown).

    Vacío cuando Meta no devolvió el desglose (cuenta sin gasto, o el
    desglose falló y report_builder ya lo dejó en []) — sin esto se vería
    una tabla con encabezados y cero filas, más confuso que no mostrarla.
    """
    if not platform_breakdown:
        return ""

    rows = "".join(
        f"""
              <tr>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;color:#111;">
                  <div style="display:flex;align-items:center;gap:7px;">
                    <div style="width:7px;height:7px;border-radius:50%;background:{_PLATFORM_DOT_COLOR.get(row["platform"], "#ccc")};flex-shrink:0;"></div>
                    {row["label"]}
                  </div>
                </td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;font-weight:500;color:#111;">{fmt_currency(row["spend"], currency_symbol)}</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;color:#888;">{fmt_percent(row["spend"] / total_spend * 100 if total_spend else 0)}</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;color:#888;">{fmt_number(row["impressions"])}</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;color:#888;">{fmt_number(row["reach"])}</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;color:#888;">{fmt_number(row["clicks"])}</td>
              </tr>"""
        for row in platform_breakdown
    )

    return f"""
        <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>

        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Facebook vs Instagram</div>
        <table style="width:100%;border-collapse:collapse;font-size:11px;">
          <thead>
            <tr>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:left;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Plataforma</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Consumido</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">% del total</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Impresiones</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Alcance</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Clics</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""


# ── Render de la página del reporte ───────────────────────────
def render_report_page(report_data: dict, currency_symbol: str = "$") -> str:
    client_name = report_data.get("client_name", "")
    period = report_data.get("period", "")
    campaigns = report_data.get("campaigns", [])
    total_spend = report_data.get("total_spend", 0)
    budget = report_data.get("budget")
    country_code = report_data.get("country_code")
    general_comment = (report_data.get("general_comment") or "").strip()

    pct = min(round((total_spend / budget) * 100), 100) if budget else None

    pleca_label = "Reporte de campañas — Meta Ads"
    country_suffix = f" · {country_code}" if country_code else ""
    pleca_sub = f"Quincenal{country_suffix}"

    budget_block = ""
    if budget:
        budget_block = f"""
            <div style="flex:1;">
              <div style="font-size:10px;color:#888;margin-bottom:2px;">Presupuesto del período</div>
              <div style="font-size:24px;font-weight:600;color:#111;line-height:1.1;">{fmt_currency(budget, currency_symbol)}</div>
              <div style="font-size:10px;color:#aaa;margin-top:3px;">Aprobado</div>
            </div>
            <div style="width:0.5px;background:#e0e0e0;align-self:stretch;"></div>"""

    pct_block = ""
    if pct is not None:
        pct_block = f"""
            <div style="width:0.5px;background:#e0e0e0;align-self:stretch;"></div>
            <div style="flex:2;">
              <div style="display:flex;justify-content:space-between;font-size:10px;color:#888;margin-bottom:5px;">
                <span>Ejecución del presupuesto</span>
                <span>{fmt_currency(total_spend, currency_symbol)} / {fmt_currency(budget, currency_symbol)}</span>
              </div>
              <div style="height:7px;background:#f0f0f0;border-radius:99px;overflow:hidden;">
                <div style="height:100%;width:{pct}%;background:linear-gradient(90deg,rgba(131,58,180,1) 0%,rgba(253,29,29,1) 50%,rgba(252,176,69,1) 100%);border-radius:99px;"></div>
              </div>
              <div style="font-size:12px;font-weight:600;color:#FD1D1D;margin-top:5px;">{pct}% ejecutado</div>
            </div>"""

    observaciones_block = ""
    if general_comment:
        observaciones_block = f"""
            <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>
            <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Observaciones del período</div>
            <div style="font-size:11px;color:#333;line-height:1.5;white-space:pre-wrap;">{html.escape(general_comment)}</div>"""

    table_rows = "".join(
        f"""
              <tr>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;color:#111;">{c.get("name","")}</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;">
                  <span style="display:inline-block;padding:2px 7px;border-radius:99px;font-size:10px;font-weight:500;{objective_badge(c.get("objective"))}">{objective_label(c.get("objective"))}</span>
                </td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;color:#888;">{len(c.get("ads") or [])} anuncios</td>
                <td style="padding:7px 8px;border-bottom:0.5px solid #f0f0f0;text-align:right;font-weight:500;color:#111;">{fmt_currency(c.get("spend"), currency_symbol)}</td>
              </tr>"""
        for c in campaigns
    )

    cards = "".join(render_campaign_card(c, currency_symbol) for c in campaigns)

    platform_block = _platform_breakdown_block(
        report_data.get("platform_breakdown") or [], total_spend, currency_symbol
    )

    return f"""
    <div style="width:100%;background:#fff;page-break-after:always;">
      <div style="background:#111;color:#fff;padding:16px 28px;display:flex;justify-content:space-between;align-items:center;">
        <div style="font-size:20px;font-weight:600;letter-spacing:2px;color:#fff;">VAO<span style="color:#FCB045;">VAO</span></div>
        <div style="text-align:right;">
          <div style="font-size:14px;font-weight:500;color:#fff;">{client_name}</div>
          <div style="font-size:11px;color:#aaa;margin-top:2px;">Período: {period} &nbsp;·&nbsp; Generado: {_today_es()}</div>
        </div>
      </div>

      <div style="background:linear-gradient(90deg,rgba(131,58,180,1) 0%,rgba(253,29,29,1) 50%,rgba(252,176,69,1) 100%);padding:9px 28px;display:flex;align-items:center;gap:10px;">
        <span style="color:#fff;font-size:13px;font-weight:600;letter-spacing:0.5px;">{pleca_label}</span>
        <span style="color:rgba(255,255,255,0.7);font-size:11px;">{pleca_sub}</span>
      </div>

      <div style="padding:18px 28px;">
        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 10px;">Resumen de inversión</div>
        <div style="display:flex;gap:28px;align-items:flex-end;margin-bottom:16px;">
          {budget_block}
          <div style="flex:1;">
            <div style="font-size:10px;color:#888;margin-bottom:2px;">Total consumido</div>
            <div style="font-size:24px;font-weight:600;color:#111;line-height:1.1;">{fmt_currency(total_spend, currency_symbol)}</div>
            <div style="font-size:10px;color:#aaa;margin-top:3px;">Al corte del período</div>
          </div>
          {pct_block}
        </div>

        {observaciones_block}

        <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>

        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Campañas activas</div>
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:7px;">
          <div style="width:7px;height:7px;border-radius:50%;background:#1877F2;flex-shrink:0;"></div>
          <span style="font-size:11px;font-weight:600;color:#111;">Meta — Facebook / Instagram</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:11px;margin-bottom:16px;">
          <thead>
            <tr>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:left;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Campaña</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:left;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Objetivo</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:left;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Anuncios</th>
              <th style="font-size:10px;font-weight:500;color:#888;text-align:right;padding:4px 8px;border-bottom:0.5px solid #e0e0e0;">Consumido</th>
            </tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>

        <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>

        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 10px;">Performance por campaña</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">{cards}</div>

        {platform_block}
      </div>

      <div style="background:#111;color:#666;padding:8px 28px;display:flex;justify-content:space-between;font-size:10px;">
        <span>VaoVao — Reporte generado automáticamente</span>
        <span>{period} &nbsp;·&nbsp; hello@vaovao.co</span>
      </div>
    </div>
    """


def generate_report_html(report_data: dict, font_css: str | None = None) -> str:
    """
    Arma el HTML completo del reporte: una página, un activo comercial.

    `font_css` es Poppins ya incrustada como data: URI (ver assets.font_css).
    Si viene None se cae al <link> a Google Fonts, que funciona igual pero
    obliga a Chromium a salir a la red antes de poder imprimir.
    """
    pages = render_report_page(report_data, report_data.get("currency_symbol", "$"))

    font_block = (
        f"<style>{font_css}</style>" if font_css else
        '<link href="https://fonts.googleapis.com/css2'
        '?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">'
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  {font_block}
  <style>
    * {{ font-family: 'Poppins', Arial, sans-serif; margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #fff; }}
    @page {{ size: Letter landscape; margin: 0; }}
  </style>
</head>
<body>{pages}</body>
</html>"""


def _rendered_ads(report_data: dict) -> list[dict]:
    """
    Los anuncios cuya imagen el HTML de verdad va a mostrar: el mejor anuncio
    de cada campaña (render_campaign_card solo dibuja ads[0]). Bajar las demás
    sería trabajo tirado a la basura.
    """
    out = []
    for c in report_data.get("campaigns") or []:
        ads = c.get("ads") or []
        if ads and ads[0].get("image_url"):
            out.append(ads[0])
    return out


def _apply_inlined_images(ads: list[dict], inlined: dict[str, str]) -> None:
    """
    Cambia la URL remota de cada anuncio por su data: URI.

    Si una imagen NO se pudo bajar, se le quita la URL en vez de dejarla:
    ya sabemos que esa URL no responde, y dejarla puesta hacía que Chromium
    la intentara otra vez con `wait_until="load"`, que espera hasta el timeout
    de Playwright. Medido con una URL muerta, eso sumaba ~21 s al reporte —
    justo lo contrario de lo que busca incrustar los recursos. Sin URL sale el
    placeholder de "Sin imagen" y el PDF se imprime al instante.
    """
    for ad in ads:
        ad["image_url"] = inlined.get(ad["image_url"])


async def generate_pdf(report_data: dict) -> bytes:
    """
    Renderiza el HTML a PDF con el navegador compartido (browser_pool).

    La fuente y los thumbnails se bajan ANTES, en paralelo entre sí, y se
    incrustan en el HTML: así la página que recibe Chromium no tiene ni una
    petición de red pendiente y `wait_until="load"` se cumple de inmediato.
    Antes, esas descargas ocurrían dentro del render y una sola URL lenta de
    fbcdn dejaba el PDF colgado hasta que respondiera.
    """
    async with perf.aphase("PDF · recursos externos") as info:
        ads = _rendered_ads(report_data)
        font_css, inlined = await asyncio.gather(
            assets.font_css(),
            assets.inline_images([ad["image_url"] for ad in ads]),
        )
        info["imágenes"] = f"{len(inlined)}/{len(ads)}"

    _apply_inlined_images(ads, inlined)
    html = generate_report_html(report_data, font_css)

    async with perf.aphase("PDF · render en Chromium"):
        return await browser_pool.render_pdf(html)
