"""
Capa de servicio del módulo de leads.

Qué vive aquí y qué NO
----------------------
El plan original de esta tarea listaba cuatro funciones, dos de ellas
(`list_leads_for_user`, `get_lead_detail`) meros reenvíos a `app/crud/leads.py`.
No están. La capa CRUD ya resuelve por sí sola el aislamiento multi-tenant y el
RBAC de *visibilidad* (`_visibility_conditions`: `owner`/`admin` ven toda la
organización, `member` sólo lo asignado a él), así que envolverla sólo agregaba
un marco de pila y un lugar más donde el filtro puede quedar desactualizado.
El router de Task 8 llama directo a `crud.list_leads_for_user` y
`crud.get_lead_for_user`.

Quedan las dos responsabilidades que la capa CRUD deliberadamente NO cubre:

A. `ingest_lead()` — ingesta del webhook. Enruta `page_id -> ClientPage ->
   Client -> org_id` (el CRUD recibe `org_id`/`client_id` ya resueltos y no
   sabe de páginas), deduplica por `leadgen_id` contra las DOS tablas de
   leads, guarda como huérfano lo que no se puede atribuir, y decide qué
   campos puede pisar una re-entrega de Meta. Nada de eso es una query.

B. `apply_lead_update()` — actualización auditada. Compara valor viejo contra
   nuevo para saber qué cambió *de verdad*, traduce el cambio a una acción de
   bitácora, resuelve nombres legibles de personas, aplica el RBAC de
   *escritura* (distinto al de lectura) y mete todo — lead + bitácora — en una
   sola transacción. `crud.update_lead` y `crud.record_audit` son dos
   escrituras independientes; coserlas de forma atómica es trabajo de aquí.

C. `reconcile_orphans()` — rescate de los huérfanos de una página que ya se
   configuró. Es la segunda mitad de (A): sin ella, la tabla `orphan_leads`
   sería un cementerio en vez de una sala de espera.

Errores
-------
Todo lo que esta capa levanta a propósito hereda de `LeadServiceError`, para
que el router pueda mapear cada caso a su HTTP sin atrapar `Exception`.
"""
from __future__ import annotations

import enum
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud import leads as crud
from app.models import Client, ClientPage, Lead, LeadAudit, OrphanLead, User, UserRole
from app.schemas.leads import LeadAuditAction, LeadSyncPayload

logger = logging.getLogger(__name__)

# Texto que se guarda en la bitácora cuando un lead queda sin responsable o
# sin notas. La columna `new_value` es NOT NULL, y un string vacío ahí se lee
# como "se perdió el dato", no como "quedó vacío a propósito".
SIN_ASIGNAR = "Sin asignar"
SIN_NOTAS = "(sin notas)"


# ── Errores del dominio ──────────────────────────────────────────
class LeadServiceError(Exception):
    """Base de todos los errores esperables de esta capa."""


class LeadPermissionError(LeadServiceError):
    """El usuario no tiene permiso para escribir sobre este lead → HTTP 403.

    Es una clase propia y no un `PermissionError` de Python ni un
    `HTTPException` para que el router decida el código de respuesta sin que
    la capa de servicio importe FastAPI, y para que nadie tenga que atrapar
    `Exception` y adivinar de qué se trata.
    """


class LeadValidationError(LeadServiceError):
    """El cambio pedido no es aplicable (campo inválido, usuario inexistente)."""


class UnknownPageError(LeadServiceError):
    """Se pidió reconciliar un `page_id` que ninguna `ClientPage` reclama.

    Ya NO la levanta `ingest_lead()`: un webhook de página desconocida es un
    caso esperado y su lead se guarda como `OrphanLead` (ver `IngestOutcome`).
    Aquí sobrevive para `reconcile_orphans()`, donde sí es un error: quien
    llama afirma que la página acaba de configurarse, y si no existe está
    reconciliando contra la nada — devolver 0 en silencio escondería el error
    de tipeo en el `page_id`.
    """

    def __init__(self, page_id: str) -> None:
        self.page_id = page_id
        super().__init__(
            f"No hay ninguna ClientPage con page_id={page_id!r}; "
            "no hay a qué cliente atribuirle sus leads."
        )


