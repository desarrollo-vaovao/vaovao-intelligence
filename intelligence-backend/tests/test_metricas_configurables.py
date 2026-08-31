"""
Métricas configurables por campaña y observaciones en reportes — ver
docs/superpowers/specs/2026-08-31-metricas-configurables-y-observaciones-design.md

Todo lo que se personaliza aquí es efímero: vive solo en la petición que
genera ese PDF puntual, no se persiste en la base de datos.
"""
from __future__ import annotations

from app.services import pdf_generator


# ── metrics_by_objective sigue igual (regresión) ──────────────────────
def test_metrics_by_objective_messages_no_cambia():
    insights = {"impressions": 1000, "spend": 50,
                "messaging_conversation_started_7d": 10}
    result = pdf_generator.metrics_by_objective("MESSAGES", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "1,000"},
        {"label": "Conversaciones", "value": "10"},
        {"label": "Costo / conv.", "value": "$5.00"},
    ]


def test_metrics_by_objective_reach_no_cambia():
    insights = {"impressions": 2000, "reach": 1500, "frequency": 1.33, "cpm": 4.2}
    result = pdf_generator.metrics_by_objective("REACH", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "2,000"},
        {"label": "Alcance", "value": "1,500"},
        {"label": "Frecuencia", "value": "1.33"},
        {"label": "CPM", "value": "$4.20"},
    ]


def test_metrics_by_objective_default_no_cambia():
    insights = {"impressions": 500, "clicks": 25, "ctr": 5.0, "cpc": 0.8}
    result = pdf_generator.metrics_by_objective("LINK_CLICKS", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "500"},
        {"label": "Clics", "value": "25"},
        {"label": "CTR", "value": "5.00%"},
        {"label": "CPC", "value": "$0.80"},
    ]


# ── default_metric_keys ────────────────────────────────────────────
def test_default_metric_keys_por_objetivo():
    assert pdf_generator.default_metric_keys("MESSAGES") == [
        "impressions", "conversations", "cost_per_conversation",
    ]
    assert pdf_generator.default_metric_keys("PAGE_LIKES") == [
        "impressions", "followers", "cost_per_follower",
    ]


def test_default_metric_keys_objetivo_desconocido_cae_en_default():
    assert pdf_generator.default_metric_keys("ALGO_QUE_META_INVENTE_MANANA") == [
        "impressions", "clicks", "ctr", "cpc",
    ]
    assert pdf_generator.default_metric_keys(None) == [
        "impressions", "clicks", "ctr", "cpc",
    ]


# ── metrics_for_campaign: control total, sin importar el objetivo ─────
def test_metrics_for_campaign_sin_seleccion_usa_el_automatico():
    campaign = {"objective": "MESSAGES",
                "insights": {"impressions": 1000, "spend": 50,
                             "messaging_conversation_started_7d": 10}}
    assert (pdf_generator.metrics_for_campaign(campaign, "$")
            == pdf_generator.metrics_by_objective("MESSAGES", campaign["insights"], "$"))


def test_metrics_for_campaign_con_seleccion_explicita_quita_y_agrega():
    """Una campaña de Alcance (REACH) pidiendo Clics y CTR en vez del set
    automático (Impresiones/Alcance/Frecuencia/CPM) — el caso central de
    'quitar las que no sirven, agregar las que sí' que pidió el usuario."""
    campaign = {"objective": "REACH",
                "insights": {"impressions": 2000, "reach": 1500,
                             "clicks": 40, "ctr": 2.0}}
    result = pdf_generator.metrics_for_campaign(
        campaign, "$", selected_keys=["clicks", "ctr"]
    )
    assert result == [
        {"label": "Clics", "value": "40"},
        {"label": "CTR", "value": "2.00%"},
    ]


def test_metrics_for_campaign_metrica_sin_dato_muestra_raya():
    """Pedir 'Conversaciones' en una campaña que nunca tuvo ese dato: '—',
    no un error — el mismo criterio que ya aplica a cualquier campo ausente."""
    campaign = {"objective": "REACH", "insights": {"impressions": 2000}}
    result = pdf_generator.metrics_for_campaign(
        campaign, "$", selected_keys=["conversations", "cost_per_conversation"]
    )
    assert result == [
        {"label": "Conversaciones", "value": "—"},
        {"label": "Costo / conv.", "value": "—"},
    ]


def test_metrics_for_campaign_sin_insights_no_revienta():
    campaign = {"objective": "MESSAGES"}  # sin la clave "insights"
    result = pdf_generator.metrics_for_campaign(campaign, "$", selected_keys=["impressions"])
    assert result == [{"label": "Impresiones", "value": "—"}]


# ── Render: comentario por campaña ─────────────────────────────────
def test_render_campaign_card_sin_comentario_no_agrega_seccion():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "reach": 90}, "ads": []}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "Observaciones" not in html_out


def test_render_campaign_card_con_comentario_lo_muestra():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "reach": 90}, "ads": [],
                "comment": "Buen desempeño esta quincena"}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "Observaciones" in html_out
    assert "Buen desempeño esta quincena" in html_out


