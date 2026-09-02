"""
La ventana de atribución de Ajustes > Preferencias de reporte llega de
verdad hasta la llamada a Meta — si no, sería un control decorativo, igual
que el selector de moneda antes de la conversión real (ver
test_conversion_moneda.py).

Meta agrupa "por día" según la zona horaria de CADA cuenta publicitaria y
eso no se puede sobreescribir por parámetro (a diferencia de la
atribución) — por eso ad_accounts.timezone_name es solo informativo, se
resuelve on-demand igual que native_currency, y estas pruebas también
cubren que quede guardado al agregar/editar un activo.
"""
from __future__ import annotations

import json

import app.api.routes.clients as clients_routes
from app.services import meta_api, report_builder


# ── El parámetro llega a la llamada real a Meta ───────────────────
def test_run_insights_job_manda_la_ventana_de_atribucion(monkeypatch):
    captured: dict = {}

    async def fake_post(client, path, token, params):
        captured.update(params)
        return {"report_run_id": "job-1"}

    async def fake_get(client, path, token, params):
        return {"async_status": "Job Completed"}

    async def fake_get_all(client, path, token, params):
        return []

    monkeypatch.setattr(meta_api, "_post", fake_post)
    monkeypatch.setattr(meta_api, "_get", fake_get)
    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)

    import asyncio
    asyncio.run(meta_api._run_insights_job(
        None, "act_1", "token", "campaign", ["campaign_id"],
        json.dumps({"since": "2026-01-01", "until": "2026-01-31"}),
        ["7d_click", "1d_view"],
    ))

    assert captured["action_attribution_windows"] == json.dumps(["7d_click", "1d_view"])


def test_run_insights_job_sin_ventana_no_manda_el_parametro(monkeypatch):
    """None es 'que Meta use el default de la cuenta' — mandar el parámetro
    vacío o con un valor inventado sería peor que no mandarlo."""
    captured: dict = {}

    async def fake_post(client, path, token, params):
        captured.update(params)
        return {"report_run_id": "job-1"}

    async def fake_get(client, path, token, params):
        return {"async_status": "Job Completed"}

    async def fake_get_all(client, path, token, params):
        return []

    monkeypatch.setattr(meta_api, "_post", fake_post)
    monkeypatch.setattr(meta_api, "_get", fake_get)
    monkeypatch.setattr(meta_api, "_get_all", fake_get_all)

    import asyncio
    asyncio.run(meta_api._run_insights_job(
        None, "act_1", "token", "campaign", ["campaign_id"],
        json.dumps({"since": "2026-01-01", "until": "2026-01-31"}),
        None,
    ))

    assert "action_attribution_windows" not in captured


# ── report_builder traduce la preferencia guardada al valor de Meta ──
def test_build_report_data_traduce_la_preferencia_guardada(monkeypatch, tenant_a, factory):
    """org.attribution_window="7d_click" tiene que llegar a
    get_account_data_with_fallback como ["7d_click"], no como el string
    crudo — Meta espera una lista JSON."""
    account = factory.ad_account(tenant_a.client)
    captured = {}

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None, include_inactive=False, include_ad_insights=True):
        captured["attribution_windows"] = attribution_windows
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(
        meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback
    )

    import asyncio
    from datetime import date
    asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 31),
        attribution_window="7d_click_1d_view",
    ))

    assert captured["attribution_windows"] == ["7d_click", "1d_view"]


def test_build_report_data_sin_preferencia_no_manda_nada(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)
    captured = {}

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None, include_inactive=False, include_ad_insights=True):
        captured["attribution_windows"] = attribution_windows
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(
        meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback
    )

    import asyncio
    from datetime import date
    asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 31),
    ))

    assert captured["attribution_windows"] is None


# ── timezone_name se resuelve y persiste igual que native_currency ───
def test_agregar_activo_guarda_moneda_y_zona_horaria(client, login, tenant_a, monkeypatch):
    login(tenant_a.owner)
    monkeypatch.setattr(
        clients_routes, "resolve_tokens", lambda current, db: (["token"], None)
    )

    async def fake_name(token, ad_account_id):
        return True, "Cuenta de Prueba"

    async def fake_currency_and_timezone(tokens, ad_account_id):
        return "GTQ", "America/Guatemala"

    monkeypatch.setattr(meta_api, "check_account_access_with_fallback", fake_name)
    monkeypatch.setattr(
        meta_api, "get_account_currency_and_timezone_with_fallback", fake_currency_and_timezone
    )

    r = client.post(
        f"/clients/{tenant_a.client.id}/ad-accounts",
        json={"meta_ad_account_id": "act_555", "recipient_emails": []},
    )
    assert r.status_code == 201
    assert r.json()["timezone_name"] == "America/Guatemala"
