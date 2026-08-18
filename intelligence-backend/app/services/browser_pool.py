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

from playwright.async_api import async_playwright, Browser, Playwright

_playwright: Playwright | None = None
_browser: Browser | None = None

# Cuántos PDFs se renderizan al mismo tiempo como máximo.
RENDER_CONCURRENCY = 4
_render_semaphore = asyncio.Semaphore(RENDER_CONCURRENCY)


async def start() -> None:
    """Levanta el navegador compartido. Llamar una vez al arrancar el server."""
    global _playwright, _browser
    if _browser is not None:
        return
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(args=[
        "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    ])


async def stop() -> None:
    """Cierra el navegador compartido. Llamar al apagar el server."""
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def render_pdf(html: str) -> bytes:
    """Abre una pestaña en el navegador compartido, renderiza el HTML y devuelve el PDF."""
    if _browser is None:
        # Fallback defensivo (p. ej. si se llama desde un script suelto sin
        # pasar por el lifespan de la app).
        await start()
    async with _render_semaphore:
        page = await _browser.new_page()
        try:
            await page.set_content(html, wait_until="networkidle")
            return await page.pdf(
                format="Letter", landscape=True, print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await page.close()