class PageOwnershipError(LeadServiceError):
    """La `ClientPage` existe, pero es de otra organización → HTTP 404.

    Convertir un huérfano escribe un `Lead` en la bandeja del tenant dueño de
    la página. Si quien llama pertenece a otra organización, eso es escribir
    en la casa ajena: no ve el resultado (el lead nace con el `org_id` del
    dueño) pero sí lo provoca. Por eso `reconcile_orphans()` exige el `org_id`
    esperado y levanta esto cuando no coincide, en vez de confiar en que cada
    llamador se acuerde de comprobarlo antes.

    El router la mapea al MISMO 404 que `UnknownPageError`: distinguirlas de
    cara afuera ("existe, pero no es tuya") ya sería contar algo de la otra
    organización. La distinción sobrevive sólo en el log del servidor.
    """

    def __init__(
        self, page_id: str, expected_org_id: int, actual_org_id: int | None
    ) -> None:
        self.page_id = page_id
        self.expected_org_id = expected_org_id
        self.actual_org_id = actual_org_id
        super().__init__(
            f"La ClientPage con page_id={page_id!r} pertenece a la organización "
            f"{actual_org_id!r}, no a la {expected_org_id!r}; reconciliar sus "
            "huérfanos escribiría leads en otro tenant."
        )


# ── Resultado de la ingesta ──────────────────────────────────────
class IngestOutcome(str, enum.Enum):
    """Los tres finales posibles de una entrega del webhook.

    Los tres se responden con HTTP 200: cualquier otro código hace que Meta
    reintente el mismo lead en bucle, y el reintento no arregla ni una
    reentrega ni una página sin configurar. El código de estado dice "te
    escuché"; qué pasó con el lead lo dice este valor, en el cuerpo.
    """

    created = "created"      # lead nuevo, atribuido a su cliente
    updated = "updated"      # reentrega de Meta de un lead ya conocido
    orphaned = "orphaned"    # página sin configurar: guardado sin atribuir


@dataclass(frozen=True)
class IngestResult:
    """Lo que la ingesta le devuelve al webhook.

    Por qué el caso huérfano es un valor y no una excepción
    -------------------------------------------------------
    Antes, un `page_id` desconocido levantaba `UnknownPageError` porque el
    lead se perdía: no había nada que devolver. Ahora se guarda, así que la
    ingesta terminó bien —hay una fila nueva en la base— y el webhook
    responde 200 igual que en los otros dos casos. Señalar con una excepción
    un final exitoso y rutinario (Meta reentrega huérfanos como reentrega
    cualquier otra cosa) obligaría al endpoint a poner su camino feliz dentro
    de un `except`, y a repetir el mapeo a 200 en dos lugares distintos donde
    un futuro `raise HTTPException(400)` pasaría desapercibido.

    `outcome` distingue los tres finales, y `action` lo entrega tal cual para
    `SyncWebhookResponse.action`. `lead` viene poblado en `created`/`updated`
    y `orphan` en `orphaned`; nunca los dos, nunca ninguno.
    """

    outcome: IngestOutcome
    lead: Lead | None = None
    orphan: OrphanLead | None = None

    @property
    def action(self) -> str:
        """`"created"`, `"updated"` u `"orphaned"`, para la respuesta HTTP."""
        return self.outcome.value


# ── Helpers internos ─────────────────────────────────────────────
def _now() -> datetime:
    """Ahora, con zona. Mismo criterio que el `default` de los modelos."""
    return datetime.now(timezone.utc)


def _raw(value: Any) -> Any:
    """Valor crudo de un Enum. `Lead.status` es `String(32)`, no un Enum de BD.

    Se compara y se guarda el string; si se dejara el miembro del Enum, el
    objeto en memoria dejaría de parecerse a la fila en disco y la comparación
    `nuevo != LeadStatus.nuevo` daría un cambio falso.
    """
    return value.value if isinstance(value, enum.Enum) else value


def _role_of(user: User) -> str:
    """Rol del usuario como string, venga como Enum o como texto."""
    return getattr(user.role, "value", user.role)


def _describe_user(db: Session, user_id: int | None) -> str:
    """Etiqueta legible de un responsable, para guardar en la bitácora.

    La bitácora se lee meses después, cuando "12" ya no le dice nada a nadie,
    así que se guarda el nombre. Se conserva también el id porque dos personas
    pueden llamarse igual.

    El usuario referido puede haber sido borrado desde entonces
    (`Lead.assigned_to_id` es `ON DELETE SET NULL`, pero un valor *histórico*
    ya escrito en la bitácora no se limpia). Por eso esto NO revienta si no
    encuentra la fila: devuelve una etiqueta que dice exactamente eso.
    """
    if user_id is None:
        return SIN_ASIGNAR
    user = db.get(User, user_id)
    if user is None:
        return f"Usuario eliminado (#{user_id})"
    return f"{user.full_name} (#{user_id})"


