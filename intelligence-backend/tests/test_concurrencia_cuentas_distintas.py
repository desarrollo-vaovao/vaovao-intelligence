"""
meta_api._account_fetch_semaphore — límite de cuántas cuentas DISTINTAS
se traen de Meta a la vez en todo el proceso.

La caché anti-estampida (_TTLCache, ver test_cache_meta_api.py) solo
ayuda cuando varias personas piden EXACTAMENTE lo mismo. Si en cambio se
generan 20-50 reportes de CLIENTES DISTINTOS casi al mismo tiempo, cada
uno es una consulta genuinamente distinta -- sin este semáforo, las 50
saldrían disparadas a la vez contra Meta, arriesgando el límite real de
la cuenta ("User request limit reached"). Con el límite, las de más
esperan su turno en fila en vez de fallar -- ver conversación del
2026-09-03.
"""
from __future__ import annotations

import asyncio

from app.services import meta_api


def test_cuentas_distintas_no_corren_todas_a_la_vez(monkeypatch):
    monkeypatch.setattr(meta_api, "_account_fetch_semaphore", asyncio.Semaphore(3))

    en_vuelo = {"activas": 0, "maximo_visto": 0}

    async def fake_get_account_data(token, ad_account_id, date_from, date_to,
                                    attribution_windows=None, include_inactive=False,
                                    include_ad_insights=True):
        en_vuelo["activas"] += 1
        en_vuelo["maximo_visto"] = max(en_vuelo["maximo_visto"], en_vuelo["activas"])
        await asyncio.sleep(0.05)
        en_vuelo["activas"] -= 1
        return {"campaigns": [], "total_spend": 0.0, "account_id": ad_account_id}

    monkeypatch.setattr(meta_api, "get_account_data", fake_get_account_data)

    async def run():
        # 10 CUENTAS DISTINTAS (clave de caché distinta cada una) -- nada
        # que compartir entre ellas, cada una es un fetch real.
        return await asyncio.gather(*[
            meta_api.get_account_data_with_fallback(["token"], f"act_{i}", "2026-01-01", "2026-01-15")
            for i in range(10)
        ])

    resultados = asyncio.run(run())
    assert len(resultados) == 10
    assert en_vuelo["maximo_visto"] <= 3  # nunca más de 3 fetch reales a la vez


def test_la_misma_cuenta_no_gasta_dos_lugares_del_semaforo(monkeypatch):
    """Si 5 solicitudes piden la MISMA cuenta, la caché anti-estampida ya
    resuelve eso con un solo fetch -- no debería siquiera competir por más
    de UN lugar del semáforo de cuentas distintas."""
    monkeypatch.setattr(meta_api, "_account_fetch_semaphore", asyncio.Semaphore(1))

    llamadas = {"n": 0}

    async def fake_get_account_data(token, ad_account_id, date_from, date_to,
                                    attribution_windows=None, include_inactive=False,
                                    include_ad_insights=True):
        llamadas["n"] += 1
        await asyncio.sleep(0.02)
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data", fake_get_account_data)

    async def run():
        return await asyncio.gather(*[
            meta_api.get_account_data_with_fallback(["token"], "act_1", "2026-01-01", "2026-01-15")
            for _ in range(5)
        ])

    resultados = asyncio.run(run())
    assert len(resultados) == 5
    assert llamadas["n"] == 1
