"""
Hueco 2: carreras reales de entregas concurrentes en `ingest_lead`.

Por qué NO se puede cerrar esto sobre SQLite
---------------------------------------------
`ingest_lead()` (app/services/leads_service.py) tiene DOS ramas de
`except IntegrityError` que sólo existen porque Meta reentrega webhooks y dos
entregas del mismo `leadgen_id` pueden llegar casi al mismo tiempo:

1. En `ingest_lead` mismo: dos entregas de un lead ATRIBUIDO (su página está
   configurada) que pasan el SELECT de deduplicación a la vez e intentan
   ambas un INSERT en `leads` con el mismo `leadgen_id` (columna UNIQUE).
2. En `_store_orphan`: lo mismo pero para un lead HUÉRFANO (su página no
   está configurada), sobre `orphan_leads.leadgen_id`.

La fixture `db` de `conftest.py` usa `StaticPool` sobre SQLite `:memory:` a
propósito: TODAS las sesiones de una prueba comparten la MISMA conexión
física (es lo único que mantiene viva una base `:memory:`). Eso significa
que sobre SQLite dos "conexiones" nunca compiten de verdad — hay una sola, y
sus operaciones se serializan sin que el código de las dos ramas de arriba
se ejerza jamás. Esas líneas podrían borrarse y ninguna prueba lo notaría.

Qué hace esta prueba
---------------------
Usa el Postgres real de `require_postgres` con DOS `Session` independientes,
cada una con su PROPIA conexión de un pool normal (no StaticPool), y las
hace competir de verdad: ambas pasan el SELECT de "¿existe ya?" antes de que
cualquiera de las dos intente el INSERT, forzando que el índice UNIQUE de
Postgres sea el árbitro — exactamente el escenario que las dos ramas
`except IntegrityError` existen para manejar.

Cómo se fuerza el cruce sin depender de la suerte del scheduler
-----------------------------------------------------------------
Un `threading.Barrier(2)` se inyecta (vía monkeypatch) en el punto exacto de
la función real que hace el SELECT de deduplicación: ambos hilos quedan
bloqueados ahí hasta que los DOS llegaron, y sólo entonces se libera la
carrera. No se reemplaza ninguna lógica de negocio — se envuelve la función
original para forzar el momento del cruce sin tocar su comportamiento.
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.crud.leads as crud
from app.core.database import Base
from app.schemas.leads import LeadSyncPayload
from app.services.leads_service import IngestOutcome, ingest_lead


@pytest.fixture()
def pg_engine(require_postgres: str):
    """Motor Postgres propio de este archivo: cada hilo abre SU conexión.

    No se reutiliza la fixture `db`/`engine` de conftest porque esas dan UNA
    sesión por prueba; aquí hacen falta DOS sesiones independientes y vivas
    al mismo tiempo, cada una con su propia conexión del pool.
    """
    eng = create_engine(require_postgres, pool_pre_ping=True)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


def _run_concurrently(pg_engine, patch_target: str, payload_factory):
    """Dispara `ingest_lead(payload)` en dos hilos, sincronizados en `patch_target`.

    `patch_target` es la función de `app.crud.leads` cuyo SELECT decide "ya
    existe" — se envuelve para que ambos hilos la crucen a la vez, antes de
    que cualquiera intente el INSERT que compite de verdad.

    Devuelve `(resultados, errores)`, ambos de longitud 2 y en el mismo orden
    que los hilos, para que la prueba pueda distinguir cuál llegó "primero".
    """
    barrier = threading.Barrier(2)
    original = getattr(crud, patch_target)
    lock = threading.Lock()
    calls = {"n": 0}

    def synced(*args, **kwargs):
        # Sólo las dos primeras llamadas (una por hilo) se sincronizan: las
        # que vengan después (la relectura dentro del `except IntegrityError`)
        # deben correr libres o un hilo se quedaría esperando a un tercero
        # que nunca llega.
        with lock:
            calls["n"] += 1
            should_wait = calls["n"] <= 2
        if should_wait:
            barrier.wait(timeout=5)
        return original(*args, **kwargs)

    Session = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    results: list[object | None] = [None, None]
    errors: list[BaseException | None] = [None, None]

    def worker(index: int) -> None:
        session = Session()
        try:
            results[index] = ingest_lead(session, payload_factory())
        except BaseException as exc:  # noqa: BLE001 — se reporta, no se traga
            errors[index] = exc
        finally:
            session.close()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(crud, patch_target, synced)
        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

    return results, errors


def test_dos_entregas_concurrentes_de_un_lead_atribuido_no_se_pierden_ni_duplican(
    pg_engine,
) -> None:
    """Carrera en `leads.leadgen_id` (rama `except IntegrityError` de `ingest_lead`).

    Dos entregas del mismo `leadgen_id`, para una página YA configurada,
    llegan "a la vez": el índice UNIQUE de Postgres deja pasar un INSERT y
    rechaza el otro con IntegrityError real. `ingest_lead` debe convertir esa
    excepción en un resultado `updated` en vez de dejarla escapar, y las DOS
    entregas deben terminar apuntando al MISMO lead — ni un duplicado, ni un
    500.
    """
    from app.models import Client, ClientPage, Organization

    setup_engine = pg_engine
    SetupSession = sessionmaker(bind=setup_engine)
    with SetupSession() as setup_db:
        org = Organization(name="Agencia de Prueba", slug="agencia-race")
        setup_db.add(org)
        setup_db.flush()
        cliente = Client(org_id=org.id, name="Cliente de Prueba")
        setup_db.add(cliente)
        setup_db.flush()
        page = ClientPage(client_id=cliente.id, page_id="page-race-1", page_name="Pagina")
        setup_db.add(page)
        setup_db.commit()

    def make_payload() -> LeadSyncPayload:
        return LeadSyncPayload(
            leadgen_id="leadgen-carrera-atribuida",
            page_id="page-race-1",
            form_data={"full_name": "Carrera Atribuida"},
            token="no-se-valida-aqui",
        )

    results, errors = _run_concurrently(
        pg_engine, "get_lead_by_leadgen_id", make_payload
    )

    assert errors == [None, None], f"ingest_lead no debe dejar escapar excepciones: {errors!r}"

    outcomes = sorted(r.outcome.value for r in results)
    assert outcomes == sorted([IngestOutcome.created.value, IngestOutcome.updated.value]), (
        "Con dos entregas concurrentes del mismo leadgen_id, una debe ganar "
        f"la carrera (created) y la otra debe leerse como reentrega "
        f"(updated). Resultados: {outcomes!r}"
    )

    lead_ids = {r.lead.id for r in results if r.lead is not None}
    assert len(lead_ids) == 1, (
        "Las dos entregas concurrentes terminaron en leads DISTINTOS: "
        f"{lead_ids!r} — la deduplicación por leadgen_id falló bajo carrera."
    )


def test_dos_entregas_concurrentes_de_un_lead_huerfano_no_duplican_el_huerfano(
    pg_engine,
) -> None:
    """Carrera en `orphan_leads.leadgen_id` (rama `except IntegrityError` de `_store_orphan`).

    Mismo escenario que la prueba anterior, pero para una página SIN
    configurar: las dos entregas deben terminar en `orphaned`, apuntando al
    MISMO `OrphanLead` — no en dos filas huérfanas para el mismo lead.
    """

    def make_payload() -> LeadSyncPayload:
        return LeadSyncPayload(
            leadgen_id="leadgen-carrera-huerfana",
            page_id="page-sin-configurar",
            form_data={"full_name": "Carrera Huerfana"},
            token="no-se-valida-aqui",
        )

    results, errors = _run_concurrently(
        pg_engine, "get_orphan_by_leadgen_id", make_payload
    )

    assert errors == [None, None], f"ingest_lead no debe dejar escapar excepciones: {errors!r}"

    outcomes = {r.outcome.value for r in results}
    assert outcomes == {IngestOutcome.orphaned.value}, (
        f"Las dos entregas de un lead huérfano deben resolver 'orphaned': {outcomes!r}"
    )

    orphan_ids = {r.orphan.id for r in results if r.orphan is not None}
    assert len(orphan_ids) == 1, (
        "Las dos entregas concurrentes crearon DOS huérfanos distintos para "
        f"el mismo leadgen_id: {orphan_ids!r} — la deduplicación falló bajo carrera."
    )
