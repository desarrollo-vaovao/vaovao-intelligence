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
from datetime import datetime
from playwright.sync_api import sync_playwright

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
}

OBJECTIVE_BADGES = {
    "TRAFFIC": "background:#E6F1FB;color:#185FA5", "LINK_CLICKS": "background:#E6F1FB;color:#185FA5",
    "MESSAGES": "background:#E1F5EE;color:#0F6E56", "POST_ENGAGEMENT": "background:#FAEEDA;color:#854F0B",
    "PAGE_LIKES": "background:#EEEDFE;color:#3C3489", "REACH": "background:#FCEBEB;color:#A32D2D",
    "BRAND_AWARENESS": "background:#FCEBEB;color:#A32D2D", "LEAD_GENERATION": "background:#EAF3DE;color:#3B6D11",
    "CONVERSIONS": "background:#EAF3DE;color:#3B6D11",
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


def metrics_by_objective(objective: str, insights: dict, currency_symbol: str = "$") -> list[dict]:
    obj = (objective or "").upper()
    if obj == "MESSAGES":
        conv = insights.get("messaging_conversation_started_7d")
        spend = insights.get("spend")
        cost = fmt_currency(float(spend) / float(conv), currency_symbol) if spend and conv else "—"
        return [
            {"label": "Impresiones", "value": fmt_number(insights.get("impressions"))},
            {"label": "Conversaciones", "value": fmt_number(conv)},
            {"label": "Costo / conv.", "value": cost},
        ]
    if obj == "POST_ENGAGEMENT":
        eng = insights.get("post_engagement")
        spend = insights.get("spend")
        cost = fmt_currency(float(spend) / float(eng), currency_symbol) if spend and eng else "—"
        return [
            {"label": "Impresiones", "value": fmt_number(insights.get("impressions"))},
            {"label": "Interacciones", "value": fmt_number(eng)},
            {"label": "Costo / int.", "value": cost},
        ]
    if obj == "PAGE_LIKES":
        likes = _find_like(insights)
        spend = insights.get("spend")
        cost = fmt_currency(float(spend) / float(likes), currency_symbol) if spend and likes else "—"
        return [
            {"label": "Impresiones", "value": fmt_number(insights.get("impressions"))},
            {"label": "Seguidores", "value": fmt_number(likes)},
            {"label": "Costo / seg.", "value": cost},
        ]
    if obj in ("REACH", "BRAND_AWARENESS"):
        freq = insights.get("frequency")
        return [
            {"label": "Impresiones", "value": fmt_number(insights.get("impressions"))},
            {"label": "Alcance", "value": fmt_number(insights.get("reach"))},
            {"label": "Frecuencia", "value": f"{float(freq):.2f}" if freq else "—"},
            {"label": "CPM", "value": fmt_currency(insights.get("cpm"), currency_symbol)},
        ]
    # Default: tráfico / clics
    return [
        {"label": "Impresiones", "value": fmt_number(insights.get("impressions"))},
        {"label": "Clics", "value": fmt_number(insights.get("clicks"))},
        {"label": "CTR", "value": fmt_percent(insights.get("ctr"))},
        {"label": "CPC", "value": fmt_currency(insights.get("cpc"), currency_symbol)},
    ]


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
    metrics = metrics_by_objective(campaign.get("objective"), campaign.get("insights", {}), currency_symbol)
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
        </div>
      </div>
    </div>
    """


# ── Render de una página (estación o reporte único) ───────────
def render_station_page(station: dict, client_name: str, period: str,
                        station_index: int, total_stations: int,
                        currency_symbol: str = "$") -> str:
    station_id = station.get("station_id")
    station_label = station.get("station_label")
    campaigns = station.get("campaigns", [])
    total_spend = station.get("total_spend", 0)
    budget = station.get("budget")

    pct = min(round((total_spend / budget) * 100), 100) if budget else None

    pleca_label = f"{station_id} — {station_label}" if station_label else "Reporte de campañas — Meta Ads"
    pleca_sub = (f'Estación {station_index} de {total_stations}'
                 if total_stations > 1 else "Quincenal")

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
      </div>

      <div style="background:#111;color:#666;padding:8px 28px;display:flex;justify-content:space-between;font-size:10px;">
        <span>VaoVao — Reporte generado automáticamente</span>
        <span>{(station_id + " — ") if station_label else ""}{period} &nbsp;·&nbsp; hello@vaovao.co</span>
      </div>
    </div>
    """


def generate_report_html(report_data: dict) -> str:
    """Arma el HTML completo del reporte (una página por estación, o una sola)."""
    client_name = report_data.get("client_name", "")
    period = report_data.get("period", "")
    currency_symbol = report_data.get("currency_symbol", "$")

    if report_data.get("type") == "multi-station":
        stations = report_data.get("stations", [])
        pages = "".join(
            render_station_page(st, client_name, period, i + 1, len(stations), currency_symbol)
            for i, st in enumerate(stations)
        )
    else:
        pages = render_station_page(
            {"station_id": None, "station_label": None,
             "campaigns": report_data.get("campaigns", []),
             "total_spend": report_data.get("total_spend", 0),
             "budget": report_data.get("budget")},
            client_name, period, 1, 1, currency_symbol,
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    * {{ font-family: 'Poppins', Arial, sans-serif; margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #fff; }}
    @page {{ size: Letter landscape; margin: 0; }}
  </style>
</head>
<body>{pages}</body>
</html>"""


def generate_pdf(report_data: dict) -> bytes:
    """Renderiza el HTML a PDF con Playwright (Chromium). Devuelve los bytes del PDF."""
    html = generate_report_html(report_data)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
        ])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            return page.pdf(
                format="Letter", landscape=True, print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
