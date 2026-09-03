"""
POST /reports/summary alimenta el panel de Resumen y ahora se guarda en
report_summary_cache (migración 0008), por (cuenta, rango de fechas,
moneda, país): a diferencia de países y campañas, el gasto de un período
que incluye hoy sigue cambiando en vivo, así que esta caché NUNCA se sirve
"para siempre" — siempre se devuelve al instante desde la base de datos, y
si tiene más de _SUMMARY_CACHE_TTL se dispara un refresco en segundo plano
para la PRÓXIMA visita, sin que quien pidió el resumen esta vez tenga que
esperarlo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.api.routes.reports as reports_routes
from app.models import ReportSummaryCache
from app.services import meta_api


def _fake_campaign(cid: str, spend: float = 10.0) -> dict:
    return {
        "id": cid, "name": f"Campaña {cid}", "objective": "REACH",
        "status": "ACTIVE", "spend": spend,
        "insights": {"impressions": 100, "reach": 90, "clicks": 5, "ctr": 5.0},
        "ads": [],
    }


def _fake_meta_data(campaigns: list[dict], total_spend: float):
    async def fake_get_account_data_with_fallback(*args, **kwargs):
        return {"campaigns": campaigns, "total_spend": total_spend}
    return fake_get_account_data_with_fallback


def _no_background_refresh(monkeypatch):
    """Evita que la prueba dispare de verdad la tarea en segundo plano
    (que abriría su propia sesión y llamaría a Meta) — solo interesa
    verificar que SE HAYA disparado, no lo que hace."""
    llamadas = []

    def fake_create_task(coro):
        llamadas.append(coro)
        coro.close()  # nunca se ejecuta: evita el warning "never awaited"
        return None

    monkeypatch.setattr(reports_routes.asyncio, "create_task", fake_create_task)
    return llamadas


def test_sin_cache_previa_consulta_a_meta_y_la_guarda(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    db.commit()
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data([_fake_campaign("1")], 10.0))

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 200
    assert r.json()["total_spend"] == 10.0

    row = db.query(ReportSummaryCache).filter_by(account_id=account.id).one()
    assert row.currency == "USD"
    assert row.country_code == ""
    assert row.payload["total_spend"] == 10.0


def test_con_cache_fresca_no_llama_a_meta(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    db.add(ReportSummaryCache(
        account_id=account.id, date_from=datetime(2026, 1, 1).date(), date_to=datetime(2026, 1, 15).date(),
        currency="USD", country_code="",
        payload={
            "client_name": "x", "period": "x", "campaigns": [_fake_campaign("1")], "total_spend": 10.0,
            "budget": None, "currency_symbol": "$", "country_code": None,
            "general_comment": None, "platform_breakdown": [],
        },
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()

    def fake_falla(*args, **kwargs):
        raise AssertionError("no debería llamar a Meta con una caché fresca")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 200
    assert r.json()["total_spend"] == 10.0


def test_con_cache_vencida_devuelve_lo_cacheado_y_agenda_refresco(
    monkeypatch, client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    db.add(ReportSummaryCache(
        account_id=account.id, date_from=datetime(2026, 1, 1).date(), date_to=datetime(2026, 1, 15).date(),
        currency="USD", country_code="",
        payload={
            "client_name": "x", "period": "x", "campaigns": [_fake_campaign("1")], "total_spend": 10.0,
            "budget": None, "currency_symbol": "$", "country_code": None,
            "general_comment": None, "platform_breakdown": [],
        },
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    ))
    db.commit()
    llamadas = _no_background_refresh(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 200
    # Responde al instante con lo que ya había, no espera el refresco.
    assert r.json()["total_spend"] == 10.0
    assert len(llamadas) == 1


def test_con_cache_fresca_no_agenda_refresco(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    db.add(ReportSummaryCache(
        account_id=account.id, date_from=datetime(2026, 1, 1).date(), date_to=datetime(2026, 1, 15).date(),
        currency="USD", country_code="",
        payload={
            "client_name": "x", "period": "x", "campaigns": [], "total_spend": 0.0,
            "budget": None, "currency_symbol": "$", "country_code": None,
            "general_comment": None, "platform_breakdown": [],
        },
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    llamadas = _no_background_refresh(monkeypatch)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 200
    assert len(llamadas) == 0


def test_presupuesto_y_personalizacion_no_se_guardan_en_la_cache(
    monkeypatch, client, login, tenant_a, factory, db,
):
    """El presupuesto y selected_metrics/comment son de ESTA petición, no
    de Meta -- si se guardaran en la caché, la personalización de quien
    pidió el resumen primero se le quedaría pegada a todos los demás."""
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    db.commit()
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data([_fake_campaign("1")], 10.0))

    r1 = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD", "budget": 500,
        "campaign_metrics": {"1": ["clicks"]}, "campaign_comments": {"1": "Buen mes"},
        "general_comment": "Resumen del período",
    })
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["budget"] == 500
    assert body1["campaigns"][0]["selected_metrics"] == ["clicks"]
    assert body1["general_comment"] == "Resumen del período"

    row = db.query(ReportSummaryCache).filter_by(account_id=account.id).one()
    assert row.payload["budget"] is None
    assert "selected_metrics" not in row.payload["campaigns"][0]
    assert row.payload["general_comment"] is None

    # Alguien más pide el mismo resumen sin presupuesto ni personalización
    # -- no debe ver NADA de lo que puso la primera persona.
    r2 = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["budget"] is None
    assert "selected_metrics" not in body2["campaigns"][0]
    assert body2["general_comment"] is None


def test_distinta_moneda_no_comparte_cache(monkeypatch, client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    db.commit()
    db.add(ReportSummaryCache(
        account_id=account.id, date_from=datetime(2026, 1, 1).date(), date_to=datetime(2026, 1, 15).date(),
        currency="USD", country_code="",
        payload={
            "client_name": "x", "period": "x", "campaigns": [_fake_campaign("1", 10.0)], "total_spend": 10.0,
            "budget": None, "currency_symbol": "$", "country_code": None,
            "general_comment": None, "platform_breakdown": [],
        },
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()

    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))
    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", _fake_meta_data([_fake_campaign("1", 77.5)], 77.5))

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "GTQ",
    })
    assert r.status_code == 200
    # No hay tipo de cambio configurado en la organización: usa el respaldo
    # DEFAULT_EXCHANGE_RATE_USD_GTQ (7.75) -- 77.5 USD * 7.75 = 600.625 GTQ.
    assert r.json()["total_spend"] == 600.625

    rows = db.query(ReportSummaryCache).filter_by(account_id=account.id).all()
    assert {row.currency for row in rows} == {"USD", "GTQ"}


def test_meta_falla_sin_cache_previa_devuelve_502(client, login, tenant_a, factory, monkeypatch, db):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    account.native_currency = "USD"
    db.commit()
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_falla(*args, **kwargs):
        raise meta_api.MetaApiError("User request limit reached")

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_falla)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
    })
    assert r.status_code == 502
