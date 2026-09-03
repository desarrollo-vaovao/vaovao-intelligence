"""
meta_api — el mensajero entre Intelligence y Meta (Graph API / Marketing API).
Port a Python de metaApi.js (reportería Node).

Su trabajo: dada una cuenta publicitaria, un rango de fechas y un token,
trae todo el rendimiento de las campañas, ordenado en un árbol:
    Cuenta → Campañas → (Insights + Anuncios) → (rendimiento e imagen por anuncio)

No genera PDF ni manda correos: solo trae datos. Esa separación es a propósito.

Mejoras respecto al Node:
- La versión de la Graph API es configurable (META_API_VERSION), no hardcodeada.
- El token llega como parámetro (el de la organización o el del usuario), no de una env suelta.
- check_account_access() VERIFICA que un token puede leer una cuenta.
- list_ad_accounts() cubre acceso directo Y cuentas del portafolio comercial.
- Todas las llamadas a la Graph API son concurrentes (asyncio.gather), no una por una:
  con muchas campañas/anuncios, hacerlas secuenciales tardaba varios segundos de más.
"""
import os
import json
import time
import random
import asyncio
import httpx

from app.services import perf

API_VERSION = os.getenv("META_API_VERSION", "v23.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
# Una consulta de insights en bloque (level=ad/campaign sobre un rango
# mensual, con varios anuncios) puede tardar bastante en calcularse del lado
# de Meta — 30s se quedaba corto y causaba httpx.ReadTimeout en cuentas
# grandes. El timeout de conexión se queda corto (10s: si Meta no ni siquiera
# contesta en eso, algo más grave pasa), pero el de lectura se da más margen.
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# Cuántas llamadas a la Graph API dejamos en vuelo al mismo tiempo EN TODO EL
# PROCESO (no por request ni por cuenta): un solo semáforo a nivel de módulo,
# compartido por todos los jobs y usuarios que estén generando reportes a la
# vez. Antes, cada llamada a get_account_data() creaba su propio semáforo, así
# que un cliente multi-estación (varias cuentas publicitarias, ej. OLR)
# multiplicaba la concurrencia por el número de cuentas al pedirlas todas en
# paralelo — con 6 estaciones eso son hasta 48 llamadas simultáneas en vez de
# 8, lo que dispara el rate limit de Meta ("User request limit reached").
_MAX_CONCURRENCY = int(os.getenv("META_MAX_CONCURRENCY", "8"))
_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

# Códigos de error de Meta que indican rate limiting (transitorio: vale la
# pena esperar y reintentar en vez de tirar todo el reporte).
# 4 = "Application request limit reached", 17 = "User request limit reached",
# 32 = "Page request limit reached", 613 = límite de la API de anuncios.
_RATE_LIMIT_CODES = {4, 17, 32, 613}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # segundos; backoff exponencial con jitter


class _TTLCache:
    """
    Caché en memoria del PROCESO, con anti-estampida ("single-flight"): si
    dos llamadas concurrentes piden la MISMA clave mientras todavía no hay
    nada en caché, la segunda espera a que termine la primera en vez de
    disparar su propio llamado a Meta — solo la primera realmente golpea
    la Graph API.

    Por qué hace falta: Resumen, Reportes, el selector de país y el modal
    de personalizar métricas terminan todos llamando a
    get_account_data_with_fallback / get_platform_breakdown_with_fallback.
    Con pocas personas usando la app eso no se nota, pero con 10-100
    usuarios generando reportes casi al mismo tiempo, varios piden
    exactamente los MISMOS datos (misma cuenta, mismo rango de fechas) en
    la misma ventana de segundos — sin esto, cada uno dispara su propio
    fetch completo, y ESE volumen extra (no el uso real) es lo que
    dispara "User request limit reached" al crecer el equipo.

    Es memoria de proceso, no una base de datos ni Redis: alcanza porque
    hoy el backend corre en UNA sola instancia (ver Railway). Si algún día
    se escala a varias instancias, esta caché deja de compartirse entre
    ellas — habría que moverla a un almacén externo (Redis) para que el
    anti-estampida siga funcionando entre procesos.
    """

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, object]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def get_or_fetch(self, key: tuple, fetch):
        now = time.monotonic()
        cached = self._store.get(key)
        if cached and now - cached[0] < self._ttl:
            return cached[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-chequear: mientras esperábamos el lock, quien lo tenía
            # pudo haber terminado de llenar la caché con esta misma clave.
            now = time.monotonic()
            cached = self._store.get(key)
            if cached and now - cached[0] < self._ttl:
                return cached[1]

            # NO se cachea un error (rate limit, token inválido, etc.): si
            # se cacheara, un fallo transitorio quedaría "pegado" durante
            # todo el TTL en vez de poder resolverse en el siguiente intento.
            value = await fetch()
            now = time.monotonic()
            self._store[key] = (now, value)
            self._prune(now)
            return value

    def _prune(self, now: float) -> None:
        """Bota entradas vencidas en cada escritura — evita que la caché
        (y el diccionario de locks) crezcan sin límite con cuentas o
        rangos de fecha que ya no se vuelven a pedir."""
        expired = [k for k, (ts, _) in self._store.items() if now - ts >= self._ttl]
        for k in expired:
            self._store.pop(k, None)
            self._locks.pop(k, None)

    def clear(self) -> None:
        """Solo para pruebas: sin esto, una caché a nivel de módulo
        compartiría resultados de una prueba con la siguiente."""
        self._store.clear()
        self._locks.clear()


# TTL corto a propósito: alcanza para absorber la ráfaga de gente pidiendo
# el MISMO reporte casi al mismo tiempo, sin que un reporte se sienta
# "viejo" — el gasto real de una campaña no cambia sensiblemente en un par
# de minutos.
_ACCOUNT_DATA_CACHE_TTL = float(os.getenv("META_ACCOUNT_DATA_CACHE_TTL", "180"))
_account_data_cache = _TTLCache(_ACCOUNT_DATA_CACHE_TTL)
_platform_breakdown_cache = _TTLCache(_ACCOUNT_DATA_CACHE_TTL)

# Métricas que pedimos según el objetivo de la campaña (igual que en Node)
METRICS_BY_OBJECTIVE = {
    "LINK_CLICKS":     ["impressions", "reach", "clicks", "ctr", "cpc", "spend"],
    "TRAFFIC":         ["impressions", "reach", "clicks", "ctr", "cpc", "spend"],
    "MESSAGES":        ["impressions", "spend", "messaging_conversation_started_7d"],
    "POST_ENGAGEMENT": ["impressions", "reach", "post_engagement", "spend"],
    "PAGE_LIKES":      ["impressions", "reach", "actions", "spend"],
    "REACH":           ["impressions", "reach", "frequency", "cpm", "spend"],
    "BRAND_AWARENESS": ["impressions", "reach", "frequency", "cpm", "spend"],
    "DEFAULT":         ["impressions", "reach", "clicks", "ctr", "cpc", "spend"],
}

# Algunas métricas NO son campos válidos para pedir directo en el endpoint
# de insights en bloque (a nivel de cuenta, o dentro de un job asíncrono) —
# Meta las rechaza con errores tipo "(#100) ... is not valid for fields
# param" o "(#100) Tried accessing nonexisting summary field", aunque sí lo
# eran en el endpoint del objeto individual (campaign_id/insights) que
# usaba el código viejo. Todas están disponibles vía el arreglo `actions`
# (que sí es válido ahí), filtrando por action_type — así que en vez de
# pedirlas directo, se pide "actions" y se derivan de ahí.
_DERIVED_FROM_ACTIONS = {
    "messaging_conversation_started_7d": {"onsite_conversion.messaging_conversation_started_7d",
                                          "messaging_conversation_started_7d"},
    "post_engagement": {"post_engagement", "onsite_conversion.post_save"},
}


def _fields_for_campaigns(campaigns: list[dict]) -> list[str]:
    """
    Solo las métricas que de verdad necesitan LOS OBJETIVOS presentes en esta
    cuenta (no la unión de TODOS los objetivos posibles). "actions" es el
    campo más caro de calcular en bloque —Meta devuelve un arreglo variable
    de eventos por fila— y solo lo necesitan MESSAGES/POST_ENGAGEMENT/
    PAGE_LIKES; pedirlo siempre, para cuentas que ni lo usan, es lo que
    dispara "Please reduce the amount of data you're asking for".
    """
    objectives = {c.get("objective", "DEFAULT") for c in campaigns}
    metrics = {m for obj in objectives
               for m in METRICS_BY_OBJECTIVE.get(obj, METRICS_BY_OBJECTIVE["DEFAULT"])}
    if metrics & _DERIVED_FROM_ACTIONS.keys():
        # Ninguna de estas es un campo válido a este nivel (ver arriba) — se
        # derivan de "actions", así que hay que pedir "actions" en su lugar.
        metrics -= _DERIVED_FROM_ACTIONS.keys()
        metrics.add("actions")
    return sorted(metrics)


def _with_derived_metrics(insights: dict) -> dict:
    """Agrega las métricas de _DERIVED_FROM_ACTIONS al insight, leyéndolas
    de `actions` (ver _fields_for_campaigns)."""
    actions = insights.get("actions") or []
    for metric, action_types in _DERIVED_FROM_ACTIONS.items():
        for a in actions:
            if a.get("action_type") in action_types:
                insights[metric] = a.get("value")
                break
    return insights

# Cuántos resultados pedimos por página al listar campañas/anuncios (objetos
# livianos: solo id/nombre/creativo).
_PAGE_SIZE = 200

# Cuánto se espera a que Meta termine de calcular un job asíncrono de
# insights antes de darse por vencido (ver _run_insights_job).
_INSIGHTS_JOB_MAX_WAIT = float(os.getenv("META_INSIGHTS_JOB_MAX_WAIT", "180"))

# Cada cuánto se le pregunta a Meta si el job ya terminó. El intervalo ARRANCA
# CORTO Y VA CRECIENDO, en vez del 1s fijo que había antes: la mayoría de los
# jobs (cuentas normales, rangos quincenales) terminan en bastante menos de un
# segundo, y con el intervalo fijo el reporte no se enteraba hasta el siguiente
# tic. Como se corren DOS jobs en paralelo (campaña y anuncio) y manda el más
# lento, ese segundo regalado se pagaba casi siempre.
#
# El techo se queda en 1s —el mismo valor fijo de antes— y NO más alto: con un
# techo mayor se abrirían huecos más grandes que los del esquema viejo y los
# jobs de duración media se detectarían más tarde que antes. Así solo se
# agregan peticiones al principio (cuando sirven), sin empeorar el gasto de
# cuota contra el rate limit de Meta (código 17) en los jobs largos.
_INSIGHTS_JOB_POLL_START = 0.25
_INSIGHTS_JOB_POLL_MAX = 1.0
_INSIGHTS_JOB_POLL_FACTOR = 1.5


class MetaApiError(Exception):
    """Error al hablar con Meta (token inválido, sin acceso, etc.)."""


async def _request(client: httpx.AsyncClient, url: str, params: dict | None = None,
                   method: str = "GET") -> dict:
    """
    Petición cruda a `url`, respetando el límite global de concurrencia. Si
    Meta responde con un código de rate limit, o si la petición se queda sin
    respuesta a tiempo (httpx.TimeoutException — pasa con insights pesados,
    ej. un rango mensual con muchos anuncios), reintenta con backoff
    exponencial (+ jitter) antes de darse por vencido.
    `params=None` cuando `url` ya trae todo lo necesario (ej. el link "next"
    de una página siguiente, que Meta devuelve ya armado con el token).
    Devuelve el JSON o lanza MetaApiError (nunca deja escapar la excepción de
    httpx sin convertir, para que el llamador la pueda distinguir de un error
    inesperado como uno de generación de PDF).
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with _semaphore:
                if method == "POST":
                    resp = await client.post(url, params=params)
                else:
                    resp = await client.get(url, params=params)
        except httpx.TimeoutException:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
                continue
            raise MetaApiError(
                "Meta tardó demasiado en responder (timeout). Intenta de nuevo en unos minutos."
            )

        data = resp.json()
        if resp.status_code == 200:
            return data

        error = data.get("error") or {}
        is_rate_limited = error.get("code") in _RATE_LIMIT_CODES or error.get("is_transient")
        if is_rate_limited and attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)
            continue
        raise MetaApiError(error.get("message", "Error desconocido de Meta"))


async def _get(client: httpx.AsyncClient, path: str, token: str, params: dict) -> dict:
    """GET a un endpoint de la Graph API con el token. Ver _request()."""
    return await _request(client, f"{BASE_URL}/{path}", {**params, "access_token": token})


async def _post(client: httpx.AsyncClient, path: str, token: str, params: dict) -> dict:
    """POST a un endpoint de la Graph API con el token. Ver _request()."""
    return await _request(client, f"{BASE_URL}/{path}", {**params, "access_token": token}, method="POST")


async def _get_all(client: httpx.AsyncClient, path: str, token: str, params: dict) -> list[dict]:
    """
    Como _get, pero sigue la paginación de Meta (paging.next) hasta juntar
    TODOS los resultados en una sola lista. Se usa para traer, por ejemplo,
    los insights de TODAS las campañas o TODOS los anuncios de una cuenta en
    unas pocas llamadas en vez de una por campaña/anuncio — lo que evita
    disparar el rate limit de Meta en cuentas con muchas campañas/anuncios.
    """
    data = await _get(client, path, token, params)
    items = list(data.get("data", []))
    next_url = (data.get("paging") or {}).get("next")
    while next_url:
        data = await _request(client, next_url)
        items.extend(data.get("data", []))
        next_url = (data.get("paging") or {}).get("next")
    return items


async def _labeled(label: str, coro):
    """
    Envuelve una petición con una etiqueta legible: si Meta rechaza esa
    llamada puntual, el error que ve el usuario (y que queda en los logs)
    dice CUÁL llamada falló ("Insights de anuncios de la campaña 'X'"), no
    solo el mensaje genérico de Meta. Sin esto, diagnosticar cuál de las
    varias llamadas en paralelo era la pesada implicaba adivinar a ciegas.
    """
    try:
        return await coro
    except MetaApiError as e:
        raise MetaApiError(f"{label}: {e}") from e


async def check_account_access(token: str, ad_account_id: str) -> tuple[bool, str]:
    """
    Verifica si el token puede LEER una cuenta publicitaria.
    Devuelve (True, nombre) si sí; (False, motivo) si no.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            data = await _get(client, ad_account_id, token, {"fields": "name,account_status"})
        return True, data.get("name", ad_account_id)
    except MetaApiError as e:
        return False, str(e)
    except httpx.InvalidURL:
        return False, "ID de cuenta inválido (revisa que no tenga espacios ni caracteres extra)"
    except httpx.HTTPError as e:
        return False, f"Error de red: {e}"


async def check_account_access_with_fallback(tokens: list[str], ad_account_id: str) -> tuple[bool, str]:
    """
    Igual que check_account_access, pero prueba varios tokens en orden y
    devuelve el primer resultado exitoso (o el último motivo de falla si
    ninguno funcionó).
    """
    result = (False, "Sin tokens disponibles.")
    for token in tokens:
        result = await check_account_access(token, ad_account_id)
        if result[0]:
            return result
    return result


async def get_account_currency(token: str, ad_account_id: str) -> str | None:
    """Moneda en la que esta cuenta reporta gasto en Meta (ej. "USD", "GTQ").

    No todas las cuentas de un mismo cliente están en la misma: algunas se
    configuraron en Meta Ads Manager directamente en quetzales. `None` si
    el token no tiene acceso o la petición falla — nunca lanza, para que
    esto se pueda intentar "en el camino" sin arriesgar el flujo principal
    (ver report_builder, que la resuelve on-demand y la cachea).
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            data = await _get(client, ad_account_id, token, {"fields": "currency"})
        return data.get("currency")
    except (MetaApiError, httpx.HTTPError, httpx.InvalidURL):
        return None


async def get_account_currency_with_fallback(tokens: list[str], ad_account_id: str) -> str | None:
    """Igual que get_account_currency, probando varios tokens en orden."""
    for token in tokens:
        currency = await get_account_currency(token, ad_account_id)
        if currency:
            return currency
    return None


async def get_account_currency_and_timezone(token: str, ad_account_id: str) -> tuple[str | None, str | None]:
    """
    Moneda Y zona horaria de la cuenta, en UNA sola llamada a Meta (mismo
    endpoint que get_account_currency, un campo más no cuesta una petición
    aparte). La zona horaria es la que Meta usa de verdad para agrupar
    insights "por día" — no se puede pedir otra, así que vale la pena
    guardarla para mostrarla (ver ad_accounts.timezone_name).

    Nunca lanza, igual que get_account_currency: (None, None) si el token no
    tiene acceso o la petición falla.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            data = await _get(client, ad_account_id, token, {"fields": "currency,timezone_name"})
        return data.get("currency"), data.get("timezone_name")
    except (MetaApiError, httpx.HTTPError, httpx.InvalidURL):
        return None, None


async def get_account_currency_and_timezone_with_fallback(
    tokens: list[str], ad_account_id: str
) -> tuple[str | None, str | None]:
    """Igual que get_account_currency_and_timezone, probando varios tokens en orden."""
    for token in tokens:
        currency, timezone_name = await get_account_currency_and_timezone(token, ad_account_id)
        if currency or timezone_name:
            return currency, timezone_name
    return None, None


async def get_campaigns(client: httpx.AsyncClient, token: str, ad_account_id: str) -> list[dict]:
    """Todas las campañas (activas y pausadas) de una cuenta, con su info básica."""
    return await _get_all(client, f"{ad_account_id}/campaigns", token, {
        "fields": "id,name,objective,status,daily_budget,lifetime_budget",
        "filtering": json.dumps([{"field": "effective_status", "operator": "IN",
                                  "value": ["ACTIVE", "PAUSED"]}]),
        "limit": _PAGE_SIZE,
    })


def _rank_by_insights(insights: dict) -> float:
    for key in ("clicks", "messaging_conversation_started_7d", "post_engagement", "impressions"):
        if insights.get(key) is not None:
            try:
                return float(insights[key])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _extract_countries_from_targeting(targeting: dict | None) -> list[str]:
    """Extrae la lista de códigos de país del objeto de targeting de un anuncio."""
    if not targeting:
        return []
    geo_locations = targeting.get("geo_locations") or {}
    countries = geo_locations.get("countries")
    if isinstance(countries, list):
        return sorted(countries)
    return []


async def get_account_data_with_fallback(tokens: list[str], ad_account_id: str,
                                         date_from: str, date_to: str,
                                         attribution_windows: list[str] | None = None,
                                         include_inactive: bool = False,
                                         include_ad_insights: bool = True) -> dict:
    """
    Igual que get_account_data, pero prueba varios tokens en orden (p. ej. el
    Facebook personal del usuario y, si a ESA cuenta le falta acceso, el token
    central de la organización) hasta que uno funcione. Así, una vez que el
    token central tiene permiso sobre una cuenta, cualquier persona del equipo
    puede generar su reporte aunque su Facebook personal no tenga acceso.

    El resultado se cachea unos minutos (ver _TTLCache) por
    (cuenta, rango de fechas, atribución, include_inactive,
    include_ad_insights) — SIN incluir los tokens en la clave, porque el
    dato que devuelve Meta es el mismo sin importar cuál token válido se
    haya usado para leerlo.
    """
    key = (ad_account_id, date_from, date_to, tuple(attribution_windows or ()),
           include_inactive, include_ad_insights)

    async def fetch() -> dict:
        last_error: MetaApiError | None = None
        for token in tokens:
            try:
                return await get_account_data(token, ad_account_id, date_from, date_to,
                                              attribution_windows, include_inactive,
                                              include_ad_insights)
            except MetaApiError as e:
                last_error = e
        assert last_error is not None  # tokens nunca llega vacío (se valida antes de llamar)
        raise last_error

    return await _account_data_cache.get_or_fetch(key, fetch)


async def _run_insights_job(client: httpx.AsyncClient, ad_account_id: str, token: str,
                            level: str, fields: list[str], time_range: str,
                            attribution_windows: list[str] | None = None) -> list[dict]:
    """
    Pide los insights de TODA la cuenta (para un `level` dado) por la vía
    ASÍNCRONA de Meta: se crea un job en segundo plano (POST), se espera a
    que termine de calcularse (polling), y se leen los resultados ya listos.

    Por qué: la vía síncrona (GET .../insights?level=...) para una cuenta
    completa choca con el límite de "Please reduce the amount of data
    you're asking for" en cuentas con volumen real. Acotar esa misma
    consulta por campaña sí evita ese límite, pero para cuentas con MUCHAS
    campañas dispara el otro límite ("User request limit reached") por la
    cantidad de llamadas. El job asíncrono es la vía que Meta documenta
    específicamente para exportar volúmenes grandes: no tiene la restricción
    síncrona de tamaño de respuesta, y es UNA sola consulta por cuenta sin
    importar cuántas campañas/anuncios tenga.

    `attribution_windows` (ej. ["7d_click", "1d_view"]) es la ventana de
    atribución de la organización (Ajustes > Preferencias de reporte, ver
    schemas.ATTRIBUTION_WINDOWS). None/vacío = no se manda el parámetro y
    Meta usa el default de CADA cuenta publicitaria, que es como se
    comportaba esto antes de que existiera esta preferencia.
    """
    params = {
        "level": level,
        "fields": ",".join(fields),
        "time_range": time_range,
    }
    if attribution_windows:
        params["action_attribution_windows"] = json.dumps(attribution_windows)
    creation = await _post(client, f"{ad_account_id}/insights", token, params)
    report_run_id = creation.get("report_run_id")
    if not report_run_id:
        raise MetaApiError("Meta no devolvió un identificador de job para los insights.")

    waited = 0.0
    delay = _INSIGHTS_JOB_POLL_START
    while True:
        status_data = await _get(client, str(report_run_id), token,
                                 {"fields": "async_status,async_percent_completion"})
        status = status_data.get("async_status")
        if status == "Job Completed":
            break
        if status in ("Job Failed", "Job Skipped"):
            raise MetaApiError(f"El cálculo de insights en Meta falló ({status}).")
        if waited >= _INSIGHTS_JOB_MAX_WAIT:
            raise MetaApiError(
                "Meta tardó demasiado en calcular los insights de la cuenta. "
                "Intenta de nuevo en unos minutos."
            )
        await asyncio.sleep(delay)
        waited += delay
        delay = min(delay * _INSIGHTS_JOB_POLL_FACTOR, _INSIGHTS_JOB_POLL_MAX)

    return await _get_all(client, f"{report_run_id}/insights", token, {"limit": _PAGE_SIZE})


# Plataformas de publicación que Meta reconoce en el breakdown
# `publisher_platform`. audience_network/messenger casi nunca tienen gasto
# en las cuentas de VaoVao, pero se incluyen para no ocultar gasto real si
# alguna campaña sí los usa como placement.
PLATFORM_LABELS = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "audience_network": "Audience Network",
    "messenger": "Messenger",
}


