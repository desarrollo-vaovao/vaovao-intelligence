"""
perf — cronómetro por fase para la generación de reportes.

Sin esto, "el reporte tardó 12 segundos" no dice NADA accionable: no se sabe
si se fueron esperando a Meta, bajando imágenes o dentro de Chromium. Cada
fase se mide y se imprime a stdout (que es lo que Railway captura), con el
mismo prefijo `[perf]` para poder filtrarlas de un vistazo en los logs.

Es deliberadamente tonto —un print, no un sistema de métricas—: el objetivo
es saber dónde está el tiempo, no montar observabilidad.
"""
import time
from contextlib import asynccontextmanager, contextmanager


def _log(label: str, elapsed: float, extra: str = "") -> None:
    print(f"[perf] {label}: {elapsed * 1000:.0f} ms{extra}")


@contextmanager
def phase(label: str):
    """
    Mide un bloque síncrono. `phase()` devuelve un dict al que el bloque le
    puede agregar detalle (ej. cuántas campañas venían), que sale en la línea
    del log:

        with phase("Insights") as info:
            ...
            info["campañas"] = len(campaigns)
    """
    info: dict = {}
    started = time.monotonic()
    try:
        yield info
    finally:
        extra = f" ({', '.join(f'{k}={v}' for k, v in info.items())})" if info else ""
        _log(label, time.monotonic() - started, extra)


@asynccontextmanager
async def aphase(label: str):
    """Igual que phase(), para bloques `async with`."""
    with phase(label) as info:
        yield info


async def timed(label: str, coro):
    """
    Envuelve una corrutina suelta para medirla. Útil dentro de un
    asyncio.gather(), donde no se puede usar un `with` por rama:

        a, b = await asyncio.gather(timed("A", foo()), timed("B", bar()))
    """
    started = time.monotonic()
    try:
        return await coro
    finally:
        _log(label, time.monotonic() - started)
