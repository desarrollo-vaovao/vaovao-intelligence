"""
Dependencias compartidas del API.
get_current_user() es la pieza clave del aislamiento multi-tenant:
todas las rutas protegidas la usan, y de ahí sale el org_id para filtrar.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    cred_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas o token expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise cred_error

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise cred_error

    return user


def require_roles(*allowed: UserRole):
    """
    Fábrica de dependencias para proteger rutas por rol.
    Uso:  current: User = Depends(require_roles(UserRole.owner, UserRole.admin))
    """
    def checker(current: User = Depends(get_current_user)) -> User:
        if current.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para esta acción",
            )
        return current

    return checker
