"""
Schemas Pydantic — validan lo que entra y definen lo que sale por el API.
Separados de los modelos ORM a propósito (nunca exponemos hashed_password, etc.).
"""
import enum
from datetime import datetime, date

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

from app.models import UserRole


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
    job_title: str | None = None
    default_currency: str | None = None
    default_cadence: str | None = None


# Cadencias válidas para User.default_cadence — mismos valores que ya usa el
# selector de tipo de reporte ("personalizado" no aplica como default: es
# un estado transitorio de cuando alguien edita las fechas a mano).
CADENCIAS_VALIDAS = ("quincenal", "mensual")

# Monedas que la app sabe convertir hoy (ver report_builder). Si algún día
# se agrega una tercera, este es el único lugar que hay que tocar aquí.
MONEDAS_VALIDAS = ("USD", "GTQ")


class ProfileUpdate(BaseModel):
    """PATCH /users/me — cada quien edita su propio perfil, no el de otros."""
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)
    default_currency: str | None = None
    default_cadence: str | None = None

    @field_validator("job_title")
    @classmethod
    def _job_title_vacio_es_none(cls, v: str | None) -> str | None:
        # Un input vacío en el frontend manda "", no null — sin esto,
        # "borrar el cargo" guardaría la cadena vacía en vez de limpiarlo.
        return v.strip() or None if v is not None else None

    @field_validator("default_currency")
    @classmethod
    def _moneda_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in MONEDAS_VALIDAS:
            raise ValueError(f"Moneda inválida. Usa una de: {', '.join(MONEDAS_VALIDAS)}")
        return v

    @field_validator("default_cadence")
    @classmethod
    def _cadencia_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in CADENCIAS_VALIDAS:
            raise ValueError(f"Cadencia inválida. Usa una de: {', '.join(CADENCIAS_VALIDAS)}")
        return v


class PasswordChange(BaseModel):
    """POST /users/me/password — exige la actual para confirmar identidad,
    no solo la sesión (un token robado no alcanza para tomar la cuenta)."""
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


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
    # False cuando la fila existe pero no se pudo descifrar (ENCRYPTION_KEY
    # distinta a la que se usó para guardarla). Se devuelve igual, en vez de
    # omitirla, para que la UI pueda mostrarla y ofrecer borrarla: si no,
    # queda una fila invisible que no sirve y que nadie puede quitar.
    # `token_masked` va vacío en ese caso — no hay nada que enmascarar.
    readable: bool = True


class MetaCredentialsStatus(BaseModel):
    """Estado de la conexión con Meta — NUNCA expone ningún token completo."""
    # Solo cuenta tokens LEGIBLES: uno ilegible no conecta con nada.
    configured: bool
    tokens: list[MetaCentralTokenOut] = Field(default_factory=list)
    # Cuántos de `tokens` vienen con readable=False.
    undecryptable_count: int = 0


# Ventanas de atribución que ofrece Ajustes > Preferencias de reporte, y a
# qué lista de valores de Meta (action_attribution_windows) traduce cada
# una. None/"default" = no se manda el parámetro y Meta usa el default de
# cada cuenta publicitaria (el comportamiento de hoy). Vive aquí, no en
# meta_api, porque es la organización quien la elige (Ajustes) y es lo que
# valida OrganizationSettingsUpdate — meta_api solo consume el resultado.
ATTRIBUTION_WINDOWS: dict[str, list[str]] = {
    "1d_click": ["1d_click"],
    "7d_click": ["7d_click"],
    "7d_click_1d_view": ["7d_click", "1d_view"],
}


class OrganizationSettings(BaseModel):
    """
    Preferencias de la organización (Ajustes > Preferencias de reporte).
    `exchange_rate_usd_gtq` y `attribution_window` son None mientras nadie
    los haya configurado — el frontend debe mostrar ese caso como "sin
    configurar", nunca como 0 o como "sin atribución".
    """
    exchange_rate_usd_gtq: float | None = None
    attribution_window: str | None = None


