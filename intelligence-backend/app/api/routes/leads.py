"""
Módulo de Leads — superficie HTTP.

Expone dos superficies muy distintas sobre el mismo `router`:

  * `POST /leads/sync-webhook` — la puerta por la que entran los leads que
    reenvía el servicio externo `leads_traker` (que a su vez recibe los
    webhooks de Meta LeadGen). Es el ÚNICO endpoint sin JWT del proyecto.
  * El CRM — listar, ver, editar, exportar, diagnosticar y reconciliar. Todo
    eso exige `Depends(get_current_user)` como el resto del API.

Toda la lógica de negocio —enrutar `page_id -> ClientPage -> Client`,
deduplicar reentregas contra las dos tablas de leads, apartar como huérfano
lo que no se puede atribuir— vive en `app.services.leads_service.ingest_lead`
y NO se repite aquí. Lo que este archivo aporta, y que sólo puede aportar la
capa HTTP, es:

  1. **Autenticación.** Es el único endpoint del proyecto abierto a Internet
     sin JWT: lo autentica un secreto compartido que viaja en el cuerpo.
  2. **El código de estado.** Quien llama reintenta ante cualquier no-2xx
     (ver `_response_for`), así que elegir mal el código no devuelve un error:
     devuelve un bucle.
  3. **No filtrar nada.** Ni el token esperado, ni el recibido, ni el interior
     del servidor cuando algo revienta.

Los endpoints del CRM heredan sin más trabajo el saneo de errores de
validación de `_LeadsRoute`. La autenticación NO se hereda: el token
compartido es exclusivo del webhook.

ORDEN DE LAS RUTAS — no reordenar sin pensarlo
-----------------------------------------------
`GET /leads/status` y `GET /leads/export/csv` se declaran ANTES que
`GET /leads/{lead_id}`. FastAPI resuelve por orden de declaración, así que
con `/{lead_id}` arriba la petición a `/leads/status` entraría por el
handler del detalle con `lead_id="status"` y devolvería un 422 de "no es un
entero" en vez del endpoint que se pidió. (`/leads/export/csv` tiene dos
segmentos y hoy no colisiona, pero se deja junto al otro para que la regla
sea una sola y no dependa de contar segmentos.)
"""

# OJO: este módulo NO puede usar `from __future__ import annotations`.
# `@limiter.limit` envuelve el endpoint, y FastAPI resuelve las anotaciones
# —que con ese import son strings— contra los globals del envoltorio, que son
# los del módulo de slowapi y no los de aquí. `LeadSyncPayload` no existe ahí,
# así que el cuerpo deja de reconocerse como cuerpo y el endpoint responde
# `422 {"loc":["query","payload"],"msg":"Field required"}` a todo. Comprobado.
import hmac
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import LEADS_SYNC_TOKEN_DEV_DEFAULT, settings
from app.core.database import get_db
from app.core.ratelimit import LIMITS, limiter
from app.crud import leads as crud
from app.models import Client, Lead, User, UserRole
from app.schemas.leads import (
    AuditEntry,
    LeadListItem,
    LeadListResponse,
    LeadResponse,
    LeadStatus,
    LeadSyncPayload,
    LeadUpdate,
    LeadsDiagnostics,
    LeadsModuleStatus,
    OrphanPageStatus,
    OrphanReconcileResponse,
    SyncWebhookResponse,
)
from app.services.leads_csv_exporter import build_export_filename, export_leads_csv
from app.services.leads_service import (
    IngestOutcome,
    IngestResult,
    LeadPermissionError,
    LeadValidationError,
    PageOwnershipError,
    UnknownPageError,
    apply_lead_update,
    ingest_lead,
    reconcile_orphans,
)

logger = logging.getLogger(__name__)

# Un único mensaje para token ausente, mal formado o simplemente equivocado.
# Decir cuál de los tres fue le regalaría al atacante la mitad del trabajo:
# "falta el campo" confirma que el nombre del campo es otro, "token inválido"
# confirma que el campo llegó bien y sólo falta acertar el valor.
_UNAUTHORIZED_DETAIL = "No autorizado."

# Lo mismo para un fallo inesperado: el detalle real va al log del servidor.
_INTERNAL_DETAIL = (
    "Ocurrió un error inesperado procesando el lead. El lead no se guardó; "
    "se puede reintentar."
)


