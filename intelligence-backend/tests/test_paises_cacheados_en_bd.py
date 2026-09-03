"""
GET /reports/countries guarda su resultado en ad_accounts.cached_countries
(migración 0006) y solo vuelve a pedirle a Meta cuando pasó
_COUNTRIES_CACHE_TTL desde la última vez -- el targeting de una cuenta
cambia con muy poca frecuencia comparado con el gasto, así que no hace
falta ir a Meta cada vez que alguien abre el selector de país.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.api.routes.reports as reports_routes
from app.models import AdAccount
from app.services import meta_api


def _fake_meta_data(countries: list[str]):
    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {
            "campaigns": [
                {"ads": [{"countries": countries}]},
            ],
            "total_spend": 0.0,
        }
    return fake_get_account_data_with_fallback


def test_sin_cache_previa_consulta_a_meta_y_la_guarda(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data(["GT", "MX"]))

    account_id = account.id
    r = client.get(f"/reports/countries/{account_id}")
    assert r.status_code == 200
    assert r.json()["countries"] == ["GT", "MX"]

    # La ruta cierra `db` antes de llamar a Meta (para no acaparar el pool),
    # lo que desprende a `account` de la sesión -- se relee por id para ver
    # lo que de verdad quedó guardado.
    refreshed = db.get(AdAccount, account_id)
    assert refreshed.cached_countries == ["GT", "MX"]
    assert refreshed.cached_countries_updated_at is not None


def test_con_cache_fresca_no_llama_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.cached_countries = ["GT"]
    account.cached_countries_updated_at = datetime.now(timezone.utc)
    db.commit()

    def fake_get_account_data_with_fallback(*args, **kwargs):
        raise AssertionError("no debería llamar a Meta con una caché fresca")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 200
    assert r.json()["countries"] == ["GT"]


def test_con_cache_vencida_vuelve_a_consultar_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.cached_countries = ["GT"]
    account.cached_countries_updated_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data(["MX", "PA"]))

    account_id = account.id
    r = client.get(f"/reports/countries/{account_id}")
    assert r.status_code == 200
    assert r.json()["countries"] == ["MX", "PA"]

    refreshed = db.get(AdAccount, account_id)
    assert refreshed.cached_countries == ["MX", "PA"]


def test_meta_falla_pero_hay_cache_vieja_devuelve_esa(monkeypatch, client, login, tenant_a, factory, db):
    """Mejor mostrar la última lista conocida (aunque esté vencida) que
    nada — el selector sigue siendo útil."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.cached_countries = ["GT"]
    account.cached_countries_updated_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 200
    assert r.json()["countries"] == ["GT"]


def test_meta_falla_sin_cache_previa_devuelve_503(monkeypatch, client, login, tenant_a, factory):
    """Regresión: sin ninguna lista guardada, un fallo de Meta se sigue
    viendo (no hay nada de respaldo que mostrar)."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 503


def test_sin_tokens_pero_con_cache_vieja_devuelve_esa(client, login, tenant_a, factory, db, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.cached_countries = ["GT"]
    account.cached_countries_updated_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db.commit()

    monkeypatch.setattr(
        reports_routes, "resolve_tokens",
        lambda current, db: ([], "No has conectado tu Facebook y no hay tokens centrales."),
    )

    r = client.get(f"/reports/countries/{account.id}")
    assert r.status_code == 200
    assert r.json()["countries"] == ["GT"]
