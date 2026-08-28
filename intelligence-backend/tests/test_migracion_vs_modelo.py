"""
Hueco 1: deriva entre modelos y migraciones.

Por qué NO se puede cerrar esto sobre SQLite
---------------------------------------------
El esquema de TODAS las demás pruebas de esta suite sale de
`Base.metadata.create_all()` (ver `tests/conftest.py`), no de Alembic. Eso
es correcto para probar comportamiento de la app —rápido, sin depender de
que alguien recuerde generar una migración—, pero significa que un modelo y
su migración se pueden separar sin que NINGUNA prueba lo note: la suite
entera seguiría en verde comprobando un esquema que nunca pasó por Alembic.

Esto ya pasó una vez de verdad: `lead_audits.user_id` se volvió `nullable`
en el modelo (para que `ON DELETE SET NULL` funcionara) sin que la migración
original lo reflejara — quedó `NOT NULL` en varias bases hasta que
`0003_bitacora_sobrevive_al_usuario.py` lo corrigió. Ninguna prueba de la
suite lo vio, porque ninguna corría contra una base migrada.

Qué hace esta prueba
---------------------
Aplica las migraciones de `alembic/versions/` a una base Postgres VACÍA
(nunca a la que usa `Base.metadata.create_all()` de las demás pruebas — se
crea una base nueva para no interferir) y usa
`alembic.autogenerate.compare_metadata()` para diferenciar ese esquema
migrado contra `Base.metadata`, el mismo origen de verdad que usa
`create_all()`. Una diferencia ahí es EXACTAMENTE el bug de
`lead_audits.user_id`: un modelo que ya cambió y una migración que no.

Por qué necesita Postgres y no alcanza con corretear Alembic sobre SQLite
--------------------------------------------------------------------------
Se podría, en teoría, migrar una base SQLite y comparar igual. Pero
`alembic/env.py` activa `render_as_batch` sólo para SQLite porque ese motor
no sabe hacer `ALTER COLUMN` (recrea la tabla completa por dentro), y ese
camino de recreación es distinto código al que corre en Postgres — probarlo
ahí no dice nada de si la migración real (la que corre en producción, contra
Postgres) coincide con el modelo. Verificar sobre SQLite sería, otra vez,
verde y falso.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import app.models  # noqa: F401 — registra TODAS las tablas en Base.metadata
from app.core.config import settings as app_settings
from app.core.database import Base

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB_NAME = "migracion_vs_modelo_check"


def _run_migrations_on_fresh_database(base_url: str) -> str:
    """Crea una base Postgres vacía y le aplica `alembic upgrade head`.

    Devuelve la URL de esa base ya migrada. Se crea aparte (no se reutiliza
    la base de la fixture `engine`) para que esta comparación no dependa de
    qué otras pruebas corrieron antes ni deje su rastro en ellas: el único
    origen de este esquema es Alembic, sin `create_all()` de por medio.

    Por qué se parchea `app_settings.DATABASE_URL` en vez de pasarle la URL
    a `Config` directamente
    ------------------------------------------------------------------------
    `alembic/env.py` IGNORA a propósito lo que traiga `Config.sqlalchemy.url`
    y lo pisa siempre con `settings.database_url_normalized` (es la decisión
    documentada en su propio docstring: una sola fuente de verdad para la URL,
    para que nunca se migre una base y sirva otra). `settings` es el
    singleton de `app/core/config.py`, ya instanciado desde que `conftest.py`
    importó la app con `DATABASE_URL=sqlite+pysqlite:///:memory:`. Pasarle la
    URL de Postgres sólo a `Config` —como haría un `alembic.ini` normal—
    terminaría migrando ese SQLite en memoria sin que ningún error lo avise,
    y la comparación de después saldría en blanco contra una base vacía.
    Parchear el atributo del singleton es la única forma de que `env.py` lea
    la URL que de verdad importa aquí.
    """
    admin_url = make_url(base_url)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
            conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    finally:
        admin_engine.dispose()

    target_url = admin_url.set(database=_DB_NAME)
    # `str(url)` enmascara la contraseña como "***" desde SQLAlchemy 1.4 (es
    # un __repr__ pensado para logs, no para reconectar). Usar eso aquí haría
    # que Alembic intentara autenticarse con la contraseña literal "***" y
    # fallara. `render_as_string(hide_password=False)` es la forma explícita
    # de pedir la URL completa y utilizable.
    target_url_str = target_url.render_as_string(hide_password=False)

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))

    original_database_url = app_settings.DATABASE_URL
    app_settings.DATABASE_URL = target_url_str
    try:
        command.upgrade(cfg, "head")
    finally:
        app_settings.DATABASE_URL = original_database_url

    return target_url_str


def _drop_database(base_url: str) -> None:
    admin_engine = create_engine(make_url(base_url), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
    finally:
        admin_engine.dispose()


def test_las_migraciones_producen_el_mismo_esquema_que_los_modelos(
    require_postgres: str,
) -> None:
    """`alembic upgrade head` y `Base.metadata` deben describir la MISMA base.

    Si esto falla, hay un modelo que cambió sin su migración (o al revés):
    exactamente el escenario de `lead_audits.user_id` que ya nos mordió una
    vez, atrapado ahora en CI en vez de en producción.
    """
    base_url = require_postgres
    migrated_url = _run_migrations_on_fresh_database(base_url)
    try:
        engine = create_engine(migrated_url)
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                diff = compare_metadata(context, Base.metadata)
        finally:
            engine.dispose()
    finally:
        _drop_database(base_url)

    assert diff == [], (
        "El esquema migrado por Alembic difiere de Base.metadata (modelos). "
        f"Diferencias: {diff!r}. Genera o corrige la migración que falta con "
        "`alembic revision --autogenerate`."
    )
