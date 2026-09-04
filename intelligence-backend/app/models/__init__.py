"""
Modelos ORM — el esquema multi-tenant de VaoVao Intelligence.

Jerarquía:
    Organization (el "tenant" — VaoVao, o cada agencia si algún día es producto)
      └── User      (las personas que entran a la plataforma, con rol)
      └── Client    (los clientes de la agencia — reemplaza el clients.js)
            └── AdAccount   (cuentas publicitarias de Meta; una o varias por cliente)
            └── ClientPage  (páginas de Facebook; enrutan el lead entrante a su cliente)
            └── Lead        (leads de los formularios de Meta; su bitácora es LeadAudit)

Todo cuelga de Organization → así el aislamiento por tenant es natural:
cada query filtra por org_id y nadie ve datos de otra organización.
"""
import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    String, ForeignKey, DateTime, Boolean, Enum, JSON, Text, Index, Float, Date, Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    owner = "owner"     # dueño de la organización
    admin = "admin"     # puede gestionar clientes y usuarios
    member = "member"   # uso normal (ej. el traficker)


class ClientType(str, enum.Enum):
    """
    Sin uso desde que el reporte se genera por activo comercial: la columna
    se conserva solo para no forzar una migración de base.
    """
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

    # Tipo de cambio USD->GTQ que usa esta organización al mostrar reportes
    # en quetzales. None = todavía no lo configuraron; ver
    # report_builder.DEFAULT_EXCHANGE_RATE_USD_GTQ para el valor de
    # respaldo. Es un valor fijo que el owner/admin actualiza a mano
    # (Ajustes), no una tasa en vivo — así un reporte nunca falla por
    # depender de un servicio externo de cambio de moneda.
    exchange_rate_usd_gtq: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Ventana de atribución que usa TODA la organización al pedir insights a
    # Meta (parámetro action_attribution_windows). None = se deja que Meta
    # use el default de cada cuenta publicitaria, igual que hoy. Es a nivel
    # organización y no por usuario: dos personas generando el mismo reporte
    # del mismo cliente no pueden ver conversiones distintas sin darse
    # cuenta. Valores válidos en app/schemas ATTRIBUTION_WINDOWS.
    attribution_window: Mapped[str | None] = mapped_column(String(30), nullable=True)

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

    # ── Perfil y preferencias de reporte (Ajustes > Cuenta) ──
    # Puramente informativo, no afecta ninguna lógica.
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Con qué moneda abre Resumen/Reportes esta persona. None = USD, el
    # comportamiento de hoy. A diferencia de attribution_window, esto SÍ es
    # por usuario: no cambia ningún número, solo en qué moneda lo ve cada
    # quien al abrir el formulario.
    default_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # "quincenal" | "mensual" | "personalizado" — mismos valores que ya usa
    # el selector de tipo de reporte. None = "quincenal", el de hoy.
    default_cadence: Mapped[str | None] = mapped_column(String(20), nullable=True)

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
    pages: Mapped[list["ClientPage"]] = relationship(
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
    # Moneda en la que ESTA cuenta reporta gasto en Meta (ej. "USD", "GTQ").
    # No todas las cuentas de un cliente están en la misma moneda: algunas
    # se configuraron en Meta Ads Manager directamente en quetzales. None
    # = todavía no se consultó a Meta (cuentas creadas antes de este campo,
    # o si la consulta falló) — report_builder la resuelve on-demand y la
    # persiste la primera vez que hace falta.
    native_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Zona horaria real de ESTA cuenta en Meta (ej. "America/Guatemala").
    # Puramente informativo: Meta agrupa los insights "por día" según la
    # zona horaria de cada cuenta publicitaria y eso no se puede
    # sobreescribir por parámetro (a diferencia de la ventana de
    # atribución) — un selector editable estaría mintiendo. Se resuelve
    # on-demand igual que native_currency, en la misma llamada a Meta.
    timezone_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Últimos países targeteados por los anuncios de esta cuenta, según la
    # última vez que se consultó a Meta (ver GET /reports/countries). Un
    # targeting cambia con poca frecuencia — a diferencia del gasto, no
    # hace falta volver a pedirlo cada vez que alguien abre el selector de
    # país. None en ambos = nunca se ha consultado.
    cached_countries: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cached_countries_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Último día hasta el que app/services/daily_sync.py trajo el gasto
    # DIARIO por campaña (ver CampaignDailyMetric). None = todavía no se ha
    # sincronizado nunca — /reports/summary usa esto para decidir si puede
    # contestar sumando de la base de datos (rápido, sin tocar Meta) o si
    # todavía necesita el camino viejo (una consulta en vivo a Meta) mientras
    # llega la primera sincronización.
    daily_metrics_synced_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Día más antiguo cubierto por esa sincronización — se fija UNA sola vez
    # en la primera sincronización (hoy - daily_sync.BACKFILL_DAYS) y nunca
    # se mueve después. Sin esto, pedir un mes anterior al backfill (ej.
    # navegando muchos meses atrás en Resumen) contestaría "$0" en silencio
    # en vez de ir a buscarlo a Meta: /reports/summary y /reports/campaigns
    # solo usan la base de datos cuando date_from cae DENTRO de esta
    # ventana; si no, caen al camino viejo para ESA consulta puntual.
    daily_metrics_synced_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Correos que reciben el reporte de esta cuenta (cliente + internos de VaoVao)
    recipient_emails: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    client: Mapped["Client"] = relationship(back_populates="ad_accounts")


class ReportCampaignsCache(Base):
    """
    Caché de GET /reports/campaigns por (cuenta, rango de fechas, país):
    ese endpoint pide a Meta cuáles campañas tuvieron datos reales en un
    período exacto, y ese resultado no cambia una vez que el período ya
    pasó (Meta no reescribe el historial) — así que una fila para un
    period cerrado (date_to en el pasado) se sirve para siempre sin volver
    a llamar a Meta. Un período que todavía incluye el día de hoy sigue
    acumulando gasto, así que esa fila solo se sirve por
    _CAMPAIGNS_CACHE_TTL (ver reports.py) antes de refrescarse — así una
    campaña nueva creada hoy aparece sin esperar a que "cierre" el período.
    """
    __tablename__ = "report_campaigns_cache"
    __table_args__ = (
        UniqueConstraint("account_id", "date_from", "date_to", "country_code", name="uq_campaigns_cache_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ad_accounts.id", ondelete="CASCADE"), index=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    # "" cuando el reporte no filtra por país (en vez de NULL, para que la
    # UniqueConstraint funcione igual — NULL no es comparable a sí mismo).
    country_code: Mapped[str] = mapped_column(String(2), default="")
    campaigns: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReportSummaryCache(Base):
    """
    Caché DE RESPALDO de POST /reports/summary (panel de Resumen) por
    (cuenta, rango de fechas, moneda, país) — SOLO se usa mientras una
    cuenta todavía no se ha sincronizado ni una vez (ver
    AdAccount.daily_metrics_synced_until y app/services/daily_sync.py,
    migración 0009). Una vez que una cuenta ya se sincronizó, Resumen
    contesta sumando CampaignDailyMetric/SyncedCampaign directamente y esta
    tabla deja de tocarse para esa cuenta.

    Un período que YA CERRÓ (date_to en el pasado) se sirve para siempre,
    igual que campañas y países. Uno que todavía incluye hoy sigue
    cambiando en vivo, así que ESE se refresca cada _SUMMARY_CACHE_TTL (ver
    reports.py) en segundo plano ("stale-while-revalidate"), sin que la
    persona que tiene Resumen abierto tenga que esperar nunca a Meta — ve
    el último dato guardado al instante mientras se actualiza para la
    próxima consulta.

    `payload` guarda la respuesta completa de report_builder.build_report_data
    (ya con la conversión de moneda aplicada, por eso la moneda es parte de
    la llave). El presupuesto y la personalización por campaña (metrics/
    comments) NO son parte de la llave porque no cambian el gasto en sí:
    se sobreescriben en la respuesta en el momento de leer la caché.
    """
    __tablename__ = "report_summary_cache"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "date_from", "date_to", "currency", "country_code",
            name="uq_summary_cache_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ad_accounts.id", ondelete="CASCADE"), index=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    country_code: Mapped[str] = mapped_column(String(2), default="")
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SyncedCampaign(Base):
    """
    El "registro" de campañas de una cuenta, según la última vez que
    app/services/daily_sync.py preguntó a Meta — SIN fecha: es la foto más
    reciente de qué campañas existen y su nombre/objetivo/estado, no una
    serie histórica (eso lo guarda CampaignDailyMetric). Existe aparte del
    gasto diario para que una campaña ACTIVA/PAUSADA sin ningún día de
    gasto en el rango que alguien pida en Resumen no desaparezca del
    listado — igual que hacía include_inactive en el camino viejo (Meta en
    vivo), pero ahora resuelto localmente.
    """
    __tablename__ = "synced_campaigns"
    __table_args__ = (
        UniqueConstraint("account_id", "campaign_id", name="uq_synced_campaign"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ad_accounts.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    objective: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CampaignDailyMetric(Base):
    """
    Gasto/alcance de UNA campaña en UN día, según la última sincronización
    en segundo plano (ver app/services/daily_sync.py). Esta es la pieza que
    permite que Resumen conteste CUALQUIER rango de fechas sumando filas
    de aquí, en vez de disparar una consulta nueva a Meta por cada mes o
    quincena que alguien elija — las fechas dejan de ser un parámetro de
    "qué pedirle a Meta" y pasan a ser solo un filtro sobre datos que ya
    tenemos guardados.

    Se trae con `time_increment=1` en el job asíncrono de insights (ver
    meta_api.get_daily_campaign_data): UNA sola llamada por cuenta cubre
    TODOS los días del rango, sin importar cuántos sean ni cuántas
    campañas tenga la cuenta.
    """
    __tablename__ = "campaign_daily_metrics"
    __table_args__ = (
        UniqueConstraint("account_id", "campaign_id", "date", name="uq_campaign_daily_metric"),
        Index("idx_campaign_daily_metric_account_date", "account_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ad_accounts.id", ondelete="CASCADE"))
    campaign_id: Mapped[str] = mapped_column(String(40))
    date: Mapped[date] = mapped_column(Date)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ClientPage(Base):
    """
    Página de Facebook de un cliente — la llave de enrutamiento de los leads:
    el webhook de Meta trae un page_id y por él sabemos de qué cliente es el lead.
    Un cliente puede tener varias páginas, igual que varias cuentas publicitarias.
    page_id es único a nivel global: una página pertenece a un solo cliente.
    """
    __tablename__ = "client_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # ej. "102938475610293"
    page_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    client: Mapped["Client"] = relationship(back_populates="pages")


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
    # Id REAL de la campaña de Meta (no el nombre) — lo manda leads_traker
    # desde el mismo fetch que ya trae campaign_name (ver LEAD_FIELDS en su
    # meta.py). Con esto se puede saber a qué ACTIVO COMERCIAL pertenece un
    # lead cruzando contra SyncedCampaign (ver app/services/daily_sync.py):
    # un cliente con varios activos ya no mezcla los leads de todos —
    # GET /leads filtra por activo, no por cliente (ver crud/leads.py
    # _account_visibility_condition). None = Meta no lo mandó (formulario
    # sin anuncio pautado) o la campaña ya no existe; ese lead se muestra en
    # TODOS los activos del cliente en vez de perderse.
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Etapa del pipeline (las 5 columnas del Kanban, más el cierre negativo):
    #     nuevo → contactado → calificado → propuesta → ganado
    #                                                  → perdido
    # `perdido` es terminal y se alcanza desde cualquier etapa.
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
    # NULL tiene DOS significados, y los dos se pintan igual ("Sistema"):
    #   1. Lo hizo el sistema: la ingesta por webhook no actúa en nombre de
    #      ningún usuario, y sin esto la fila `created` de un lead nacido de
    #      Meta no se podría escribir.
    #   2. Lo hizo un usuario que después se borró: `SET NULL` degrada la fila
    #      a "atribuida al sistema" en vez de borrarla.
    # `SET NULL` y no `CASCADE`: una bitácora que desaparece cuando se borra a
    # quien la escribió no es una bitácora. Es el mismo criterio que
    # `Lead.assigned_to_id`, y `leads_service._describe_user` ya contempla al
    # usuario inexistente.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # created | status_changed | assigned | notes_added | notes_changed
    action: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lead: Mapped["Lead"] = relationship()
    user: Mapped["User | None"] = relationship()


class OrphanLead(Base):
    """
    Lead que llegó de una página de Facebook que nadie configuró todavía.

    No se puede atribuir a un cliente (no hay `ClientPage` con ese `page_id`,
    así que no hay `client_id` ni `org_id` que ponerle), pero tampoco se tira:
    descartarlo con una línea de log es perder un lead real —plata— por un
    error de configuración que nadie va a notar. Se guarda aquí sin atribuir y,
    cuando alguien registre esa página, `reconcile_orphans()` lo convierte en
    un `Lead` normal y le marca `resolved_at`.

    `leadgen_id` es único también aquí, y la deduplicación mira las DOS tablas:
    un `leadgen_id` que ya existe como `Lead` no vuelve a entrar como huérfano.
    Por eso esta tabla no tiene org_id: es justo el dato que falta.
    """
    __tablename__ = "orphan_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    leadgen_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    page_id: Mapped[str] = mapped_column(String(64), index=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Se llena cuando el huérfano ya fue convertido en Lead real.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
