"""
VaoVao Intelligence — punto de entrada.
Plataforma multi-tenant en FastAPI. Módulos: auth, clientes, usuarios,
conexión con Meta (token central + OAuth por usuario) y reportes.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.database import Base, engine
from app.core.ratelimit import limiter
from app.api.routes import (
    auth,
    clients,
    users,
    organization,
    reports,
    facebook,
)
from app.services import assets, browser_pool

# Importar los modelos antes de create_all para que se registren las tablas
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Al arrancar: crea las tablas que aún no existan, levanta el navegador
    compartido para generar PDFs (ver app/services/browser_pool.py — evita
    lanzar un Chromium nuevo por cada reporte) y precarga la tipografía del
    reporte (ver app/services/assets.py — así ni el primer reporte tras un
    despliegue espera a que baje Poppins).
    Cuando el esquema se estabilice y haya datos reales en producción,
    migrar a Alembic para manejar los cambios sin perder datos.
    """
    Base.metadata.create_all(bind=engine)
    await browser_pool.start()
    await assets.warm_font()
    yield
    await browser_pool.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: en desarrollo permite el frontend local; en producción, los orígenes de CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
    # Sin esto, el navegador no deja leer Content-Disposition en cross-origin
    # (frontend en Vercel, backend en Railway) y el nombre del PDF se pierde.
    expose_headers=["Content-Disposition"],
)

# Security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Rutas de la API
app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(organization.router)
app.include_router(reports.router)
app.include_router(facebook.router)


@app.get("/health", tags=["health"])
def health():
    """Comprobación rápida de que el servicio está vivo. No expone detalles internos."""
    return {"status": "ok"}


@app.get("/", tags=["health"])
def root():
    return {"message": "VaoVao Intelligence API"}