# ── Saneo de los errores de validación ───────────────────────────
def _scrub(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deja de cada error de Pydantic sólo el "dónde" y el "qué", nunca el valor.

    FastAPI, por defecto, mete en el 422 la clave `input` con el cuerpo que
    recibió. En este endpoint el cuerpo lleva el secreto compartido, así que
    un payload al que le falte cualquier otro campo hace que la respuesta
    devuelva el token en texto plano a quien lo mandó — y a cualquiera que lea
    ese 422 en un log de acceso o en un proxy. Se comprobó: sin este filtro,
    `{"page_id": "1", "token": "..."}` responde
    `{"detail":[{... "input":{"page_id":"1","token":"<el token>"}}]}`.

    `loc`, `msg` y `type` sí se conservan: no son valores del payload —son el
    nombre del campo, que ya está publicado en /docs— y sin ellos depurar
    `leads_traker` sería adivinar.
    """
    return [
        {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
        for err in errors
    ]


def _is_token_error(errors: list[dict[str, Any]]) -> bool:
    """¿La validación falló (también) por el campo `token`?

    `LeadSyncPayload.token` es obligatorio, así que un cuerpo sin token muere
    en la validación de Pydantic antes de llegar al endpoint y saldría como
    422 "Field required" — revelando exactamente la diferencia entre "no
    mandaste token" y "mandaste uno equivocado" que el 401 genérico existe
    para esconder. Detectarlo aquí devuelve los tres casos al mismo 401.
    """
    return any(tuple(err.get("loc") or ())[-1:] == ("token",) for err in errors)


class _LeadsRoute(APIRoute):
    """Convierte los 422 de FastAPI en respuestas que no repiten el cuerpo.

    Se hace con una clase de ruta y no con un `exception_handler` de la app
    porque un handler global cambiaría la forma del 422 de TODO el API —
    incluidos endpoints de otras tareas cuyo front ya lee ese formato. El
    radio de impacto queda en este router.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def sanitized_handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                errors = exc.errors()
                if _is_token_error(errors):
                    logger.warning(
                        "Webhook de leads rechazado: el cuerpo no trae un token "
                        "utilizable. client=%s",
                        request.client.host if request.client else "?",
                    )
                    raise HTTPException(
                        status.HTTP_401_UNAUTHORIZED, _UNAUTHORIZED_DETAIL
                    ) from exc
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, _scrub(errors)
                ) from exc

        return sanitized_handler


router = APIRouter(prefix="/leads", tags=["leads"], route_class=_LeadsRoute)


# ── Autenticación por secreto compartido ─────────────────────────
def _token_matches(token: SecretStr | None) -> bool:
    """Compara el token recibido con `LEADS_SYNC_TOKEN` en tiempo constante.

    Un `==` normal corta en cuanto encuentra el primer byte distinto, y ese
    corte se nota en cuánto tarda la respuesta. Midiendo miles de intentos se
    reconstruye el secreto byte a byte, sin acertarlo nunca de golpe.
    `hmac.compare_digest` recorre siempre todo el largo.

    Se comparan `bytes` y no `str` a propósito: `compare_digest` acepta `str`
    sólo si ambos son ASCII puro y revienta con `TypeError` si no, y el token
    lo escribe un humano que puede meter cualquier cosa. Codificar a utf-8
    quita ese modo de fallo y mantiene la comparación en el camino constante.

    El largo sí se filtra (dos cadenas de largo distinto no tardan lo mismo);
    es una fuga inherente a `compare_digest` y no revela el contenido.
    """
    provided = token.get_secret_value() if token is not None else ""
    expected = settings.LEADS_SYNC_TOKEN or ""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


# ── Mapeo del resultado a HTTP ───────────────────────────────────
_NOTES: dict[IngestOutcome, str | None] = {
    IngestOutcome.created: None,
    IngestOutcome.updated: (
        "Reentrega de un lead ya registrado; se refrescaron los datos que "
        "vienen de Meta y se conservaron estado, responsable y notas."
    ),
    IngestOutcome.orphaned: (
        "La página no está asociada a ningún cliente todavía. El lead SÍ quedó "
        "guardado en orphan_leads y se atribuirá solo cuando la página se dé "
        "de alta: no hace falta reintentar, reintentar no cambia nada."
    ),
}


def _response_for(result: IngestResult, leadgen_id: str) -> SyncWebhookResponse:
    """Los tres finales de la ingesta se responden 200. Sí, los tres.

    Quien llama es `leads_traker`, que reenvía los webhooks de Meta y hereda
    su comportamiento: cualquier respuesta que no sea 2xx significa "no me
    llegó" y provoca un reintento del MISMO lead. La pregunta correcta ante
    cada camino no es "¿salió bien?" sino "¿reintentar arreglaría algo?".

      * `created` — sí salió bien. 200 evidente.
      * `updated` — es justamente el reintento de una entrega anterior. Si
        respondiéramos error, pediríamos un tercer intento idéntico.
      * `orphaned` — el lead está guardado y a salvo en `orphan_leads`; lo que
        falta es que un humano dé de alta la página, cosa que ningún reintento
        provoca. Un 4xx/5xx aquí sería el peor caso: bucle infinito sobre un
        lead que ya tenemos, hasta que quien llama se rinda y lo dé por
        perdido — perdiendo la única señal de que había algo que configurar.

    Qué pasó de verdad se cuenta en `action` y `note`, en el cuerpo, que es
    donde un consumidor puede leerlo sin que el transporte se ponga a
    reintentar por su cuenta.
    """
    return SyncWebhookResponse(
        status="ok",
        leadgen_id=leadgen_id,
        action=result.action,
        note=_NOTES[result.outcome],
    )


