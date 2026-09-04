"""
GET /reports/campaigns (panel de "Personalizar métricas") también contesta
desde CampaignDailyMetric/SyncedCampaign cuando no hay filtro de país y la
cuenta ya cubre el rango pedido -- el mismo patrón que /reports/summary
(ver app/services/daily_sync.py). Con filtro de país, o fuera de la
ventana sincronizada, sigue el camino viejo (report_campaigns_cache).
"""
from __future__ import annotations

from datetime import date, timedelta

import app.api.routes.reports as reports_routes
from app.models import CampaignDailyMetric, ReportCampaignsCache, SyncedCampaign
from app.services import meta_api


def _marcar_sincronizada(db, account, desde=None, hasta=None):
    account.daily_metrics_synced_since = desde or date(2020, 1, 1)
    account.daily_metrics_synced_until = hasta or date.today()
    db.commit()


def _campania(db, account, campaign_id, name="Campaña", objective="REACH"):
    row = SyncedCampaign(account_id=account.id, campaign_id=campaign_id, name=name,
                         objective=objective, status="ACTIVE")
    db.add(row)
    db.commit()
    return row


def _metrica(db, account, campaign_id, day, spend=10.0, impressions=100):
    row = CampaignDailyMetric(account_id=account.id, campaign_id=campaign_id, date=day,
                              spend=spend, impressions=impressions, reach=0, clicks=0)
    db.add(row)
    db.commit()
    return row


def _no_meta(monkeypatch):
    def falla(*args, **kwargs):
        raise AssertionError("no debería tocar Meta para una cuenta ya sincronizada")

    monkeypatch.setattr(reports_routes, "resolve_tokens", falla)
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", falla)


def test_sin_filtro_de_pais_contesta_desde_lo_sincronizado(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    _marcar_sincronizada(db, account)
    _campania(db, account, "1", name="Con gasto")
    _campania(db, account, "2", name="Sin gasto en el rango")
    _metrica(db, account, "1", date(2026, 8, 1), spend=10.0)
    _no_meta(monkeypatch)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-08-01&date_to=2026-08-31")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["campaigns"]]
    assert ids == ["1"]


def test_no_escribe_en_report_campaigns_cache(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    _marcar_sincronizada(db, account)
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 8, 1))
    _no_meta(monkeypatch)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-08-01&date_to=2026-08-31")
    assert r.status_code == 200
    assert db.query(ReportCampaignsCache).filter_by(account_id=account.id).count() == 0


def test_con_filtro_de_pais_sigue_el_camino_viejo(monkeypatch, client, login, tenant_a, factory, db):
    """Las tablas de sincronización diaria son por campaña, no por
    anuncio/país -- un filtro de país no se puede resolver ahí."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    _marcar_sincronizada(db, account)
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 8, 1), spend=999.0)

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": [{"id": "2", "name": "De Meta", "objective": "REACH",
                              "ads": [{"countries": ["GT"]}]}], "total_spend": 5.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-08-01&date_to=2026-08-31&country_code=GT")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["2"]


def test_rango_anterior_al_backfill_sigue_el_camino_viejo(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    _marcar_sincronizada(db, account, desde=date(2026, 6, 1))
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 1, 15), spend=999.0)

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": [{"id": "2", "name": "De Meta", "objective": "REACH", "ads": []}],
               "total_spend": 5.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-31")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["2"]


def test_cuenta_sin_sincronizar_sigue_el_camino_viejo(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    assert account.daily_metrics_synced_until is None

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": [{"id": "2", "name": "De Meta", "objective": "REACH", "ads": []}],
               "total_spend": 5.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-08-01&date_to=2026-08-31")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["campaigns"]] == ["2"]
