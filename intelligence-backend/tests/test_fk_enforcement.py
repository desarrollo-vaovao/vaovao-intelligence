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

Qué cambia al migrar a Postgres (y qué NO)
-------------------------------------------
PostgreSQL no tiene el interruptor de SQLite: las llaves foráneas se
respetan siempre, por conexión y sin pragma que alguien pueda borrar por
accidente. Eso significa que `test_pragma_foreign_keys_esta_encendido_en_la_conexion`
—que lee literalmente `PRAGMA foreign_keys`, sintaxis exclusiva de SQLite—
no tiene un equivalente que ejecutar en Postgres, y por eso se salta ahí en
vez de fallar con un error de sintaxis SQL que no dice nada sobre el
problema real.

Ese salto NO deja el guardia ciego en CI: se mantiene porque casi toda la
suite (incluida esta) sigue corriendo también en modo SQLite en local sin
`USE_POSTGRES_CONTAINER`, que es donde el pragma sí puede desaparecer sin
que nadie lo note. Y la segunda prueba de este archivo —la que de verdad
importa, la que comprueba el RECHAZO de una referencia colgante— no se
salta en ningún motor: en SQLite prueba que el pragma surtió efecto: en
Postgres prueba lo mismo que en producción, sin pragma de por medio. Es,
además, la prueba que test_cascada_real_bd.py da por sentada al asumir que
las FK de Postgres aplican sin necesitar nada especial.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Lead


def test_pragma_foreign_keys_esta_encendido_en_la_conexion(db: Session) -> None:
    """Si esto es 0, TODA prueba de cascada de la suite es un falso verde.

    Se salta sobre Postgres: `PRAGMA foreign_keys` es sintaxis de SQLite y
    Postgres no tiene un pragma equivalente porque no tiene el interruptor
    que este guardia vigila — ahí las FK están SIEMPRE activas. El guardia
    real en Postgres es la prueba de abajo.
    """
    dialect = db.get_bind().dialect.name
    if dialect != "sqlite":
        pytest.skip(
            f"PRAGMA foreign_keys es sintaxis de SQLite; el motor activo es "
            f"'{dialect}', donde las FK se respetan sin pragma. Ver "
            f"test_insertar_un_lead_con_client_id_inexistente_es_rechazado."
        )
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_insertar_un_lead_con_client_id_inexistente_es_rechazado(db: Session) -> None:
    """La base rechaza referencias colgantes: prueba viva de que las FK aplican.

    Corre igual en los dos motores y en los dos prueba algo distinto:

    * En SQLite, que el pragma de `conftest.py` sigue en su sitio — si
      desapareciera, SQLite aceptaría este INSERT sin chistar y esta prueba
      fallaría, que es exactamente el aviso que se busca.
    * En Postgres, que la FK de la migración (`ondelete="CASCADE"` en
      `leads.client_id`, ver `app/models/__init__.py` y
      `alembic/versions/0002_modulo_de_leads.py`) está de verdad en el
      esquema aplicado, sin depender de ningún interruptor de sesión.
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
