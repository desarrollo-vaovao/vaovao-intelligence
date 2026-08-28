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
from app.models import User, Organization, MetaCentralToken, UserRole
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
                readable=True,
            ))
        else:
            # No descifra (típicamente ENCRYPTION_KEY distinta a la que se usó
            # para guardarlo). Se devuelve igual, marcada como ilegible, para
            # que la UI la muestre y ofrezca borrarla: antes solo se contaba,
            # así que la fila quedaba invisible, inservible y sin forma de
            # quitarla desde la aplicación.
            undecryptable += 1
            tokens.append(MetaCentralTokenOut(
                id=row.id, label=row.label,
                token_masked="", created_at=row.created_at,
                readable=False,
            ))
    return MetaCredentialsStatus(
        # Un token ilegible no conecta con nada, así que no cuenta aquí.
        configured=any(t.readable for t in tokens),
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

    # NO se crea un Client automáticamente para este portafolio. Se probó
    # (un portafolio ~1:1 con un cliente) y generaba clientes fantasma sin
    # activos comerciales configurados, contaminando el selector de cliente
    # del sidebar con nombres de portafolios de Meta en vez de clientes
    # reales. Dar de alta un cliente sigue siendo manual, en Clientes.
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
    organización (las necesita para generar reportes en GTQ, y para saber
    con qué ventana de atribución está reportando todo el equipo)."""
    org = db.get(Organization, current.org_id)
    return OrganizationSettings(
        exchange_rate_usd_gtq=org.exchange_rate_usd_gtq,
        attribution_window=org.attribution_window,
    )


@router.patch("/settings", response_model=OrganizationSettings)
def update_settings(
    data: OrganizationSettingsUpdate,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """
    Solo owner/admin pueden CAMBIAR estos valores — afectan el gasto en GTQ
    y las conversiones que ve todo el equipo, no son una preferencia
    personal. Parcial: solo se tocan los campos que vienen en el body.
    """
    org = db.get(Organization, current.org_id)
    data_dict = data.model_dump(exclude_unset=True)
    if "exchange_rate_usd_gtq" in data_dict:
        org.exchange_rate_usd_gtq = data_dict["exchange_rate_usd_gtq"]
    if "attribution_window" in data_dict:
        org.attribution_window = data_dict["attribution_window"]
    db.commit()
    return OrganizationSettings(
        exchange_rate_usd_gtq=org.exchange_rate_usd_gtq,
        attribution_window=org.attribution_window,
    )
