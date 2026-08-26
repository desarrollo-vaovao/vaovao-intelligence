"""
Rutas de autenticación: registro inicial y login.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.ratelimit import limiter, LIMITS
from app.models import Organization, User, UserRole
from app.schemas import RegisterRequest, Token, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit(LIMITS["auth_register"])
def register(request: Request, data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Bootstrap de una organización: crea la org y su primer usuario (dueño).
    Pensado para arrancar VaoVao. En producto multi-agencia, este es el alta de cada agencia.
    """
    existing = db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un usuario con ese email")

    # slug único para la organización
    base_slug = _slugify(data.organization_name)
    slug, i = base_slug, 1
    while db.scalar(select(Organization).where(Organization.slug == slug)):
        i += 1
        slug = f"{base_slug}-{i}"

    org = Organization(name=data.organization_name, slug=slug)
    db.add(org)
    db.flush()  # para tener org.id

    user = User(
        org_id=org.id,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.owner,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit(LIMITS["auth_login"])
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Login estándar OAuth2: 'username' es el email, 'password' la contraseña.
    Devuelve un JWT para usar como 'Authorization: Bearer <token>'.
    """
    user = db.scalar(select(User).where(User.email == form.username))
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuario desactivado")

    token = create_access_token(subject=user.id, extra={"org_id": user.org_id})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)):
    """Devuelve el usuario autenticado (verifica que el token funciona)."""
    return current
