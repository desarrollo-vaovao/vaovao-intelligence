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
import asyncio
import httpx

API_VERSION = os.getenv("META_API_VERSION", "v23.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
TIMEOUT = httpx.Timeout(30.0)

# Cuántas llamadas a la Graph API dejamos en vuelo al mismo tiempo.
# Sin límite se puede topar con el rate limit de Meta si hay muchos anuncios.
_MAX_CONCURRENCY = 8

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


class MetaApiError(Exception):
    """Error al hablar con Meta (token inválido, sin acceso, etc.)."""


def _metrics_for(objective: str) -> list[str]:
    return METRICS_BY_OBJECTIVE.get(objective, METRICS_BY_OBJECTIVE["DEFAULT"])


async def _get(client: httpx.AsyncClient, sem: asyncio.Semaphore, path: str,
                token: str, params: dict) -> dict:
    """GET a la Graph API con el token. Devuelve el JSON o lanza MetaApiError."""
    params = {**params, "access_token": token}
    async with sem:
        resp = await client.get(f"{BASE_URL}/{path}", params=params)
    data = resp.json()
    if resp.status_code != 200:
        err = (data.get("error") or {}).get("message", "Error desconocido de Meta")
        raise MetaApiError(err)
    return data


async def check_account_access(token: str, ad_account_id: str) -> tuple[bool, str]:
    """
    Verifica si el token puede LEER una cuenta publicitaria.
    Devuelve (True, nombre) si sí; (False, motivo) si no.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            sem = asyncio.Semaphore(_MAX_CONCURRENCY)
            data = await _get(client, sem, ad_account_id, token, {"fields": "name,account_status"})
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


async def get_campaigns(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                        token: str, ad_account_id: str) -> list[dict]:
    """Todas las campañas (activas y pausadas) de una cuenta, con su info básica."""
    data = await _get(client, sem, f"{ad_account_id}/campaigns", token, {
        "fields": "id,name,objective,status,daily_budget,lifetime_budget",
        "filtering": json.dumps([{"field": "effective_status", "operator": "IN",
                                  "value": ["ACTIVE", "PAUSED"]}]),
        "limit": 50,
    })
    return data.get("data", [])


async def get_campaign_insights(client: httpx.AsyncClient, sem: asyncio.Semaphore, token: str,
                                campaign_id: str, objective: str,
                                date_from: str, date_to: str) -> dict | None:
    """Números de rendimiento de UNA campaña en el rango de fechas."""
    data = await _get(client, sem, f"{campaign_id}/insights", token, {
        "fields": ",".join(_metrics_for(objective)),
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "level": "campaign",
    })
    rows = data.get("data", [])
    return rows[0] if rows else None


async def get_campaign_ads(client: httpx.AsyncClient, sem: asyncio.Semaphore, token: str,
                           campaign_id: str, objective: str,
                           date_from: str, date_to: str) -> list[dict]:
    """Anuncios de una campaña con su rendimiento e imagen, ordenados por desempeño."""
    metrics = _metrics_for(objective)

    adsets = (await _get(client, sem, f"{campaign_id}/adsets", token,
                         {"fields": "id,name", "limit": 20})).get("data", [])

    async def _ads_for_adset(adset: dict) -> list[dict]:
        ads = (await _get(client, sem, f"{adset['id']}/ads", token, {
            "fields": "id,name,creative{thumbnail_url,image_url,object_story_spec}",
            "limit": 20,
        })).get("data", [])

        async def _with_insights(ad: dict) -> dict:
            insights_rows = (await _get(client, sem, f"{ad['id']}/insights", token, {
                "fields": ",".join(metrics),
                "time_range": json.dumps({"since": date_from, "until": date_to}),
            })).get("data", [])
            insights = insights_rows[0] if insights_rows else {}

            creative = ad.get("creative") or {}
            image_url = creative.get("thumbnail_url") or creative.get("image_url")

            return {
                "id": ad["id"],
                "name": ad.get("name"),
                "image_url": image_url,
                "insights": insights,
            }

        if not ads:
            return []
        return list(await asyncio.gather(*(_with_insights(ad) for ad in ads)))

    if not adsets:
        all_ads: list[dict] = []
    else:
        groups = await asyncio.gather(*(_ads_for_adset(adset) for adset in adsets))
        all_ads = [ad for group in groups for ad in group]

    def _rank(ad: dict) -> float:
        i = ad["insights"]
        for key in ("clicks", "messaging_conversation_started_7d", "post_engagement", "impressions"):
            if i.get(key) is not None:
                try:
                    return float(i[key])
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    all_ads.sort(key=_rank, reverse=True)
    return all_ads


async def get_account_data_with_fallback(tokens: list[str], ad_account_id: str,
                                         date_from: str, date_to: str) -> dict:
    """
    Igual que get_account_data, pero prueba varios tokens en orden (p. ej. el
    Facebook personal del usuario y, si a ESA cuenta le falta acceso, el token
    central de la organización) hasta que uno funcione. Así, una vez que el
    token central tiene permiso sobre una cuenta, cualquier persona del equipo
    puede generar su reporte aunque su Facebook personal no tenga acceso.
    """
    last_error: MetaApiError | None = None
    for token in tokens:
        try:
            return await get_account_data(token, ad_account_id, date_from, date_to)
        except MetaApiError as e:
            last_error = e
    assert last_error is not None  # tokens nunca llega vacío (se valida antes de llamar)
    raise last_error


async def get_account_data(token: str, ad_account_id: str, date_from: str, date_to: str) -> dict:
    """
    Director de orquesta: trae TODO para una cuenta publicitaria.
    Devuelve {"campaigns": [...], "total_spend": float}.
    Todas las campañas (y, dentro de cada una, insights + anuncios) se piden en paralelo.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        campaigns = await get_campaigns(client, sem, token, ad_account_id)

        async def _for_campaign(campaign: dict) -> dict:
            objective = campaign.get("objective", "DEFAULT")
            insights, ads = await asyncio.gather(
                get_campaign_insights(client, sem, token, campaign["id"], objective, date_from, date_to),
                get_campaign_ads(client, sem, token, campaign["id"], objective, date_from, date_to),
            )
            spend = float((insights or {}).get("spend", 0) or 0)
            return {
                "id": campaign["id"],
                "name": campaign.get("name"),
                "objective": objective,
                "status": campaign.get("status"),
                "insights": insights or {},
                "ads": ads,
                "spend": spend,
            }

        campaign_data = list(await asyncio.gather(*(_for_campaign(c) for c in campaigns))) if campaigns else []

    total_spend = sum(c["spend"] for c in campaign_data)
    return {"campaigns": campaign_data, "total_spend": total_spend}


# ── Listado de cuentas (acceso directo + portafolios comerciales) ──────────
async def _collect(client: httpx.AsyncClient, sem: asyncio.Semaphore, token: str,
                   path: str, source: str, out: dict, warnings: list) -> None:
    """Pide una lista de cuentas y las acumula en `out` (dedup por id)."""
    try:
        data = await _get(client, sem, path, token, {
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
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        # 1. Acceso directo (en paralelo con traer los portafolios)
        async def _load_businesses() -> list[dict]:
            try:
                biz = await _get(client, sem, "me/businesses", token, {"fields": "id,name", "limit": 100})
                return [{"id": b.get("id"), "name": b.get("name")} for b in biz.get("data", [])]
            except MetaApiError as e:
                warnings.append(f"Portafolios: {e}")
                return []

        _, businesses = await asyncio.gather(
            _collect(client, sem, token, "me/adaccounts", "Acceso directo", out, warnings),
            _load_businesses(),
        )

        # 2 y 3. A través de los portafolios comerciales, todos en paralelo
        if businesses:
            await asyncio.gather(*(
                _collect(client, sem, token, f"{b['id']}/owned_ad_accounts",
                        f"Portafolio: {b.get('name') or b['id']}", out, warnings)
                for b in businesses
            ), *(
                _collect(client, sem, token, f"{b['id']}/client_ad_accounts",
                        f"Compartida con: {b.get('name') or b['id']}", out, warnings)
                for b in businesses
            ))

    accounts = sorted(out.values(), key=lambda a: (a.get("name") or "").lower())
    return {"accounts": accounts, "businesses": businesses, "warnings": warnings}
