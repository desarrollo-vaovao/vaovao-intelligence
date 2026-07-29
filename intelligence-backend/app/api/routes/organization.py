"""
Configuración de la organización — credenciales de Meta.

Puede haber VARIOS tokens centrales (System User), uno por cada portafolio
comercial independiente de Meta (ej. "Vao Vao", "Menos Pausa", "Cementerios").
Un solo System User no puede ver activos de un portafolio que no es el suyo,
así que cada portafolio necesita su propio token — se usan como respaldo
cuando el Facebook personal de un usuario no tiene acceso a una cuenta puntual
(ver reports.py _resolve_tokens).

Reglas de seguridad:
- Los tokens se guardan CIFRADOS (core/crypto.py).
- Nunca se devuelven completos por el API: solo un estado enmascarado.
- Solo owner/admin pueden configurarlos.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core import crypto
from app.models import User, Organization, MetaCentralToken, UserRole
from app.schemas import (
    MetaAppIdIn,
    MetaCentralTokenIn,
    MetaCentralTokenOut,
    MetaCredentialsStatus,
)

router = APIRouter(prefix="/organization", tags=["organization"])


def _status(org: Organization, db: Session) -> MetaCredentialsStatus:
    rows = db.scalars(
        select(MetaCentralToken)
        .where(MetaCentralToken.org_id == org.id)
        .order_by(MetaCentralToken.label)
    ).all()
    tokens = []
    for row in rows:
        token = crypto.decrypt(row.token_encrypted)
        if token:  # si no descifra (p. ej. cambió ENCRYPTION_KEY), no lo listamos
            tokens.append(MetaCentralTokenOut(
                id=row.id, label=row.label,
                token_masked=crypto.mask(token), created_at=row.created_at,
            ))
    return MetaCredentialsStatus(
        configured=len(tokens) > 0,
        meta_app_id=org.meta_app_id,
        tokens=tokens,
    )


@router.get("/meta-credentials", response_model=MetaCredentialsStatus)
def get_meta_credentials(
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    return _status(org, db)


@router.put("/meta-app-id", response_model=MetaCredentialsStatus)
def set_meta_app_id(
    data: MetaAppIdIn,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    org.meta_app_id = data.meta_app_id
    db.commit()
    db.refresh(org)
    return _status(org, db)


@router.post("/meta-credentials", response_model=MetaCredentialsStatus, status_code=201)
def add_meta_central_token(
    data: MetaCentralTokenIn,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    try:
        encrypted = crypto.encrypt(data.system_user_token)
    except RuntimeError as e:
        # ENCRYPTION_KEY no configurada → fallar claro, no guardar inseguro
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    token_row = MetaCentralToken(org_id=org.id, label=data.label, token_encrypted=encrypted)
    db.add(token_row)
    db.commit()
    return _status(org, db)


@router.delete("/meta-credentials/{token_id}", response_model=MetaCredentialsStatus)
def delete_meta_central_token(
    token_id: int,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    token_row = db.scalar(
        select(MetaCentralToken).where(
            MetaCentralToken.id == token_id, MetaCentralToken.org_id == org.id
        )
    )
    if not token_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token no encontrado")
    db.delete(token_row)
    db.commit()
    return _status(org, db)
