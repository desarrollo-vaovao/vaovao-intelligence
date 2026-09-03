"""
Sincroniza en segundo plano el gasto DIARIO por campaña de cada activo
comercial, guardado en CampaignDailyMetric + SyncedCampaign (migración
0009).

Por qué existe
---------------
Antes, Resumen le pedía a Meta una consulta EN VIVO por cada combinación
nueva de (cuenta, rango de fechas): cambiar de mes, de quincena, o abrir
un período que nadie había visto antes disparaba una llamada nueva a
Meta. Con suficiente tráfico (varias personas, varios activos, más las
pruebas de carga) eso terminó en un "User request limit reached" real en
producción.

Este módulo le da la vuelta: en vez de reaccionar a lo que alguien pide
en pantalla, un bucle en segundo plano recorre TODAS las cuentas y trae
su gasto diario con una sola llamada por cuenta (ver
meta_api.get_daily_campaign_data, `time_increment=1`). Las fechas que
elige la persona en Resumen dejan de ser una petición a Meta y pasan a
ser solo un filtro SQL sobre lo que ya está guardado — ver
app/api/routes/reports.py (_summary_from_local_data).
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core import crypto
from app.core.database import SessionLocal
from app.models import AdAccount, CampaignDailyMetric, Client, MetaCentralToken, SyncedCampaign
from app.services import meta_api

log = logging.getLogger(__name__)

# La primera vez que se sincroniza una cuenta, cuántos días hacia atrás se
# traen. Alcanza de sobra para el mes o la quincena actual y comparaciones
# recientes — no hace falta el historial completo de la cuenta para lo que
# hoy usa Resumen.
BACKFILL_DAYS = 90

# Cada sincronización vuelve a traer los últimos días ya guardados, no solo
# los nuevos — Meta sigue afinando la atribución de conversiones unos días
# después de que ocurrieron, así que un día "cerrado" puede cambiar un poco.
OVERLAP_DAYS = 3

# Cada cuánto se vuelve a sincronizar una cuenta ya sincronizada.
SYNC_INTERVAL_SECONDS = int(os.getenv("DAILY_METRICS_SYNC_INTERVAL_MINUTES", "60")) * 60

# Pausa entre cuenta y cuenta dentro de una misma vuelta — para no
# ráfaguear a Meta con todas las cuentas a la vez (el mismo problema que ya
# causó un rate limit real).
ACCOUNT_GAP_SECONDS = 5


def _central_tokens(org_id: int, db) -> list[str]:
    """
    Solo tokens CENTRALES (de la organización) — un ciclo en segundo plano
    no tiene un "usuario actual" cuyo Facebook personal usar, a diferencia
    de resolve_tokens (ver meta_tokens.py). Una cuenta cuyo único acceso es
    el Facebook personal de alguien simplemente no se sincroniza sola: cae
    al camino viejo (consulta en vivo) la próxima vez que alguien la pida.
    """
    rows = db.scalars(select(MetaCentralToken).where(MetaCentralToken.org_id == org_id)).all()
    tokens = []
    for row in rows:
        token = crypto.decrypt(row.token_encrypted)
        if token:
            tokens.append(token)
    return tokens


async def sync_account(account_id: int) -> bool:
    """
    Sincroniza UNA cuenta. Devuelve True si logró traer datos frescos de
    Meta (aunque sea una lista vacía de campañas), False si no pudo
    (sin token, cuenta borrada, o Meta falló) — el llamador decide qué
    hacer con eso.
    """
    db = SessionLocal()
    try:
        account = db.get(AdAccount, account_id)
        if account is None:
            return False
        client = db.get(Client, account.client_id)
        tokens = _central_tokens(client.org_id, db) if client else []
        if not tokens:
            return False

        today = date.today()
        if account.daily_metrics_synced_until is None:
            since = today - timedelta(days=BACKFILL_DAYS)
        else:
            since = min(account.daily_metrics_synced_until - timedelta(days=OVERLAP_DAYS), today)
        meta_ad_account_id = account.meta_ad_account_id
    finally:
        db.close()

    try:
        data = await meta_api.get_daily_campaign_data_with_fallback(
            tokens, meta_ad_account_id, since.isoformat(), today.isoformat(),
        )
    except meta_api.MetaApiError as e:
        log.warning("No se pudo sincronizar el gasto diario de la cuenta %s: %s", account_id, e)
        return False

    campaign_meta = {str(c["id"]): c for c in data["campaigns"]}
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        for cid, info in campaign_meta.items():
            row = db.execute(select(SyncedCampaign).where(
                SyncedCampaign.account_id == account_id,
                SyncedCampaign.campaign_id == cid,
            )).scalar_one_or_none()
            if row is None:
                row = SyncedCampaign(account_id=account_id, campaign_id=cid)
                db.add(row)
            row.name = info.get("name") or ""
            row.objective = info.get("objective") or "DEFAULT"
            row.status = info.get("status") or "ACTIVE"
            row.updated_at = now

        for entry in data["daily"]:
            cid = entry["campaign_id"]
            day = date.fromisoformat(entry["date"])
            row = db.execute(select(CampaignDailyMetric).where(
                CampaignDailyMetric.account_id == account_id,
                CampaignDailyMetric.campaign_id == cid,
                CampaignDailyMetric.date == day,
            )).scalar_one_or_none()
            if row is None:
                row = CampaignDailyMetric(account_id=account_id, campaign_id=cid, date=day)
                db.add(row)
            row.spend = entry["spend"]
            row.impressions = entry["impressions"]
            row.reach = entry["reach"]
            row.clicks = entry["clicks"]
            row.updated_at = now

        acc = db.get(AdAccount, account_id)
        if acc is not None:
            acc.daily_metrics_synced_until = today
        db.commit()
    finally:
        db.close()

    return True


async def _sync_account_safely(account_id: int) -> None:
    try:
        await sync_account(account_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Una cuenta que falla no debe tumbar el ciclo completo — las demás
        # siguen sincronizándose normalmente.
        log.exception("Fallo inesperado sincronizando el gasto diario de la cuenta %s", account_id)


async def run_forever() -> None:
    """
    Bucle en segundo plano: recorre todas las cuentas, una a la vez con una
    pausa entre cada una, y al terminar la vuelta espera
    SYNC_INTERVAL_SECONDS antes de volver a empezar. Arranca desde el
    lifespan de main.py, igual que las demás precargas de arranque —
    corre mientras el servicio esté vivo y se cancela al apagar.
    """
    while True:
        db = SessionLocal()
        try:
            account_ids = [row[0] for row in db.execute(select(AdAccount.id)).all()]
        finally:
            db.close()

        for account_id in account_ids:
            await _sync_account_safely(account_id)
            await asyncio.sleep(ACCOUNT_GAP_SECONDS)

        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
