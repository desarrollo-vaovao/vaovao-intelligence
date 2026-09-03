"""
Una vez que una cuenta ya se sincronizó al menos una vez (ver
app/services/daily_sync.py, migración 0009), POST /reports/summary
contesta sumando CampaignDailyMetric/SyncedCampaign directamente -- SIN
tocar Meta ni el camino viejo de report_summary_cache, sin importar qué
rango de fechas se pida.
"""
from __future__ import annotations

from datetime import date, timedelta

import app.api.routes.reports as reports_routes
from app.models import CampaignDailyMetric, SyncedCampaign
from app.services import meta_api


def _marcar_sincronizada(db, account, hasta=None):
    account.daily_metrics_synced_until = hasta or date.today()
    db.commit()


def _campania(db, account, campaign_id, name="Campaña", objective="REACH", status="ACTIVE"):
    row = SyncedCampaign(account_id=account.id, campaign_id=campaign_id, name=name,
                         objective=objective, status=status)
    db.add(row)
    db.commit()
    return row


def _metrica(db, account, campaign_id, day, spend=10.0, impressions=100, reach=90, clicks=5):
    row = CampaignDailyMetric(account_id=account.id, campaign_id=campaign_id, date=day,
                              spend=spend, impressions=impressions, reach=reach, clicks=clicks)
    db.add(row)
    db.commit()
    return row


def _no_meta(monkeypatch):
    """Ni resolve_tokens ni ninguna llamada a meta_api deben ejecutarse por
    el camino local -- cualquier intento hace fallar la prueba."""
    def falla(*args, **kwargs):
        raise AssertionError("no debería tocar Meta para una cuenta ya sincronizada")

    monkeypatch.setattr(reports_routes, "resolve_tokens", falla)
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", falla)


def test_suma_solo_los_dias_dentro_del_rango_pedido(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    _marcar_sincronizada(db, account)
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 8, 1), spend=10.0)
    _metrica(db, account, "1", date(2026, 8, 2), spend=5.0)
    _metrica(db, account, "1", date(2026, 9, 1), spend=100.0)  # fuera del rango pedido
    _no_meta(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "USD",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["total_spend"] == 15.0
    assert body["campaigns"][0]["spend"] == 15.0


def test_campana_activa_sin_gasto_en_el_rango_igual_aparece(monkeypatch, client, login, tenant_a, factory, db):
    """Paridad con include_inactive del camino viejo: una campaña
    ACTIVA/PAUSADA sin ningún día de gasto en el rango elegido no debe
    desaparecer del listado."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    _marcar_sincronizada(db, account)
    _campania(db, account, "1", name="Sin gasto este mes")
    _no_meta(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "USD",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["campaigns"]) == 1
    assert body["campaigns"][0]["spend"] == 0.0


def test_campana_archivada_no_aparece(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    _marcar_sincronizada(db, account)
    _campania(db, account, "1", status="ACTIVE")
    _campania(db, account, "2", status="ARCHIVED")
    _metrica(db, account, "1", date(2026, 8, 1), spend=10.0)
    _metrica(db, account, "2", date(2026, 8, 1), spend=999.0)
    _no_meta(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "USD",
    })
    assert r.status_code == 200
    body = r.json()
    assert [c["id"] for c in body["campaigns"]] == ["1"]
    assert body["total_spend"] == 10.0


def test_convierte_moneda_igual_que_el_camino_viejo(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    _marcar_sincronizada(db, account)
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 8, 1), spend=100.0)
    _no_meta(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "GTQ",
    })
    assert r.status_code == 200
    # Sin tipo de cambio configurado: usa el respaldo (7.75).
    assert r.json()["total_spend"] == 775.0


def test_presupuesto_y_personalizacion_se_aplican_igual(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    _marcar_sincronizada(db, account)
    _campania(db, account, "1")
    _metrica(db, account, "1", date(2026, 8, 1), spend=10.0)
    _no_meta(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "USD", "budget": 200,
        "campaign_metrics": {"1": ["clicks"]}, "campaign_comments": {"1": "Buen mes"},
        "general_comment": "Resumen de agosto",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["budget"] == 200
    assert body["campaigns"][0]["selected_metrics"] == ["clicks"]
    assert body["campaigns"][0]["comment"] == "Buen mes"
    assert body["general_comment"] == "Resumen de agosto"


def test_cuenta_sin_sincronizar_sigue_el_camino_viejo(monkeypatch, client, login, tenant_a, factory, db):
    """Regresión: una cuenta que TODAVÍA no se ha sincronizado nunca
    (daily_metrics_synced_until es None) no debe intentar leer de las
    tablas nuevas -- sigue exactamente el comportamiento de antes."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    db.commit()
    assert account.daily_metrics_synced_until is None

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": [{"id": "1", "name": "x", "objective": "REACH", "status": "ACTIVE",
                              "spend": 42.0, "insights": {}, "ads": []}], "total_spend": 42.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-08-01", "date_to": "2026-08-31",
        "currency": "USD",
    })
    assert r.status_code == 200
    assert r.json()["total_spend"] == 42.0
