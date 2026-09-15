"""
Historial de reportes: un PDF generado se puede volver a descargar.

QUÉ SE CUBRE Y POR QUÉ
Antes de la migración 0012 un reporte terminado vivía en un diccionario en
memoria del proceso (`_JOBS` en routes/reports.py) con 30 minutos de vida.
Eso tenía dos costos reales:

  1. Un despliegue o un reinicio a media mañana borraba TODOS los PDF ya
     generados. La única salida era regenerarlos, que es la parte cara:
     traer todo de Meta y volver a renderizar en Chromium.
  2. Pedir de nuevo el mismo reporte de ayer pagaba ese costo completo otra
     vez, aunque el archivo idéntico hubiera existido minutos antes.

Las pruebas de aquí fijan el comportamiento que reemplaza eso: la
generación queda guardada, se puede volver a descargar sin regenerar, y el
historial respeta el aislamiento entre organizaciones igual que todo lo
demás de la plataforma.

Lo que NO se cubre a propósito: deduplicar dos generaciones con los mismos
parámetros. El presupuesto y las observaciones por campaña son de cada
quien y no viajan en la llave — devolver el PDF de otra persona porque
"coincide el período" le entregaría sus comentarios a alguien más. Es el
mismo criterio que ya aplica ReportSummaryCache al dejarlos fuera de su
llave (ver _apply_summary_overrides).
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes import reports as reports_routes
from app.models import GeneratedReport
from app.services import report_builder


@pytest.fixture()
def sin_tokens_reales(monkeypatch):
    """Ni resolver tokens ni llamar a Meta: estas pruebas son del historial."""
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))


@pytest.fixture()
def pdf_falso(monkeypatch):
    """build_pdf devuelve un PDF mínimo sin tocar Meta ni Chromium."""
    async def fake_build_pdf(account, tokens, date_from, date_to, budget, currency,
                             country_code=None, source_currency="USD", exchange_rate=None,
                             attribution_window=None, campaign_metrics=None,
                             campaign_comments=None, general_comment=None):
        return (b"%PDF-1.4 contenido de prueba%", "reporte-de-prueba.pdf")

    monkeypatch.setattr(report_builder, "build_pdf", fake_build_pdf)


def _generar_y_esperar(client, account_id, **extra) -> str:
    """Arranca una generación y espera a que el job deje de estar 'processing'."""
    payload = {
        "ad_account_id": account_id,
        "date_from": "2026-01-01",
        "date_to": "2026-01-15",
        "currency": "USD",
        **extra,
    }
    r = client.post("/reports/generate", json=payload)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    for _ in range(50):
        body = client.get(f"/reports/jobs/{job_id}").json()
        if body["status"] != "processing":
            break
        time.sleep(0.05)
    assert body["status"] == "done", body
    return job_id


# ── El reporte sobrevive y se puede volver a descargar ───────────
def test_un_reporte_generado_se_puede_descargar_dos_veces(
    client, login, tenant_a, factory, db, monkeypatch, sin_tokens_reales, pdf_falso
):
    """
    La segunda descarga NO vuelve a generar: sale de la fila guardada.

    Es la razón de ser de todo esto — antes el PDF vivía en memoria y la
    segunda descarga después de un reinicio (o de 30 minutos) obligaba a
    rehacer el trabajo completo contra Meta.
    """
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)

    job_id = _generar_y_esperar(client, account.id)

    primera = client.get(f"/reports/jobs/{job_id}/pdf")
    assert primera.status_code == 200
    assert primera.content == b"%PDF-1.4 contenido de prueba%"

    # Si build_pdf se volviera a llamar aquí, este monkeypatch lo delataría:
    # se reemplaza por uno que falla. La descarga debe salir de la base.
    async def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("La segunda descarga regeneró el reporte.")

    monkeypatch.setattr(report_builder, "build_pdf", no_debe_llamarse)

    segunda = client.get(f"/reports/jobs/{job_id}/pdf")
    assert segunda.status_code == 200
    assert segunda.content == primera.content


def test_el_job_sobrevive_a_perder_la_memoria_del_proceso(
    client, login, tenant_a, factory, db, sin_tokens_reales, pdf_falso
):
    """
    El estado del job sale de la base, no de una variable del proceso.

    Antes bastaba un reinicio para que GET /reports/jobs/{job_id}
    respondiera 404 sobre un reporte que sí se había generado. Como aquí no
    se puede reiniciar el proceso, se comprueba lo equivalente: la fila está
    en la base con sus bytes, que es lo único que un reinicio conserva.
    """
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)

    job_id = _generar_y_esperar(client, account.id)

    fila = db.query(GeneratedReport).filter_by(job_id=job_id).one()
    assert fila.status == "done"
    assert fila.pdf == b"%PDF-1.4 contenido de prueba%"
    assert fila.size_bytes == len(b"%PDF-1.4 contenido de prueba%")
    assert fila.completed_at is not None


def test_la_descarga_cuenta_cuantas_veces_se_bajo(
    client, login, tenant_a, factory, db, sin_tokens_reales, pdf_falso
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    job_id = _generar_y_esperar(client, account.id)

    for _ in range(3):
        assert client.get(f"/reports/jobs/{job_id}/pdf").status_code == 200

    db.expire_all()
    assert db.query(GeneratedReport).filter_by(job_id=job_id).one().download_count == 3


# ── El historial ─────────────────────────────────────────────────
def test_el_historial_lista_los_reportes_del_activo_del_mas_nuevo_al_mas_viejo(
    client, login, tenant_a, factory, db, sin_tokens_reales, pdf_falso
):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)

    primero = _generar_y_esperar(client, account.id)
    segundo = _generar_y_esperar(client, account.id, date_from="2026-02-01", date_to="2026-02-15")

    r = client.get(f"/reports/history/{account.id}")
    assert r.status_code == 200
    historial = r.json()

    assert [h["job_id"] for h in historial] == [segundo, primero]
    assert all(h["downloadable"] for h in historial)
    assert historial[0]["date_from"] == "2026-02-01"
    assert historial[0]["filename"] == "reporte-de-prueba.pdf"


def test_el_historial_no_mezcla_activos_del_mismo_cliente(
    client, login, tenant_a, factory, db, sin_tokens_reales, pdf_falso
):
    """
    Dos activos del MISMO cliente pueden ser marcas sin relación entre sí
    (es la razón por la que el reporte se genera por activo y nunca por
    cliente, ver el encabezado de routes/reports.py). Su historial tampoco
    se puede mezclar.
    """
    login(tenant_a.owner)
    uno = factory.ad_account(tenant_a.client)
    otro = factory.ad_account(tenant_a.client)

    job_de_uno = _generar_y_esperar(client, uno.id)

    assert [h["job_id"] for h in client.get(f"/reports/history/{uno.id}").json()] == [job_de_uno]
    assert client.get(f"/reports/history/{otro.id}").json() == []


def test_un_companero_de_la_misma_organizacion_puede_descargar_lo_que_generó_otro(
    client, login, tenant_a, factory, db, sin_tokens_reales, pdf_falso
):
    """
    Un reporte es de la organización, no de quien apretó el botón: si solo
    su autor pudiera bajarlo, el resto del equipo tendría que regenerarlo
    — exactamente el gasto que este historial existe para evitar.
    """
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    job_id = _generar_y_esperar(client, account.id)

    login(tenant_a.member)
    assert client.get(f"/reports/jobs/{job_id}/pdf").status_code == 200
    assert [h["job_id"] for h in client.get(f"/reports/history/{account.id}").json()] == [job_id]


# ── Aislamiento entre organizaciones ─────────────────────────────
def test_otra_organizacion_no_ve_ni_descarga_reportes_ajenos(
    client, login, tenant_a, tenant_b, factory, db, sin_tokens_reales, pdf_falso
):
    login(tenant_a.owner)
    account_a = factory.ad_account(tenant_a.client)
    job_de_a = _generar_y_esperar(client, account_a.id)

    login(tenant_b.owner)
    assert client.get(f"/reports/jobs/{job_de_a}").status_code == 404
    assert client.get(f"/reports/jobs/{job_de_a}/pdf").status_code == 404
    # Ni siquiera puede preguntar por el historial de un activo que no es suyo.
    assert client.get(f"/reports/history/{account_a.id}").status_code == 404


# ── Purga por antigüedad ─────────────────────────────────────────
def test_la_purga_suelta_los_bytes_pero_conserva_la_entrada(
    client, login, tenant_a, factory, db, monkeypatch, sin_tokens_reales, pdf_falso
):
    """
    Pasada la retención el PDF se borra, pero la fila queda: el historial
    debe seguir diciendo la verdad sobre qué se generó y cuándo, solo que
    sin botón de descargar.
    """
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    viejo = _generar_y_esperar(client, account.id)

    # Envejecer la fila más allá de la retención.
    fila = db.query(GeneratedReport).filter_by(job_id=viejo).one()
    fila.created_at = datetime.now(timezone.utc) - timedelta(
        days=reports_routes._HISTORY_RETENTION_DAYS + 1
    )
    db.commit()

    # Cualquier generación nueva dispara la purga.
    reciente = _generar_y_esperar(client, account.id, date_from="2026-03-01", date_to="2026-03-15")

    historial = {h["job_id"]: h for h in client.get(f"/reports/history/{account.id}").json()}
    assert historial[viejo]["status"] == "done"       # la entrada sigue ahí
    assert historial[viejo]["downloadable"] is False  # pero ya no se puede bajar
    assert historial[reciente]["downloadable"] is True

    # 410 y no 404: el reporte existió, y el mensaje debe decir por qué no está.
    r = client.get(f"/reports/jobs/{viejo}/pdf")
    assert r.status_code == 410
    assert str(reports_routes._HISTORY_RETENTION_DAYS) in r.json()["detail"]


# ── Un job que falla ─────────────────────────────────────────────
def test_un_reporte_que_falla_queda_registrado_con_su_error(
    client, login, tenant_a, factory, db, monkeypatch, sin_tokens_reales
):
    """
    Un fallo también se guarda: sin esto, un reporte que reventó
    desaparecía sin dejar rastro y nadie podía decir si se intentó.
    """
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)

    async def build_pdf_que_falla(*args, **kwargs):
        raise ValueError("No hay campañas con datos en ese período.")

    monkeypatch.setattr(report_builder, "build_pdf", build_pdf_que_falla)

    r = client.post("/reports/generate", json={
        "ad_account_id": account.id,
        "date_from": "2026-01-01", "date_to": "2026-01-15", "currency": "USD",
    })
    job_id = r.json()["job_id"]

    for _ in range(50):
        body = client.get(f"/reports/jobs/{job_id}").json()
        if body["status"] != "processing":
            break
        time.sleep(0.05)

    assert body["status"] == "error"
    assert "No hay campañas" in body["error"]

    historial = client.get(f"/reports/history/{account.id}").json()
    assert historial[0]["status"] == "error"
    assert historial[0]["downloadable"] is False

    # Descargar un reporte que falló es un 409 (no está listo), no un 410.
    assert client.get(f"/reports/jobs/{job_id}/pdf").status_code == 409
