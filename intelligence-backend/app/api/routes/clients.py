"""
Rutas de clientes y sus cuentas publicitarias.
Esto es lo que reemplaza el clients.js hardcodeado de la reportería:
ahora los clientes viven en la base, por organización, y se gestionan por API.

OJO — el aislamiento multi-tenant está en CADA query:
siempre se filtra por current.org_id. Un usuario jamás toca datos de otra organización.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models import User, Client, AdAccount, Lead, UserRole
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

    client = Client(org_id=current.org_id, name=name, type=data.type)
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
    """Borra un cliente, salvo que todavía tenga leads.

    Qué se lleva por delante el borrado
    -----------------------------------
    Todo lo que cuelga de `clients.id` con `ondelete="CASCADE"`: sus
    `ad_accounts`, sus `client_pages` (el enrutamiento de páginas de Facebook)
    y —esto es lo grave— sus `leads`, y con cada lead su `lead_audits`.

    Por eso se rechaza si hay leads: el historial comercial de un cliente no
    se puede reponer, y perderlo por un DELETE mal apuntado no es aceptable.
    Quien de verdad quiera borrarlo tiene que exportar antes.

    Qué NO bloquea, y por qué:
    - `client_pages`: es configuración de enrutamiento. Si se pierde, se
      recupera volviendo a dar de alta la página con el mismo `page_id`.
    - `orphan_leads`: no cuelgan de `clients` —no tienen `client_id` ni
      `org_id`, que es justo el dato que les falta—, así que este borrado ni
      los toca. Siguen pendientes y se reconcilian cuando su página se
      registre de nuevo.
    """
    client = _get_owned_client(client_id, current, db)

    # El filtro por org_id es redundante (el cliente ya se validó como propio)
    # pero se deja explícito: en este archivo TODA query lleva su tenant.
    leads_count = db.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.client_id == client.id, Lead.org_id == current.org_id)
    ) or 0
    if leads_count:
        plural = "lead" if leads_count == 1 else "leads"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No puedes borrar este cliente: tiene {leads_count} {plural} "
            "y borrarlo eliminaría todo su historial, incluida la bitácora. "
            "Exporta los leads a CSV antes de borrar el cliente.",
        )

    # cascade elimina también sus ad_accounts y sus client_pages
    db.delete(client)
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


@router.patch("/{client_id}/ad-accounts/{account_id}", response_model=AdAccountOut)
def update_ad_account(
    client_id: int,
    account_id: int,
    data: AdAccountUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = _get_owned_client(client_id, current, db)
    account = next((a for a in client.ad_accounts if a.id == account_id), None)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    if data.label is not None:
        account.label = data.label
    if data.meta_ad_account_id is not None:
        account.meta_ad_account_id = data.meta_ad_account_id
    if data.recipient_emails is not None:
        account.recipient_emails = [str(e) for e in data.recipient_emails]

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