async def get_platform_breakdown(token: str, ad_account_id: str,
                                 date_from: str, date_to: str) -> list[dict]:
    """
    Gasto/alcance de TODA la cuenta en el período, desglosado por
    plataforma de publicación (Facebook vs Instagram, etc.) — para el
    resumen "Facebook vs Instagram" al final del reporte.

    Es una consulta SÍNCRONA (a diferencia de _run_insights_job): el
    breakdown produce a lo mucho unas pocas filas (una por plataforma) sin
    importar cuántas campañas/anuncios tenga la cuenta, muy lejos del
    límite de tamaño que obliga a la vía asíncrona para insights por
    campaña/anuncio.

    SOLO por plataforma, sin cruzar con país: combinar publisher_platform
    con country dispara "(#100) Current combination of data breakdown
    columns ... is invalid" en cuentas reales (confirmado en producción,
    no documentado claramente por Meta). Por eso este desglose es SIEMPRE
    de la cuenta completa — report_builder lo omite cuando el reporte
    tiene un filtro de país activo, en vez de mostrar un total que no
    coincidiría con las campañas ya filtradas.
    """
    time_range = json.dumps({"since": date_from, "until": date_to})
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await _get_all(client, f"{ad_account_id}/insights", token, {
            "level": "account",
            "fields": "spend,impressions,reach,clicks",
            "breakdowns": "publisher_platform",
            "time_range": time_range,
        })


