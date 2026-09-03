"""
app/services/daily_sync.py trae el gasto DIARIO por campaña de cada cuenta
en segundo plano y lo guarda en CampaignDailyMetric/SyncedCampaign
(migración 0009) -- la pieza que permite que Resumen conteste cualquier
rango de fechas sumando de la base de datos, sin volver a tocar a Meta por
cada mes o quincena que alguien elija.

`daily_sync.sync_account` usa `SessionLocal()` directamente (corre en
segundo plano, sin un request ni una sesión de prueba que heredar) -- la
fixture `_usa_bd_de_pruebas` de este archivo apunta esa SessionLocal al
mismo motor de pruebas que usan `db`/`factory`, para poder verificar sus
escrituras de principio a fin.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core import crypto
import app.services.daily_sync as daily_sync
from app.models import CampaignDailyMetric, MetaCentralToken, SyncedCampaign
from app.services import meta_api


@pytest.fixture(autouse=True)
def _usa_bd_de_pruebas(monkeypatch, engine):
    monkeypatch.setattr(daily_sync, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False))


def _fake_data(campaigns, daily):
    async def fake(*args, **kwargs):
        return {"campaigns": campaigns, "daily": daily}
    return fake


def _central_token(db, org, label="Central"):
    token = MetaCentralToken(org_id=org.id, label=label, token_encrypted=crypto.encrypt("token-de-prueba"))
    db.add(token)
    db.commit()
    return token


def test_sin_token_central_no_hace_nada(tenant_a, factory, db):
    account = factory.ad_account(tenant_a.client)
    ok = asyncio.run(daily_sync.sync_account(account.id))
    assert ok is False
    db.refresh(account)
    assert account.daily_metrics_synced_until is None


def test_primera_vez_trae_los_ultimos_backfill_days(monkeypatch, tenant_a, factory, db):
    account = factory.ad_account(tenant_a.client)
    _central_token(db, tenant_a.org)

    captured = {}

    async def fake_get_daily_campaign_data_with_fallback(tokens, ad_account_id, date_from, date_to):
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        return {
            "campaigns": [{"id": "1", "name": "Campaña 1", "objective": "REACH", "status": "ACTIVE"}],
            "daily": [{"campaign_id": "1", "date": "2026-08-01", "spend": 12.5,
                      "impressions": 100, "reach": 90, "clicks": 5}],
        }

    monkeypatch.setattr(meta_api, "get_daily_campaign_data_with_fallback",
                        fake_get_daily_campaign_data_with_fallback)

    ok = asyncio.run(daily_sync.sync_account(account.id))
    assert ok is True

    today = date.today()
    assert captured["date_from"] == (today - timedelta(days=daily_sync.BACKFILL_DAYS)).isoformat()
    assert captured["date_to"] == today.isoformat()

    db.refresh(account)
    assert account.daily_metrics_synced_until == today

    synced = db.query(SyncedCampaign).filter_by(account_id=account.id, campaign_id="1").one()
    assert synced.name == "Campaña 1"
    assert synced.objective == "REACH"
    assert synced.status == "ACTIVE"

    metric = db.query(CampaignDailyMetric).filter_by(
        account_id=account.id, campaign_id="1", date=date(2026, 8, 1),
    ).one()
    assert metric.spend == 12.5
    assert metric.impressions == 100


def test_segunda_vez_trae_desde_lo_ya_sincronizado_con_solapamiento(monkeypatch, tenant_a, factory, db):
    account = factory.ad_account(tenant_a.client)
    account.daily_metrics_synced_until = date.today() - timedelta(days=10)
    db.commit()
    _central_token(db, tenant_a.org)

    captured = {}

    async def fake(tokens, ad_account_id, date_from, date_to):
        captured["date_from"] = date_from
        return {"campaigns": [], "daily": []}

    monkeypatch.setattr(meta_api, "get_daily_campaign_data_with_fallback", fake)

    asyncio.run(daily_sync.sync_account(account.id))

    esperado = date.today() - timedelta(days=10) - timedelta(days=daily_sync.OVERLAP_DAYS)
    assert captured["date_from"] == esperado.isoformat()


def test_sincronizar_dos_veces_actualiza_en_vez_de_duplicar(monkeypatch, tenant_a, factory, db):
    account = factory.ad_account(tenant_a.client)
    _central_token(db, tenant_a.org)

    monkeypatch.setattr(meta_api, "get_daily_campaign_data_with_fallback", _fake_data(
        [{"id": "1", "name": "Vieja", "objective": "REACH", "status": "ACTIVE"}],
        [{"campaign_id": "1", "date": "2026-08-01", "spend": 10.0, "impressions": 50, "reach": 40, "clicks": 2}],
    ))
    asyncio.run(daily_sync.sync_account(account.id))

    monkeypatch.setattr(meta_api, "get_daily_campaign_data_with_fallback", _fake_data(
        [{"id": "1", "name": "Nueva", "objective": "REACH", "status": "PAUSED"}],
        [{"campaign_id": "1", "date": "2026-08-01", "spend": 15.0, "impressions": 60, "reach": 45, "clicks": 3}],
    ))
    asyncio.run(daily_sync.sync_account(account.id))

    assert db.query(SyncedCampaign).filter_by(account_id=account.id).count() == 1
    assert db.query(CampaignDailyMetric).filter_by(account_id=account.id).count() == 1

    synced = db.query(SyncedCampaign).filter_by(account_id=account.id, campaign_id="1").one()
    assert synced.name == "Nueva"
    assert synced.status == "PAUSED"

    metric = db.query(CampaignDailyMetric).filter_by(account_id=account.id, campaign_id="1").one()
    assert metric.spend == 15.0


def test_meta_falla_no_actualiza_synced_until(monkeypatch, tenant_a, factory, db):
    account = factory.ad_account(tenant_a.client)
    _central_token(db, tenant_a.org)

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_daily_campaign_data_with_fallback", fake_falla)

    ok = asyncio.run(daily_sync.sync_account(account.id))
    assert ok is False

    db.refresh(account)
    assert account.daily_metrics_synced_until is None


def test_sync_account_safely_no_deja_escapar_excepciones_inesperadas(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)

    async def fake_revienta(_account_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(daily_sync, "sync_account", fake_revienta)

    # No debe lanzar -- si lo hiciera, tumbaría el bucle run_forever completo.
    asyncio.run(daily_sync._sync_account_safely(account.id))
