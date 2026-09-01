"""
Panel de Resumen: las campañas ACTIVA/PAUSADA sin gasto en el período NO
deben desaparecer — a diferencia del PDF (build_pdf), donde ocultarlas
evita inflar un reporte con años de historial sin actividad, en el panel
en vivo la persona quiere ver siempre sus campañas, aparezcan o no con
gasto en el rango de fechas elegido. Ver meta_api.get_account_data
(include_inactive) y app/api/routes/reports.py (/reports/summary).
"""
from __future__ import annotations

import asyncio
from datetime import date

from app.services import meta_api, report_builder


def _fake_campaigns():
    return [
        {"id": "1", "name": "Con gasto", "objective": "REACH", "status": "ACTIVE",
         "daily_budget": None, "lifetime_budget": None},
        {"id": "2", "name": "Sin gasto en el periodo", "objective": "REACH", "status": "PAUSED",
         "daily_budget": None, "lifetime_budget": None},
    ]


def _patch_meta_api(monkeypatch):
    async def fake_get_campaigns(client, token, ad_account_id):
        return _fake_campaigns()

    async def fake_run_insights_job(client, ad_account_id, token, level, fields, time_range,
                                    attribution_windows=None):
        if level != "campaign":
            return []
        # Solo la campaña "1" tuvo actividad en el período — Meta ni
        # siquiera devuelve fila para la que no tuvo gasto/impresiones.
        return [{"campaign_id": "1", "impressions": 100, "reach": 90, "spend": 10.0}]

    async def fake_get_all(client, path, token, params):
        return []  # sin anuncios: no afecta lo que se prueba aquí

    monkeypatch.setattr(meta_api, "get_campaigns", fake_get_campaigns)
    monkeypatch.setattr(meta_api, "_run_insights_job", fake_run_insights_job)
    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)


def test_get_account_data_por_defecto_descarta_campanas_sin_actividad(monkeypatch):
    _patch_meta_api(monkeypatch)
    data = asyncio.run(meta_api.get_account_data("token", "act_1", "2026-01-01", "2026-01-15"))
    ids = [c["id"] for c in data["campaigns"]]
    assert ids == ["1"]


def test_get_account_data_include_inactive_conserva_las_sin_actividad(monkeypatch):
    _patch_meta_api(monkeypatch)
    data = asyncio.run(meta_api.get_account_data(
        "token", "act_1", "2026-01-01", "2026-01-15", include_inactive=True,
    ))
    campanas = {c["id"]: c for c in data["campaigns"]}
    assert set(campanas) == {"1", "2"}
    assert campanas["2"]["spend"] == 0.0
    assert campanas["2"]["insights"] == {}
    assert campanas["2"]["status"] == "PAUSED"
    # El total sigue siendo solo el gasto real — la campaña sin actividad
    # aporta cero, no debe alterar el consumido del período.
    assert data["total_spend"] == 10.0


def test_build_report_data_reenvia_include_inactive(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)
    captured = {}

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None, include_inactive=False):
        captured["include_inactive"] = include_inactive
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15), include_inactive=True,
    ))
    assert captured["include_inactive"] is True


def test_summary_pide_include_inactive_pero_generate_no(monkeypatch, client, login, tenant_a, factory):
    """/reports/summary alimenta el panel de Resumen (siempre quiere ver
    las campañas activas/pausadas); /reports/generate arma el PDF y no
    debe heredar ese comportamiento sin querer."""
    import app.api.routes.reports as reports_routes

    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    captured = {}

    async def fake_build_report_data(*args, include_inactive=False, **kwargs):
        captured["include_inactive"] = include_inactive
        return {
            "client_name": "x", "period": "x", "campaigns": [], "total_spend": 0.0,
            "budget": None, "currency_symbol": "$", "country_code": None,
            "general_comment": None, "platform_breakdown": [],
        }

    monkeypatch.setattr(reports_routes.report_builder, "build_report_data", fake_build_report_data)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 200
    assert captured["include_inactive"] is True