def _resolve_new_assignee(db: Session, org_id: int, user_id: int | None) -> User | None:
    """Valida a quién se está asignando el lead. Estricto, a diferencia del histórico.

    Un responsable *nuevo* sí tiene que existir y tiene que ser de la misma
    organización: asignarle un lead a alguien de otro tenant es una fuga de
    datos entre organizaciones, que es el peor fallo posible de este módulo.
    (Un responsable *viejo* que ya no existe se tolera — ver `_describe_user`.)
    """
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.org_id != org_id:
        raise LeadValidationError(
            f"El usuario #{user_id} no existe o no pertenece a esta organización."
        )
    return user


def _assert_can_update(lead: Lead, user: User) -> None:
    """RBAC de ESCRITURA. Ojo: no es el mismo que el de lectura.

    `owner` y `admin` escriben sobre cualquier lead de su organización; un
    `member` sólo sobre los que tiene asignados — el mismo recorte que
    `crud._visibility_conditions` aplica al leer, pero aquí no se puede
    expresar como filtro de query porque el lead ya está en la mano.

    El chequeo de organización va primero y es incondicional: aunque el router
    ya use `crud.get_lead_for_user` (que filtra por `org_id`), esta capa es
    invocable desde otros lados y no delega en que alguien más se acuerde.
    """
    if lead.org_id != user.org_id:
        raise LeadPermissionError(
            f"El lead #{lead.id} no pertenece a la organización del usuario #{user.id}."
        )
    if _role_of(user) == UserRole.member.value and lead.assigned_to_id != user.id:
        raise LeadPermissionError(
            f"El usuario #{user.id} tiene rol 'member' y sólo puede modificar "
            f"los leads asignados a él; el lead #{lead.id} no lo está."
        )


def _diff_to_audit_entries(
    db: Session, lead: Lead, changes: Mapping[str, Any]
) -> list[tuple[str, str | None, str]]:
    """Traduce el dict de cambios a filas de bitácora — sólo lo que cambió de verdad.

    Devuelve tuplas `(action, old_value, new_value)`. Un campo presente en
    `changes` cuyo valor ya es el actual NO produce tupla: la bitácora cuenta
    la historia del lead, no la de los PATCH que le llegaron, y una fila
    "cambió de contactado a contactado" es ruido que le quita valor al resto.

    Se lee el estado del lead ANTES de tocarlo; por eso esta función corre
    antes de `crud.update_lead`.
    """
    entries: list[tuple[str, str | None, str]] = []

    if "status" in changes:
        new_status = _raw(changes["status"])
        if new_status != lead.status:
            entries.append(
                (LeadAuditAction.status_changed.value, lead.status, str(new_status))
            )

    if "assigned_to_id" in changes:
        new_id = changes["assigned_to_id"]
        # `None` explícito ES un cambio (desasignar), y por eso la comparación
        # es contra el valor actual y no un `if new_id is not None`.
        if new_id != lead.assigned_to_id:
            new_user = _resolve_new_assignee(db, lead.org_id, new_id)
            new_label = SIN_ASIGNAR if new_user is None else f"{new_user.full_name} (#{new_user.id})"
            entries.append(
                (
                    LeadAuditAction.assigned.value,
                    _describe_user(db, lead.assigned_to_id),
                    new_label,
                )
            )

    if "notes" in changes:
        # `None` y `""` son la misma cosa para el usuario ("no hay notas"), así
        # que mandar `""` sobre un lead sin notas no es un cambio.
        old_notes = lead.notes or ""
        new_notes = changes["notes"] or ""
        if new_notes != old_notes:
            action = (
                LeadAuditAction.notes_added.value
                if not old_notes
                else LeadAuditAction.notes_changed.value
            )
            entries.append((action, lead.notes, new_notes or SIN_NOTAS))

    return entries


