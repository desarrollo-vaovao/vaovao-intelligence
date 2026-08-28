"""
El servicio tiene que levantar aunque sus precargas opcionales fallen.

POR QUÉ EXISTE ESTE ARCHIVO
Uvicorn no abre el puerto hasta que el lifespan de `app/main.py` devuelve el
control. Mientras las dos precargas de arranque se esperaban ahí dentro
(`await browser_pool.start()` y `await assets.warm_font()`), un fallo en
cualquiera de ellas reventaba el lifespan y la API COMPLETA no llegaba a
escuchar: ni login, ni /health, ni nada.

Eso no es hipotético — tumbó el despliegue de staging. El binario de Chromium
que Playwright resuelve por defecto cambió de nombre entre versiones, el
contenedor se quedó sin él, y `chromium.launch()` se llevó por delante todo el
backend. El healthcheck solo podía reportar "la aplicación no responde",
porque efectivamente nunca abrió el puerto.

Ninguna de las dos precargas hace falta para servir una petición: `render_pdf`
levanta el navegador solo si hace falta y `assets.font_css` cae a la fuente de
respaldo. Un Chromium roto debe costar los PDFs, no el servicio.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services import assets, browser_pool


@pytest.fixture(autouse=True)
def _pool_limpio():
    """
    Deja `browser_pool` como recién importado antes y después de cada prueba.

    El lock se recrea, no solo se libera: `asyncio.Lock` se queda atado al
    event loop donde se usó por primera vez, y aquí cada prueba corre en un
    loop distinto (`asyncio.run` / `TestClient`). Reutilizarlo daría un
    "bound to a different event loop" que no dice nada del código real.
    """
    browser_pool._playwright = None
    browser_pool._browser = None
    browser_pool._start_lock = asyncio.Lock()
    yield
    browser_pool._playwright = None
    browser_pool._browser = None
    browser_pool._start_lock = asyncio.Lock()


# ── Fakes de Playwright ───────────────────────────────────────────
class _FakeChromium:
    def __init__(self, dueño: "_FakePlaywright"):
        self._dueño = dueño

    async def launch(self, **_kwargs):
        self._dueño.lanzamientos += 1
        if self._dueño.falla_al_lanzar:
            raise RuntimeError(
                "BrowserType.launch: Executable doesn't exist at "
                ".../chromium_headless_shell-1234/chrome-headless-shell"
            )
        # Un arranque lento de verdad: da lugar a que un segundo llamador
        # concurrente entre antes de que el primero termine.
        await asyncio.sleep(0.01)
        return _FakeBrowser()


class _FakeBrowser:
    def __init__(self):
        self.cerrado = False

    async def close(self):
        self.cerrado = True


class _FakePlaywright:
    def __init__(self, falla_al_lanzar: bool):
        self.falla_al_lanzar = falla_al_lanzar
        self.lanzamientos = 0
        self.detenido = False
        self.chromium = _FakeChromium(self)

    async def stop(self):
        self.detenido = True


def _parchar_playwright(monkeypatch, *, falla_al_lanzar: bool) -> _FakePlaywright:
    fake = _FakePlaywright(falla_al_lanzar)

    class _Arrancador:
        async def start(self):
            return fake

    monkeypatch.setattr(browser_pool, "async_playwright", lambda: _Arrancador())
    return fake


# ── El servicio levanta pase lo que pase ──────────────────────────
def _health_con_precargas(monkeypatch, *, start_falla: bool, fuente_falla: bool) -> int:
    """Arranca la app de verdad (lifespan incluido) y pide /health."""
    async def _start():
        if start_falla:
            raise RuntimeError("BrowserType.launch: Executable doesn't exist")

    async def _warm_font():
        if fuente_falla:
            raise RuntimeError("fonts.googleapis.com no responde")

    # `warm_font` se parcha SIEMPRE: una prueba no puede depender de salir a
    # Internet a bajar Poppins.
    monkeypatch.setattr(browser_pool, "start", _start)
    monkeypatch.setattr(assets, "warm_font", _warm_font)

    with TestClient(main.app) as client:
        return client.get("/health").status_code


def test_la_api_sirve_aunque_el_navegador_no_arranque(monkeypatch):
    """El caso exacto que tumbó staging."""
    assert _health_con_precargas(
        monkeypatch, start_falla=True, fuente_falla=False
    ) == 200


def test_la_api_sirve_aunque_no_se_pueda_bajar_la_tipografia(monkeypatch):
    assert _health_con_precargas(
        monkeypatch, start_falla=False, fuente_falla=True
    ) == 200


def test_la_api_sirve_aunque_fallen_las_dos_precargas(monkeypatch):
    assert _health_con_precargas(
        monkeypatch, start_falla=True, fuente_falla=True
    ) == 200


# ── El pool no se queda a medias ──────────────────────────────────
def test_un_launch_fallido_no_deja_el_driver_huerfano(monkeypatch):
    """
    Si `chromium.launch()` falla, el proceso del driver de Playwright YA está
    vivo. Sin limpiarlo, cada reintento perezoso de `render_pdf` sumaría otro
    driver huérfano — un goteo de procesos hasta quedarse sin memoria, justo
    en el escenario donde el navegador ya viene fallando.
    """
    fake = _parchar_playwright(monkeypatch, falla_al_lanzar=True)

    with pytest.raises(RuntimeError, match="Executable doesn't exist"):
        asyncio.run(browser_pool.start())

    assert fake.detenido, "el driver quedó vivo tras fallar el launch"
    assert browser_pool._playwright is None
    assert browser_pool._browser is None


def test_dos_arranques_concurrentes_lanzan_un_solo_navegador(monkeypatch):
    """
    La precarga en segundo plano del lifespan y el primer `render_pdf` pueden
    coincidir. Sin el lock, cada uno lanzaba su propio Chromium: el segundo
    pisaba `_browser` y el primero quedaba huérfano ocupando memoria.
    """
    fake = _parchar_playwright(monkeypatch, falla_al_lanzar=False)

    async def _dos_a_la_vez():
        await asyncio.gather(browser_pool.start(), browser_pool.start())

    asyncio.run(_dos_a_la_vez())

    assert fake.lanzamientos == 1
    assert browser_pool._browser is not None


def test_start_es_idempotente(monkeypatch):
    """Llamarlo con el navegador ya arriba no relanza nada."""
    fake = _parchar_playwright(monkeypatch, falla_al_lanzar=False)

    async def _dos_veces():
        await browser_pool.start()
        await browser_pool.start()

    asyncio.run(_dos_veces())

    assert fake.lanzamientos == 1


def test_stop_deja_el_modulo_reutilizable(monkeypatch):
    """
    Tras `stop()` el módulo tiene que quedar como recién importado, o el
    siguiente `start()` creería que sigue habiendo navegador.
    """
    fake = _parchar_playwright(monkeypatch, falla_al_lanzar=False)

    async def _ciclo():
        await browser_pool.start()
        navegador = browser_pool._browser
        await browser_pool.stop()
        return navegador

    navegador = asyncio.run(_ciclo())

    assert navegador.cerrado
    assert fake.detenido
    assert browser_pool._playwright is None
    assert browser_pool._browser is None
