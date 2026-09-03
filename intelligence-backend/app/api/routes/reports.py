"""
Módulo de Reportes — MOTOR ACTIVO.

Genera el reporte de campañas de Meta en PDF de UN activo comercial (una
cuenta publicitaria). Nunca de varios a la vez: los activos de un mismo
cliente pueden ser marcas sin relación entre sí. La generación corre en
segundo plano (puede tardar bastante con muchas campañas/anuncios): el
endpoint de "generate" solo valida y arranca el trabajo, el frontend
consulta el estado por job_id y descarga el PDF cuando está listo.
Usa, en orden de preferencia:
  1. El Facebook conectado del usuario ("por usuario", recomendado)
  2. Los tokens centrales de la organización (uno por portafolio comercial)

Endpoints:
- GET  /reports/status              → si hay conexión con Meta y si la generación está lista
- POST /reports/generate            → valida y arranca la generación, devuelve job_id
- GET  /reports/jobs/{job_id}       → estado del job (processing/done/error)
- GET  /reports/jobs/{job_id}/pdf   → descarga el PDF una vez que el job está "done"
- POST /reports/check-access        → verifica en vivo si podemos leer una cuenta
"""
import asyncio
import logging
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db, SessionLocal
from app.models import (
    User, Organization, Client, AdAccount, FacebookConnection, MetaCentralToken,
    ReportCampaignsCache, ReportSummaryCache,
)

log = logging.getLogger(__name__)
from app.schemas import (
    ReportStatus,
    ReportRequest,
    CheckAccessRequest,
    CheckAccessResult,
    ReportJobCreated,
    ReportJobStatus,
    ATTRIBUTION_WINDOWS,
)
from app.services import meta_api, pdf_generator, report_builder
from app.services.meta_tokens import resolve_tokens

router = APIRouter(prefix="/reports", tags=["reports"])

# El motor de generación (Meta + PDF) ya está conectado.
GENERATION_AVAILABLE = True

# Cada cuánto se vuelve a pedir a Meta la lista de países targeteados por
# una cuenta (ver GET /reports/countries y ad_accounts.cached_countries,
# migración 0006). El targeting de una cuenta cambia con muy poca
# frecuencia comparado con el gasto — no hace falta ir a Meta cada vez
# que alguien abre el selector de país en Reportes.
_COUNTRIES_CACHE_TTL = timedelta(hours=int(os.getenv("REPORT_COUNTRIES_CACHE_HOURS", "24")))

# Cada cuánto se vuelve a pedir a Meta la lista de campañas con datos en un
# período que TODAVÍA incluye hoy (ver GET /reports/campaigns y
# ReportCampaignsCache, migración 0007). Un período ya cerrado (date_to en
# el pasado) no necesita TTL: Meta no reescribe el historial, así que esa
# fila se sirve para siempre.
_CAMPAIGNS_CACHE_TTL = timedelta(hours=float(os.getenv("REPORT_CAMPAIGNS_CACHE_HOURS", "1")))

# Cada cuánto se refresca en segundo plano el panel de Resumen (ver
# ReportSummaryCache, migración 0008). A diferencia de países y campañas,
# el gasto de un período que incluye hoy sigue cambiando en vivo, así que
# esto SIEMPRE se refresca — nunca se sirve "para siempre".
_SUMMARY_CACHE_TTL = timedelta(minutes=float(os.getenv("REPORT_SUMMARY_CACHE_MINUTES", "5")))

# Evita que dos peticiones que llegan casi juntas con la misma caché vencida
# disparen DOS refrescos en segundo plano para la misma llave — el primero
# que entra gana, el resto simplemente sigue sirviendo la caché tal cual.
_summary_refresh_in_flight: set[tuple] = set()

# ── Jobs de generación en segundo plano ─────────────────────────
# En memoria del proceso: alcanza para el tamaño de este equipo (un solo
# servicio de Railway, sin múltiples workers). Si el proceso se reinicia
# a mitad de un job, ese reporte se pierde y hay que regenerarlo — es un
# costo aceptable frente a montar una cola real (Redis/Celery) para esto.
_JOBS: dict[str, dict] = {}
_JOB_TTL_SECONDS = 30 * 60

