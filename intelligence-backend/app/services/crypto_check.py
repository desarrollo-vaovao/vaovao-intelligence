"""
Chequeo de arranque: ¿la llave actual puede leer las credenciales guardadas?

El incidente del 2026-08-27 fue silencioso. Se cambió ENCRYPTION_KEY, el
servidor arrancó sin una sola queja, y el problema recién apareció horas
después cuando alguien pidió un reporte y recibió un 503. Para entonces la
llave anterior ya no existía en ningún lado y las credenciales de Meta eran
irrecuperables.

Este chequeo mueve el aviso al momento del despliegue, que es cuando quien
cambió la variable todavía está mirando y todavía tiene la llave anterior a
mano.

NO tumba el arranque a propósito. Un tropiezo de la base al bootear dejaría
la aplicación entera en ciclo de reinicio, que es peor que el problema que
intenta evitar: con las credenciales ilegibles el resto del sistema (login,
clientes, usuarios) sigue siendo perfectamente utilizable.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.database import SessionLocal
from app.models import FacebookConnection, MetaCentralToken

log = logging.getLogger(__name__)


def _contar_ilegibles(db: Session) -> tuple[int, int]:
    """Devuelve (ilegibles, total) entre todas las credenciales guardadas."""
    cifrados = [
        row.token_encrypted
        for row in db.scalars(select(MetaCentralToken)).all()
    ] + [
        row.token_encrypted
        for row in db.scalars(select(FacebookConnection)).all()
    ]
    ilegibles = sum(1 for c in cifrados if crypto.decrypt(c) is None)
    return ilegibles, len(cifrados)


def revisar_credenciales() -> None:
    """Reporta en los logs de arranque si algo quedó ilegible."""
    try:
        with SessionLocal() as db:
            ilegibles, total = _contar_ilegibles(db)
    except Exception as e:
        # Incluye el caso de una ENCRYPTION_KEY con formato inválido, que
        # crypto.decrypt deja salir como ValueError a propósito.
        log.warning("No se pudo revisar el cifrado de credenciales: %s", e)
        return

    if not total:
        return

    if ilegibles:
        log.error(
            "CIFRADO: %d de %d credencial(es) de Meta no se pueden leer con la "
            "ENCRYPTION_KEY actual. Casi siempre significa que la llave se "
            "cambió sin conservar la anterior. Si todavía tienes la llave "
            "previa, agrégala a ENCRYPTION_KEYS (nueva primero, anterior "
            "después) y se recuperan solas. Si no la tienes, esas credenciales "
            "no se pueden recuperar y hay que volver a capturarlas en "
            "Conexión Meta.",
            ilegibles, total,
        )
    else:
        log.info("CIFRADO: las %d credencial(es) guardadas se leen bien.", total)
