"""
VaoVao Intelligence — punto de entrada.
Plataforma multi-tenant en FastAPI. Módulos: auth, clientes, usuarios,
conexión con Meta (token central + OAuth por usuario) y reportes.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.ratelimit import limiter
from app.api.routes import (
    auth,
    clients,
    users,
    organization,
    reports,
    facebook,
    leads,
)
from app.services import browser_pool

# Importa todos los modelos de una vez. Ya no es para `create_all` (ver el
# lifespan), pero sigue haciendo falta: las `relationship()` se declaran con el
# nombre de la clase destino en un string, y SQLAlchemy sólo puede resolverlas
# cuando todas las clases mapeadas están importadas.
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Al arrancar: levanta el navegador compartido para generar PDFs
    (ver app/services/browser_pool.py — evita lanzar un Chromium nuevo por
    cada reporte).

    Aquí ya NO se crean tablas
    --------------------------
    Antes esto llamaba a `Base.metadata.create_all()`. Ahora el esquema lo
    versiona Alembic (`alembic/`), y `alembic upgrade head` corre en el
    arranque del servicio, antes de uvicorn (ver Procfile y Dockerfile).

    Convivir con las dos cosas sería tener dos fuentes de verdad, y no dos
    equivalentes: `create_all` crea las tablas que faltan pero NUNCA altera
    una columna de una tabla que ya existe. Es justo lo que dejó a varias
    bases con `lead_audits.user_id` NOT NULL después de que el modelo lo
    hiciera nullable. Dejarlo puesto significaría que la app puede fabricarse
    en silencio un esquema que ninguna migración describe, y que el siguiente
    `alembic upgrade` se encuentre una base en un estado que no esperaba.

    A cambio, una base nueva (un desarrollador que empieza, o los tests
    cuando existan) necesita `alembic upgrade head` una vez antes de arrancar.
    Es un comando más en el README contra una clase entera de derivas
    silenciosas: vale la pena.
    """
    await browser_pool.start()
    yield
    await browser_pool.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# Límite de tasa. slowapi busca el limiter en `app.state`, y sin el handler
# registrado un límite excedido saldría como 500 en vez de 429 — y un 500 le
# pide a quien llama que reintente justo lo que acabamos de frenar.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: en desarrollo permite el frontend local; en producción, los orígenes de CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto, el navegador no deja leer Content-Disposition en cross-origin
    # (frontend en Vercel, backend en Railway) y el nombre del PDF se pierde.
    expose_headers=["Content-Disposition"],
)

# Rutas de la API
app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(organization.router)
app.include_router(reports.router)
app.include_router(facebook.router)
app.include_router(leads.router)


@app.get("/health", tags=["health"])
def health():
    """Comprobación rápida de que el servicio está vivo."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENVIRONMENT}


@app.get("/", tags=["health"])
def root():
    return {"message": f"{settings.APP_NAME} API — ver /docs"}