# Cuántos reportes completos (traer datos de Meta + armar el PDF) corren a
# la vez como máximo. Sin este límite, si 50-100 personas generan reportes
# al mismo tiempo se dispararían cientos de llamadas simultáneas a la Graph
# API (riesgo de rate limit de Meta) además de saturar memoria/CPU. Los
# jobs de más simplemente esperan su turno en "processing" — no fallan.
_GENERATION_CONCURRENCY = 6
_generation_semaphore = asyncio.Semaphore(_GENERATION_CONCURRENCY)


def _cleanup_jobs() -> None:
    cutoff = time.monotonic() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _JOBS.items() if j["created_at"] < cutoff]
    for jid in stale:
        _JOBS.pop(jid, None)


async def _run_report_job(
    job_id: str, account: AdAccount, tokens: list[str],
    date_from, date_to, budget, currency: str, country_code: str | None = None,
    source_currency: str = "USD", exchange_rate: float | None = None,
    attribution_window: str | None = None,
    campaign_metrics: dict[str, list[str]] | None = None,
    campaign_comments: dict[str, str] | None = None,
    general_comment: str | None = None,
) -> None:
    try:
        async with _generation_semaphore:
            pdf_bytes, filename = await report_builder.build_pdf(
                account, tokens, date_from, date_to, budget, currency, country_code,
                source_currency, exchange_rate, attribution_window,
                campaign_metrics, campaign_comments, general_comment,
            )
        _JOBS[job_id].update(status="done", pdf=pdf_bytes, filename=filename)
    except ValueError as e:
        _JOBS[job_id].update(status="error", error=str(e))
    except meta_api.MetaApiError as e:
        _JOBS[job_id].update(status="error", error=f"Meta: {e}")
    except Exception as e:
        # Cualquier error que NO sea de validación ni de Meta (ej. algo real
        # de Playwright/Chromium, o un bug en el armado del PDF). El detalle
        # completo va a los logs del servidor; al usuario solo un mensaje
        # genérico, para no asumir una causa que puede no ser la real.
        print(f"[reports] Error generando el PDF (job {job_id}): {type(e).__name__}: {e}")
        _JOBS[job_id].update(status="error", error=(
            "Ocurrió un error inesperado generando el reporte. Intenta de nuevo; "
            "si persiste, revisa los logs del servidor."
        ))


# ── Helpers ──────────────────────────────────────────────────
def _get_owned_account(account_id: int, current: User, db: Session) -> AdAccount:
    """Trae un activo comercial SOLO si pertenece a la organización del usuario."""
    account = db.scalar(
        select(AdAccount)
        .join(Client, AdAccount.client_id == Client.id)
        .where(AdAccount.id == account_id, Client.org_id == current.org_id)
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo comercial no encontrado")
    return account


async def _resolve_currency_context(
    account: AdAccount, tokens: list[str], current: User, db: Session
) -> tuple[str, float | None, str | None]:
    """
    (moneda_de_origen, tipo_de_cambio_de_la_organizacion, ventana_de_atribucion)
    para convertir el reporte de esta cuenta. Si `account.native_currency`
    todavia no se conoce (cuenta creada antes de este campo, o la consulta a
    Meta falló en su momento), se intenta una vez aquí y se persiste para la
    próxima — así el costo de la consulta a Meta se paga una sola vez por
    cuenta, no en cada reporte. Si vuelve a fallar, se asume "USD" (lo más
    común) en vez de bloquear el reporte por esto.
    """
    if account.native_currency is None:
        currency = await meta_api.get_account_currency_with_fallback(
            tokens, account.meta_ad_account_id
        )
        if currency:
            account.native_currency = currency
            db.commit()

    org = db.get(Organization, current.org_id)
    return (
        account.native_currency or "USD",
        org.exchange_rate_usd_gtq if org else None,
        org.attribution_window if org else None,
    )


def _meta_connected(org: Organization, db: Session) -> bool:
    """Hay al menos un token central de la organización guardado."""
    if not org:
        return False
    return db.scalar(
        select(MetaCentralToken.id).where(MetaCentralToken.org_id == org.id)
    ) is not None


# ── Endpoints ────────────────────────────────────────────────
@router.get("/status", response_model=ReportStatus)
def report_status(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estado del módulo: si hay conexión con Meta y si la generación está disponible."""
    org = db.get(Organization, current.org_id)

    has_fb = db.scalar(
        select(FacebookConnection.id).where(FacebookConnection.user_id == current.id)
    ) is not None
    connected = _meta_connected(org, db) or has_fb

    return ReportStatus(
        meta_connected=connected,
        generation_available=connected and GENERATION_AVAILABLE,
    )


@router.post("/generate", response_model=ReportJobCreated, status_code=202)
async def generate_report(
    data: ReportRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Valida todo lo que se puede validar rápido (activo comercial, fechas,
    tokens) y arranca la generación del PDF en segundo plano. Devuelve un
    job_id para consultar el progreso en GET /reports/jobs/{job_id}.
    """
    _cleanup_jobs()

    # El activo comercial debe ser de la organización del usuario
    account = _get_owned_account(data.ad_account_id, current, db)

    if data.date_from > data.date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de inicio no puede ser posterior a la de fin.",
        )

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    if not GENERATION_AVAILABLE:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "El motor de generación aún no está activo.",
        )

    source_currency, exchange_rate, attribution_window = await _resolve_currency_context(
        account, tokens, current, db
    )

    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "org_id": current.org_id,
        "status": "processing",
        "pdf": None,
        "filename": None,
        "error": None,
        "created_at": time.monotonic(),
    }
    asyncio.create_task(_run_report_job(
        job_id, account, tokens, data.date_from, data.date_to, data.budget, data.currency.value,
        data.country_code, source_currency, exchange_rate, attribution_window,
        data.campaign_metrics, data.campaign_comments, data.general_comment,
    ))
    return ReportJobCreated(job_id=job_id)


