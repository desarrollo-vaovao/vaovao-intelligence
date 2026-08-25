"""
Modelos ORM — el esquema multi-tenant de VaoVao Intelligence.

Jerarquía:
    Organization (el "tenant" — VaoVao, o cada agencia si algún día es producto)
      └── User      (las personas que entran a la plataforma, con rol)
      └── Client    (los clientes de la agencia — reemplaza el clients.js)
            └── AdAccount  (cuentas publicitarias de Meta; una o varias por cliente)

Todo cuelga de Organization → así el aislamiento por tenant es natural:
cada query filtra por org_id y nadie ve datos de otra organización.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import String, ForeignKey, DateTime, Boolean, Enum, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    owner = "owner"     # dueño de la organización
    admin = "admin"     # puede gestionar clientes y usuarios
    member = "member"   # uso normal (ej. el traficker)


class ClientType(str, enum.Enum):
    single = "single"               # un solo ad account
    multi_station = "multi_station" # varias estaciones/países


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # ── Credenciales de Meta ──
    # La app de Meta es una sola para toda la organización.
    meta_app_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    clients: Mapped[list["Client"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    meta_central_tokens: Mapped[list["MetaCentralToken"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.member)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped["Organization"] = relationship(back_populates="users")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[ClientType] = mapped_column(Enum(ClientType), default=ClientType.single)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped["Organization"] = relationship(back_populates="clients")
    ad_accounts: Mapped[list["AdAccount"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    leads: Mapped[list["Lead"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class AdAccount(Base):
    __tablename__ = "ad_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))            # ej. "Guatemala", "Panamá", o "Principal"
    meta_ad_account_id: Mapped[str] = mapped_column(String(60))  # ej. "act_1234567890"
    # Correos que reciben el reporte de esta cuenta (cliente + internos de VaoVao)
    recipient_emails: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    client: Mapped["Client"] = relationship(back_populates="ad_accounts")


class Lead(Base):
    """Lead generado desde formularios de captura (LeadGen o forms custom)."""
    __tablename__ = "leads"
    __table_args__ = (
        Index("idx_lead_org_client_status", "org_id", "client_id", "status"),
        Index("idx_lead_org_assigned", "org_id", "assigned_to_id"),
        Index("idx_lead_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    leadgen_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Etapa del pipeline: nuevo | contactado | ganado | perdido
    # String y no Enum a propósito: agregar una etapa es un cambio de código,
    # no un ALTER TYPE en Postgres.
    status: Mapped[str] = mapped_column(String(32), default="nuevo")
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    organization: Mapped["Organization"] = relationship(back_populates="leads")
    client: Mapped["Client"] = relationship(back_populates="leads")
    assigned_to: Mapped["User | None"] = relationship()


class LeadAudit(Base):
    """Auditoría de cambios en leads."""
    __tablename__ = "lead_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # created | status_changed | assigned | notes_added | notes_changed
    action: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lead: Mapped["Lead"] = relationship()
    user: Mapped["User"] = relationship()


class FacebookConnection(Base):
    """Conexión de Facebook de un usuario (una por usuario). Token cifrado."""
    __tablename__ = "facebook_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    fb_user_id: Mapped[str] = mapped_column(String(60))
    fb_name: Mapped[str] = mapped_column(String(160))
    token_encrypted: Mapped[str] = mapped_column(String(700))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MetaCentralToken(Base):
    """
    Token de System User de Meta, uno por cada portafolio comercial independiente
    (ej. "Vao Vao", "Menos Pausa", "Cementerios"). Un solo System User no puede
    cruzar de un portafolio a otro, así que cada portafolio necesita el suyo.
    Se usan como respaldo cuando el Facebook personal del usuario no tiene
    acceso a una cuenta puntual (ver reports.py _resolve_tokens).
    """
    __tablename__ = "meta_central_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))  # ej. "Vao Vao", "Menos Pausa"
    token_encrypted: Mapped[str] = mapped_column(String(700))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped["Organization"] = relationship(back_populates="meta_central_tokens")
