"""
Schemas Pydantic — validan lo que entra y definen lo que sale por el API.
Separados de los modelos ORM a propósito (nunca exponemos hashed_password, etc.).
"""
import enum
from datetime import datetime, date

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models import UserRole, ClientType


# ── Auth ──────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    """Bootstrap: crea una organización y su usuario dueño."""
    organization_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── User ──────────────────────────────────────────────────────
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool


class UserCreate(BaseModel):
    """Alta de un usuario dentro de la organización (la hace un owner/admin)."""
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.member


class UserUpdate(BaseModel):
    """Actualización parcial: activar/desactivar o cambiar rol."""
    is_active: bool | None = None
    role: UserRole | None = None


# ── Credenciales de Meta ──────────────────────────────────────
class MetaCredentialsIn(BaseModel):
    meta_app_id: str = Field(min_length=3, max_length=40)
    system_user_token: str = Field(min_length=10)


class MetaCredentialsStatus(BaseModel):
    """Estado de la conexión con Meta — NUNCA expone el token completo."""
    configured: bool
    meta_app_id: str | None = None
    token_masked: str | None = None


# ── Reportes (módulo preparado, se activa al conectar Meta) ────
class ReportType(str, enum.Enum):
    quincenal = "quincenal"
    mensual = "mensual"
    personalizado = "personalizado"


class ReportStatus(BaseModel):
    meta_connected: bool
    generation_available: bool


class ReportRequest(BaseModel):
    client_id: int
    report_type: ReportType = ReportType.quincenal
    date_from: date
    date_to: date
    budget: float | None = None


class CheckAccessRequest(BaseModel):
    account_id: int  # id de la cuenta publicitaria en nuestra base


class CheckAccessResult(BaseModel):
    ok: bool
    detail: str  # nombre de la cuenta si ok; motivo si no


# ── Ad Account ────────────────────────────────────────────────
class AdAccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    meta_ad_account_id: str = Field(min_length=3, max_length=60)
    recipient_emails: list[EmailStr] = Field(default_factory=list)


class AdAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    meta_ad_account_id: str
    recipient_emails: list[str]


# ── Client ────────────────────────────────────────────────────
class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    type: ClientType = ClientType.single


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: ClientType
    created_at: datetime
    ad_accounts: list[AdAccountOut] = Field(default_factory=list)