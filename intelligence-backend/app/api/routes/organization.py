"""
Configuración de la organización — por ahora, las credenciales de Meta.
Este es el "espacio" preparado para conectar Meta cuando tengas el System User token.

Reglas de seguridad:
- El token se guarda CIFRADO (core/crypto.py).
- El token completo NUNCA se devuelve por el API: solo un estado enmascarado.
- Solo owner/admin pueden configurarlo.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core import crypto
from app.models import User, Organization, UserRole
from app.schemas import MetaCredentialsIn, MetaCredentialsStatus

router = APIRouter(prefix="/organization", tags=["organization"])


def _status(org: Organization) -> MetaCredentialsStatus:
    if not org.meta_token_encrypted:
        return MetaCredentialsStatus(configured=False)
    token = crypto.decrypt(org.meta_token_encrypted)
    return MetaCredentialsStatus(
        configured=token is not None,
        meta_app_id=org.meta_app_id,
        token_masked=crypto.mask(token) if token else None,
    )


@router.get("/meta-credentials", response_model=MetaCredentialsStatus)
def get_meta_credentials(
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    return _status(org)


@router.put("/meta-credentials", response_model=MetaCredentialsStatus)
def set_meta_credentials(
    data: MetaCredentialsIn,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    try:
        org.meta_token_encrypted = crypto.encrypt(data.system_user_token)
    except RuntimeError as e:
        # ENCRYPTION_KEY no configurada → fallar claro, no guardar inseguro
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    org.meta_app_id = data.meta_app_id
    db.commit()
    db.refresh(org)
    return _status(org)


@router.delete("/meta-credentials", response_model=MetaCredentialsStatus)
def clear_meta_credentials(
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
    org.meta_app_id = None
    org.meta_token_encrypted = None
    db.commit()
    db.refresh(org)
    return _status(org)
