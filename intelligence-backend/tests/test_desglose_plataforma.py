"""
Resumen "Facebook vs Instagram" al final del reporte — en qué plataforma de
publicación se fue el gasto de la cuenta en el período, además de por
campaña. Ver report_builder._aggregate_platform_breakdown y
pdf_generator._platform_breakdown_block.
"""
from __future__ import annotations

import asyncio
from datetime import date

from app.services import meta_api, pdf_generator, report_builder

# Referencia capturada ANTES de que el autouse de conftest (ver
# _sin_llamada_real_de_desglose_por_plataforma) reemplace
# meta_api.get_platform_breakdown por un mock — así esta prueba puede
# ejercitar la función real sin pelear con ese default de seguridad.
_real_get_platform_breakdown = meta_api.get_platform_breakdown


def _fake_campaign(cid: str) -> dict:
    return {
        "id": cid, "name": f"Campaña {cid}", "objective": "REACH",
        "status": "ACTIVE", "spend": 10.0,
        "insights": {"impressions": 100, "reach": 90},
        "ads": [],
    }


# ── _aggregate_platform_breakdown ─────────────────────────────────────
def test_aggregate_suma_por_plataforma_y_descarta_lo_desconocido():
    rows = [
        {"publisher_platform": "facebook", "spend": "6", "impressions": "100", "reach": "80", "clicks": "3"},
        {"publisher_platform": "facebook", "spend": "4", "impressions": "50", "reach": "40", "clicks": "1"},
        {"publisher_platform": "instagram", "spend": "2", "impressions": "30", "reach": "25", "clicks": "1"},
        {"publisher_platform": "unknown_future_platform", "spend": "99", "impressions": "1", "reach": "1", "clicks": "1"},
    ]
    result = report_builder._aggregate_platform_breakdown(rows)
    assert result == [
        {"platform": "facebook", "label": "Facebook", "spend": 10.0, "impressions": 150, "reach": 120, "clicks": 4},
        {"platform": "instagram", "label": "Instagram", "spend": 2.0, "impressions": 30, "reach": 25, "clicks": 1},
    ]


def test_aggregate_omite_plataformas_sin_gasto():
    """Una fila con spend=0 (Meta a veces la manda igual) no debe generar
    una fila vacía en el resumen."""
    rows = [{"publisher_platform": "messenger", "spend": "0", "impressions": "5", "reach": "5", "clicks": "0"}]
    assert report_builder._aggregate_platform_breakdown(rows) == []


def test_aggregate_lista_vacia_si_meta_no_devuelve_nada():
    assert report_builder._aggregate_platform_breakdown([]) == []


# ── _convert_platform_breakdown ────────────────────────────────────────
def test_convert_platform_breakdown_solo_toca_spend():
    breakdown = [{"platform": "facebook", "label": "Facebook", "spend": 10.0, "impressions": 100, "reach": 90, "clicks": 5}]
    converted = report_builder._convert_platform_breakdown(breakdown, factor=7.75)
    assert converted == [{"platform": "facebook", "label": "Facebook", "spend": 77.5, "impressions": 100, "reach": 90, "clicks": 5}]


# ── build_report_data: wiring end-to-end ───────────────────────────────
def test_build_report_data_incluye_el_desglose_por_plataforma(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1")], "total_spend": 10.0}

    async def fake_get_platform_breakdown_with_fallback(tokens, ad_account_id, date_from, date_to):
        return [
            {"publisher_platform": "facebook", "spend": "7", "impressions": "70", "reach": "60", "clicks": "2"},
            {"publisher_platform": "instagram", "spend": "3", "impressions": "30", "reach": "25", "clicks": "1"},
        ]

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)
    monkeypatch.setattr(meta_api, "get_platform_breakdown_with_fallback", fake_get_platform_breakdown_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
    ))

    assert result["platform_breakdown"] == [
        {"platform": "facebook", "label": "Facebook", "spend": 7.0, "impressions": 70, "reach": 60, "clicks": 2},
        {"platform": "instagram", "label": "Instagram", "spend": 3.0, "impressions": 30, "reach": 25, "clicks": 1},
    ]


def test_build_report_data_sin_gasto_no_pide_el_desglose(monkeypatch, tenant_a, factory):
    """Una cuenta sin actividad en el período no debería generar una
    llamada extra a Meta que de todos modos volvería vacía."""
    account = factory.ad_account(tenant_a.client)
    llamadas = []

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [], "total_spend": 0.0}

    async def fake_get_platform_breakdown_with_fallback(tokens, ad_account_id, date_from, date_to):
        llamadas.append(1)
        return []

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)
    monkeypatch.setattr(meta_api, "get_platform_breakdown_with_fallback", fake_get_platform_breakdown_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
    ))

    assert result["platform_breakdown"] == []
    assert llamadas == []


def test_build_report_data_con_filtro_de_pais_omite_el_desglose(monkeypatch, tenant_a, factory):
    """Meta no permite cruzar publisher_platform con country (ver
    meta_api.get_platform_breakdown) — con un filtro de país activo, el
    desglose se omite del todo en vez de mostrar un total de TODA la
    cuenta que no coincidiría con las campañas ya filtradas por país."""
    account = factory.ad_account(tenant_a.client)
    llamadas = []

    campaign_con_pais = _fake_campaign("1")
    campaign_con_pais["ads"] = [{"id": "ad1", "name": "Anuncio", "insights": {}, "countries": ["GT"]}]

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [campaign_con_pais], "total_spend": 10.0}

    async def fake_get_platform_breakdown_with_fallback(tokens, ad_account_id, date_from, date_to):
        llamadas.append(1)
        return [{"publisher_platform": "facebook", "spend": "10"}]

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)
    monkeypatch.setattr(meta_api, "get_platform_breakdown_with_fallback", fake_get_platform_breakdown_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15), country_code="GT",
    ))

    assert result["platform_breakdown"] == []
    assert llamadas == []


