"""
browser_pool — un solo Chromium compartido para renderizar PDFs.

Lanzar un navegador nuevo por reporte (arrancar Chromium desde cero) cuesta
1-2+ segundos solo de arranque, y bajo carga concurrente (varias personas
generando reportes a la vez) lanzaría un proceso de Chromium por cada uno —
suficiente para tumbar el servicio por memoria con 10-100 reportes a la vez.

En vez de eso: se levanta UN navegador cuando arranca el servidor (ver
lifespan en app/main.py) y cada reporte solo abre/cierra una pestaña, mucho
más barato. Un semáforo limita cuántos PDFs se renderizan en paralelo — el
resto espera su turno sin fallar ni saturar CPU/memoria.
"""
import asyncio

from playwright.async_api import (
    async_playwright,
    Browser,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
)

_playwright: Playwright | None = None
_browser: Browser | None = None

# Serializa los arranques del navegador. Sin esto, dos reportes que llegan
# a la vez con el pool frío (o un reporte que llega mientras el arranque en
# segundo plano del lifespan todavía no termina) lanzaban DOS Chromium: el
# segundo pisaba `_browser` y el primero quedaba huérfano, consumiendo
# memoria hasta que se cayera el contenedor.
_start_lock = asyncio.Lock()

# Cuántos PDFs se renderizan al mismo tiempo como máximo.
RENDER_CONCURRENCY = 4
_render_semaphore = asyncio.Semaphore(RENDER_CONCURRENCY)

# Techo de espera a que la página termine de cargar antes de imprimirla igual
# (ver render_pdf). Con todo incrustado el "load" real es de milisegundos.
_LOAD_TIMEOUT_MS = 5_000


async def _soltar_todo() -> None:
    """
    Cierra navegador y driver dejando el módulo como recién importado, sin
    propagar errores.

    Se usa tanto al apagar como para limpiar un arranque a medias: si
    `chromium.launch()` falla, el proceso del driver de Playwright YA quedó
    vivo. Sin esto, cada reintento sumaba un driver huérfano.
    """
    global _playwright, _browser
    try:
        if _browser is not None:
            await _browser.close()
    except Exception as e:
        print(f"[browser_pool] No se pudo cerrar el navegador "
              f"({type(e).__name__}: {e}).", flush=True)
    finally:
        _browser = None
    try:
        if _playwright is not None:
            await _playwright.stop()
    except Exception as e:
        print(f"[browser_pool] No se pudo cerrar el driver de Playwright "
              f"({type(e).__name__}: {e}).", flush=True)
    finally:
        _playwright = None


async def start() -> None:
    """
    Levanta el navegador compartido si no está ya levantado.

    Es idempotente y seguro de llamar concurrentemente: lo invocan tanto la
    precarga en segundo plano del arranque (ver el lifespan de app/main.py)
    como `render_pdf` cuando el pool está frío, y las dos pueden coincidir.
    """
    global _playwright, _browser
    if _browser is not None:
        return
    async with _start_lock:
        # Otro llamador pudo haberlo levantado mientras esperábamos el lock.
        if _browser is not None:
            return
        try:
            if _playwright is None:
                _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(args=[
                "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
            ])
        except BaseException:
            # BaseException y no Exception: si esto se cancela (timeout del
            # llamador, apagado del server), igual hay que soltar el driver
            # a medio levantar antes de re-lanzar.
            await _soltar_todo()
            raise


async def stop() -> None:
    """Cierra el navegador compartido. Llamar al apagar el server."""
    await _soltar_todo()


async def render_pdf(html: str) -> bytes:
    """Abre una pestaña en el navegador compartido, renderiza el HTML y devuelve el PDF."""
    if _browser is None:
        # Fallback defensivo (p. ej. si se llama desde un script suelto sin
        # pasar por el lifespan de la app).
        await start()
    async with _render_semaphore:
        page = await _browser.new_page()
        try:
            # "load" (recursos cargados) en vez de "networkidle" (500ms SIN
            # actividad de red): con muchas imágenes de anuncios de Meta,
            # networkidle sumaba esa espera de más incluso cuando el
            # contenido ya estaba listo para imprimir.
            #
            # El HTML llega con la tipografía y las imágenes ya incrustadas
            # como data: URI (ver app/services/assets.py), así que "load" se
            # cumple sin tocar la red y esta espera es de milisegundos. El
            # tope está por si alguna vez se cuela una URL remota: antes,
            # una sola imagen que no respondía dejaba el reporte esperando
            # hasta el timeout por defecto de Playwright (30 s). Si se agota,
            # se imprime igual con lo que sí cargó — un PDF con una imagen de
            # menos es mejor que medio minuto de spinner.
            try:
                await page.set_content(html, wait_until="load",
                                       timeout=_LOAD_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                print("[browser_pool] La página tardó más de "
                      f"{_LOAD_TIMEOUT_MS} ms en cargar; se imprime igual.")
            return await page.pdf(
                format="Letter", landscape=True, print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await page.close()