# ── A. Ingesta del webhook ───────────────────────────────────────
def _pending_orphan(db: Session, leadgen_id: str) -> OrphanLead | None:
    """El huérfano PENDIENTE de ese `leadgen_id`, si es que quedó alguno.

    Existe para un caso concreto: el lead llegó cuando su página no estaba
    configurada (quedó huérfano), alguien registró la `ClientPage` y DESPUÉS
    Meta reentregó el mismo `leadgen_id`. La reentrega entra por el camino
    normal y crea —o refresca— el `Lead` real, pero la fila huérfana se
    quedaba con `resolved_at IS NULL` para siempre, inflando el contador de
    pendientes de `/leads/status` sin que hubiera nada pendiente de verdad.

    Se filtra por `resolved_at IS NULL` para no volver a tocar —ni moverle la
    fecha a— un huérfano que ya cerró la reconciliación.
    """
    return db.scalar(
        select(OrphanLead).where(
            OrphanLead.leadgen_id == leadgen_id,
            OrphanLead.resolved_at.is_(None),
        )
    )


def _refresh_from_meta(
    db: Session,
    lead: Lead,
    payload: LeadSyncPayload,
    *,
    resolve_orphan: OrphanLead | None = None,
) -> Lead:
    """Reentrega de un lead ya conocido: refresca SÓLO lo que viene de Meta.

    Meta reentrega el mismo `leadgen_id` cuando no recibe un 200 a tiempo, y
    esa reentrega llega con `status` = el default del schema (`nuevo`). Si la
    ingesta pisara el estado, un lead que el equipo ya movió a `ganado`
    volvería a `nuevo` solo, en silencio, y con él se perdería a quién estaba
    asignado y sus notas. Así que `status`, `assigned_to_id` y `notes` — las
    tres columnas que edita un humano — no se tocan nunca por esta vía.

    Tampoco se sobrescribe con vacío: un payload sin `form_data` no puede
    borrar los datos de contacto que sí llegaron la primera vez.

    `resolve_orphan`, si viene, se cierra en el MISMO commit que el refresco
    —y se commitea aunque no haya cambiado ningún campo, que es el caso
    normal de una reentrega—. Ver `_pending_orphan`.
    """
    changed = False
    if resolve_orphan is not None:
        resolve_orphan.resolved_at = _now()
        changed = True

    if payload.form_data and payload.form_data != lead.form_data:
        lead.form_data = payload.form_data
        changed = True
    if payload.form_id is not None and payload.form_id != lead.form_id:
        lead.form_id = payload.form_id
        changed = True
    if payload.campaign_name is not None and payload.campaign_name != lead.campaign_name:
        lead.campaign_name = payload.campaign_name
        changed = True

    if changed:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(lead)

    return lead


def _create_lead_with_audit(
    db: Session,
    *,
    client: Client,
    leadgen_id: str,
    form_data: dict | None,
    form_id: str | None,
    campaign_name: str | None,
    status: str = "nuevo",
    received_at: datetime | None = None,
    resolve_orphan: OrphanLead | None = None,
) -> Lead:
    """Inserta un lead y su fila `created` de bitácora en UNA transacción.

    `user_id=None` en la bitácora es lo que hace posible esta fila: el webhook
    no actúa en nombre de nadie, y hasta que `LeadAudit.user_id` fue nullable
    la acción `created` no tenía emisor posible y sencillamente no se escribía
    (ver §14.2 del spec). NULL se lee como "lo hizo el sistema".

    `new_value` guarda la etapa con la que nace el lead. La columna es NOT
    NULL y tenía que llevar algo: se elige el estado —y no, por ejemplo, el
    `leadgen_id`— para que la bitácora se lea como una sola línea de tiempo
    del pipeline, donde la fila `created` da el punto de partida que la
    primera `status_changed` usa como `old_value`.

    `resolve_orphan`, si viene, se marca resuelto DENTRO de la misma
    transacción: o quedan el `Lead`, su bitácora y el huérfano cerrado, o no
    queda nada de las tres cosas. Un commit por separado dejaría, ante una
    caída en medio, o un huérfano resuelto sin su `Lead` (el lead se perdió,
    que es justo lo que esta tabla existe para evitar) o un `Lead` cuyo
    huérfano sigue pendiente (la próxima reconciliación intentaría duplicarlo).

    No atrapa `IntegrityError`: quién puede tratarlo como reentrega y quién no
    depende del que llama, y taparlo aquí le quitaría esa decisión.
    """
    try:
        lead = crud.create_lead(
            db,
            org_id=client.org_id,
            client_id=client.id,
            leadgen_id=leadgen_id,
            form_data=form_data,
            form_id=form_id,
            campaign_name=campaign_name,
            status=status,
            received_at=received_at,
            commit=False,
        )
        crud.record_audit(
            db,
            lead_id=lead.id,
            user_id=None,  # lo hizo el sistema
            action=LeadAuditAction.created.value,
            old_value=None,
            new_value=lead.status,
            commit=False,
        )
        if resolve_orphan is not None:
            resolve_orphan.resolved_at = _now()
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(lead)
    return lead