def test_build_report_data_si_el_desglose_falla_el_reporte_sigue(monkeypatch, tenant_a, factory):
    """El desglose Facebook/Instagram es un extra sobre el reporte, no su
    corazón: un error de Meta al pedirlo (rate limit puntual, etc.) no debe
    tirar todo el reporte, que ya tiene los datos de campañas."""
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1")], "total_spend": 10.0}

    async def fake_get_platform_breakdown_with_fallback(tokens, ad_account_id, date_from, date_to):
        raise meta_api.MetaApiError("rate limit")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)
    monkeypatch.setattr(meta_api, "get_platform_breakdown_with_fallback", fake_get_platform_breakdown_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
    ))

    assert result["platform_breakdown"] == []
    assert result["campaigns"][0]["id"] == "1"


def test_build_report_data_convierte_el_spend_del_desglose(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1")], "total_spend": 10.0}

    async def fake_get_platform_breakdown_with_fallback(tokens, ad_account_id, date_from, date_to):
        return [{"publisher_platform": "facebook", "spend": "10", "impressions": "1", "reach": "1", "clicks": "1"}]

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)
    monkeypatch.setattr(meta_api, "get_platform_breakdown_with_fallback", fake_get_platform_breakdown_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
        source_currency="USD", currency="GTQ", exchange_rate=7.75,
    ))

    assert result["platform_breakdown"][0]["spend"] == 77.5


# ── meta_api.get_platform_breakdown: parámetros que le manda a Meta ────
def test_get_platform_breakdown_manda_solo_publisher_platform(monkeypatch):
    """SIN country: combinar publisher_platform+country hace que Meta
    rechace la petición con '(#100) Current combination of data breakdown
    columns ... is invalid' — confirmado contra una cuenta real."""
    captured = {}

    async def fake_get_all(client, path, token, params):
        captured.update(params)
        captured["path"] = path
        return [{"publisher_platform": "facebook", "spend": "1"}]

    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)

    result = asyncio.run(_real_get_platform_breakdown(
        "token", "act_1", "2026-01-01", "2026-01-15",
    ))

    assert captured["breakdowns"] == "publisher_platform"
    assert captured["level"] == "account"
    assert captured["path"] == "act_1/insights"
    assert result == [{"publisher_platform": "facebook", "spend": "1"}]


def test_get_platform_breakdown_with_fallback_prueba_el_siguiente_token(monkeypatch):
    async def fake_get_platform_breakdown(token, ad_account_id, date_from, date_to):
        if token == "malo":
            raise meta_api.MetaApiError("sin acceso")
        return [{"publisher_platform": "facebook", "spend": "5"}]

    monkeypatch.setattr(meta_api, "get_platform_breakdown", fake_get_platform_breakdown)

    result = asyncio.run(meta_api.get_platform_breakdown_with_fallback(
        ["malo", "bueno"], "act_1", "2026-01-01", "2026-01-15",
    ))
    assert result == [{"publisher_platform": "facebook", "spend": "5"}]


# ── pdf_generator: la sección aparece (o no) en el HTML ────────────────
def test_platform_breakdown_block_vacio_sin_datos():
    assert pdf_generator._platform_breakdown_block([], 0, "$") == ""


def test_platform_breakdown_block_incluye_ambas_plataformas():
    breakdown = [
        {"platform": "facebook", "label": "Facebook", "spend": 70.0, "impressions": 700, "reach": 600, "clicks": 20},
        {"platform": "instagram", "label": "Instagram", "spend": 30.0, "impressions": 300, "reach": 250, "clicks": 10},
    ]
    html_block = pdf_generator._platform_breakdown_block(breakdown, 100.0, "$")
    assert "Facebook vs Instagram" in html_block
    assert "Facebook" in html_block and "Instagram" in html_block
    assert "$70.00" in html_block and "$30.00" in html_block
    assert "70.00%" in html_block and "30.00%" in html_block


def test_render_report_page_incluye_el_bloque_cuando_hay_desglose():
    report_data = {
        "client_name": "Cliente X", "period": "1 – 15 ene 2026",
        "campaigns": [], "total_spend": 10.0, "budget": None,
        "platform_breakdown": [
            {"platform": "instagram", "label": "Instagram", "spend": 10.0, "impressions": 100, "reach": 90, "clicks": 5},
        ],
    }
    html_page = pdf_generator.render_report_page(report_data, "$")
    assert "Facebook vs Instagram" in html_page


def test_render_report_page_sin_desglose_no_muestra_la_seccion():
    report_data = {
        "client_name": "Cliente X", "period": "1 – 15 ene 2026",
        "campaigns": [], "total_spend": 0, "budget": None,
        "platform_breakdown": [],
    }
    html_page = pdf_generator.render_report_page(report_data, "$")
    assert "Facebook vs Instagram" not in html_page
