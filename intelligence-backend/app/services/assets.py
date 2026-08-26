"""
assets — los recursos externos que el PDF necesita (la tipografía Poppins y
los thumbnails de los anuncios), bajados por adelantado y guardados en
memoria del proceso.

POR QUÉ EXISTE
pdf_generator renderiza con `wait_until="load"`: Chromium no devuelve el PDF
hasta que TODO recurso remoto de la página terminó de bajar. Con la fuente
enlazada a fonts.googleapis.com y las imágenes a fbcdn.net, cada reporte
pagaba de nuevo el DNS + TLS + descarga de todo eso desde el contenedor de
Railway. Y peor: una sola URL lenta congelaba el reporte entero, porque
`load` espera a la última.

Aquí se bajan antes de armar el HTML, en paralelo y con un tope de tiempo
propio, y se incrustan como data: URI. Así Chromium recibe una página sin
una sola petición de red y el PDF sale de inmediato. Un recurso que falla o
tarda de más simplemente no se incrusta —la fuente cae a Arial, la imagen al
placeholder de "Sin imagen"— en vez de frenar el reporte completo.

Todo se cachea en memoria del proceso, igual que _JOBS en routes/reports.py y
por la misma razón: es un solo servicio en Railway y el costo de perder la
caché en un reinicio es un reporte un poco más lento, no un dato perdido.
"""
import asyncio
import base64
import re

import httpx

# ── Tipografía ────────────────────────────────────────────────
_FONT_CSS_URL = ("https://fonts.googleapis.com/css2"
                 "?family=Poppins:wght@400;500;600&display=swap")

# Google Fonts decide el formato según el User-Agent: con el de httpx devuelve
# TTF (varias veces más pesado), con uno de Chrome moderno devuelve woff2.
_WOFF2_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_FONT_TIMEOUT = httpx.Timeout(10.0)
_font_css: str | None = None
_font_lock = asyncio.Lock()

# ── Imágenes de anuncios ──────────────────────────────────────
# Las URLs de thumbnail de Meta traen su propio token de expiración, así que
# la URL cambia cuando el contenido cambia: cachear por URL nunca sirve una
# imagen vieja.
_IMAGE_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
# Un thumbnail de Meta pesa unos pocos KB; `image_url` (el respaldo cuando no
# hay thumbnail) puede ser la creatividad completa. Más que esto no vale la
# pena incrustarlo en un recuadro de 72×72 px.
_IMAGE_MAX_BYTES = 2 * 1024 * 1024
# Tope de la caché en número de imágenes. Con ~2 MB de techo por imagen esto
# acota el peor caso a unos cientos de MB, pero en la práctica son thumbnails
# de pocos KB. Al llenarse se descartan las más viejas (FIFO).
_IMAGE_CACHE_MAX = 400
_image_cache: dict[str, str | None] = {}


async def _fetch_font_css() -> str | None:
    """
    Trae el CSS de Poppins y reemplaza cada `url(https://fonts.gstatic.com/…)`
    por el woff2 ya incrustado en base64. Se conservan los bloques @font-face
    tal cual los manda Google (con sus `unicode-range`), así que el resultado
    se comporta igual que el <link> original, pero sin red.
    """
    try:
        async with httpx.AsyncClient(timeout=_FONT_TIMEOUT,
                                     headers={"User-Agent": _WOFF2_UA}) as client:
            resp = await client.get(_FONT_CSS_URL)
            resp.raise_for_status()
            css = resp.text

            urls = sorted(set(re.findall(r"url\((https://[^)]+)\)", css)))
            if not urls:
                return None

            responses = await asyncio.gather(
                *(client.get(u) for u in urls), return_exceptions=True
            )

        for url, resp in zip(urls, responses):
            if isinstance(resp, Exception) or resp.status_code != 200:
                # Falta un subset (ej. latin-ext): se deja la URL remota de ese
                # bloque. Chromium solo la pedirá si el texto la necesita.
                continue
            b64 = base64.b64encode(resp.content).decode("ascii")
            css = css.replace(url, f"data:font/woff2;base64,{b64}")
        return css
    except (httpx.HTTPError, ValueError) as e:
        print(f"[assets] No se pudo incrustar Poppins ({type(e).__name__}: {e}); "
              "el PDF usará la fuente de respaldo.")
        return None


async def font_css() -> str | None:
    """
    El CSS de Poppins con las fuentes incrustadas, o None si no se pudo bajar
    (el PDF cae a Arial y se genera igual). Se baja UNA vez por proceso; el
    lock evita que varios reportes simultáneos en frío la bajen en paralelo.
    """
    global _font_css
    if _font_css is not None:
        return _font_css
    async with _font_lock:
        if _font_css is None:
            _font_css = await _fetch_font_css()
    return _font_css


async def warm_font() -> None:
    """
    Precarga la tipografía al arrancar el servidor, para que ni el primer
    reporte del día pague la bajada. Nunca lanza: si falla, el reporte se
    genera igual con la fuente de respaldo.
    """
    await font_css()


def _cache_image(url: str, value: str | None) -> None:
    if len(_image_cache) >= _IMAGE_CACHE_MAX:
        for old in list(_image_cache)[:len(_image_cache) - _IMAGE_CACHE_MAX + 1]:
            _image_cache.pop(old, None)
    _image_cache[url] = value


async def _fetch_image(client: httpx.AsyncClient, url: str) -> str | None:
    """Baja una imagen y la devuelve como data: URI, o None si no se pudo."""
    try:
        resp = await client.get(url)
        if resp.status_code != 200 or len(resp.content) > _IMAGE_MAX_BYTES:
            return None
        mime = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            return None
        return f"data:{mime};base64,{base64.b64encode(resp.content).decode('ascii')}"
    except httpx.HTTPError:
        return None


async def inline_images(urls: list[str]) -> dict[str, str]:
    """
    Baja en paralelo las imágenes que no estén en caché y devuelve
    {url_original: data_uri} solo con las que se pudieron bajar. Las que
    fallan quedan fuera del diccionario a propósito: el llamador conserva la
    URL original (o el placeholder) y el reporte sale igual.

    Los fallos también se cachean, para que un anuncio con una imagen rota no
    haga reintentar la misma descarga en cada reporte del período.
    """
    wanted = [u for u in dict.fromkeys(urls) if u]
    pending = [u for u in wanted if u not in _image_cache]

    if pending:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT, follow_redirects=True) as client:
            results = await asyncio.gather(*(_fetch_image(client, u) for u in pending))
        for url, data_uri in zip(pending, results):
            _cache_image(url, data_uri)

    return {u: _image_cache[u] for u in wanted if _image_cache.get(u)}
