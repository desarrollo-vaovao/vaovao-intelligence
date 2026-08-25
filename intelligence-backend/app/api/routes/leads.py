"""
Módulo de Leads — superficie HTTP.

Hoy expone un solo endpoint, `POST /leads/sync-webhook`: la puerta por la
que entran los leads que reenvía el servicio externo `leads_traker` (que a
su vez recibe los webhooks de Meta LeadGen).

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

Los endpoints del CRM (listar, detalle, PATCH, exportar CSV) son de otra
tarea y entran en este mismo `router`: heredan sin más trabajo el saneo de
errores de validación de `_LeadsRoute`. La autenticación NO se hereda —
esos endpoints usan `Depends(get_current_user)` como el resto del API; el
token compartido es exclusivo del webhook.
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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import LIMITS, limiter
from app.schemas.leads import LeadSyncPayload, SyncWebhookResponse
from app.services.leads_service import IngestOutcome, IngestResult, ingest_lead

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