def _store_orphan(db: Session, payload: LeadSyncPayload) -> OrphanLead:
    """Guarda (o recupera) el huérfano de un `page_id` sin configurar.

    Idempotente por `leadgen_id`: Meta reentrega los huérfanos igual que
    cualquier otro lead, y una reentrega no puede dejar una segunda fila. El
    huérfano ya guardado se devuelve tal cual, sin refrescarlo con el payload
    nuevo — la reentrega de Meta trae el mismo contenido, y el estado que
    importa aquí (`resolved_at`) no lo decide el webhook.

    El WARNING se emite sólo la primera vez: repetirlo en cada reentrega
    convertiría el log en ruido justo cuando el operador lo necesita legible.
    """
    existing = crud.get_orphan_by_leadgen_id(db, payload.leadgen_id)
    if existing is not None:
        logger.info(
            "Reentrega de un lead huérfano ya guardado; no se duplica. "
            "page_id=%s leadgen_id=%s",
            payload.page_id,
            payload.leadgen_id,
        )
        return existing

    logger.warning(
        "Lead no atribuible: page_id sin ClientPage configurada. Se guarda "
        "como huérfano y se reconciliará cuando la página se dé de alta. "
        "page_id=%s leadgen_id=%s form_id=%s campaign_name=%s",
        payload.page_id,
        payload.leadgen_id,
        payload.form_id,
        payload.campaign_name,
    )
    try:
        return crud.create_orphan_lead(
            db,
            leadgen_id=payload.leadgen_id,
            page_id=payload.page_id,
            form_data=payload.form_data,
            form_id=payload.form_id,
            campaign_name=payload.campaign_name,
        )
    except IntegrityError:
        # Dos entregas del mismo huérfano que pasaron el SELECT a la vez.
        db.rollback()
        existing = crud.get_orphan_by_leadgen_id(db, payload.leadgen_id)
        if existing is None:
            raise  # El UNIQUE que reventó era otro; no lo tapamos.
        return existing


def ingest_lead(db: Session, payload: LeadSyncPayload) -> IngestResult:
    """Crea, actualiza o aparta el lead que manda el servicio `leads_traker`.

    El `token` del payload NO se verifica aquí: eso es autenticación y la hace
    el endpoint antes de llamar (ver `LeadSyncPayload.token`).

    Enrutamiento
    ------------
    `page_id -> ClientPage -> Client -> org_id`. No existe `Client.page_id`:
    un cliente puede tener varias páginas de Facebook, y por eso la llave vive
    en su propia tabla. Si esa página no está configurada, el lead NO se tira:
    va a `orphan_leads` y el resultado es `orphaned` (§14.1 del spec).

    Si ese lead ya había quedado huérfano y la página se configuró antes de la
    reentrega de Meta, el huérfano pendiente se marca resuelto en el mismo
    commit que el `Lead` real. Ver `_pending_orphan`.

    Deduplicación
    -------------
    Obligatoria, no opcional — Meta reentrega. `leadgen_id` es único global y
    la dedup mira las DOS tablas: primero `leads`, y sólo en el camino del
    huérfano también `orphan_leads`. Por eso el SELECT de `leads` va ANTES de
    resolver la página: un lead que ya existe es una reentrega y punto,
    aunque su `ClientPage` haya sido borrada entre una entrega y la otra —
    mandarlo a `orphan_leads` en ese caso lo duplicaría, y la reconciliación
    tendría que deshacerlo después.

    Cada comprobación se hace dos veces: con un SELECT previo (el caso normal)
    y atrapando el `IntegrityError` del UNIQUE (el caso de dos reentregas
    concurrentes que pasan el SELECT a la vez, donde el índice es el único
    árbitro real).

    Nunca levanta `UnknownPageError`: ver `IngestResult`.
    """
    # `org_id=None` a propósito: el webhook se autenticó con el token
    # compartido y todavía no sabe de qué tenant es el lead.
    existing = crud.get_lead_by_leadgen_id(db, payload.leadgen_id)
    if existing is not None:
        return IngestResult(
            IngestOutcome.updated,
            lead=_refresh_from_meta(
                db,
                existing,
                payload,
                resolve_orphan=_pending_orphan(db, payload.leadgen_id),
            ),
        )

    page = db.scalar(select(ClientPage).where(ClientPage.page_id == payload.page_id))
    if page is None:
        return IngestResult(IngestOutcome.orphaned, orphan=_store_orphan(db, payload))

    try:
        lead = _create_lead_with_audit(
            db,
            client=page.client,
            leadgen_id=payload.leadgen_id,
            form_data=payload.form_data,
            form_id=payload.form_id,
            campaign_name=payload.campaign_name,
            status=_raw(payload.status),
            resolve_orphan=_pending_orphan(db, payload.leadgen_id),
        )
    except IntegrityError:
        # Carrera con otra entrega del mismo leadgen_id: el UNIQUE hizo su
        # trabajo. Se trata como reentrega, que es lo que es.
        existing = crud.get_lead_by_leadgen_id(db, payload.leadgen_id)
        if existing is None:
            raise  # El UNIQUE que reventó era otro; no lo tapamos.
        return IngestResult(
            IngestOutcome.updated,
            lead=_refresh_from_meta(
                db,
                existing,
                payload,
                resolve_orphan=_pending_orphan(db, payload.leadgen_id),
            ),
        )

    return IngestResult(IngestOutcome.created, lead=lead)


