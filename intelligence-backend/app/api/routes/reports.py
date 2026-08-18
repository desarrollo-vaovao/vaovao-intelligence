"""
Módulo de Reportes — MOTOR ACTIVO.

Genera el reporte de campañas de Meta en PDF. La generación corre en
segundo plano (puede tardar bastante con muchas campañas/anuncios): el
endpoint de "generate" solo valida y arranca el trabajo, el frontend
consulta el estado por job_id y descarga el PDF cuando está listo.
Usa, en orden de preferencia:
  1. El Facebook conectado del usuario ("por usuario", recomendado)
  2. Los tokens centrales de la organización (uno por portafolio comercial)

Endpoints:
- GET  /reports/status              → si hay conexión con Meta y si la generación está lista
- POST /reports/generate            → valida y arranca la generación, devuelve job_id
- GET  /reports/jobs/{job_id}       → estado del job (processing/done/error)
- GET  /reports/jobs/{job_id}/pdf   → descarga el PDF una vez que el job está "done"
- POST /reports/check-access        → verifica en vivo si podemos leer una cuenta
"""
import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core import crypto
from app.models import User, Organization, Client, AdAccount, FacebookConnection, MetaCentralToken
from app.schemas import (
    ReportStatus,
    ReportRequest,
    CheckAccessRequest,
    CheckAccessResult,
    ReportJobCreated,
    ReportJobStatus,
)
from app.services import meta_api, report_builder

router = APIRouter(prefix="/reports", tags=["reports"])

# El motor de generación (Meta + PDF) ya está conectado.
GENERATION_AVAILABLE = True

# ── Jobs de generación en segundo plano ─────────────────────────
# En memoria del proceso: alcanza para el tamaño de este equipo (un solo
# servicio de Railway, sin múltiples workers). Si el proceso se reinicia
# a mitad de un job, ese reporte se pierde y hay que regenerarlo — es un
# costo aceptable frente a montar una cola real (Redis/Celery) para esto.
_JOBS: dict[str, dict] = {}
_JOB_TTL_SECONDS = 30 * 60


def _cleanup_jobs() -> None:
    cutoff = time.monotonic() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _JOBS.items() if j["created_at"] < cutoff]
    for jid in stale:
        _JOBS.pop(jid, None)


async def _run_report_job(
    job_id: str, client: Client, tokens: list[str],
    date_from, date_to, budget, currency: str,
) -> None:
    try:
        pdf_bytes, filename = await report_builder.build_pdf(
            client, tokens, date_from, date_to, budget, currency
        )
        _JOBS[job_id].update(status="done", pdf=pdf_bytes, filename=filename)
    except ValueError as e:
        _JOBS[job_id].update(status="error", error=str(e))
    except meta_api.MetaApiError as e:
        _JOBS[job_id].update(status="error", error=f"Meta: {e}")
    except Exception as e:
        print(f"[reports] Error generando el PDF (job {job_id}): {type(e).__name__}: {e}")
        _JOBS[job_id].update(status="error", error=(
            "No se pudo generar el PDF. Verifica que Playwright y Chromium estén "
            "instalados (pip install playwright && playwright install chromium)."
        ))


# ── Helpers ──────────────────────────────────────────────────
def _meta_connected(org: Organization, db: Session) -> bool:
    """Hay al menos un token central de la organización guardado."""
    if not org:
        return False
    return db.scalar(
        select(MetaCentralToken.id).where(MetaCentralToken.org_id == org.id)
    ) is not None


def _resolve_tokens(current: User, db: Session) -> tuple[list[str], str | None]:
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


# ── Endpoints ────────────────────────────────────────────────
@router.get("/status", response_model=ReportStatus)
def report_status(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estado del módulo: si hay conexión con Meta y si la generación está disponible."""
    org = db.get(Organization, current.org_id)

    has_fb = db.scalar(
        select(FacebookConnection.id).where(FacebookConnection.user_id == current.id)
    ) is not None
    connected = _meta_connected(org, db) or has_fb

    return ReportStatus(
        meta_connected=connected,
        generation_available=connected and GENERATION_AVAILABLE,
    )


@router.post("/generate", response_model=ReportJobCreated, status_code=202)
async def generate_report(
    data: ReportRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Valida todo lo que se puede validar rápido (cliente, fechas, tokens) y
    arranca la generación del PDF en segundo plano. Devuelve un job_id para
    consultar el progreso en GET /reports/jobs/{job_id}.
    """
    _cleanup_jobs()

    # El cliente debe ser de la organización del usuario
    client = db.scalar(
        select(Client)
        .where(Client.id == data.client_id, Client.org_id == current.org_id)
        .options(selectinload(Client.ad_accounts))
    )
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no encontrado")

    if data.date_from > data.date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de inicio no puede ser posterior a la de fin.",
        )

    tokens, error = _resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    if not GENERATION_AVAILABLE:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "El motor de generación aún no está activo.",
        )

    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "org_id": current.org_id,
        "status": "processing",
        "pdf": None,
        "filename": None,
        "error": None,
        "created_at": time.monotonic(),
    }
    asyncio.create_task(_run_report_job(
        job_id, client, tokens, data.date_from, data.date_to, data.budget, data.currency.value
    ))
    return ReportJobCreated(job_id=job_id)


def _get_owned_job(job_id: str, current: User) -> dict:
    job = _JOBS.get(job_id)
    if not job or job["org_id"] != current.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job no encontrado")
    return job


@router.get("/jobs/{job_id}", response_model=ReportJobStatus)
def get_report_job(job_id: str, current: User = Depends(get_current_user)):
    job = _get_owned_job(job_id, current)
    return ReportJobStatus(
        job_id=job_id, status=job["status"], error=job["error"], filename=job["filename"],
    )


@router.get("/jobs/{job_id}/pdf")
def download_report_job(job_id: str, current: User = Depends(get_current_user)):
    job = _get_owned_job(job_id, current)
    if job["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "El reporte todavía no está listo.")
    return Response(
        content=job["pdf"],
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{job["filename"]}"'},
    )


@router.post("/check-access", response_model=CheckAccessResult)
async def check_access(
    data: CheckAccessRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifica en vivo si podemos leer una cuenta publicitaria específica.
    Usa el Facebook del usuario si está conectado; si no, el token central.
    """
    account = db.scalar(
        select(AdAccount)
        .join(Client, AdAccount.client_id == Client.id)
        .where(AdAccount.id == data.account_id, Client.org_id == current.org_id)
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    tokens, error = _resolve_tokens(current, db)
    if not tokens:
        return CheckAccessResult(ok=False, detail=error)

    ok, detail = await meta_api.check_account_access_with_fallback(tokens, account.meta_ad_account_id)
    return CheckAccessResult(ok=ok, detail=detail)