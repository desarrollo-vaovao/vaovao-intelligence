"""
meta_api.get_daily_campaign_data trae, en una sola llamada de insights con
time_increment=1, el gasto DIARIO por campaña que alimenta
app/services/daily_sync.py — la pieza que reemplaza una consulta nueva a
Meta por cada rango de fechas que alguien pida en Resumen.
"""
from __future__ import annotations

import asyncio

from app.services import meta_api


def test_get_daily_campaign_data_manda_time_increment_1(monkeypatch):
    captured = {}

    async def fake_get_campaigns(client, token, ad_account_id):
        return [{"id": "1", "name": "Campaña 1", "objective": "REACH", "status": "ACTIVE"}]

    async def fake_run_insights_job(client, ad_account_id, token, level, fields, time_range,
                                    attribution_windows=None, time_increment=None):
        captured["time_increment"] = time_increment
        captured["level"] = level
        return [
            {"campaign_id": "1", "date_start": "2026-01-01", "spend": "10.5",
             "impressions": "100", "reach": "90", "clicks": "5"},
            {"campaign_id": "1", "date_start": "2026-01-02", "spend": "8.25",
             "impressions": "80", "reach": "70", "clicks": "3"},
        ]

    monkeypatch.setattr(meta_api, "get_campaigns", fake_get_campaigns)
    monkeypatch.setattr(meta_api, "_run_insights_job", fake_run_insights_job)

    data = asyncio.run(meta_api.get_daily_campaign_data("token", "act_1", "2026-01-01", "2026-01-02"))

    assert captured["time_increment"] == 1
    assert captured["level"] == "campaign"
    assert [c["id"] for c in data["campaigns"]] == ["1"]
    assert data["daily"] == [
        {"campaign_id": "1", "date": "2026-01-01", "spend": 10.5, "impressions": 100, "reach": 90, "clicks": 5},
        {"campaign_id": "1", "date": "2026-01-02", "spend": 8.25, "impressions": 80, "reach": 70, "clicks": 3},
    ]


def test_get_daily_campaign_data_descarta_filas_sin_campana_o_fecha(monkeypatch):
    async def fake_get_campaigns(client, token, ad_account_id):
        return []

    async def fake_run_insights_job(*args, **kwargs):
        return [
            {"campaign_id": "1", "date_start": "2026-01-01", "spend": "5"},
            {"campaign_id": None, "date_start": "2026-01-01", "spend": "5"},
            {"campaign_id": "2", "date_start": None, "spend": "5"},
        ]

    monkeypatch.setattr(meta_api, "get_campaigns", fake_get_campaigns)
    monkeypatch.setattr(meta_api, "_run_insights_job", fake_run_insights_job)

    data = asyncio.run(meta_api.get_daily_campaign_data("token", "act_1", "2026-01-01", "2026-01-01"))
    assert len(data["daily"]) == 1
    assert data["daily"][0]["campaign_id"] == "1"


def test_get_daily_campaign_data_with_fallback_prueba_el_siguiente_token(monkeypatch):
    intentos = []

    async def fake_get_daily_campaign_data(token, ad_account_id, date_from, date_to):
        intentos.append(token)
        if token == "malo":
            raise meta_api.MetaApiError("sin acceso")
        return {"campaigns": [], "daily": []}

    monkeypatch.setattr(meta_api, "get_daily_campaign_data", fake_get_daily_campaign_data)

    data = asyncio.run(meta_api.get_daily_campaign_data_with_fallback(
        ["malo", "bueno"], "act_1", "2026-01-01", "2026-01-01",
    ))
    assert intentos == ["malo", "bueno"]
    assert data == {"campaigns": [], "daily": []}


def test_get_daily_campaign_data_with_fallback_todos_fallan_lanza_el_ultimo_error(monkeypatch):
    async def fake_get_daily_campaign_data(token, ad_account_id, date_from, date_to):
        raise meta_api.MetaApiError(f"falló {token}")

    monkeypatch.setattr(meta_api, "get_daily_campaign_data", fake_get_daily_campaign_data)

    try:
        asyncio.run(meta_api.get_daily_campaign_data_with_fallback(
            ["a", "b"], "act_1", "2026-01-01", "2026-01-01",
        ))
        assert False, "debía lanzar MetaApiError"
    except meta_api.MetaApiError as e:
        assert "b" in str(e)