# ── Endpoint ─────────────────────────────────────────────────────
@router.post(
    "/sync-webhook",
    response_model=SyncWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Recibe un lead desde el servicio leads_traker",
)
@limiter.limit(LIMITS["leads_sync_webhook"])
def sync_webhook(
    request: Request,
    payload: LeadSyncPayload,
    db: Session = Depends(get_db),
) -> SyncWebhookResponse:
    """Da de alta (o reconoce) un lead que llega desde `leads_traker`.

    Límite de tasa — por qué 120/minuto
    -----------------------------------
    El límite se cuenta por IP de origen y quien llama es un servicio, no una
    persona: TODOS los leads de TODOS los clientes entran por la misma IP y
    caen en el mismo balde. Un límite pensado "por cliente" (unos pocos leads
    por minuto) cortaría a la plataforma entera en cuanto dos campañas
    coincidieran.

    120/minuto = 2 por segundo sostenidos. Por arriba del uso real con mucho
    margen —una operación de agencia mide sus leads en cientos por día, no por
    minuto— y con espacio para los dos picos que sí ocurren: las reentregas de
    Meta cuando algo va lento, y el drenaje de la cola acumulada tras una
    caída (500 leads represados se despachan en poco más de cuatro minutos, y
    el 429 del resto sólo los pospone porque quien llama reintenta).

    Hacia el otro lado le pone techo a una URL filtrada: acota el ruido a
    ~172k peticiones diarias en vez de infinitas, y deja la búsqueda a ciegas
    del token en 120 intentos por minuto, que contra un secreto aleatorio de
    largo decente no termina nunca.

    El 429 es de los pocos no-2xx correctos aquí: reintentar más tarde es
    exactamente lo que arregla haber ido demasiado rápido.

    Códigos
    -------
    * 200 — el lead quedó guardado (`created`, `updated` u `orphaned`).
    * 401 — token ausente, mal formado o incorrecto. No reintentar: hay que
      arreglar la configuración de quien llama.
    * 422 — el cuerpo no cumple el contrato. No reintentar, por lo mismo.
    * 429 — se excedió el límite. Reintentar con espera.
    * 500 — falló algo del servidor (la base, un bug). El lead NO se guardó;
      reintentar sí puede funcionar.
    """
    if not _token_matches(payload.token):
        # Nunca el token —ni el recibido ni el esperado— en el log. Lo que
        # sirve para investigar es de dónde vino y qué lead traía.
        logger.warning(
            "Webhook de leads rechazado: token incorrecto. client=%s page_id=%s "
            "leadgen_id=%s",
            request.client.host if request.client else "?",
            payload.page_id,
            payload.leadgen_id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTHORIZED_DETAIL)

    try:
        result = ingest_lead(db, payload)
    except Exception:
        # `logger.exception` deja el traceback completo del lado del servidor;
        # al que llama sólo le va un mensaje genérico. Un `str(e)` de
        # SQLAlchemy en el cuerpo publicaría el SQL, los nombres de las tablas
        # y a veces hasta el DSN de la base.
        logger.exception(
            "Fallo inesperado ingiriendo un lead del webhook. page_id=%s leadgen_id=%s",
            payload.page_id,
            payload.leadgen_id,
        )
        # 500 y no 200: aquí el lead NO quedó guardado en ninguna tabla, y una
        # caída de la base o un deadlock son justamente las cosas que un
        # reintento sí resuelve. Es el único camino donde pedir otro intento
        # tiene sentido.
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, _INTERNAL_DETAIL
        ) from None
    logger.info(
        "Webhook de leads: %s. page_id=%s leadgen_id=%s",
        result.action,
        payload.page_id,
        payload.leadgen_id,
    )
    return _response_for(result, payload.leadgen_id)


# ═════════════════════════════════════════════════════════════════
#  CRM de leads — todo lo de aquí para abajo exige JWT
# ═════════════════════════════════════════════════════════════════

