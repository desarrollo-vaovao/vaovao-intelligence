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
from app.schemas import ClientCreate, ClientUpdate, ClientOut, AdAccountCreate, AdAccountOut

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
    client = Client(org_id=current.org_id, name=data.name, type=data.type)
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
        client.name = data.name
    if data.type is not None:
        client.type = data.type
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


@router.post("/{client_id}/ad-accounts", response_model=AdAccountOut, status_code=201)
def add_ad_account(
    client_id: int,
    data: AdAccountCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = _get_owned_client(client_id, current, db)
    account = AdAccount(
        client_id=client.id,
        label=data.label,
        meta_ad_account_id=data.meta_ad_account_id,
        recipient_emails=[str(e) for e in data.recipient_emails],
    )
    db.add(account)
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
    client = _get_owned_client(client_id, current, db)
    account = next((a for a in client.ad_accounts if a.id == account_id), None)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    db.delete(account)
    db.commit()