async def get_platform_breakdown_with_fallback(tokens: list[str], ad_account_id: str,
                                               date_from: str, date_to: str) -> list[dict]:
    """Igual que get_platform_breakdown, probando varios tokens en orden.
    Cacheado igual que get_account_data_with_fallback — ver _TTLCache."""
    key = (ad_account_id, date_from, date_to)

    async def fetch() -> list[dict]:
        last_error: MetaApiError | None = None
        for token in tokens:
            try:
                return await get_platform_breakdown(token, ad_account_id, date_from, date_to)
            except MetaApiError as e:
                last_error = e
        assert last_error is not None
        raise last_error

    return await _platform_breakdown_cache.get_or_fetch(key, fetch)


async def _fetch_top_ad_creatives(token: str, ad_ids: list[str]) -> dict[str, str | None]:
    """
    Trae la imagen (thumbnail/creative) SOLO de los anuncios pedidos —
    típicamente el mejor anuncio de cada campaña, que es el único que el
    PDF llega a dibujar (ver pdf_generator.render_campaign_card, que solo
    usa ads[0]).

    Antes, el listado de anuncios de get_account_data pedía
    creative{thumbnail_url,image_url} para TODOS los anuncios de la
    cuenta, sin importar cuántos fueran a mostrarse. En una cuenta con
    muchos anuncios eso inflaba esa consulta (que corre en paralelo a los
    dos jobs de insights, así que su duración también cuenta) por datos
    que se descartaban. Este segundo llamado es UNO SOLO — el endpoint
    "?ids=..." de Meta permite pedir varios objetos a la vez — y su costo
    escala con el número de CAMPAÑAS, no de anuncios.
    """
    if not ad_ids:
        return {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        data = await _get(client, "", token, {
            "ids": ",".join(ad_ids),
            "fields": "creative{thumbnail_url,image_url}",
        })
    result: dict[str, str | None] = {}
    for ad_id, obj in data.items():
        creative = (obj or {}).get("creative") or {}
        result[ad_id] = creative.get("thumbnail_url") or creative.get("image_url")
    return result


async def get_account_data(token: str, ad_account_id: str, date_from: str, date_to: str,
                           attribution_windows: list[str] | None = None,
                           include_inactive: bool = False,
                           include_ad_insights: bool = True) -> dict:
    """
    Director de orquesta: trae TODO para una cuenta publicitaria.
    Devuelve {"campaigns": [...], "total_spend": float}.

    Los insights (campaña y anuncio) se piden vía job asíncrono de Meta —ver
    _run_insights_job—, uno para toda la cuenta por nivel, sin importar
    cuántas campañas o anuncios tenga. El listado de anuncios (nombre y
    targeting, SIN imagen ni insights) SÍ se pide de forma síncrona en
    bloque porque es liviano y NO se filtra por effective_status: Meta
    tiene más estados posibles que "ACTIVE"/"PAUSED" (ej. ADSET_PAUSED,
    CAMPAIGN_PAUSED) y filtrar por esos dos nada más escondía anuncios
    legítimos que sí deberían aparecer. La imagen se trae aparte, al final,
    solo para el mejor anuncio de cada campaña — ver _fetch_top_ad_creatives.

    `include_inactive=True` conserva las campañas ACTIVA/PAUSADA sin
    insights en el período (spend=0, insights={}) en vez de descartarlas —
    lo usa /reports/summary (panel de Resumen, ver report_builder), donde
    la persona quiere ver SIEMPRE sus campañas activas/pausadas aunque el
    rango de fechas elegido no tenga gasto todavía. El PDF (build_pdf) se
    queda con el default False: ahí sí importa no inflar un reporte con
    años de campañas viejas sin actividad (ver comentario más abajo).
    `include_ad_insights=False` se salta el job asincrono de insights POR
    ANUNCIO (el mas caro de los dos: una fila por anuncio en vez de por
    campana) -- cada ad["insights"] queda en {}. Lo usan endpoints que solo
    necesitan metadata de campana/anuncio (nombre, objetivo, paises de
    targeting) pero nunca performance por anuncio: /reports/campaigns
    (panel de personalizar metricas) y /reports/countries. Antes ambos
    pagaban el costo COMPLETO de un reporte -incluido este job que ni
    usaban- solo para leer un listado.
    """
    time_range = json.dumps({"since": date_from, "until": date_to})
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with perf.aphase("Meta · listado de campañas") as info:
            campaigns = await _labeled("Listado de campañas",
                                       get_campaigns(client, token, ad_account_id))
            info["campañas"] = len(campaigns)
        if not campaigns:
            return {"campaigns": [], "total_spend": 0.0}

        api_fields = _fields_for_campaigns(campaigns)

        tasks = [
            perf.timed("Meta · insights de campañas", _labeled("Insights de campañas", _run_insights_job(
                client, ad_account_id, token, "campaign", ["campaign_id"] + api_fields, time_range,
                attribution_windows,
            ))),
            perf.timed("Meta · listado de anuncios", _labeled("Listado de anuncios", _get_all(
                client, f"{ad_account_id}/ads", token, {
                    "fields": "id,name,campaign_id,targeting",
                    "limit": _PAGE_SIZE,
                },
            ))),
        ]
        if include_ad_insights:
            tasks.append(
                perf.timed("Meta · insights de anuncios", _labeled("Insights de anuncios", _run_insights_job(
                    client, ad_account_id, token, "ad", ["ad_id"] + api_fields, time_range,
                    attribution_windows,
                )))
            )
        results = await asyncio.gather(*tasks)
        campaign_insights, ads = results[0], results[1]
        ad_insights = results[2] if include_ad_insights else []

        insights_by_campaign = {i["campaign_id"]: _with_derived_metrics(i)
                                for i in campaign_insights if i.get("campaign_id")}
        insights_by_ad = {i["ad_id"]: _with_derived_metrics(i)
                          for i in ad_insights if i.get("ad_id")}
        ads_by_campaign: dict[str, list[dict]] = {}
        for ad in ads:
            ads_by_campaign.setdefault(ad.get("campaign_id"), []).append(ad)

    campaign_data = []
    for c in campaigns:
        insights = insights_by_campaign.get(c["id"])
        if insights is None:
            # Sigue ACTIVA/PAUSADA en Meta pero no tuvo ni un dólar de gasto
            # ni impresión en el período pedido (Meta solo devuelve fila de
            # insights para entidades con actividad real) — no tiene sentido
            # meterla en un reporte de ESE período. Sin este filtro, cuentas
            # con historial largo (años de campañas viejas que nunca se
            # archivaron) inflan el reporte a decenas de páginas de puras
            # rayitas ("—"), como pasaba con OLR.
            if not include_inactive:
                continue
            insights = {}
        campaign_ads = []
        for ad in ads_by_campaign.get(c["id"], []):
            campaign_ads.append({
                "id": ad["id"],
                "name": ad.get("name"),
                "image_url": None,  # se completa más abajo, solo para el mejor anuncio de cada campaña
                "insights": insights_by_ad.get(ad["id"], {}),
                "countries": _extract_countries_from_targeting(ad.get("targeting")),
            })
        campaign_ads.sort(key=lambda a: _rank_by_insights(a["insights"]), reverse=True)

        spend = float(insights.get("spend", 0) or 0)
        campaign_data.append({
            "id": c["id"],
            "name": c.get("name"),
            "objective": c.get("objective", "DEFAULT"),
            "status": c.get("status"),
            "insights": insights,
            "ads": campaign_ads,
            "spend": spend,
        })

    if include_ad_insights:
        # Solo tiene sentido pedir imágenes cuando el llamador va a
        # dibujarlas (el PDF real) — /reports/campaigns y /reports/countries
        # ya piden include_ad_insights=False y nunca las usan.
        top_ad_ids = [c["ads"][0]["id"] for c in campaign_data if c["ads"]]
        creatives = await perf.timed(
            "Meta · imágenes del mejor anuncio por campaña",
            _labeled("Imágenes del mejor anuncio por campaña", _fetch_top_ad_creatives(token, top_ad_ids)),
        )
        for c in campaign_data:
            if c["ads"]:
                c["ads"][0]["image_url"] = creatives.get(c["ads"][0]["id"])

    total_spend = sum(c["spend"] for c in campaign_data)
    return {"campaigns": campaign_data, "total_spend": total_spend}


# ── Listado de cuentas (acceso directo + portafolios comerciales) ──────────
async def _collect(client: httpx.AsyncClient, token: str,
                   path: str, source: str, out: dict, warnings: list) -> None:
    """Pide una lista de cuentas y las acumula en `out` (dedup por id)."""
    try:
        data = await _get(client, path, token, {
            "fields": "account_id,name,account_status",
            "limit": 250,
        })
    except MetaApiError as e:
        warnings.append(f"{source}: {e}")
        return

    for a in data.get("data", []):
        acc_id = a.get("id")
        if not acc_id:
            continue
        if acc_id in out:
            # Ya la teníamos por otra vía: sumamos el origen
            if source not in out[acc_id]["sources"]:
                out[acc_id]["sources"].append(source)
            continue
        out[acc_id] = {
            "id": acc_id,                          # ej. "act_123..."
            "account_id": a.get("account_id"),     # solo el número
            "name": a.get("name"),
            "status": a.get("account_status"),
            "sources": [source],
        }


async def list_ad_accounts(token: str) -> dict:
    """
    Lista TODAS las cuentas publicitarias que un token puede ver, juntando:
      1. /me/adaccounts                      → acceso directo (rol propio)
      2. /{portafolio}/owned_ad_accounts     → cuentas que el portafolio POSEE
      3. /{portafolio}/client_ad_accounts    → cuentas de clientes COMPARTIDAS con el portafolio

    Las dos últimas son clave para agencias: las cuentas de clientes normalmente
    llegan por el portafolio comercial, no por rol directo del usuario.

    Es tolerante a fallos: si una fuente no está disponible (p. ej. falta el
    permiso business_management), se anota en 'warnings' y se devuelven las demás.

    Devuelve {"accounts": [...], "businesses": [...], "warnings": [...]}
    """
    out: dict = {}
    warnings: list = []
    businesses: list = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 1. Acceso directo (en paralelo con traer los portafolios)
        async def _load_businesses() -> list[dict]:
            try:
                biz = await _get(client, "me/businesses", token, {"fields": "id,name", "limit": 100})
                return [{"id": b.get("id"), "name": b.get("name")} for b in biz.get("data", [])]
            except MetaApiError as e:
                warnings.append(f"Portafolios: {e}")
                return []

        _, businesses = await asyncio.gather(
            _collect(client, token, "me/adaccounts", "Acceso directo", out, warnings),
            _load_businesses(),
        )

        # 2 y 3. A través de los portafolios comerciales, todos en paralelo
        if businesses:
            await asyncio.gather(*(
                _collect(client, token, f"{b['id']}/owned_ad_accounts",
                        f"Portafolio: {b.get('name') or b['id']}", out, warnings)
                for b in businesses
            ), *(
                _collect(client, token, f"{b['id']}/client_ad_accounts",
                        f"Compartida con: {b.get('name') or b['id']}", out, warnings)
                for b in businesses
            ))

    accounts = sorted(out.values(), key=lambda a: (a.get("name") or "").lower())
    return {"accounts": accounts, "businesses": businesses, "warnings": warnings}
