"""
Entorno de Alembic.

Dos decisiones que conviene no deshacer:

1. La URL de la base sale de `app.core.config.settings`, no de `alembic.ini`.
   Es la MISMA fuente que usa la app (`app/core/database.py`), así que no
   existe la posibilidad de migrar una base y servir otra. Además pasa por
   `database_url_normalized`, que arregla el `postgres://` que Railway entrega
   a veces y que psycopg2 rechaza.

2. `target_metadata` apunta al `Base` de la app, y se importa `app.models`
   ANTES de leerlo. Un modelo que no se importe no está registrado en el
   metadata, y para `--autogenerate` una tabla invisible no es "sin cambios":
   es una tabla que sobra en la base y que propone BORRAR. Hoy todos los
   modelos viven en `app/models/__init__.py`, así que este único import
   alcanza; si algún día se parten en varios módulos, hay que importarlos
   todos aquí.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base

# Registra TODAS las tablas en Base.metadata. Ver punto 2 del docstring.
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Los `%` de una contraseña se comen como interpolación de configparser si no
# se escapan; con `%%` la URL llega literal.
config.set_main_option(
    "sqlalchemy.url", settings.database_url_normalized.replace("%", "%%")
)

target_metadata = Base.metadata


def _dialect_opts(connection=None) -> dict:
    """Opciones que dependen del motor.

    `render_as_batch` sólo importa en SQLite, que no sabe hacer
    `ALTER COLUMN`: Alembic emula el cambio recreando la tabla. En Postgres no
    hace falta y se deja apagado para que el SQL sea el directo.
    """
    is_sqlite = (
        connection.dialect.name == "sqlite"
        if connection is not None
        else config.get_main_option("sqlalchemy.url", "").startswith("sqlite")
    )
    return {"render_as_batch": is_sqlite}


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
        **_dialect_opts(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Corre las migraciones contra la base de verdad."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
            **_dialect_opts(connection),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
