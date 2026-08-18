"""
Schemas Pydantic — validan lo que entra y definen lo que sale por el API.
Separados de los modelos ORM a propósito (nunca exponemos hashed_password, etc.).
"""
import enum
from datetime import datetime, date

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

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
# Puede haber varios tokens centrales (uno por portafolio comercial
# independiente, ej. "Vao Vao", "Menos Pausa") — un solo System User no puede
# cruzar de un portafolio a otro en Meta.
class MetaCentralTokenIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    system_user_token: str = Field(min_length=10)


class MetaCentralTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    token_masked: str
    created_at: datetime


class MetaCredentialsStatus(BaseModel):
    """Estado de la conexión con Meta — NUNCA expone ningún token completo."""
    configured: bool
    tokens: list[MetaCentralTokenOut] = Field(default_factory=list)
    # Tokens guardados que existen en la base pero no se pudieron descifrar
    # (típicamente ENCRYPTION_KEY distinta a la que se usó para guardarlos).
    undecryptable_count: int = 0


# ── Reportes (módulo preparado, se activa al conectar Meta) ────
class ReportType(str, enum.Enum):
    quincenal = "quincenal"
    mensual = "mensual"
    personalizado = "personalizado"


class ReportStatus(BaseModel):
    meta_connected: bool
    generation_available: bool


class ReportCurrency(str, enum.Enum):
    USD = "USD"
    GTQ = "GTQ"


class ReportRequest(BaseModel):
    client_id: int
    report_type: ReportType = ReportType.quincenal
    date_from: date
    date_to: date
    budget: float | None = None
    currency: ReportCurrency = ReportCurrency.USD


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

    @field_validator("label", "meta_ad_account_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        # Copiar/pegar desde Excel/Sheets suele meter tabs o espacios de sobra,
        # y eso rompe la URL al llamar a la Graph API (ver httpx.InvalidURL).
        return v.strip()


class AdAccountUpdate(BaseModel):
    """Actualización parcial de una cuenta publicitaria."""
    label: str | None = Field(default=None, min_length=1, max_length=80)
    meta_ad_account_id: str | None = Field(default=None, min_length=3, max_length=60)
    recipient_emails: list[EmailStr] | None = None

    @field_validator("label", "meta_ad_account_id")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


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


class ClientUpdate(BaseModel):
    """Actualización parcial de un cliente."""
    name: str | None = Field(default=None, min_length=2, max_length=160)
    type: ClientType | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: ClientType
    created_at: datetime
    ad_accounts: list[AdAccountOut] = Field(default_factory=list)