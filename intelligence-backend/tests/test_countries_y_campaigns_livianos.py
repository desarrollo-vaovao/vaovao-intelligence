"""
GET /reports/countries y GET /reports/campaigns (panel "Personalizar
métricas y observaciones") no muestran performance por anuncio, pero antes
pagaban el costo COMPLETO de un reporte: los dos jobs asíncronos de Meta
(insights por campaña Y por anuncio) más el listado de anuncios. El job
por anuncio es el más lento de los dos y ninguno de estos endpoints lo
usa — ver meta_api.get_account_data(include_ad_insights).
"""
from __future__ import annotations

import asyncio
from datetime import date

from app.services import meta_api


def _fake_campaigns():
    return [{"id": "1", "name": "Campana", "objective": "REACH", "status": "ACTIVE",
             "daily_budget": None, "lifetime_budget": None}]


def test_get_account_data_include_ad_insights_false_no_pide_el_job_de_anuncio(monkeypatch):
    levels_pedidos = []

    async def fake_get_campaigns(client, token, ad_account_id):
        return _fake_campaigns()

    async def fake_run_insights_job(client, ad_account_id, token, level, fields, time_range,
                                    attribution_windows=None):
        levels_pedidos.append(level)
        if level == "campaign":
            return [{"campaign_id": "1", "spend": 10.0}]
        return [{"ad_id": "a1", "spend": 5.0}]  # no debería llegar a pedirse

    async def fake_get_all(client, path, token, params):
        if path.endswith("/ads"):
            return [{"id": "a1", "name": "Anuncio", "campaign_id": "1", "targeting": {}}]
        return []

    monkeypatch.setattr(meta_api, "get_campaigns", fake_get_campaigns)
    monkeypatch.setattr(meta_api, "_run_insights_job", fake_run_insights_job)
    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)

    data = asyncio.run(meta_api.get_account_data(
        "token", "act_1", "2026-01-01", "2026-01-15", include_ad_insights=False,
    ))

    assert levels_pedidos == ["campaign"]  # nunca se pidió "ad"
    campaign_ads = data["campaigns"][0]["ads"]
    assert campaign_ads[0]["insights"] == {}


def test_get_account_data_include_ad_insights_true_sigue_igual_por_defecto(monkeypatch):
    """Regresión: /reports/generate y /reports/summary siguen pidiendo
    ambos jobs (default True) — no deben perder el performance por
    anuncio que sí muestran."""
    levels_pedidos = []

    async def fake_get_campaigns(client, token, ad_account_id):
        return _fake_campaigns()

    async def fake_run_insights_job(client, ad_account_id, token, level, fields, time_range,
                                    attribution_windows=None):
        levels_pedidos.append(level)
        if level == "campaign":
            return [{"campaign_id": "1", "spend": 10.0}]
        return [{"ad_id": "a1", "spend": 5.0}]

    async def fake_get_all(client, path, token, params):
        if path.endswith("/ads"):
            return [{"id": "a1", "name": "Anuncio", "campaign_id": "1", "targeting": {}}]
        return []

    monkeypatch.setattr(meta_api, "get_campaigns", fake_get_campaigns)
    monkeypatch.setattr(meta_api, "_run_insights_job", fake_run_insights_job)
    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)

    data = asyncio.run(meta_api.get_account_data("token", "act_1", "2026-01-01", "2026-01-15"))

    assert sorted(levels_pedidos) == ["ad", "campaign"]
    assert data["campaigns"][0]["ads"][0]["insights"] == {"ad_id": "a1", "spend": 5.0}


def test_get_account_data_with_fallback_reenvia_include_ad_insights(monkeypatch):
    captured = {}

    async def fake_get_account_data(token, ad_account_id, date_from, date_to,
                                    attribution_windows=None, include_inactive=False,
                                    include_ad_insights=True):
        captured["include_ad_insights"] = include_ad_insights
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data", fake_get_account_data)

    asyncio.run(meta_api.get_account_data_with_fallback(
        ["token"], "act_1", "2026-01-01", "2026-01-15", include_ad_insights=False,
    ))
    assert captured["include_ad_insights"] is False


# ── Las rutas piden la versión liviana ──────────────────────────────────
def test_ruta_countries_pide_sin_insights_de_anuncio(client, login, tenant_a, factory, monkeypatch):
    import app.api.routes.reports as reports_routes

    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    captured = {}

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None, include_inactive=False,
                                                   include_ad_insights=True):
        captured["include_ad_insights"] = include_ad_insights
        captured["include_inactive"] = include_inactive
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 200
    assert captured["include_ad_insights"] is False
    assert captured["include_inactive"] is True


def test_ruta_campaigns_pide_sin_insights_de_anuncio(client, login, tenant_a, factory, monkeypatch):
    import app.api.routes.reports as reports_routes

    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    captured = {}

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None, include_inactive=False,
                                                   include_ad_insights=True):
        captured["include_ad_insights"] = include_ad_insights
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    assert captured["include_ad_insights"] is False