def _get_owned_job(job_id: str, current: User) -> dict:
    job = _JOBS.get(job_id)
    if not job or job["org_id"] != current.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job no encontrado")
    return job


@router.get("/jobs/{job_id}", response_model=ReportJobStatus)
def get_report_job(job_id: str, current: User = Depends(get_current_user)):
    job = _get_owned_job(job_id, current)
    return ReportJobStatus(
        job_id=job_id, status=job["status"], error=job["error"], filename=job["filename"],
    )


@router.get("/jobs/{job_id}/pdf")
def download_report_job(job_id: str, current: User = Depends(get_current_user)):
    job = _get_owned_job(job_id, current)
    if job["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "El reporte todavía no está listo.")
    return Response(
        content=job["pdf"],
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{job["filename"]}"'},
    )


def _summary_cache_query(account_id: int, date_from: date, date_to: date, currency: str, country_key: str):
    return select(ReportSummaryCache).where(
        ReportSummaryCache.account_id == account_id,
        ReportSummaryCache.date_from == date_from,
        ReportSummaryCache.date_to == date_to,
        ReportSummaryCache.currency == currency,
        ReportSummaryCache.country_code == country_key,
    )


def _apply_summary_overrides(payload: dict, data: ReportRequest) -> dict:
    """
    Encima de lo que haya en report_summary_cache (o de una respuesta recién
    salida de Meta) se sobreponen SIEMPRE el presupuesto y la personalización
    por campaña de ESTA petición puntual — ninguno de los dos es un dato de
    Meta, así que nunca se guardan en la caché: si se guardaran, la
    personalización de la primera persona que pidió este resumen se le
    quedaría pegada a todos los que lo pidan después, hasta el próximo
    refresco.
    """
    result = dict(payload)
    result["budget"] = data.budget
    if data.campaign_metrics or data.campaign_comments:
        result["campaigns"] = report_builder._apply_customization(
            result["campaigns"], data.campaign_metrics, data.campaign_comments,
        )
    if data.general_comment:
        result["general_comment"] = data.general_comment
    return result


def _save_summary_cache(db: Session, account_id: int, date_from: date, date_to: date,
                         currency: str, country_key: str, payload: dict) -> None:
    row = db.execute(_summary_cache_query(account_id, date_from, date_to, currency, country_key)).scalar_one_or_none()
    if row is None:
        row = ReportSummaryCache(
            account_id=account_id, date_from=date_from, date_to=date_to,
            currency=currency, country_code=country_key,
        )
        db.add(row)
    row.payload = payload
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


async def _refresh_summary_cache_background(
    account_id: int, user_id: int, date_from: date, date_to: date, currency: str, country_key: str,
) -> None:
    """
    Repite, en segundo plano, la misma consulta a Meta que ya sirvió esta
    respuesta desde la caché — para que la PRÓXIMA visita a Resumen ya
    encuentre el dato al día. Quien pidió el resumen esta vez ya recibió su
    respuesta (la de la caché); esto no lo bloquea.

    Corre después de que la petición HTTP ya terminó, así que no puede
    reusar la sesión de esa petición (FastAPI ya la cerró) — abre la suya
    propia y la cierra al terminar.
    """
    key = (account_id, date_from, date_to, currency, country_key)
    if key in _summary_refresh_in_flight:
        return
    _summary_refresh_in_flight.add(key)
    db = SessionLocal()
    try:
        try:
            account = db.get(AdAccount, account_id)
            current = db.get(User, user_id)
            if account is None or current is None:
                return
            tokens, error = resolve_tokens(current, db)
            if not tokens:
                return
            org = db.get(Organization, current.org_id)
            source_currency = account.native_currency or "USD"
            exchange_rate = org.exchange_rate_usd_gtq if org else None
            attribution_window = org.attribution_window if org else None
            db.close()

            payload = await report_builder.build_report_data(
                account, tokens, date_from, date_to, None, currency, country_key or None,
                source_currency, exchange_rate, attribution_window,
                include_inactive=True,
            )
            _save_summary_cache(db, account_id, date_from, date_to, currency, country_key, payload)
        except meta_api.MetaApiError as e:
            log.warning(
                "No se pudo refrescar en segundo plano el resumen de la cuenta %s (%s a %s): %s",
                account_id, date_from, date_to, e,
            )
        except Exception:
            # Un refresco en segundo plano que falla no debe tumbar nada ni
            # llenar los logs de un traceback ruidoso — quien pidió el
            # resumen ya recibió su respuesta desde la caché; esto solo
            # afecta si la PRÓXIMA visita ve datos más o menos frescos.
            log.exception(
                "Fallo inesperado refrescando en segundo plano el resumen de la cuenta %s (%s a %s)",
                account_id, date_from, date_to,
            )
    finally:
        db.close()
        _summary_refresh_in_flight.discard(key)


@router.post("/summary")
async def report_summary(
    data: ReportRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Igual que /generate pero sin PDF: devuelve el mismo dict que arma el
    reporte (gasto, presupuesto, campañas) en JSON, para el panel de Resumen.

    Se guarda en report_summary_cache (migración 0008) por (cuenta, rango de
    fechas, moneda, país) y SIEMPRE se sirve desde ahí cuando existe — nadie
    espera nunca a Meta para ver el Resumen. Si la fila tiene más de
    _SUMMARY_CACHE_TTL, además se dispara una actualización en segundo plano
    para la próxima visita (ver _refresh_summary_cache_background). Un
    período que YA CERRÓ (date_to en el pasado) no vuelve a refrescarse
    nunca, igual que países y campañas: solo un período que todavía incluye
    hoy sigue cambiando en vivo y necesita ese refresco periódico.
    El presupuesto y la personalización por campaña (metrics/comments) se
    aplican encima de lo cacheado en cada lectura, porque no afectan el
    gasto en sí y deben reflejar siempre lo que la persona tiene en pantalla.

    Este endpoint nunca llegó a funcionar antes de que existiera: quedó
    escrito contra el modelo viejo (reporte por Client) de antes del
    refactor a "activo comercial" que ya usa /generate, y arrastraba tres
    bugs encadenados que un 422 genérico en el frontend escondía por
    completo:
      1. ReportRequest.ad_account_id es el campo real del schema; esta
         ruta leía data.client_id, que no existe ahí — Pydantic rechazaba
         la petición ANTES de que el código de abajo corriera.
      2. Aunque hubiera llegado a correr, pasaba un Client (con muchas
         cuentas posibles) a build_report_data(), que espera UN AdAccount
         — client.meta_ad_account_id no existe, hubiera reventado con
         AttributeError.
      3. Llamaba a _resolve_tokens (con guion bajo), que nunca existió;
         solo está importado resolve_tokens (sin guion) de meta_tokens.
    """
    account = _get_owned_account(data.ad_account_id, current, db)

    if data.date_from > data.date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de inicio no puede ser posterior a la de fin.",
        )

    currency_value = data.currency.value
    country_key = data.country_code or ""
    cached = db.execute(
        _summary_cache_query(account.id, data.date_from, data.date_to, currency_value, country_key)
    ).scalar_one_or_none()

    if cached is not None:
        updated_at = cached.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        result = _apply_summary_overrides(cached.payload, data)

        # Un período ya cerrado (date_to en el pasado) no vuelve a cambiar
        # de gasto — igual que campañas y países, no tiene sentido seguir
        # refrescándolo cada _SUMMARY_CACHE_TTL para siempre. Sin esto, cada
        # pestaña de Resumen abierta (que además reconsulta sola cada 5 min,
        # ver resumen/page.jsx) seguía generando tráfico a Meta por meses ya
        # cerrados hace tiempo — contribuyó a un "User request limit
        # reached" real en producción.
        period_closed = data.date_to < date.today()
        if not period_closed and datetime.now(timezone.utc) - updated_at >= _SUMMARY_CACHE_TTL:
            asyncio.create_task(_refresh_summary_cache_background(
                account.id, current.id, data.date_from, data.date_to, currency_value, country_key,
            ))

        return result

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    source_currency, exchange_rate, attribution_window = await _resolve_currency_context(
        account, tokens, current, db
    )

    # De aquí en adelante ya no se toca la base de datos: se cierra la
    # conexión ANTES de la espera larga a Meta (puede tardar minutos en
    # cuentas grandes) en vez de dejarla ocupada del pool (5 + 10 de
    # overflow = 15 como máximo) durante todo ese tiempo. Sin esto, varias
    # personas generando reportes a la vez agotan el pool
    # ("QueuePool limit... connection timed out") mucho antes de que Meta
    # alcance a responder — confirmado con una prueba de carga real contra
    # producción (20 solicitudes concurrentes a un cliente pesado).
    db.close()

    try:
        raw_result = await report_builder.build_report_data(
            account, tokens, data.date_from, data.date_to, None,
            currency_value, data.country_code,
            source_currency, exchange_rate, attribution_window,
            include_inactive=True,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except meta_api.MetaApiError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Meta: {e}")

    _save_summary_cache(db, account.id, data.date_from, data.date_to, currency_value, country_key, raw_result)
    return _apply_summary_overrides(raw_result, data)


@router.post("/check-access", response_model=CheckAccessResult)
async def check_access(
    data: CheckAccessRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifica en vivo si podemos leer una cuenta publicitaria específica.
    Usa el Facebook del usuario si está conectado; si no, el token central.
    """
    account = _get_owned_account(data.account_id, current, db)

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        return CheckAccessResult(ok=False, detail=error)

    db.close()  # ver el comentario en /reports/summary

    ok, detail = await meta_api.check_account_access_with_fallback(tokens, account.meta_ad_account_id)
    return CheckAccessResult(ok=ok, detail=detail)


@router.get("/countries/{account_id}")
async def get_available_countries(
    account_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Devuelve la lista de países únicos en los que se han pautado anuncios
    para una cuenta publicitaria. Útil para mostrar un selector en el frontend.

    Se guarda en ad_accounts.cached_countries (migración 0006) y solo se
    vuelve a pedir a Meta si pasaron más de _COUNTRIES_CACHE_TTL desde la
    última vez — el targeting de una cuenta cambia con muy poca
    frecuencia, a diferencia del gasto. Cuando SÍ hace falta ir a Meta, se
    usa el último mes como rango de fechas.

    Solo necesita el targeting de los anuncios, nunca su performance — pide
    include_ad_insights=False (se salta el job asíncrono de insights por
    anuncio, el más lento de los dos que usa un reporte completo) e
    include_inactive=True (para que una campaña activa/pausada sin gasto
    en los últimos 30 días no le esconda sus países al selector).
    """
    account = _get_owned_account(account_id, current, db)

    # SQLite (dev local y tests) no conserva la zona horaria de un
    # DateTime(timezone=True) al releerlo: vuelve como naive. Siempre se
    # escribe en UTC, así que un valor naive se asume UTC.
    updated_at = account.cached_countries_updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if (
        account.cached_countries is not None
        and updated_at is not None
        and now - updated_at < _COUNTRIES_CACHE_TTL
    ):
        return {"countries": account.cached_countries}

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        # Ya había una lista guardada (aunque esté vencida): mejor mostrar
        # ESA que nada — el selector sigue siendo útil aunque no sea la
        # más reciente posible.
        if account.cached_countries is not None:
            return {"countries": account.cached_countries}
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    # Rango de fechas: últimos 30 días
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    org = db.get(Organization, current.org_id)
    attribution_windows = ATTRIBUTION_WINDOWS.get(org.attribution_window if org else None)

    # Ver el mismo comentario en /reports/summary: cerrar la conexión ANTES
    # de esperar a Meta, no después, para no agotar el pool de la base de
    # datos si muchas personas piden esto a la vez.
    db.close()

    try:
        data = await meta_api.get_account_data_with_fallback(
            tokens, account.meta_ad_account_id,
            thirty_days_ago.isoformat(), today.isoformat(),
            attribution_windows, include_inactive=True, include_ad_insights=False,
        )
    except meta_api.MetaApiError as e:
        if account.cached_countries is not None:
            return {"countries": account.cached_countries}
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Meta: {e}")

    countries = set()
    for campaign in data.get("campaigns", []):
        for ad in campaign.get("ads", []):
            countries.update(ad.get("countries", []))

    result = sorted(countries)
    db.execute(
        update(AdAccount)
        .where(AdAccount.id == account_id)
        .values(cached_countries=result, cached_countries_updated_at=datetime.now(timezone.utc))
    )
    db.commit()

    return {"countries": result}


@router.get("/campaigns/{account_id}")
async def get_report_campaigns(
    account_id: int,
    date_from: date,
    date_to: date,
    country_code: str | None = None,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Preview de las campañas del período: nombre, objetivo y el set de
    métricas que se mostraría automáticamente (`default_metrics`, claves de
    pdf_generator.METRIC_REGISTRY). Alimenta el panel "Personalizar métricas y
    observaciones" del formulario de Reportes.

    Se guarda en report_campaigns_cache (migración 0007) por combinación
    exacta de (cuenta, date_from, date_to, país): un período ya cerrado no
    vuelve a pedirse nunca (Meta no reescribe el historial), y uno que
    todavía incluye hoy se refresca cada _CAMPAIGNS_CACHE_TTL para que una
    campaña nueva no tarde en aparecer.

    Cuando SÍ hace falta ir a Meta: la respuesta es liviana (sin anuncios ni
    imágenes) y ya NO paga el costo completo de un reporte — pide
    include_ad_insights=False, así que se salta el job asíncrono de
    insights por anuncio (el más lento de los dos, y este panel nunca
    muestra performance por anuncio). Sigue corriendo el job de insights
    POR CAMPAÑA, porque sin eso no se sabría cuáles campañas tendrán datos
    reales en el reporte final de ESTE período.
    """
    account = _get_owned_account(account_id, current, db)

    if date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de inicio no puede ser posterior a la de fin.",
        )

    country_key = country_code or ""
    cached = db.execute(
        select(ReportCampaignsCache).where(
            ReportCampaignsCache.account_id == account_id,
            ReportCampaignsCache.date_from == date_from,
            ReportCampaignsCache.date_to == date_to,
            ReportCampaignsCache.country_code == country_key,
        )
    ).scalar_one_or_none()

    period_closed = date_to < date.today()
    if cached is not None:
        updated_at = cached.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if period_closed or datetime.now(timezone.utc) - updated_at < _CAMPAIGNS_CACHE_TTL:
            return {"campaigns": cached.campaigns}

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        if cached is not None:
            return {"campaigns": cached.campaigns}
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    org = db.get(Organization, current.org_id)
    attribution_windows = ATTRIBUTION_WINDOWS.get(org.attribution_window if org else None)

    # Ver el mismo comentario en /reports/summary.
    db.close()

    try:
        data = await meta_api.get_account_data_with_fallback(
            tokens, account.meta_ad_account_id,
            date_from.isoformat(), date_to.isoformat(),
            attribution_windows, include_ad_insights=False,
        )
    except meta_api.MetaApiError as e:
        if cached is not None:
            return {"campaigns": cached.campaigns}
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Meta: {e}")

    campaigns_data, _ = report_builder._filter_campaigns_by_country(data["campaigns"], country_code)

    result = [
        {
            "id": str(c["id"]),
            "name": c.get("name") or "",
            "objective": c.get("objective") or "DEFAULT",
            "default_metrics": pdf_generator.default_metric_keys(c.get("objective")),
        }
        for c in campaigns_data
    ]

    row = db.execute(
        select(ReportCampaignsCache).where(
            ReportCampaignsCache.account_id == account_id,
            ReportCampaignsCache.date_from == date_from,
            ReportCampaignsCache.date_to == date_to,
            ReportCampaignsCache.country_code == country_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ReportCampaignsCache(
            account_id=account_id, date_from=date_from, date_to=date_to, country_code=country_key,
        )
        db.add(row)
    row.campaigns = result
    row.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"campaigns": result}