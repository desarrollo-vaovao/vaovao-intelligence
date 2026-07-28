"""
Módulo de Reportes — MOTOR ACTIVO.

Genera el reporte de campañas de Meta en PDF y lo devuelve para descargar.
Usa, en orden de preferencia:
  1. El Facebook conectado del usuario ("por usuario", recomendado)
  2. El token central de la organización (alternativa)

Endpoints:
- GET  /reports/status        → si hay conexión con Meta y si la generación está lista
- POST /reports/generate      → genera el PDF con datos reales y lo descarga
- POST /reports/check-access  → verifica en vivo si podemos leer una cuenta
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core import crypto
from app.models import User, Organization, Client, AdAccount, FacebookConnection
from app.schemas import (
    ReportStatus,
    ReportRequest,
    CheckAccessRequest,
    CheckAccessResult,
)
from app.services import meta_api, report_builder

router = APIRouter(prefix="/reports", tags=["reports"])

# El motor de generación (Meta + PDF) ya está conectado.
GENERATION_AVAILABLE = True


# ── Helpers ──────────────────────────────────────────────────
def _meta_connected(org: Organization) -> bool:
    """Hay token central de la organización guardado."""
    return bool(org and org.meta_token_encrypted)


def _resolve_token(current: User, db: Session) -> tuple[str | None, str | None]:
    """
    Elige qué token usar para hablar con Meta, en este orden:
      1) El Facebook conectado del usuario actual (por usuario, recomendado).
      2) El token central de la organización (alternativa).
    Devuelve (token, motivo_de_error). Si hay token, motivo es None.
    """
    fb_conn = db.scalar(
        select(FacebookConnection).where(FacebookConnection.user_id == current.id)
    )
    if fb_conn:
        token = crypto.decrypt(fb_conn.token_encrypted)
        if token:
            return token, None

    org = db.get(Organization, current.org_id)
    if org and org.meta_token_encrypted:
        token = crypto.decrypt(org.meta_token_encrypted)
        if token:
            return token, None

    return None, "No has conectado tu Facebook y no hay token central (Conexión Meta)."


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
    connected = _meta_connected(org) or has_fb

    return ReportStatus(
        meta_connected=connected,
        generation_available=connected and GENERATION_AVAILABLE,
    )


@router.post("/generate")
async def generate_report(
    data: ReportRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Genera el reporte en PDF con datos reales de Meta y lo devuelve para descargar.
    """
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

    token, error = _resolve_token(current, db)
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    if not GENERATION_AVAILABLE:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "El motor de generación aún no está activo.",
        )

    try:
        pdf_bytes, filename = await report_builder.build_pdf(
            client, token, data.date_from, data.date_to, data.budget, data.currency.value
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except meta_api.MetaApiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Meta: {e}")
    except Exception as e:
        # Falla del motor de PDF (p. ej. Playwright/Chromium no instalado)
        print(f"[reports] Error generando el PDF: {type(e).__name__}: {e}")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "No se pudo generar el PDF. Verifica que Playwright y Chromium estén "
            "instalados (pip install playwright && playwright install chromium).",
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    token, error = _resolve_token(current, db)
    if not token:
        return CheckAccessResult(ok=False, detail=error)

    ok, detail = await meta_api.check_account_access(token, account.meta_ad_account_id)
    return CheckAccessResult(ok=ok, detail=detail)