# Mensajes fijos. Igual que en el webhook: lo que se filtra en un cuerpo de
# error no se puede des-filtrar, así que ninguno de estos incluye el detalle
# real (que sí va al log del servidor).
_LEAD_NOT_FOUND_DETAIL = "Lead no encontrado."
_CLIENT_NOT_FOUND_DETAIL = "Cliente no encontrado"
_FORBIDDEN_DETAIL = "No tienes permisos para modificar este lead."
_UPDATE_FAILED_DETAIL = (
    "Ocurrió un error inesperado actualizando el lead. No se guardó ningún "
    "cambio; se puede reintentar."
)
_RECONCILE_FAILED_DETAIL = (
    "Ocurrió un error inesperado reconciliando los leads huérfanos de esta "
    "página. Los que alcanzaron a convertirse quedaron guardados; volver a "
    "ejecutar la reconciliación no duplica nada."
)
_PAGE_NOT_FOUND_DETAIL = (
    "No hay ninguna página de Facebook con ese page_id registrada en tu "
    "organización. Da de alta la página en su cliente antes de reconciliar."
)

# Tope de filas de una exportación. `export_leads_csv` arma el archivo entero
# en memoria (es un StringIO), y este servicio corre en un solo proceso de
# Railway compartido con la generación de PDFs: un `GET /leads/export/csv` sin
# filtros sobre una organización con 300.000 leads no devolvería un archivo,
# tumbaría el proceso para todos. 20.000 filas está muy por encima de una
# exportación real (un cliente activo hace miles de leads al año, no cientos
# de miles) y el 413 dice exactamente qué hacer para pasar por debajo.
EXPORT_MAX_ROWS = 20_000
_EXPORT_TOO_LARGE_DETAIL = (
    f"La exportación excede el máximo de {EXPORT_MAX_ROWS} leads por archivo. "
    "Filtra por cliente o por estado para descargarla por partes."
)


# ── Helpers del CRM ──────────────────────────────────────────────
def _is_operator(user: User) -> bool:
    """`owner` o `admin`. El rol puede venir como Enum o como texto."""
    role = getattr(user.role, "value", user.role)
    return role in (UserRole.owner.value, UserRole.admin.value)


def _resolve_client_filter(
    db: Session, current: User, client_id: int | None
) -> Client | None:
    """Comprueba que el `client_id` del filtro sea de la organización del usuario.

    Sin esto, filtrar por un cliente ajeno no devolvería sus leads —el
    `org_id` del CRUD ya lo impide— pero sí devolvería una lista vacía con
    200, que se lee como "ese cliente no tiene leads" en vez de "ese cliente
    no es tuyo". 404, igual que `clients.py` y `reports.py`.

    Devuelve el `Client` porque el exportador necesita su nombre para el
    archivo; `None` cuando no se filtró por cliente.
    """
    if client_id is None:
        return None
    client = db.scalar(
        select(Client).where(Client.id == client_id, Client.org_id == current.org_id)
    )
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _CLIENT_NOT_FOUND_DETAIL)
    return client


# Los campos del detalle que SÍ salen del ORM. `audit_log` no está en la
# lista porque no se puede sacar de ahí — ver `_detail_response`.
_DETAIL_ORM_FIELDS = tuple(
    name for name in LeadResponse.model_fields if name != "audit_log"
)


def _detail_response(db: Session, lead: Lead) -> LeadResponse:
    """Arma el detalle del lead pegándole su bitácora, que NO vive en el ORM.

    `Lead` no tiene relación `audit_log`: `LeadAudit` sólo declara la llave
    foránea `lead_id`, sin back-reference (decisión de Task 1, y el reporte de
    Task 3 la dejó anotada para aquí). O sea que
    `LeadResponse.model_validate(lead)` no puede poblar `audit_log` por más
    que el campo exista en el schema — como mucho lo dejaría en su default.
    Las filas se traen aparte con `crud.get_audit_log`, que además hace
    `selectinload` del usuario de cada entrada para no caer en N+1 al
    serializar `AuditEntry.user`.

    Se construye un dict explícito en vez de validar el objeto ORM y parchear
    el resultado: así el ensamblado es visible en una sola línea de código y
    no depende de qué hace Pydantic cuando un atributo no existe pero el campo
    tiene default.

    Sobre `user_id IS NULL`: esas filas son las que escribió el sistema (la
    ingesta del webhook no actúa en nombre de nadie). `AuditEntry.user` es
    `UserSummary | None` justamente para eso, así que la entrada sale con
    `"user": null` y el front la pinta como "Sistema" — ver el comentario del
    schema. NO se inventa aquí un `UserSummary(id=0, full_name="Sistema")`:
    sería un usuario que no existe, con un id que sí podría existir mañana, y
    contradiría el contrato que el schema ya documenta.
    """
    data: dict[str, Any] = {name: getattr(lead, name) for name in _DETAIL_ORM_FIELDS}
    data["audit_log"] = [
        AuditEntry.model_validate(row, from_attributes=True)
        for row in crud.get_audit_log(db, lead.id)
    ]
    return LeadResponse.model_validate(data)


