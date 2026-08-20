"""
Rutas de clientes y sus cuentas publicitarias.
Esto es lo que reemplaza el clients.js hardcodeado de la reportería:
ahora los clientes viven en la base, por organización, y se gestionan por API.

OJO — el aislamiento multi-tenant está en CADA query:
siempre se filtra por current.org_id. Un usuario jamás toca datos de otra organización.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models import User, Client, AdAccount, UserRole
from app.services import meta_api
from app.services.meta_tokens import resolve_tokens
from app.schemas import (
    ClientCreate,
    ClientUpdate,
    ClientOut,
    AdAccountCreate,
    AdAccountUpdate,
    AdAccountOut,
)

router = APIRouter(prefix="/clients", tags=["clients"])


def _get_owned_client(client_id: int, current: User, db: Session) -> Client:
    """Trae un cliente SOLO si pertenece a la organización del usuario."""
    client = db.scalar(
        select(Client)
        .where(Client.id == client_id, Client.org_id == current.org_id)
        .options(selectinload(Client.ad_accounts))
    )
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no encontrado")
    return client


@router.get("", response_model=list[ClientOut])
def list_clients(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    clients = db.scalars(
        select(Client)
        .where(Client.org_id == current.org_id)
        .options(selectinload(Client.ad_accounts))
        .order_by(Client.name)
    ).all()
    return clients


@router.post("", response_model=ClientOut, status_code=201)
def create_client(
    data: ClientCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = data.name.strip()
    existing = db.scalars(
        select(Client).where(Client.org_id == current.org_id)
    ).all()
    if any(c.name.strip().lower() == name.lower() for c in existing):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un cliente con ese nombre")

    client = Client(org_id=current.org_id, name=name)
    db.add(client)
    db.commit()
    db.refresh(client)
    # cargar relación para la respuesta
    db.refresh(client, attribute_names=["ad_accounts"])
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(
    client_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_client(client_id, current, db)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int,
    data: ClientUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = _get_owned_client(client_id, current, db)
    if data.name is not None:
        name = data.name.strip()
        others = db.scalars(
            select(Client).where(Client.org_id == current.org_id, Client.id != client.id)
        ).all()
        if any(c.name.strip().lower() == name.lower() for c in others):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un cliente con ese nombre")
        client.name = name
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(
    client_id: int,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    client = _get_owned_client(client_id, current, db)
    db.delete(client)  # cascade elimina también sus ad_accounts
    db.commit()


async def _meta_account_name(meta_ad_account_id: str, current: User, db: Session) -> str:
    """
    Nombre real de la cuenta en Meta. Es la única fuente del label de un activo
    comercial: si Meta no lo puede dar (ID mal escrito, o ningún token con
    acceso), no se registra ni se modifica nada.
    """
    tokens, error = resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    ok, detail = await meta_api.check_account_access_with_fallback(tokens, meta_ad_account_id)
    if not ok:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No se pudo leer la cuenta en Meta: {detail}",
        )
    return detail


@router.post("/{client_id}/ad-accounts", response_model=AdAccountOut, status_code=201)
async def add_ad_account(
    client_id: int,
    data: AdAccountCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Registra un activo comercial. El nombre no se pide: se hereda de Meta, y
    con eso el registro lleva la verificación de acceso incorporada.
    """
    client = _get_owned_client(client_id, current, db)
    label = await _meta_account_name(data.meta_ad_account_id, current, db)

    account = AdAccount(
        client_id=client.id,
        label=label,
        meta_ad_account_id=data.meta_ad_account_id,
        recipient_emails=[str(e) for e in data.recipient_emails],
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _get_owned_account(client_id: int, account_id: int, current: User, db: Session) -> AdAccount:
    client = _get_owned_client(client_id, current, db)
    account = next((a for a in client.ad_accounts if a.id == account_id), None)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo comercial no encontrado")
    return account


@router.patch("/{client_id}/ad-accounts/{account_id}", response_model=AdAccountOut)
async def update_ad_account(
    client_id: int,
    account_id: int,
    data: AdAccountUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(client_id, account_id, current, db)

    # Cambiar el ID cambia de qué cuenta se trata, así que el nombre se
    # vuelve a heredar (y si Meta no responde, el cambio no pasa).
    if data.meta_ad_account_id is not None:
        account.label = await _meta_account_name(data.meta_ad_account_id, current, db)
        account.meta_ad_account_id = data.meta_ad_account_id
    if data.recipient_emails is not None:
        account.recipient_emails = [str(e) for e in data.recipient_emails]

    db.commit()
    db.refresh(account)
    return account


@router.post("/{client_id}/ad-accounts/{account_id}/refresh-name", response_model=AdAccountOut)
async def refresh_ad_account_name(
    client_id: int,
    account_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Vuelve a traer el nombre desde Meta, para cuando renombran la cuenta allá."""
    account = _get_owned_account(client_id, account_id, current, db)
    account.label = await _meta_account_name(account.meta_ad_account_id, current, db)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{client_id}/ad-accounts/{account_id}", status_code=204)
def delete_ad_account(
    client_id: int,
    account_id: int,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(client_id, account_id, current, db)
    db.delete(account)
    db.commit()
