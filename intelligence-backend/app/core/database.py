"""
Conexión a PostgreSQL con SQLAlchemy 2.0 (modo síncrono, igual que el Tracker).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

_url = settings.database_url_normalized
_engine_kwargs: dict = {"pool_pre_ping": True}  # evita conexiones muertas (típico en Railway)
if _url.startswith("postgresql"):
    # Pool real solo aplica para Postgres (producción). SQLite lo ignora.
    _engine_kwargs.update(pool_size=5, max_overflow=10)
else:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Clase base de todos los modelos ORM."""
    pass


def get_db():
    """Dependencia de FastAPI: abre una sesión por request y la cierra al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