# ── C. Reconciliación de huérfanos ───────────────────────────────
def _mark_orphan_resolved(db: Session, orphan: OrphanLead) -> None:
    """Cierra un huérfano que no hay que convertir: su `Lead` ya existe."""
    orphan.resolved_at = _now()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def reconcile_orphans(db: Session, page_id: str, *, org_id: int) -> int:
    """Convierte en `Lead` los huérfanos pendientes de una página ya configurada.

    `org_id` es la organización que quien llama afirma estar reconciliando, y
    es OBLIGATORIO y sólo por nombre: la página tiene que ser suya o esto no
    hace nada. Ver "Aislamiento por tenant" abajo.

    Devuelve cuántos se convirtieron de verdad, para que quien llame lo pueda
    reportar ("se recuperaron 12 leads"). Los huérfanos que se cierran porque
    su `Lead` ya existía NO cuentan: no se recuperó nada nuevo.

    Cada lead se convierte en su propia transacción (ver
    `_create_lead_with_audit`), no todos en una: con una sola, un `leadgen_id`
    problemático en la posición 40 tiraría abajo los 39 rescates anteriores.
    Aislados, la reconciliación avanza y es reentrante — volver a correrla no
    duplica nada porque los ya convertidos dejaron de estar pendientes.

    Sólo mira `resolved_at IS NULL`. Un `leadgen_id` que ya existe como `Lead`
    —carrera con el webhook, o alta manual— se marca resuelto sin duplicarlo.

    Quién la llama
    --------------
    El disparador natural es dar de alta una `ClientPage`: ese endpoint no
    existe todavía, así que esta función es autónoma a propósito y se puede
    invocar sola (desde un shell, un job, o el endpoint de administración
    cuando exista). Levanta `UnknownPageError` si la página sigue sin
    configurarse — reconciliar contra la nada es un error de quien llama.

    Aislamiento por tenant
    ----------------------
    Convertir un huérfano es una ESCRITURA en la bandeja de la organización
    dueña de la página. Esta función no recibe un `User` —a propósito: la
    llaman jobs y scripts que no actúan en nombre de nadie—, así que el tenant
    entra como `org_id` explícito y se compara contra el dueño real de la
    página; si no coinciden, `PageOwnershipError` y no se escribe nada.

    El parámetro es obligatorio y keyword-only justamente para que no exista
    la llamada distraída. Un `org_id: int | None = None` que sólo comprueba
    cuando se lo pasan es una defensa que el llamador nuevo —el job, el script
    de mantenimiento, el endpoint que todavía no existe— olvida sin que nada
    se lo advierta; así fue como el agujero llegó a producción la primera vez,
    con la comprobación viviendo únicamente en el router.
    """
    page = db.scalar(select(ClientPage).where(ClientPage.page_id == page_id))
    if page is None:
        raise UnknownPageError(page_id=page_id)

    client = page.client
    # `client is None` no debería pasar (client_id es NOT NULL), pero si
    # pasara no habría org_id contra el cual comparar: sin poder demostrar la
    # propiedad, se rechaza igual que si fuera de otro tenant.
    if client is None or client.org_id != org_id:
        raise PageOwnershipError(
            page_id=page_id,
            expected_org_id=org_id,
            actual_org_id=None if client is None else client.org_id,
        )

    pending = crud.list_pending_orphans(db, page_id)
    converted = 0

    for orphan in pending:
        existing = crud.get_lead_by_leadgen_id(db, orphan.leadgen_id)
        if existing is not None:
            logger.info(
                "Huérfano ya presente como lead #%s; se marca resuelto sin duplicar. "
                "page_id=%s leadgen_id=%s",
                existing.id,
                page_id,
                orphan.leadgen_id,
            )
            _mark_orphan_resolved(db, orphan)
            continue

        try:
            _create_lead_with_audit(
                db,
                client=client,
                leadgen_id=orphan.leadgen_id,
                # Copia: el dict del huérfano no debe quedar compartido con
                # el Lead nuevo, o editar uno mutaría al otro en memoria.
                form_data=dict(orphan.form_data or {}),
                form_id=orphan.form_id,
                campaign_name=orphan.campaign_name,
                # El lead llegó cuando llegó, no cuando alguien configuró la
                # página: si se pusiera `now`, un lead de hace tres días
                # aparecería arriba en la bandeja como si fuera reciente.
                received_at=orphan.received_at,
                resolve_orphan=orphan,
            )
        except IntegrityError:
            # El `Lead` apareció entre el SELECT de arriba y este INSERT.
            db.rollback()
            if crud.get_lead_by_leadgen_id(db, orphan.leadgen_id) is None:
                raise  # El UNIQUE que reventó era otro; no lo tapamos.
            _mark_orphan_resolved(db, orphan)
            continue

        converted += 1

    logger.info(
        "Reconciliación de huérfanos: page_id=%s org_id=%s pendientes=%s "
        "convertidos=%s",
        page_id,
        org_id,
        len(pending),
        converted,
    )
    return converted