def _collect_for_export(
    db: Session,
    current: User,
    *,
    client_id: int | None,
    status_filter: LeadStatus | None,
    search: str | None,
) -> list[Lead]:
    """Todos los leads que hacen match con el filtro, no sólo una página.

    Reusa `crud.list_leads_for_user` en vez de escribir una query propia sin
    paginar: el aislamiento multi-tenant y el RBAC viven ahí y no se
    reimplementan (una segunda cadena de filtros es exactamente el bug que el
    CRUD documenta como inaceptable). El precio es pedirlo por páginas de
    `MAX_PAGE_SIZE`, que es el tope duro del CRUD.
    """
    total, items = crud.list_leads_for_user(
        db,
        current,
        client_id=client_id,
        status=status_filter,
        search=search,
        page=1,
        size=crud.MAX_PAGE_SIZE,
    )
    if total > EXPORT_MAX_ROWS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, _EXPORT_TOO_LARGE_DETAIL
        )

    collected = list(items)
    page = 2
    while len(collected) < total:
        _, more = crud.list_leads_for_user(
            db,
            current,
            client_id=client_id,
            status=status_filter,
            search=search,
            page=page,
            size=crud.MAX_PAGE_SIZE,
        )
        if not more:
            # La base cambió entre página y página (alguien borró leads). Se
            # exporta lo que hay en vez de girar para siempre.
            break
        collected.extend(more)
        page += 1
    return collected


