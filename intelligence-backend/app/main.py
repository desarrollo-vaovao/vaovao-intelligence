"""
VaoVao Intelligence — punto de entrada.
Plataforma multi-tenant en FastAPI. Módulos: auth, clientes, usuarios,
conexión con Meta (token central + OAuth por usuario) y reportes.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.api.routes import (
    auth,
    clients,
    users,
    organization,
    reports,
    facebook,
)
from app.services import browser_pool

# Importar los modelos antes de create_all para que se registren las tablas
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Al arrancar: crea las tablas que aún no existan y levanta el navegador
    compartido para generar PDFs (ver app/services/browser_pool.py — evita
    lanzar un Chromium nuevo por cada reporte).
    Cuando el esquema se estabilice y haya datos reales en producción,
    migrar a Alembic para manejar los cambios sin perder datos.
    """
    Base.metadata.create_all(bind=engine)
    await browser_pool.start()
    yield
    await browser_pool.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

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


@app.get("/health", tags=["health"])
def health():
    """Comprobación rápida de que el servicio está vivo."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENVIRONMENT}


@app.get("/", tags=["health"])
def root():
    return {"message": f"{settings.APP_NAME} API — ver /docs"}