# ── B. Actualización auditada ────────────────────────────────────
def apply_lead_update(
    db: Session, lead: Lead, changes: Mapping[str, Any], user: User
) -> list[LeadAudit]:
    """Aplica `changes` al lead y deja en la bitácora una fila por cambio real.

    `changes` es `payload.model_dump(exclude_unset=True)` de un `LeadUpdate`:
    una clave ausente es "no lo mandaron", una clave con `None` es "mándalo a
    null". Ver el docstring de `LeadUpdate` en app/schemas/leads.py.

    Devuelve las filas de bitácora escritas — lista vacía si el PATCH no
    cambiaba nada. `lead` se modifica en sitio y queda refrescado.

    Atomicidad
    ----------
    El lead y su bitácora se escriben en UNA transacción (`commit=False` en
    las llamadas al CRUD, un solo `db.commit()` al final). Si se hicieran dos
    commits, una caída en medio dejaría o un lead cambiado sin rastro o un
    rastro de un cambio que no ocurrió; en una bitácora, cualquiera de las dos
    la vuelve inservible como evidencia.

    Levanta:
      * `LeadPermissionError` — el `member` no es el responsable del lead.
      * `LeadValidationError` — campo no actualizable, o responsable nuevo
        inexistente / de otra organización.
    """
    _assert_can_update(lead, user)

    unknown = set(changes) - crud.UPDATABLE_FIELDS
    if unknown:
        raise LeadValidationError(
            f"Campos no actualizables en un lead: {sorted(unknown)}. "
            f"Permitidos: {sorted(crud.UPDATABLE_FIELDS)}"
        )

    # Se calcula el diff ANTES de tocar el lead: después ya no hay valor viejo
    # que registrar.
    entries = _diff_to_audit_entries(db, lead, changes)

    if not entries:
        # PATCH que repite los valores actuales: ni UPDATE ni bitácora. Así
        # `updated_at` sigue diciendo cuándo cambió el lead por última vez y
        # no cuándo alguien lo abrió y le dio guardar.
        return []

    try:
        crud.update_lead(db, lead, changes, commit=False)
        audits = [
            crud.record_audit(
                db,
                lead_id=lead.id,
                user_id=user.id,
                action=action,
                old_value=old_value,
                new_value=new_value,
                commit=False,
            )
            for action, old_value, new_value in entries
        ]
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(lead)
    for audit in audits:
        db.refresh(audit)

    return audits
