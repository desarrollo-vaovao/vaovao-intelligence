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
    assert "Clics" in html_out
    assert "Alcance" not in html_out  # métrica automática de REACH, no elegida


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