def test_render_campaign_card_escapa_html_del_comentario():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100}, "ads": [],
                "comment": "<script>alert(1)</script>"}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_campaign_card_usa_selected_metrics():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "clicks": 5, "ctr": 5.0}, "ads": [],
                "selected_metrics": ["clicks", "ctr"]}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    # Las métricas seleccionadas deben aparecer en la tarjeta
    assert "Clics" in html_out
    assert "CTR" in html_out
    # Las métricas automáticas de REACH que NO fueron elegidas no deben aparecer
    # (Frecuencia es un metric card label, nunca aparece en el badge)
    assert "Frecuencia" not in html_out


# ── Render: observación general del período ────────────────────────
def test_render_report_page_sin_general_comment_no_agrega_seccion():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "Observaciones del período" not in html_out


def test_render_report_page_con_general_comment_lo_muestra():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0,
                    "general_comment": "El período tuvo buen desempeño en general."}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "Observaciones del período" in html_out
    assert "El período tuvo buen desempeño en general." in html_out


def test_render_report_page_escapa_html_del_general_comment():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0,
                    "general_comment": "<b>negrita</b> & cosas"}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "<b>negrita</b>" not in html_out
    assert "&lt;b&gt;negrita&lt;/b&gt; &amp; cosas" in html_out


# ── report_builder: pasa la personalización hasta report_data ──────
import asyncio
from datetime import date

from app.services import meta_api, report_builder


def _fake_campaign(cid: str, objective: str = "REACH") -> dict:
    return {
        "id": cid, "name": f"Campaña {cid}", "objective": objective,
        "status": "ACTIVE", "spend": 10.0,
        "insights": {"impressions": 100, "reach": 90, "clicks": 5, "ctr": 5.0},
        "ads": [],
    }


def test_build_report_data_sin_personalizacion_no_agrega_claves(monkeypatch, tenant_a, factory):
    """Regresión: sin campaign_metrics/campaign_comments/general_comment, el
    resultado es el mismo de antes de este cambio."""
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1")], "total_spend": 10.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
    ))
    assert "selected_metrics" not in result["campaigns"][0]
    assert "comment" not in result["campaigns"][0]
    assert result.get("general_comment") is None


def test_build_report_data_con_personalizacion_adjunta_por_campana(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1"), _fake_campaign("2")], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
        campaign_metrics={"1": ["clicks", "ctr"]},
        campaign_comments={"1": "Buen mes"},
        general_comment="Resumen del período",
    ))

    campanas = {c["id"]: c for c in result["campaigns"]}
    assert campanas["1"]["selected_metrics"] == ["clicks", "ctr"]
    assert campanas["1"]["comment"] == "Buen mes"
    # La campaña "2" no tiene entrada en ninguno de los dos dicts: intacta.
    assert "selected_metrics" not in campanas["2"]
    assert "comment" not in campanas["2"]
    assert result["general_comment"] == "Resumen del período"


# ── GET /reports/campaigns/{account_id} ─────────────────────────────
import app.api.routes.reports as reports_routes


def test_get_campaigns_devuelve_nombre_objetivo_y_default_metrics(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("111", "MESSAGES")], "total_spend": 10.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    body = r.json()
    assert body["campaigns"] == [{
        "id": "111", "name": "Campaña 111", "objective": "MESSAGES",
        "default_metrics": ["impressions", "conversations", "cost_per_conversation"],
    }]


def test_get_campaigns_404_si_no_es_de_la_organizacion(client, login, tenant_a, tenant_b, factory):
    login(tenant_a.owner)
    account_ajena = factory.ad_account(tenant_b.client)
    r = client.get(f"/reports/campaigns/{account_ajena.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 404


def test_get_campaigns_503_sin_tokens(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(
        reports_routes, "resolve_tokens",
        lambda current, db: ([], "No has conectado tu Facebook y no hay tokens centrales."),
    )
    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 503


def test_get_campaigns_respeta_filtro_de_pais(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    con_pais = _fake_campaign("1", "REACH")
    con_pais["ads"] = [{"id": "ad1", "name": "Anuncio", "insights": {}, "countries": ["GT"]}]
    sin_pais_pedido = _fake_campaign("2", "REACH")
    sin_pais_pedido["ads"] = [{"id": "ad2", "name": "Anuncio", "insights": {}, "countries": ["US"]}]

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [con_pais, sin_pais_pedido], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15&country_code=GT")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["campaigns"]]
    assert ids == ["1"]


# ── POST /reports/summary reenvía la personalización ────────────────
def test_summary_reenvia_campaign_metrics_y_comentarios(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1"), _fake_campaign("2")], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id,
        "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
        "campaign_metrics": {"1": ["clicks"]},
        "campaign_comments": {"1": "Buen mes"},
        "general_comment": "Resumen del período",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["general_comment"] == "Resumen del período"
    campanas = {c["id"]: c for c in body["campaigns"]}
    assert campanas["1"]["selected_metrics"] == ["clicks"]
    assert campanas["1"]["comment"] == "Buen mes"
    assert "selected_metrics" not in campanas["2"]
