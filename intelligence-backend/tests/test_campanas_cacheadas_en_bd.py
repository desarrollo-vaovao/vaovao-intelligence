"""
GET /reports/campaigns guarda su resultado en report_campaigns_cache
(migración 0007), por combinación exacta de (cuenta, date_from, date_to,
país). Un período ya cerrado se sirve para siempre sin volver a llamar a
Meta -- Meta no reescribe el historial. Un período que todavía incluye
hoy se refresca cada _CAMPAIGNS_CACHE_TTL, para que una campaña nueva no
tarde en aparecer en el panel de "Personalizar métricas".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import app.api.routes.reports as reports_routes
from app.models import ReportCampaignsCache
from app.services import meta_api


def _fake_meta_data(campaigns: list[dict]):
    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": campaigns, "total_spend": 0.0}
    return fake_get_account_data_with_fallback


def _campania(id_, name="Campaña", objective="OUTCOME_TRAFFIC", countries=None):
    ads = [{"id": f"ad-{id_}", "countries": countries}] if countries else []
    return {"id": id_, "name": name, "objective": objective, "ads": ads}


def test_periodo_cerrado_sin_cache_previa_consulta_a_meta_y_la_guarda(
    monkeypatch, client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data([_campania("1")]))

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["1"]

    row = db.query(ReportCampaignsCache).filter_by(account_id=account.id).one()
    assert row.date_from == date(2026, 1, 1)
    assert row.date_to == date(2026, 1, 15)
    assert row.country_code == ""
    assert [c["id"] for c in row.campaigns] == ["1"]


def test_periodo_cerrado_con_cache_nunca_vuelve_a_llamar_a_meta(
    monkeypatch, client, login, tenant_a, factory, db,
):
    """Aunque la fila lleve mucho tiempo sin refrescarse -- un período
    cerrado no tiene TTL, Meta no le va a cambiar los datos."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    db.add(ReportCampaignsCache(
        account_id=account.id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 15),
        country_code="", campaigns=[{"id": "1", "name": "Vieja", "objective": "DEFAULT", "default_metrics": []}],
        updated_at=datetime.now(timezone.utc) - timedelta(days=400),
    ))
    db.commit()

    def fake_falla(*args, **kwargs):
        raise AssertionError("no debería llamar a Meta con un período cerrado ya cacheado")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["1"]


def test_periodo_abierto_con_cache_fresca_no_llama_a_meta(
    monkeypatch, client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    hoy = date.today()
    db.add(ReportCampaignsCache(
        account_id=account.id, date_from=hoy - timedelta(days=5), date_to=hoy,
        country_code="", campaigns=[{"id": "1", "name": "Actual", "objective": "DEFAULT", "default_metrics": []}],
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()

    def fake_falla(*args, **kwargs):
        raise AssertionError("no debería llamar a Meta con una caché fresca")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(
        f"/reports/campaigns/{account.id}?date_from={(hoy - timedelta(days=5)).isoformat()}&date_to={hoy.isoformat()}"
    )
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["1"]


def test_periodo_abierto_con_cache_vencida_vuelve_a_consultar_a_meta(
    monkeypatch, client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    hoy = date.today()
    db.add(ReportCampaignsCache(
        account_id=account.id, date_from=hoy - timedelta(days=5), date_to=hoy,
        country_code="", campaigns=[{"id": "1", "name": "Vieja", "objective": "DEFAULT", "default_metrics": []}],
        updated_at=datetime.now(timezone.utc) - timedelta(hours=48),
    ))
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(
        meta_api, "get_account_data_with_fallback",
        _fake_meta_data([_campania("1"), _campania("2", "Nueva")]),
    )

    r = client.get(
        f"/reports/campaigns/{account.id}?date_from={(hoy - timedelta(days=5)).isoformat()}&date_to={hoy.isoformat()}"
    )
    assert r.status_code == 200
    assert sorted(c["id"] for c in r.json()["campaigns"]) == ["1", "2"]


def test_meta_falla_pero_hay_cache_vieja_devuelve_esa(
    monkeypatch, client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    hoy = date.today()
    db.add(ReportCampaignsCache(
        account_id=account.id, date_from=hoy - timedelta(days=5), date_to=hoy,
        country_code="", campaigns=[{"id": "1", "name": "Vieja", "objective": "DEFAULT", "default_metrics": []}],
        updated_at=datetime.now(timezone.utc) - timedelta(hours=48),
    ))
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(
        f"/reports/campaigns/{account.id}?date_from={(hoy - timedelta(days=5)).isoformat()}&date_to={hoy.isoformat()}"
    )
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["1"]


def test_meta_falla_sin_cache_previa_devuelve_503(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 503


def test_distintos_paises_no_comparten_cache(monkeypatch, client, login, tenant_a, factory, db):
    """Filtrar por país cambia qué campañas tienen datos -- cada país
    necesita su propia fila, no puede compartir la de "todos"."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    db.add(ReportCampaignsCache(
        account_id=account.id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 15),
        country_code="", campaigns=[{"id": "1", "name": "Todos", "objective": "DEFAULT", "default_metrics": []}],
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(
        meta_api, "get_account_data_with_fallback",
        _fake_meta_data([_campania("2", countries=["GT"])]),
    )

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15&country_code=GT")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["2"]

    rows = db.query(ReportCampaignsCache).filter_by(account_id=account.id).all()
    assert {row.country_code for row in rows} == {"", "GT"}
