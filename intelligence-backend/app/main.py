"""
VaoVao Intelligence — punto de entrada.
Plataforma multi-tenant en FastAPI. Módulos: auth, clientes, usuarios,
conexión con Meta (token central + OAuth por usuario) y reportes.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
from app.services import assets, browser_pool

# Importa todos los modelos de una vez. Ya no es para `create_all` (ver el
# lifespan), pero sigue haciendo falta: las `relationship()` se declaran con el
# nombre de la clase destino en un string, y SQLAlchemy sólo puede resolverlas
# cuando todas las clases mapeadas están importadas.
import app.models  # noqa: F401


async def _precargar(nombre: str, tarea) -> None:
    """
    Corre una precarga de arranque sin que pueda tumbar el servicio.

    POR QUÉ EXISTE
    Un fallo aquí no debe costar más que la optimización que traía. Antes
    estas dos precargas se esperaban (`await`) directamente en el lifespan,
    y eso las volvía requisitos para servir: si una fallaba, el lifespan
    reventaba y uvicorn nunca llegaba a escuchar. Fue exactamente lo que
    tumbó staging — `browser_pool.start()` no encontraba el binario de
    Chromium y se llevó por delante la API COMPLETA, login y /health
    incluidos, cuando lo único que debía degradarse era la generación de
    PDFs.

    Ninguna de las dos es un requisito real: `render_pdf` levanta el
    navegador solo si hace falta y `assets.font_css` cae a la fuente de
    respaldo. Así que se registran los fallos y se sigue.
    """
    try:
        await tarea
    except asyncio.CancelledError:
        # El server se está apagando; no es un fallo que reportar.
        raise
    except Exception as e:
        print(f"[startup] La precarga '{nombre}' falló ({type(e).__name__}: {e}); "
              "el servicio sigue arriba y se reintentará cuando se use.",
              flush=True)
    else:
        print(f"[startup] Precarga '{nombre}' lista.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Al arrancar: levanta el navegador compartido para generar PDFs
    (ver app/services/browser_pool.py — evita lanzar un Chromium nuevo por
    cada reporte) y precarga la tipografía del reporte (ver
    app/services/assets.py — así ni el primer reporte tras un despliegue
    espera a que baje Poppins).

    Las dos van en segundo plano, no esperadas
    -----------------------------------------
    Uvicorn no abre el puerto hasta que este lifespan devuelve el control.
    Cualquier cosa que se espere aquí retrasa —o impide— que /health
    empiece a responder, y el healthcheck del despliegue lee eso como que
    la aplicación no levantó. Como ninguna de las dos precargas hace falta
    para servir una petición (ver `_precargar`), se lanzan como tareas y el
    puerto se abre de inmediato. Lo peor que puede pasar es que el primer
    reporte pague la espera que la precarga iba a ahorrarle.

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

    A cambio, una base nueva (un desarrollador que empieza, o los tests)
    necesita `alembic upgrade head` una vez antes de arrancar. Es un comando
    más en el README contra una clase entera de derivas silenciosas.
    """
    precargas = [
        asyncio.create_task(_precargar("navegador para PDFs", browser_pool.start())),
        asyncio.create_task(_precargar("tipografía del reporte", assets.warm_font())),
    ]

    yield

    # Al apagar: cortar las precargas que sigan en vuelo antes de cerrar el
    # navegador, o `stop()` competiría con un `start()` a medio terminar.
    for tarea in precargas:
        tarea.cancel()
    await asyncio.gather(*precargas, return_exceptions=True)
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
app.include_router(leads.router)


@app.get("/health", tags=["health"])
def health():
    """Comprobación rápida de que el servicio está vivo. No expone detalles internos."""
    return {"status": "ok"}


@app.get("/", tags=["health"])
def root():
    return {"message": "VaoVao Intelligence API"}