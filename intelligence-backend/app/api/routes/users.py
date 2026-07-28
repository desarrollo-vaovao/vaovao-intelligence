"""
Gestión de usuarios dentro de una organización.
Solo owner/admin pueden crear y administrar usuarios.
Todo está aislado por org_id: nadie toca usuarios de otra organización.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.security import hash_password
from app.models import User, UserRole
from app.schemas import UserCreate, UserUpdate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


def _primary_owner_id(org_id: int, db: Session) -> int | None:
    """
    El owner fundador de la organización: el más antiguo (menor id) con rol owner.
    Es el único que puede degradar o desactivar a otro owner — así ningún owner
    puede quitar a otro owner (ni a sí mismo lo puede quitar un tercero).
    """
    return db.scalar(
        select(User.id)
        .where(User.org_id == org_id, User.role == UserRole.owner)
        .order_by(User.id)
        .limit(1)
    )


@router.get("", response_model=list[UserOut])
def list_users(
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    users = db.scalars(
        select(User).where(User.org_id == current.org_id).order_by(User.full_name)
    ).all()
    return users


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    data: UserCreate,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    # email único a nivel global (es el login)
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un usuario con ese email")

    # solo un owner puede crear otro owner
    if data.role == UserRole.owner and current.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un owner puede crear otro owner")

    user = User(
        org_id=current.org_id,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdate,
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
):
    target = db.scalar(
        select(User).where(User.id == user_id, User.org_id == current.org_id)
    )
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    # Guardas de seguridad
    if target.id == current.id and data.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes desactivarte a ti mismo")

    if data.role == UserRole.owner and current.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un owner puede asignar el rol owner")

    # Degradar o desactivar a un owner: solo lo puede hacer el owner fundador
    if target.role == UserRole.owner and (data.role and data.role != UserRole.owner or data.is_active is False):
        if current.id != _primary_owner_id(current.org_id, db):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Solo el owner fundador de la organización puede modificar a otro owner",
            )

        # No dejar la organización sin ningún owner activo
        owners_activos = db.scalars(
            select(User).where(
                User.org_id == current.org_id,
                User.role == UserRole.owner,
                User.is_active == True,  # noqa: E712
            )
        ).all()
        if len(owners_activos) <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No puedes dejar la organización sin un owner activo",
            )

    if data.role is not None:
        target.role = data.role
    if data.is_active is not None:
        target.is_active = data.is_active

    db.commit()
    db.refresh(target)
    return target
