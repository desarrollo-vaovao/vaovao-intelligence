"""
Módulo de Reportes — MOTOR ACTIVO.

Genera el reporte de campañas de Meta en PDF y lo devuelve para descargar.
Usa, en orden de preferencia:
  1. El Facebook conectado del usuario ("por usuario", recomendado)
  2. Los tokens centrales de la organización (uno por portafolio comercial)

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
from app.models import User, Organization, Client, AdAccount, FacebookConnection, MetaCentralToken
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

    fb_conn = db.scalar(
        select(FacebookConnection).where(FacebookConnection.user_id == current.id)
    )
    if fb_conn:
        token = crypto.decrypt(fb_conn.token_encrypted)
        if token:
            tokens.append(token)

    central_rows = db.scalars(
        select(MetaCentralToken).where(MetaCentralToken.org_id == current.org_id)
    ).all()
    for row in central_rows:
        token = crypto.decrypt(row.token_encrypted)
        if token:
            tokens.append(token)

    if not tokens:
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

    tokens, error = _resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    if not GENERATION_AVAILABLE:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "El motor de generación aún no está activo.",
        )

    try:
        pdf_bytes, filename = await report_builder.build_pdf(
            client, tokens, data.date_from, data.date_to, data.budget, data.currency.value
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

    tokens, error = _resolve_tokens(current, db)
    if not tokens:
        return CheckAccessResult(ok=False, detail=error)

    ok, detail = await meta_api.check_account_access_with_fallback(tokens, account.meta_ad_account_id)
    return CheckAccessResult(ok=ok, detail=detail)