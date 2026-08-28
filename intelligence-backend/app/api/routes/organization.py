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

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core import crypto
from app.models import User, Organization, MetaCentralToken, Client, UserRole
from app.schemas import (
    MetaCentralTokenIn,
    MetaCentralTokenOut,
    MetaCredentialsStatus,
    OrganizationSettings,
    OrganizationSettingsUpdate,
)
from app.services import meta_api

router = APIRouter(prefix="/organization", tags=["organization"])


def _status(org: Organization, db: Session) -> MetaCredentialsStatus:
    rows = db.scalars(
        select(MetaCentralToken)
        .where(MetaCentralToken.org_id == org.id)
        .order_by(MetaCentralToken.label)
    ).all()
    tokens = []
    undecryptable = 0
    for row in rows:
        token = crypto.decrypt(row.token_encrypted)
        if token:
            tokens.append(MetaCentralTokenOut(
                id=row.id, label=row.label,
                token_masked=crypto.mask(token), created_at=row.created_at,
            ))
        else:
            # No descifra (típicamente ENCRYPTION_KEY distinta a la que se usó
            # para guardarlo) — se cuenta aparte para no ocultar que el dato
            # sigue ahí, solo que la llave no coincide.
            undecryptable += 1
    return MetaCredentialsStatus(
        configured=len(tokens) > 0,
        tokens=tokens,
        undecryptable_count=undecryptable,
    )


@router.get("/meta-credentials", response_model=MetaCredentialsStatus)
def get_meta_credentials(
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, current.org_id)
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

    # El portafolio suele ser 1:1 con un cliente (ver conversación del setup) —
    # si no existe ya un cliente con ese nombre, lo creamos para no tener que
    # darlo de alta a mano en dos lugares distintos.
    # Comparación en Python (no SQL) para no depender de TRIM de la base:
    # copiar/pegar nombres desde otros lados a veces mete tabs/espacios que
    # TRIM de SQL no siempre limpia (ya nos pasó con un ID de cuenta).
    label = data.label.strip()
    existing_clients = db.scalars(select(Client).where(Client.org_id == org.id)).all()
    if not any(c.name.strip().lower() == label.lower() for c in existing_clients):
        db.add(Client(org_id=org.id, name=label))

    db.commit()
    return _status(org, db)


@router.get("/meta-credentials/{token_id}/adaccounts")
async def get_meta_central_token_adaccounts(
    token_id: int,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Cuentas publicitarias visibles para el System User de este portafolio."""
    org = db.get(Organization, current.org_id)
    token_row = db.scalar(
        select(MetaCentralToken).where(
            MetaCentralToken.id == token_id, MetaCentralToken.org_id == org.id
        )
    )
    if not token_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token no encontrado")
    token = crypto.decrypt(token_row.token_encrypted)
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El token guardado no se pudo leer")
    try:
        return await meta_api.list_ad_accounts(token)
    except meta_api.MetaApiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


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


@router.get("/settings", response_model=OrganizationSettings)
def get_settings(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cualquier usuario autenticado puede LEER las preferencias de su
    organización (las necesita para generar reportes en GTQ)."""
    org = db.get(Organization, current.org_id)
    return OrganizationSettings(exchange_rate_usd_gtq=org.exchange_rate_usd_gtq)


@router.patch("/settings", response_model=OrganizationSettings)
def update_settings(
    data: OrganizationSettingsUpdate,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Solo owner/admin pueden CAMBIAR el tipo de cambio — afecta el gasto
    en GTQ que ve todo el equipo, no es una preferencia personal."""
    org = db.get(Organization, current.org_id)
    org.exchange_rate_usd_gtq = data.exchange_rate_usd_gtq
    db.commit()
    return OrganizationSettings(exchange_rate_usd_gtq=org.exchange_rate_usd_gtq)
