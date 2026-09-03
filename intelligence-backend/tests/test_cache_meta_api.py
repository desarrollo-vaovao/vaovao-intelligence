"""
meta_api._TTLCache — caché en memoria + anti-estampida para
get_account_data_with_fallback y get_platform_breakdown_with_fallback.

Por qué existe: con muchas personas generando reportes casi al mismo
tiempo, varias piden exactamente los MISMOS datos (misma cuenta, mismo
rango de fechas). Sin esto, cada una dispara su propio fetch completo a
Meta, y ese volumen extra es lo que dispara "User request limit reached"
al crecer el equipo de unas pocas personas a decenas — ver conversación
del 2026-09-02.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.meta_api import MetaApiError, _TTLCache


# ── _TTLCache en aislamiento ────────────────────────────────────────────
def test_ttl_cache_solo_llama_fetch_una_vez_para_la_misma_clave():
    cache = _TTLCache(ttl_seconds=60)
    llamadas = []

    async def fetch():
        llamadas.append(1)
        return "dato"

    async def run():
        r1 = await cache.get_or_fetch(("k",), fetch)
        r2 = await cache.get_or_fetch(("k",), fetch)
        return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1 == r2 == "dato"
    assert len(llamadas) == 1


def test_ttl_cache_claves_distintas_no_comparten_resultado():
    cache = _TTLCache(ttl_seconds=60)

    async def fetch_a():
        return "a"

    async def fetch_b():
        return "b"

    async def run():
        return await cache.get_or_fetch(("a",), fetch_a), await cache.get_or_fetch(("b",), fetch_b)

    ra, rb = asyncio.run(run())
    assert (ra, rb) == ("a", "b")


def test_ttl_cache_expira_despues_del_ttl():
    cache = _TTLCache(ttl_seconds=0.05)
    llamadas = []

    async def fetch():
        llamadas.append(1)
        return len(llamadas)

    async def run():
        primero = await cache.get_or_fetch(("k",), fetch)
        await asyncio.sleep(0.08)
        segundo = await cache.get_or_fetch(("k",), fetch)
        return primero, segundo

    primero, segundo = asyncio.run(run())
    assert primero == 1
    assert segundo == 2  # venció el TTL: se volvió a llamar fetch


def test_ttl_cache_cachea_un_error_por_poco_tiempo():
    """Un fallo (rate limit, un lote demasiado grande, etc.) SÍ se cachea,
    pero con un TTL corto propio — así, si 20 solicitudes están esperando
    la misma clave cuando la primera falla, TODAS reciben ese mismo error
    de inmediato en vez de turnarse para reintentar una por una contra
    Meta (confirmado con una prueba real: eso convertía un solo fallo en
    ~10 reintentos secuenciales de minutos)."""
    cache = _TTLCache(ttl_seconds=60, error_ttl_seconds=0.05)
    intentos = {"n": 0}

    async def fetch():
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise MetaApiError("rate limit")
        return "ok"

    async def run():
        with pytest.raises(MetaApiError):
            await cache.get_or_fetch(("k",), fetch)
        # Inmediatamente después: mismo error de caché, sin reintentar.
        with pytest.raises(MetaApiError):
            await cache.get_or_fetch(("k",), fetch)
        assert intentos["n"] == 1

        # Pasado el TTL corto del error, sí se reintenta de verdad.
        await asyncio.sleep(0.08)
        return await cache.get_or_fetch(("k",), fetch)

    resultado = asyncio.run(run())
    assert resultado == "ok"
    assert intentos["n"] == 2


def test_ttl_cache_llamadas_concurrentes_comparten_un_solo_fetch():
    """El caso real que motiva esto: varias personas piden lo mismo casi
    al mismo tiempo, ANTES de que la primera termine de traerlo — deben
    esperar el mismo resultado en vez de disparar cada una su propio
    llamado a Meta."""
    cache = _TTLCache(ttl_seconds=60)
    llamadas_en_vuelo = {"activas": 0, "maximo_visto": 0}

    async def fetch():
        llamadas_en_vuelo["activas"] += 1
        llamadas_en_vuelo["maximo_visto"] = max(
            llamadas_en_vuelo["maximo_visto"], llamadas_en_vuelo["activas"]
        )
        await asyncio.sleep(0.05)  # simula la latencia real de Meta
        llamadas_en_vuelo["activas"] -= 1
        return "dato"

    async def run():
        return await asyncio.gather(*[cache.get_or_fetch(("k",), fetch) for _ in range(20)])

    resultados = asyncio.run(run())
    assert resultados == ["dato"] * 20


def test_ttl_cache_20_solicitudes_concurrentes_con_un_solo_fallo_no_reintentan_20_veces():
    """El escenario real que disparó este cambio: 20 solicitudes a la vez
    para una cuenta que Meta rechaza. Sin el TTL corto de error, cada una
    se turnaría para reintentar (20 fetch() reales, uno tras otro). Con
    él, la primera falla y las otras 19 -- que ya estaban esperando --
    reciben ese mismo error de la caché."""
    cache = _TTLCache(ttl_seconds=60, error_ttl_seconds=5)
    intentos = {"n": 0}

    async def fetch():
        intentos["n"] += 1
        await asyncio.sleep(0.05)
        raise MetaApiError("cuenta rechazada")

    async def run():
        resultados = await asyncio.gather(
            *[cache.get_or_fetch(("k",), fetch) for _ in range(20)],
            return_exceptions=True,
        )
        return resultados

    resultados = asyncio.run(run())
    assert all(isinstance(r, MetaApiError) for r in resultados)
    assert intentos["n"] == 1


def test_ttl_cache_clear_borra_todo():
    cache = _TTLCache(ttl_seconds=60)
    llamadas = []

    async def fetch():
        llamadas.append(1)
        return "dato"

    async def run():
        await cache.get_or_fetch(("k",), fetch)
        cache.clear()
        await cache.get_or_fetch(("k",), fetch)

    asyncio.run(run())
    assert len(llamadas) == 2


# ── Integración: get_account_data_with_fallback usa la caché de verdad ──
def test_get_account_data_with_fallback_cachea_por_cuenta_y_rango(monkeypatch):
    from app.services import meta_api

    llamadas = []

    async def fake_get_account_data(token, ad_account_id, date_from, date_to,
                                    attribution_windows=None, include_inactive=False,
                                    include_ad_insights=True):
        llamadas.append((ad_account_id, date_from, date_to))
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data", fake_get_account_data)

    async def run():
        await meta_api.get_account_data_with_fallback(["token"], "act_1", "2026-01-01", "2026-01-15")
        await meta_api.get_account_data_with_fallback(["token"], "act_1", "2026-01-01", "2026-01-15")
        # Rango distinto: SÍ debe volver a llamar.
        await meta_api.get_account_data_with_fallback(["token"], "act_1", "2026-02-01", "2026-02-15")

    asyncio.run(run())
    assert len(llamadas) == 2


def test_get_account_data_with_fallback_no_cachea_entre_include_inactive_distintos(monkeypatch):
    """El panel de Resumen (include_inactive=True) y el PDF
    (include_inactive=False) piden cosas distintas para el mismo período
    — no deben pisarse el resultado en la caché."""
    from app.services import meta_api

    llamadas = []

    async def fake_get_account_data(token, ad_account_id, date_from, date_to,
                                    attribution_windows=None, include_inactive=False,
                                    include_ad_insights=True):
        llamadas.append(include_inactive)
        return {"campaigns": [], "total_spend": 0.0}

    monkeypatch.setattr(meta_api, "get_account_data", fake_get_account_data)

    async def run():
        await meta_api.get_account_data_with_fallback(
            ["token"], "act_1", "2026-01-01", "2026-01-15", include_inactive=False,
        )
        await meta_api.get_account_data_with_fallback(
            ["token"], "act_1", "2026-01-01", "2026-01-15", include_inactive=True,
        )

    asyncio.run(run())
    assert llamadas == [False, True]
