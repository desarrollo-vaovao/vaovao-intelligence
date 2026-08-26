"""
"Conectar con Facebook" — flujo OAuth (Facebook Login for Business).

Diseño POR USUARIO: cada persona conecta su propia cuenta de Facebook y sus
reportes usan SU acceso. Así VaoVao no depende de una sola cuenta central.

Flujo:
  1. GET  /auth/facebook/login     → devuelve la URL de login de Meta (con 'state' firmado)
  2. GET  /auth/facebook/callback  → Meta regresa aquí con un 'code'; lo cambiamos por
                                     un token de larga duración, lo guardamos cifrado,
                                     y devolvemos al usuario al frontend.
  3. GET  /auth/facebook/status    → si el usuario ya conectó, con qué nombre y hasta cuándo
  4. GET  /auth/facebook/adaccounts→ las cuentas que su token puede ver
  5. DELETE /auth/facebook         → desconectar
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import logging

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core import crypto
from app.core.ratelimit import limiter, LIMITS
from app.models import User, FacebookConnection
from app.services import meta_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/facebook", tags=["facebook"])

FB = f"https://graph.facebook.com/{settings.FB_API_VERSION}"
FB_DIALOG = f"https://www.facebook.com/{settings.FB_API_VERSION}/dialog/oauth"
SCOPES = "ads_read,business_management,public_profile"


def _sign_state(user_id: int) -> str:
    """Firma un 'state' de corta duración para correlacionar el callback con el usuario."""
    payload = {
        "uid": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "kind": "fb_oauth_state",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _read_state(state: str) -> int | None:
    try:
        data = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if data.get("kind") != "fb_oauth_state":
            return None
        return int(data["uid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def _require_config():
    if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Falta configurar FB_APP_ID / FB_APP_SECRET en el servidor.",
        )


@router.get("/login")
def facebook_login(current: User = Depends(get_current_user)):
    """Devuelve la URL a la que el frontend debe redirigir para iniciar el login."""
    _require_config()
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": settings.FB_REDIRECT_URI,
        "state": _sign_state(current.id),
        "scope": SCOPES,
        "response_type": "code",
    }
    return {"auth_url": f"{FB_DIALOG}?{urlencode(params)}"}


@router.get("/callback")
@limiter.limit(LIMITS["facebook_callback"])
def facebook_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    """Meta regresa aquí tras el login. No lleva JWT: la identidad va en 'state'."""
    front = settings.FRONTEND_URL.rstrip("/") + "/conexion"

    if error:
        logger.warning(f"FB callback error from Meta: {error}", extra={"error_description": error_description})
        return RedirectResponse(f"{front}?fb=error")
    if not code or not state:
        logger.warning(f"FB callback missing parameters", extra={"code": bool(code), "state": bool(state)})
        return RedirectResponse(f"{front}?fb=error")

    user_id = _read_state(state)
    if not user_id:
        logger.warning("FB callback state invalid or expired (JWT verification failed)")
        return RedirectResponse(f"{front}?fb=error")
    user = db.get(User, user_id)
    if not user:
        logger.warning(f"FB callback user not found", extra={"user_id": user_id})
        return RedirectResponse(f"{front}?fb=error")

    if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
        logger.error("FB callback missing configuration: FB_APP_ID or FB_APP_SECRET")
        return RedirectResponse(f"{front}?fb=error")

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            # 1) code → token de corta duración
            r = client.get(f"{FB}/oauth/access_token", params={
                "client_id": settings.FB_APP_ID,
                "client_secret": settings.FB_APP_SECRET,
                "redirect_uri": settings.FB_REDIRECT_URI,
                "code": code,
            })
            short = r.json()
            if r.status_code != 200 or "access_token" not in short:
                logger.warning(f"FB callback: Meta rejected code", extra={"status": r.status_code})
                return RedirectResponse(f"{front}?fb=error")

            # 2) corto → token de larga duración (~60 días)
            r2 = client.get(f"{FB}/oauth/access_token", params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.FB_APP_ID,
                "client_secret": settings.FB_APP_SECRET,
                "fb_exchange_token": short["access_token"],
            })
            long = r2.json()
            token = long.get("access_token", short["access_token"])
            expires_in = long.get("expires_in")

            # 3) datos del usuario de Facebook (para mostrar)
            me = client.get(f"{FB}/me", params={"fields": "id,name", "access_token": token}).json()
            if "error" in me:
                logger.warning("FB callback: /me endpoint returned error", extra={"user_id": user.id})
                return RedirectResponse(f"{front}?fb=error")
    except httpx.HTTPError as e:
        logger.warning(f"FB callback: network error calling Meta API", extra={"error": str(e), "user_id": user.id})
        return RedirectResponse(f"{front}?fb=error")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if expires_in else None
    )

    conn = db.scalar(select(FacebookConnection).where(FacebookConnection.user_id == user.id))
    if not conn:
        conn = FacebookConnection(user_id=user.id)
        db.add(conn)
    conn.fb_user_id = me.get("id", "")
    conn.fb_name = me.get("name", "Facebook")
    conn.token_encrypted = crypto.encrypt(token)
    conn.expires_at = expires_at
    db.commit()

    logger.info(f"FB callback: user connected", extra={"user_id": user.id, "fb_name": conn.fb_name})
    return RedirectResponse(f"{front}?fb=ok")

@router.get("/status")
def facebook_status(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(FacebookConnection).where(FacebookConnection.user_id == current.id))
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "fb_name": conn.fb_name,
        "expires_at": conn.expires_at.isoformat() if conn.expires_at else None,
    }


@router.get("/adaccounts")
async def facebook_adaccounts(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lista las cuentas publicitarias que la sesión de Facebook del usuario puede ver."""
    conn = db.scalar(select(FacebookConnection).where(FacebookConnection.user_id == current.id))
    if not conn:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No has conectado tu Facebook.")
    token = crypto.decrypt(conn.token_encrypted)
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El token guardado no se pudo leer; reconecta.")
    try:
        return await meta_api.list_ad_accounts(token)
    except meta_api.MetaApiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.delete("/")
def facebook_disconnect(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(FacebookConnection).where(FacebookConnection.user_id == current.id))
    if conn:
        db.delete(conn)
        db.commit()
    return {"connected": False}
