"""
Schemas Pydantic del módulo de leads.

Contexto crítico: `Lead.status` y `LeadAudit.action` son columnas
`String(32)` a propósito (ver app/models/__init__.py) — así agregar una
etapa del pipeline es un cambio de código, no un `ALTER TYPE` en Postgres.
La consecuencia es que la base de datos NO valida esos valores: si algo
inválido llega hasta el INSERT/UPDATE, se guarda tal cual. Estos schemas
son el único punto de aplicación (enforcement) de esa validación, así que
`LeadStatus` y `LeadAuditAction` abajo son la fuente de verdad única de
los valores permitidos — no repetir la lista de strings en ningún otro
schema ni endpoint; importar estas clases.
"""
import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


# ── Valores válidos del pipeline (fuente de verdad única) ───────
class LeadStatus(str, enum.Enum):
    """Las 6 etapas del pipeline. `perdido` es terminal y alcanzable desde
    cualquier etapa; el orden nuevo→contactado→calificado→propuesta→ganado
    NO se valida aquí (eso es lógica de negocio, no de forma)."""
    nuevo = "nuevo"
    contactado = "contactado"
    calificado = "calificado"
    propuesta = "propuesta"
    ganado = "ganado"
    perdido = "perdido"


class LeadAuditAction(str, enum.Enum):
    """Las acciones que puede registrar una fila de LeadAudit."""
    created = "created"
    status_changed = "status_changed"
    assigned = "assigned"
    notes_added = "notes_added"
    notes_changed = "notes_changed"


# ── Usuario resumido (para no exponer hashed_password, etc.) ────
class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str


# ── Lectura de leads ─────────────────────────────────────────────
class LeadListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    leadgen_id: str
    form_data: dict
    status: LeadStatus
    assigned_to: UserSummary | None = None
    notes: str | None = None
    received_at: datetime


class LeadListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[LeadListItem]


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: LeadAuditAction
    # `None` significa "lo hizo el sistema" — así entra la fila `created` de
    # todo lead que llegó por webhook, que no actúa en nombre de ningún
    # usuario (ver `LeadAudit.user_id` en app/models/__init__.py). El front
    # lo pinta como "Sistema"; si este campo fuera obligatorio, el detalle de
    # cualquier lead nacido de Meta reventaría al serializarse.
    user: UserSummary | None = None
    old_value: str | None = None
    new_value: str
    timestamp: datetime


class LeadResponse(LeadListItem):
    """Detalle completo de un lead: todo lo de LeadListItem + su bitácora."""
    form_id: str | None = None
    campaign_name: str | None = None
    campaign_id: str | None = None
    updated_at: datetime
    audit_log: list[AuditEntry] | None = None


# ── Escritura de leads ───────────────────────────────────────────
class LeadUpdate(BaseModel):
    """
    Cuerpo de PATCH /leads/{id} — todos los campos son opcionales, se
    actualiza solo lo que el cliente mandó.

    Ambigüedad de `None` (nota para quien implemente el router, Task 8):
    `assigned_to_id` y `notes` son `... | None = None`, así que un valor
    `None` por sí solo es ambiguo: puede significar "no mandaron este
    campo" (no tocar) o "mandaron null explícito" (desasignar el lead /
    borrar sus notas — ambas son operaciones reales que la UI necesita).
    Este schema no resuelve la ambigüedad con un tipo especial (un sentinel
    "no-provisto" habría sido sobre-ingeniería para un caso que Pydantic ya
    resuelve): la resuelve quien lo consume, usando `model_fields_set` /
    `exclude_unset`, NO comparando contra `is not None`:

        data = payload.model_dump(exclude_unset=True)
        # 'assigned_to_id' solo aparece en `data` si el cliente lo envió
        # (incluido si lo envió como null). Iterar data.items() y hacer
        # setattr(lead, campo, valor) es seguro: nunca pisa un campo que
        # el cliente no tocó, y sí permite poner NULL cuando lo pidieron.

    NO usar `if payload.assigned_to_id is not None: ...` — eso hace
    imposible desasignar un lead o vaciar sus notas vía PATCH, porque un
    `None` explícito y un campo ausente lucen idénticos en ese chequeo.
    """
    status: LeadStatus | None = None
    assigned_to_id: int | None = None
    notes: str | None = None


# ── Webhook de sincronización (lo llama el servicio leads_traker) ──
class LeadSyncPayload(BaseModel):
    """
    Cuerpo de POST /leads/sync-webhook. `token` es el secreto compartido
    (LEADS_SYNC_TOKEN, ver Task 2) — se usa SecretStr para que el valor no
    aparezca en logs, repr()/str() ni en un `.model_dump()` que se loguee
    por accidente. Para comparar contra el token esperado en el endpoint:
    `payload.token.get_secret_value() == settings.LEADS_SYNC_TOKEN`.
    """
    leadgen_id: str = Field(min_length=1, max_length=64)
    page_id: str = Field(min_length=1, max_length=64)
    form_id: str | None = Field(default=None, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=64)
    campaign_name: str | None = Field(default=None, max_length=255)
    form_data: dict = Field(default_factory=dict)
    status: LeadStatus = LeadStatus.nuevo
    token: SecretStr


class SyncWebhookResponse(BaseModel):
    status: str
    leadgen_id: str
    action: str | None = None
    note: str | None = None


# ── Estado del módulo y huérfanos (GET /leads/status) ────────────
class OrphanPageStatus(BaseModel):
    """Cuántos leads huérfanos pendientes acumuló una página sin configurar.

    Es la mitad visible de `OrphanLead` (§14.1): sin esto, una página de
    Facebook mal dada de alta sólo se nota leyendo los WARNING de Railway, y
    mientras tanto los leads reales se acumulan sin que nadie los trabaje.
    `oldest_received_at` es lo que dice si el problema es de hoy o de hace
    tres semanas.
    """
    page_id: str
    pending: int
    oldest_received_at: datetime


class LeadsDiagnostics(BaseModel):
    """Diagnóstico operativo del módulo. Sólo se entrega a `owner`/`admin`.

    Por qué NO lo ve un `member`: `orphan_leads` no tiene `org_id` —es
    justamente el dato que falta cuando un lead no se puede atribuir (ver
    `OrphanLead` en app/models/__init__.py)— así que la lista de huérfanos
    pendientes es global a la instalación, no de una organización. Entregarla
    a cualquier usuario autenticado le mostraría a un miembro de la
    organización A los `page_id` de las páginas mal configuradas de la
    organización B. Se acota al rol que además es el único que puede hacer
    algo al respecto (dar de alta la `ClientPage` y reconciliar).
    """
    webhook_configured: bool
    orphans_pending: int
    orphan_pages: list[OrphanPageStatus]


class LeadsModuleStatus(BaseModel):
    """Salud del módulo de leads.

    `diagnostics` en `null` NO significa "no hay huérfanos": significa "tu rol
    no ve esta sección". Un 0 ahí sería mentir.
    """
    module_available: bool
    total_leads: int
    diagnostics: LeadsDiagnostics | None = None


class OrphanReconcileResponse(BaseModel):
    """Resultado de POST /leads/orphans/{page_id}/reconcile.

    `recovered` cuenta sólo los huérfanos que se convirtieron en `Lead` de
    verdad; los que se cerraron porque su lead ya existía no suman (ver
    `reconcile_orphans`). `still_pending` debería quedar en 0 y, si no,
    delata que algo se quedó atrás.
    """
    page_id: str
    recovered: int
    still_pending: int
