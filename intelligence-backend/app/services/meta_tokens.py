"""
Resolución de tokens de Meta.

Vive aparte de las rutas porque lo usan tanto Reportes (para generar el PDF)
como Clientes (para resolver el nombre de una cuenta al registrarla).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.models import User, FacebookConnection, MetaCentralToken


def resolve_tokens(current: User, db: Session) -> tuple[list[str], str | None]:
    """
    Junta TODOS los tokens disponibles para hablar con Meta, en orden de preferencia:
      1) El Facebook conectado del usuario actual (por usuario, recomendado).
      2) Los tokens centrales de la organización (uno por portafolio comercial
         independiente — ej. "Vao Vao", "Menos Pausa" — un solo System User no
         puede cruzar de un portafolio a otro).
    Se devuelven todos (si existen) para que el llamador pueda reintentar con el
    siguiente cuando el primero no tenga acceso a una cuenta puntual — así, una
    vez que algún token central tiene permiso sobre una cuenta, cualquier
    persona del equipo puede usarla sin pedir su propio permiso individual en Meta.
    Devuelve (tokens, motivo_de_error). Si hay al menos un token, motivo es None.
    """
    tokens: list[str] = []
    undecryptable = 0

    fb_conn = db.scalar(
        select(FacebookConnection).where(FacebookConnection.user_id == current.id)
    )
    if fb_conn:
        token = crypto.decrypt(fb_conn.token_encrypted)
        if token:
            tokens.append(token)
        else:
            undecryptable += 1

    central_rows = db.scalars(
        select(MetaCentralToken).where(MetaCentralToken.org_id == current.org_id)
    ).all()
    for row in central_rows:
        token = crypto.decrypt(row.token_encrypted)
        if token:
            tokens.append(token)
        else:
            undecryptable += 1

    if not tokens:
        if undecryptable:
            # Hay credenciales guardadas pero ninguna se pudo descifrar — casi
            # siempre ENCRYPTION_KEY cambió o no coincide con la del entorno
            # donde se guardaron. Distinto de "nunca se conectó nada".
            return [], (
                f"Hay {undecryptable} credencial(es) de Meta guardadas pero no se "
                "pudieron leer (ENCRYPTION_KEY no coincide con la que se usó para "
                "guardarlas). Revisa la variable ENCRYPTION_KEY del servidor."
            )
        return [], "No has conectado tu Facebook y no hay tokens centrales (Conexión Meta)."
    return tokens, None