# ── Listado ──────────────────────────────────────────────────────
@router.get(
    "",
    response_model=LeadListResponse,
    summary="Lista paginada de leads visibles para el usuario",
)
@limiter.limit(LIMITS["leads_list"])
def list_leads(
    request: Request,
    page: int = Query(1, ge=1, description="Página, empezando en 1."),
    size: int = Query(
        crud.DEFAULT_PAGE_SIZE,
        ge=1,
        le=crud.MAX_PAGE_SIZE,
        description="Leads por página.",
    ),
    client_id: int | None = Query(None, description="Filtra por cliente."),
    status_filter: LeadStatus | None = Query(
        None, alias="status", description="Filtra por etapa del pipeline."
    ),
    search: str | None = Query(
        None, max_length=200, description="Busca dentro de los datos del formulario."
    ),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    """La bandeja de leads: `total` para el paginador, `items` para la página.

    Quién ve qué lo decide `crud.list_leads_for_user`, no este endpoint:
    siempre acota a `current.org_id` y, si el rol es `member`, además a los
    leads asignados a esa persona. `size` está topado en `crud.MAX_PAGE_SIZE`;
    pedir más es un 422, no una descarga de la tabla entera.

    El parámetro de la URL se llama `status` (el `alias`), no `status_filter`:
    en Python no puede llamarse así porque `status` es el módulo de códigos
    HTTP de FastAPI que se usa en el resto del archivo, y sombrearlo dejaría
    `status.HTTP_404_NOT_FOUND` roto dentro de la función.

    Límite de tasa — 120/minuto
    ---------------------------
    Lectura barata (un COUNT y una página, ambos por índice) pero repetida:
    cambiar de página, filtrar y teclear en el buscador son peticiones
    distintas. El balde de slowapi es por IP, así que una oficina entera
    detrás de un NAT lo comparte; 120/minuto deja trabajar a varias personas a
    la vez y aun así corta a un scraper que pagine la organización entera.
    """
    _resolve_client_filter(db, current, client_id)

    total, items = crud.list_leads_for_user(
        db,
        current,
        client_id=client_id,
        status=status_filter,
        search=search,
        page=page,
        size=size,
    )
    return LeadListResponse(
        total=total,
        page=page,
        size=size,
        items=[
            LeadListItem.model_validate(item, from_attributes=True) for item in items
        ],
    )


# ── Estado del módulo ────────────────────────────────────────────
# OJO: este endpoint y el de exportar van ANTES que `/{lead_id}`.
# Ver "ORDEN DE LAS RUTAS" en el docstring del módulo.
@router.get(
    "/status",
    response_model=LeadsModuleStatus,
    summary="Salud del módulo de leads y huérfanos pendientes",
)
@limiter.limit(LIMITS["leads_status"])
def leads_status(
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadsModuleStatus:
    """Estado del módulo. Para `owner`/`admin`, además el diagnóstico de huérfanos.

    Por qué existe (§14.1)
    ----------------------
    Un lead que llega de una página de Facebook que nadie dio de alta no se
    pierde —se guarda en `orphan_leads`— pero tampoco aparece en ninguna
    bandeja. Sin este endpoint, la única señal de que hay una página mal
    configurada es un WARNING en los logs de Railway, que nadie lee hasta que
    el cliente reclama los leads que no le llegaron. Aquí sale el número de
    pendientes y de QUÉ `page_id` son, que es exactamente lo que hace falta
    para arreglarlo (dar de alta esa página y reconciliar).

    Por qué el diagnóstico no lo ve un `member`
    -------------------------------------------
    `orphan_leads` no tiene `org_id` — es justo el dato que falta cuando un
    lead no se puede atribuir. La lista de pendientes es, por tanto, global a
    la instalación: entregarla a cualquiera le mostraría a un usuario de la
    organización A los `page_id` mal configurados de la organización B. Se
    acota al rol que además es el único que puede actuar. Para un `member`,
    `diagnostics` viaja como `null` — "no lo ves", que no es lo mismo que 0.

    Límite de tasa — 60/minuto
    --------------------------
    Es un panel: se pide al abrir la sección y, si el front decide sondearlo,
    cada pocos segundos. Cuesta dos conteos por índice. Uno por segundo por
    persona con margen para el equipo entero detrás de la misma IP.
    """
    total_leads, _ = crud.list_leads_for_user(db, current, page=1, size=1)

    diagnostics: LeadsDiagnostics | None = None
    if _is_operator(current):
        by_page: dict[str, OrphanPageStatus] = {}
        for orphan in crud.list_pending_orphans(db):
            found = by_page.get(orphan.page_id)
            if found is None:
                by_page[orphan.page_id] = OrphanPageStatus(
                    page_id=orphan.page_id,
                    pending=1,
                    oldest_received_at=orphan.received_at,
                )
            else:
                found.pending += 1
                if orphan.received_at < found.oldest_received_at:
                    found.oldest_received_at = orphan.received_at

        pages = sorted(
            by_page.values(), key=lambda p: (-p.pending, p.oldest_received_at)
        )
        diagnostics = LeadsDiagnostics(
            # No se expone el token ni un hash suyo: sólo si sigue siendo el
            # valor de desarrollo, que es un fallo de despliegue accionable.
            webhook_configured=bool(settings.LEADS_SYNC_TOKEN)
            and settings.LEADS_SYNC_TOKEN != LEADS_SYNC_TOKEN_DEV_DEFAULT,
            orphans_pending=sum(p.pending for p in pages),
            orphan_pages=pages,
        )

    return LeadsModuleStatus(
        module_available=True,
        total_leads=total_leads,
        diagnostics=diagnostics,
    )


# ── Exportación a CSV ────────────────────────────────────────────
@router.get(
    "/export/csv",
    summary="Descarga en CSV los leads que hacen match con el filtro",
    response_class=Response,
)
@limiter.limit(LIMITS["leads_export_csv"])
def export_csv(
    request: Request,
    client_id: int | None = Query(None, description="Filtra por cliente."),
    status_filter: LeadStatus | None = Query(
        None, alias="status", description="Filtra por etapa del pipeline."
    ),
    search: str | None = Query(
        None, max_length=200, description="Busca dentro de los datos del formulario."
    ),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """El mismo filtro que el listado, pero sin paginar y como archivo.

    `Content-Disposition` es obligatorio: sin él el navegador pinta el CSV
    como texto en una pestaña en vez de descargarlo, y el nombre del archivo
    se pierde. El front está en otro origen (Vercel) y el API en otro
    (Railway), así que ese header además tiene que estar en `expose_headers`
    del CORS — ya lo está en `app/main.py`, puesto ahí para la descarga del
    PDF de reportes; este endpoint se apoya en el mismo.

    El nombre lo arma `build_export_filename`, que convierte el nombre del
    cliente a slug alfanumérico: por construcción no puede meter una comilla
    ni un salto de línea en el header aunque alguien nombre a un cliente
    `x" ; drop`.

    Límite de tasa — 20/hora
    ------------------------
    Es la operación más cara del módulo: hasta `EXPORT_MAX_ROWS` filas traídas
    del CRUD, el CSV completo armado en memoria, y —si vino `search`— un scan
    de texto sobre la tabla ya filtrada por organización. El precedente de la
    casa para algo de este costo es `reports_generate` ("20/1 hour"), y se
    copia a propósito en vez de inventar un número nuevo: una descarga es un
    acto deliberado que una persona hace unas pocas veces al día, no algo que
    se repita al navegar.
    """
    client = _resolve_client_filter(db, current, client_id)

    leads = _collect_for_export(
        db, current, client_id=client_id, status_filter=status_filter, search=search
    )
    body = export_leads_csv(leads)
    filename = build_export_filename(client.name if client is not None else None)

    logger.info(
        "Exportación de leads a CSV: user=%s org=%s filas=%s archivo=%s",
        current.id,
        current.org_id,
        len(leads),
        filename,
    )
    return Response(
        content=body,
        # El charset va explícito aunque el cuerpo ya lleve BOM: un cliente
        # HTTP que no sea Excel (el front, un curl) lee el header, no el BOM.
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Reconciliación de huérfanos ──────────────────────────────────
@router.post(
    "/orphans/{page_id}/reconcile",
    response_model=OrphanReconcileResponse,
    summary="Convierte en leads los huérfanos de una página ya configurada",
)
@limiter.limit(LIMITS["leads_reconcile"])
def reconcile_page_orphans(
    request: Request,
    page_id: str = Path(min_length=1, max_length=64),
    current: User = Depends(require_roles(UserRole.owner, UserRole.admin)),
    db: Session = Depends(get_db),
) -> OrphanReconcileResponse:
    """Rescata los leads que llegaron antes de que la página estuviera dada de alta.

    Restringido a `owner`/`admin`: escribe leads nuevos en la bandeja de la
    organización y es la contraparte del diagnóstico de `/leads/status`, que
    tampoco ve un `member`.

    La página tiene que ser de la organización de quien llama
    --------------------------------------------------------
    `reconcile_orphans` sigue siendo autónomo (se puede llamar desde un shell
    o un job) y por eso no sabe de usuarios, pero ya no le basta el `page_id`:
    exige el `org_id` esperado y rechaza la página que sea de otro tenant.
    Este endpoint es quien traduce "quien llama" a ese `org_id` — es donde por
    primera vez hay un usuario del cual sacarlo.

    Este router NO repite la comprobación de propiedad. La hacía antes, cuando
    era el único sitio donde existía; ahora sería una segunda copia de la
    misma query y la misma comparación, imposible de saltarse por un lado e
    imposible de recordar actualizar por el otro. La regla vive en la capa de
    servicio, que es la que ningún llamador futuro puede esquivar.

    Una página que no existe y una que es de otra organización responden lo
    mismo, 404: confirmar "esa página existe pero no es tuya" ya es contar
    algo de la otra organización. Por eso `UnknownPageError` y
    `PageOwnershipError` se mapean al mismo detalle; quién fue queda en el log.

    Idempotente: volver a llamarlo no duplica nada (los ya convertidos dejaron
    de estar pendientes) y devuelve `recovered=0`.

    Límite de tasa — 20/hora
    ------------------------
    Cada llamada puede convertir N huérfanos, y cada conversión es un INSERT
    de lead + otro de bitácora en su propia transacción; el costo lo decide el
    tamaño de la cola, no quien llama. Es además una acción de configuración
    que ocurre cuando se da de alta una página —unas pocas veces al mes—, así
    que el mismo balde que la exportación sobra. Ya está acotado por rol, de
    modo que el límite es un tope de daño, no la defensa principal.
    """
    try:
        recovered = reconcile_orphans(db, page_id, org_id=current.org_id)
    except (UnknownPageError, PageOwnershipError) as exc:
        # Página inexistente o de otra organización: hacia afuera, el mismo
        # 404. El log sí distingue — es el único lugar donde puede hacerlo sin
        # filtrarle al llamante la existencia de la página ajena.
        logger.warning(
            "Reconciliación rechazada: page_id=%s user=%s org_id=%s motivo=%s",
            page_id,
            current.id,
            current.org_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, _PAGE_NOT_FOUND_DETAIL
        ) from None
    except Exception:
        logger.exception(
            "Fallo inesperado reconciliando huérfanos. page_id=%s user=%s",
            page_id,
            current.id,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, _RECONCILE_FAILED_DETAIL
        ) from None

    still_pending = len(crud.list_pending_orphans(db, page_id))
    logger.info(
        "Reconciliación de huérfanos por API: page_id=%s user=%s recuperados=%s "
        "pendientes=%s",
        page_id,
        current.id,
        recovered,
        still_pending,
    )
    return OrphanReconcileResponse(
        page_id=page_id, recovered=recovered, still_pending=still_pending
    )


# ── Detalle ──────────────────────────────────────────────────────
# Cualquier ruta GET de un solo segmento que se agregue DESPUÉS de esta
# quedará inalcanzable: la captura este `{lead_id}`.
@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Un lead con su bitácora completa",
)
@limiter.limit(LIMITS["leads_detail"])
def get_lead_detail(
    request: Request,
    lead_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """El lead más su bitácora, o 404.

    404 —y no 403— para un lead que existe pero no es visible: un 403 le
    confirmaría a quien prueba ids que ese lead existe en alguna organización.
    `crud.get_lead_for_user` devuelve `None` tanto para "no existe" como para
    "es de otro tenant" y para "eres `member` y no es tuyo", así que los tres
    casos salen idénticos desde afuera.

    OJO — el PATCH no usa este mismo criterio: ahí un `member` que intenta
    editar un lead de su propia organización SÍ recibe 403. Ver
    `update_lead_detail`.

    Límite de tasa — 240/minuto
    ---------------------------
    Es la lectura más barata del módulo (una fila por llave primaria más su
    bitácora por índice) y la más repetida: un tablero Kanban abre una tarjeta
    tras otra. 4 por segundo por IP no lo alcanza ni un usuario impaciente y
    sigue siendo un techo.
    """
    lead = crud.get_lead_for_user(db, lead_id, current)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _LEAD_NOT_FOUND_DETAIL)
    return _detail_response(db, lead)


# ── Actualización ────────────────────────────────────────────────
@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Cambia estado, responsable o notas de un lead",
)
@limiter.limit(LIMITS["leads_update"])
def update_lead_detail(
    request: Request,
    lead_id: int,
    payload: LeadUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Aplica sólo los campos que el cliente mandó de verdad y audita el cambio.

    "No lo mandaron" vs. "lo mandaron en null"
    ------------------------------------------
    `payload.model_dump(exclude_unset=True)` — no `if x is not None`. Con
    `exclude_unset`, una clave ausente sencillamente no está en el dict y no
    se toca; una clave con `null` sí está, y por eso desasignar un lead
    (`{"assigned_to_id": null}`) o vaciar sus notas son operaciones posibles.
    Ver el docstring de `LeadUpdate` en app/schemas/leads.py, que documenta
    esta idea y por qué el schema no la resuelve con un tipo centinela.

    Por qué se busca el lead con `crud.get_lead` y no con `get_lead_for_user`
    ------------------------------------------------------------------------
    `get_lead_for_user` aplica el RBAC de LECTURA, que devolvería `None` —o
    sea 404— cuando un `member` intenta editar un lead de un compañero. Pero
    ese lead sí existe y sí es de su organización: la respuesta correcta es
    403 "no puedes", no 404 "no existe". Así que aquí se acota sólo por
    organización (`crud.get_lead`, que filtra por `org_id`) y el RBAC de
    ESCRITURA lo aplica `apply_lead_update` levantando `LeadPermissionError`.
    El resultado son los dos códigos que corresponden: 404 para otro tenant
    (donde sí hay que negar la existencia) y 403 dentro del propio.

    Códigos
    -------
    * 200 — aplicado. Un PATCH que repite los valores actuales también es 200,
      pero no escribe bitácora ni mueve `updated_at` (lo decide el servicio).
    * 400 — el cambio no es aplicable: campo no actualizable, o un responsable
      que no existe o es de otra organización.
    * 403 — `member` intentando editar un lead que no tiene asignado.
    * 404 — el lead no existe o es de otra organización.

    Asignar a alguien de otra organización
    --------------------------------------
    Lo impide `_resolve_new_assignee` en la capa de servicio, que exige que el
    usuario nuevo exista y comparta `org_id` con el lead. No se repite el
    chequeo aquí: duplicarlo daría dos lugares donde puede quedar
    desactualizado. Sale como 400.

    Límite de tasa — 60/minuto
    --------------------------
    Escribe: un UPDATE más una fila de bitácora por cada campo que cambió de
    verdad. Un humano arrastrando tarjetas en un Kanban hace unas pocas por
    minuto; 1 por segundo sostenido le queda holgado y le pone techo a llenar
    la bitácora de un lead con miles de entradas, que es la forma barata de
    volver ilegible la evidencia de quién tocó qué.
    """
    lead = crud.get_lead(db, lead_id, current.org_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _LEAD_NOT_FOUND_DETAIL)

    changes = payload.model_dump(exclude_unset=True)

    try:
        apply_lead_update(db, lead, changes, current)
    except LeadPermissionError:
        # El motivo real (rol, a quién estaba asignado) va al log; a quien
        # llama sólo "no puedes", sin describirle el estado del lead ajeno.
        logger.warning(
            "PATCH de lead denegado por RBAC. lead=%s user=%s",
            lead_id,
            current.id,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, _FORBIDDEN_DETAIL) from None
    except LeadValidationError as exc:
        # Este mensaje SÍ se devuelve: lo escribió la capa de servicio para un
        # humano, habla del propio dato que mandó quien llama y no dice nada
        # del interior del servidor. Además es deliberadamente ambiguo ("no
        # existe o no pertenece a esta organización"), así que no sirve para
        # averiguar si un id de usuario existe en otro tenant.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except Exception:
        logger.exception(
            "Fallo inesperado actualizando un lead. lead=%s user=%s",
            lead_id,
            current.id,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, _UPDATE_FAILED_DETAIL
        ) from None

    return _detail_response(db, lead)