class OrganizationSettingsUpdate(BaseModel):
    """
    Parcial a propósito: el tipo de cambio y la atribución los puede
    cambiar la misma persona en momentos distintos, y mandar el campo que
    no se toca de vuelta obligaría al frontend a conocer siempre el valor
    actual del otro.
    """
    exchange_rate_usd_gtq: float | None = Field(default=None, gt=0)
    attribution_window: str | None = None

    @field_validator("attribution_window")
    @classmethod
    def _ventana_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in ATTRIBUTION_WINDOWS:
            raise ValueError(f"Ventana de atribución inválida. Usa una de: {', '.join(ATTRIBUTION_WINDOWS)}")
        return v


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
    ad_account_id: int  # id del activo comercial en nuestra base
    report_type: ReportType = ReportType.quincenal
    date_from: date
    date_to: date
    budget: float | None = None
    currency: ReportCurrency = ReportCurrency.USD
    country_code: str | None = None  # ej. "GT" para Guatemala, "US" para USA; None = todos
    campaign_metrics: dict[str, list[str]] | None = None    # campaign_id (Meta) -> claves de pdf_generator.METRIC_REGISTRY
    campaign_comments: dict[str, str] | None = None          # campaign_id (Meta) -> observación de esa campaña
    general_comment: str | None = None                       # observación general del período

    @field_validator("general_comment")
    @classmethod
    def _comentario_general_no_muy_largo(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 2000:
            raise ValueError("La observación general no puede superar los 2000 caracteres.")
        return v

    @field_validator("campaign_comments")
    @classmethod
    def _comentarios_por_campana_no_muy_largos(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None:
            for comment in v.values():
                if len(comment) > 2000:
                    raise ValueError("Las observaciones por campaña no pueden superar los 2000 caracteres.")
        return v


class CheckAccessRequest(BaseModel):
    account_id: int  # id de la cuenta publicitaria en nuestra base


class CheckAccessResult(BaseModel):
    ok: bool
    detail: str  # nombre de la cuenta si ok; motivo si no


# ── Generación de reportes en segundo plano ─────────────────────
class ReportJobCreated(BaseModel):
    job_id: str


class ReportJobStatus(BaseModel):
    job_id: str
    status: str  # "processing" | "done" | "error"
    error: str | None = None
    filename: str | None = None


# ── Ad Account ────────────────────────────────────────────────
class AdAccountCreate(BaseModel):
    """
    El nombre (label) NO se pide: se hereda del nombre real de la cuenta en
    Meta al registrarla. Ver clients.add_ad_account.
    """
    meta_ad_account_id: str = Field(min_length=3, max_length=60)
    recipient_emails: list[EmailStr] = Field(default_factory=list)

    @field_validator("meta_ad_account_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        # Copiar/pegar desde Excel/Sheets suele meter tabs o espacios de sobra,
        # y eso rompe la URL al llamar a la Graph API (ver httpx.InvalidURL).
        return v.strip()


class AdAccountUpdate(BaseModel):
    """Actualización parcial de una cuenta publicitaria (label es heredado)."""
    meta_ad_account_id: str | None = Field(default=None, min_length=3, max_length=60)
    recipient_emails: list[EmailStr] | None = None

    @field_validator("meta_ad_account_id")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class AdAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    meta_ad_account_id: str
    recipient_emails: list[str]
    # Puramente informativo (ver ad_accounts.timezone_name). None hasta que
    # se agregue o edite el activo, que es cuando se resuelve contra Meta.
    timezone_name: str | None = None


# ── Client ────────────────────────────────────────────────────
class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class ClientUpdate(BaseModel):
    """Actualización parcial de un cliente."""
    name: str | None = Field(default=None, min_length=2, max_length=160)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    created_at: datetime
    ad_accounts: list[AdAccountOut] = Field(default_factory=list)