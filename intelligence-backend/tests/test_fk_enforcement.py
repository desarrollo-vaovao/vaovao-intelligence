"""
Guardia de la propia suite: las llaves foráneas TIENEN que estar activas.

Por qué este archivo existe
---------------------------
SQLite trae el soporte de llaves foráneas apagado y se enciende por conexión
(`PRAGMA foreign_keys=ON`). El listener que lo hace vive en `conftest.py`. Si
alguien lo borra —refactorizando fixtures, cambiando de motor, "limpiando"—
las pruebas de cascada de `test_cascadas.py` NO fallarían: pasarían igual,
porque un `ON DELETE SET NULL` que nunca se ejecuta deja las filas intactas y
un `ON DELETE CASCADE` que nunca se ejecuta también. La suite quedaría verde
comprobando nada, que es peor que no tenerla.

Estas dos pruebas son las únicas que rompen ruidosamente en ese escenario:
comprueban la ENFORCEMENT en sí, no una cascada concreta.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Lead


def test_pragma_foreign_keys_esta_encendido_en_la_conexion(db: Session) -> None:
    """Si esto es 0, TODA prueba de cascada de la suite es un falso verde."""
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_insertar_un_lead_con_client_id_inexistente_es_rechazado(db: Session) -> None:
    """La base rechaza referencias colgantes: prueba viva de que las FK aplican.

    Si el pragma desapareciera, SQLite aceptaría este INSERT sin chistar y esta
    prueba fallaría — que es exactamente el aviso que se busca.
    """
    lead = Lead(
        org_id=999_999,
        client_id=999_999,
        leadgen_id="lead-con-padres-inexistentes",
        form_data={},
    )
    db.add(lead)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
