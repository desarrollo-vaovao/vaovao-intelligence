"""
/reports/summary, /reports/countries, /reports/campaigns y /check-access
esperan a Meta (puede tardar minutos en cuentas grandes) DESPUÉS de haber
terminado de usar la base de datos. Si la conexión sigue "prestada" del
pool durante esa espera, varias personas generando reportes a la vez
agotan el pool (5 + 10 de overflow = 15 como máximo) mucho antes de que
Meta responda — confirmado con una prueba de carga real contra
producción: 20 solicitudes concurrentes a un cliente pesado terminaron en
"sqlalchemy.exc.TimeoutError: QueuePool limit... connection timed out".

Estas pruebas fijan que la sesión se cierra explícitamente ANTES de la
espera larga, no después.
"""
from __future__ import annotations

import app.api.routes.reports as reports_routes
from app.services import meta_api


def _mock_close_spy(monkeypatch, db):
    """Envuelve db.close para contar cuántas veces se llamó hasta el
    momento en que se ejecuta el callback que se le pase a assert_cerrada."""
    estado = {"cierres": 0}
    original_close = db.close

    def spy_close():
        estado["cierres"] += 1
        return original_close()

    monkeypatch.setattr(db, "close", spy_close)
    return estado


def test_summary_cierra_la_bd_antes_de_esperar_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"  # evita la consulta aparte a Meta por la moneda
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    estado = _mock_close_spy(monkeypatch, db)

    cierres_al_llamar_meta = {"valor": None}

    async def fake_build_report_data(*args, **kwargs):
        cierres_al_llamar_meta["valor"] = estado["cierres"]
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
    assert cierres_al_llamar_meta["valor"] == 1


def test_countries_cierra_la_bd_antes_de_esperar_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    estado = _mock_close_spy(monkeypatch, db)

    cierres_al_llamar_meta = {"valor": None}

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        cierres_al_llamar_meta["valor"] = estado["cierres"]
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 200
    assert cierres_al_llamar_meta["valor"] == 1


def test_campaigns_cierra_la_bd_antes_de_esperar_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    estado = _mock_close_spy(monkeypatch, db)

    cierres_al_llamar_meta = {"valor": None}

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        cierres_al_llamar_meta["valor"] = estado["cierres"]
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    assert cierres_al_llamar_meta["valor"] == 1


def test_check_access_cierra_la_bd_antes_de_esperar_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    estado = _mock_close_spy(monkeypatch, db)

    cierres_al_llamar_meta = {"valor": None}

    async def fake_check_account_access_with_fallback(*args, **kwargs):
        cierres_al_llamar_meta["valor"] = estado["cierres"]
        return True, "ok"

    monkeypatch.setattr(meta_api, "check_account_access_with_fallback", fake_check_account_access_with_fallback)

    r = client.post("/reports/check-access", json={"account_id": account.id})
    assert r.status_code == 200
    assert cierres_al_llamar_meta["valor"] == 1
