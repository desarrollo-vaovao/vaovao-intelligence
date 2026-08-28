"""
Infraestructura de las pruebas del backend.

Tres cosas que este archivo garantiza y que ninguna prueba debería tener que
repetir:

1. **Entorno determinista.** Las variables sensibles se fijan ANTES de
   importar `app.core.config`, porque `Settings` se instancia al importar el
   módulo. Si no, una prueba leería el `.env` del desarrollador y su resultado
   dependería de la máquina donde corre.

2. **Base nueva por prueba, con las llaves foráneas ENCENDIDAS.** SQLite
   ignora `ON DELETE CASCADE` / `ON DELETE SET NULL` salvo que cada conexión
   emita `PRAGMA foreign_keys=ON`. Sin eso, toda prueba de cascada pasaría sin
   comprobar nada — el peor resultado posible: verde y falso. Ver
   `tests/test_fk_enforcement.py`, que existe para vigilar justamente esto.

3. **Overrides limpios.** `get_db` y `get_current_user` se sustituyen por la
   duración de la prueba y se restauran al final, para que una prueba no
   herede el usuario autenticado de la anterior.

4. **Postgres real, opcional.** Con `USE_POSTGRES_CONTAINER=true` la fixture
   `engine` deja de ser SQLite en memoria y pasa a ser un PostgreSQL real
   levantado en Docker (testcontainers), UNO SOLO para toda la sesión de
   pruebas — cada prueba sigue recibiendo su propio esquema limpio, pero el
   contenedor no se reinicia por prueba porque tardaría minutos en vez de
   milisegundos. Es el modo que corre en CI (ver
   .github/workflows/tests.yml) y el que hay que usar en local para
   reproducir un fallo de CI: sin él, cuatro huecos quedan sin cubrir de
   verdad (ver docstring de tests/test_migracion_vs_modelo.py,
   tests/test_concurrencia_ingest_lead.py, tests/test_busqueda_acentos.py y
   tests/test_cascada_real_bd.py).
"""
from __future__ import annotations

import os

# ── Entorno, antes de cualquier import de la app ─────────────────
# `LEADS_SYNC_TOKEN`: `app/core/config.py` rechaza el valor de desarrollo si
# ENVIRONMENT=production. Se fija un valor propio de pruebas para que el
# webhook se pueda autenticar sin depender del .env local.
os.environ["ENVIRONMENT"] = "development"
os.environ["LEADS_SYNC_TOKEN"] = "token-de-pruebas-no-usar-en-produccion"
os.environ["SECRET_KEY"] = "clave-de-pruebas-solo-para-firmar-jwt-en-tests"
# Fernet válida de pruebas (crypto.encrypt/decrypt para tokens de Meta). Se
# fija aquí, y NO con setdefault, para que un .env local con una llave real
# nunca enmascare un bug que solo aparece cuando ENCRYPTION_KEY falta —
# pasó exactamente eso: una prueba pasaba en local (con la llave del .env
# del desarrollador) y fallaba en CI (sin .env) con 503 en vez del 201
# esperado, porque crypto.keys() no tenía ninguna llave configurada.
os.environ["ENCRYPTION_KEY"] = "e47BNVRrIu4ESbBSqp3eEOD74HzFPkLMFBE7RLFHUf4="
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

# `USE_POSTGRES_CONTAINER=true` cambia la fixture `engine` de SQLite en
# memoria a un PostgreSQL real en Docker. Se lee UNA vez aquí, a nivel de
# módulo, para que valga lo mismo durante toda la sesión de pytest — nada
# posterior debería releer el env var directamente.
USE_POSTGRES_CONTAINER = os.environ.get("USE_POSTGRES_CONTAINER", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

from collections.abc import Iterator  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402

if USE_POSTGRES_CONTAINER:
    try:
        # Ruta no deprecada desde testcontainers 4.x reciente.
        from testcontainers.community.postgres import PostgresContainer  # noqa: E402
    except ImportError:  # pragma: no cover - compat con testcontainers viejo
        from testcontainers.postgres import PostgresContainer  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdAccount,
    Client,
    ClientPage,
    Lead,
    LeadAudit,
    Organization,
    OrphanLead,
    User,
    UserRole,
)

TEST_SYNC_TOKEN = os.environ["LEADS_SYNC_TOKEN"]


# ── Motor de pruebas ─────────────────────────────────────────────
def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Emite `PRAGMA foreign_keys=ON` en CADA conexión nueva del motor.

    No es opcional ni cosmético: SQLite trae el soporte de llaves foráneas
    apagado por defecto, y el interruptor es por conexión. Sin este listener,
    un `ON DELETE CASCADE` o un `ON DELETE SET NULL` declarados en el modelo
    simplemente no ocurren, y una prueba que borre a un usuario y luego afirme
    que su bitácora quedó con `user_id IS NULL` fallaría — o, peor, pasaría
    vacía si el aserto estuviera mal escrito.

    El pragma va en el evento `connect` y no en un `execute` suelto porque el
    pool abre conexiones cuando le hace falta: una sola ejecución al inicio
    dejaría sin proteger a todas las que se abran después.
    """

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture(scope="session")
def _postgres_container():
    """Un PostgreSQL real en Docker, UNO SOLO para toda la sesión de pytest.

    Arrancar un container por prueba costaría varios segundos cada vez —
    inaceptable para una suite de decenas de pruebas—; uno por sesión y una
    base limpia por prueba (ver `engine`, que hace create_all/drop_all sobre
    él) da el mismo aislamiento por una fracción del costo.

    `None` cuando `USE_POSTGRES_CONTAINER` no está activo, para que todo lo
    que dependa de esta fixture (incluida `engine`) pueda ramificar con un
    simple `is not None` sin su propio `if` de entorno.
    """
    if not USE_POSTGRES_CONTAINER:
        yield None
        return

    # Imagen Debian, NO -alpine: la variante alpine corre sobre musl, que no
    # trae locales ICU/glibc completas y por eso `initdb` la deja en "C" —
    # ahí ILIKE sólo pliega mayúsculas ASCII, la MISMA limitación que
    # test_busqueda_acentos.py existe para probar que Postgres no tiene.
    # Se descubrió al fallar esa prueba en la primera corrida real contra
    # este contenedor.
    with PostgresContainer("postgres:16", driver="psycopg2") as container:
        yield container


@pytest.fixture()
def postgres_url(_postgres_container) -> str | None:
    """URL de conexión al Postgres de la sesión, o `None` si no está activo.

    La usan las pruebas que necesitan SUS PROPIAS conexiones —no la sesión
    única que da la fixture `db`— para ejercitar de verdad dos transacciones
    compitiendo (`test_concurrencia_ingest_lead.py`), comparar el esquema
    migrado por Alembic contra `Base.metadata`
    (`test_migracion_vs_modelo.py`), o forzar un DELETE en SQL crudo que
    dispare el `ON DELETE CASCADE` de la base sin pasar por el ORM
    (`test_cascada_real_bd.py`).
    """
    if _postgres_container is None:
        return None
    return _postgres_container.get_connection_url()


@pytest.fixture()
def engine(_postgres_container) -> Iterator[Engine]:
    """Motor de pruebas: PostgreSQL real si `USE_POSTGRES_CONTAINER=true`,
    SQLite en memoria si no (comportamiento histórico, sin cambios).

    Aislamiento por construcción en ambos casos: el esquema se crea antes de
    la prueba y se destruye después, así que ninguna fila puede filtrarse a
    la siguiente ni el orden de ejecución puede cambiar un resultado.
    """
    if _postgres_container is not None:
        # Motor real, con su pool normal (NO StaticPool): a diferencia de
        # SQLite, aquí cada `Session` puede abrir su propia conexión de
        # verdad, que es exactamente lo que hace falta para probar carreras
        # entre entregas concurrentes (ver test_concurrencia_ingest_lead.py).
        eng = create_engine(_postgres_container.get_connection_url(), pool_pre_ping=True)
        Base.metadata.create_all(eng)
        try:
            yield eng
        finally:
            Base.metadata.drop_all(eng)
            eng.dispose()
        return

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    enable_sqlite_foreign_keys(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def require_postgres(postgres_url: str | None) -> str:
    """Salta la prueba si no hay Postgres real (`USE_POSTGRES_CONTAINER=true`).

    Las cuatro pruebas que cubren huecos honestos de SQLite (deriva
    modelo/migración, carreras de `ingest_lead`, acentos, CASCADE real de la
    base) NO pueden fingir un resultado sobre SQLite: o corren contra
    Postgres de verdad, o se saltan con un motivo explícito. `pytest.skip`
    y no un `xfail` ni un `assert True`, para que la corrida deje claro en
    el resumen que esos cuatro huecos NO se comprobaron esta vez, en vez de
    aparecer como si hubieran pasado.
    """
    if postgres_url is None:
        pytest.skip(
            "Requiere PostgreSQL real: corre con USE_POSTGRES_CONTAINER=true "
            "(necesita Docker). Sobre SQLite este hueco no se puede cerrar "
            "honestamente — ver docstring del módulo de la prueba."
        )
    return postgres_url


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    """Sesión de la prueba. Es la MISMA que ve el endpoint (ver `client`)."""
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ── Cliente HTTP y autenticación ─────────────────────────────────
class _Auth:
    """Quién está autenticado ahora. Lo lee el override de `get_current_user`."""

    def __init__(self) -> None:
        self.user: User | None = None


@pytest.fixture()
def auth() -> _Auth:
    return _Auth()


@pytest.fixture()
def client(db: Session, auth: _Auth) -> Iterator[TestClient]:
    """TestClient con `get_db` y `get_current_user` sustituidos.

    * `get_db` devuelve la sesión de la prueba, así que lo que escribe el
      endpoint lo ve el aserto sin tener que reabrir nada.
    * `get_current_user` devuelve el usuario que la prueba haya puesto con la
      fixture `login`. Sustituirlo evita fabricar un JWT real en cada prueba;
      lo que se prueba aquí es la autorización (org_id + rol), no la firma del
      token, que es otro módulo.
    * NO se usa `with TestClient(app)`: eso dispararía el `lifespan`, que
      levanta un Chromium de Playwright para los PDFs. Ninguna prueba de leads
      lo necesita.
    * El limitador de tasa se apaga: el balde de slowapi es por IP y todas las
      peticiones de la suite llegan como "testclient", así que con él encendido
      la enésima prueba de un mismo endpoint empezaría a recibir 429 según el
      orden de ejecución.
    """

    def _override_get_db() -> Iterator[Session]:
        yield db

    def _override_get_current_user() -> User:
        assert auth.user is not None, (
            "Ninguna prueba autenticó a un usuario: usa la fixture `login`."
        )
        return auth.user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    limiter_was_enabled = limiter.enabled
    limiter.enabled = False

    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        limiter.enabled = limiter_was_enabled
        app.dependency_overrides.clear()


@pytest.fixture()
def login(auth: _Auth):
    """`login(user)` — deja a `user` como el autenticado de aquí en adelante."""

    def _login(user: User) -> User:
        auth.user = user
        return user

    return _login


# ── Fábrica del grafo de objetos ─────────────────────────────────
class Factory:
    """Construye organización → usuarios / clientes → páginas → leads → bitácora.

    Todo lleva valores por defecto razonables y contadores propios, para que
    una prueba sólo nombre lo que de verdad le importa (el org_id de un lead,
    el rol de un usuario) y no repita el andamiaje.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    def org(self, name: str | None = None) -> Organization:
        n = self._next()
        org = Organization(name=name or f"Agencia {n}", slug=f"agencia-{n}")
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)
        return org

    def user(
        self,
        org: Organization,
        role: UserRole = UserRole.member,
        *,
        email: str | None = None,
        full_name: str | None = None,
    ) -> User:
        n = self._next()
        user = User(
            org_id=org.id,
            # ".test" es un TLD reservado (RFC 2606); email-validator lo
            # rechaza como "special-use" al serializar por EmailStr — nadie
            # lo había notado porque ningún endpoint devolvía UserOut para
            # un usuario de fábrica sin correo explícito hasta ahora.
            email=email or f"user{n}@ejemplo.com",
            hashed_password="no-es-un-hash-real",
            full_name=full_name or f"Usuario {n}",
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def client_of(self, org: Organization, name: str | None = None) -> Client:
        n = self._next()
        cli = Client(org_id=org.id, name=name or f"Cliente {n}")
        self.db.add(cli)
        self.db.commit()
        self.db.refresh(cli)
        return cli

    def page(self, cli: Client, page_id: str | None = None) -> ClientPage:
        n = self._next()
        page = ClientPage(
            client_id=cli.id,
            page_id=page_id or f"page-{n}",
            page_name=f"Pagina {n}",
        )
        self.db.add(page)
        self.db.commit()
        self.db.refresh(page)
        return page

    def ad_account(self, cli: Client) -> AdAccount:
        n = self._next()
        acc = AdAccount(
            client_id=cli.id,
            label=f"Cuenta {n}",
            meta_ad_account_id=f"act_{n}",
            recipient_emails=[],
        )
        self.db.add(acc)
        self.db.commit()
        self.db.refresh(acc)
        return acc

    def lead(
        self,
        cli: Client,
        *,
        assigned_to: User | None = None,
        status: str = "nuevo",
        form_data: dict | None = None,
        notes: str | None = None,
        leadgen_id: str | None = None,
        received_at: datetime | None = None,
    ) -> Lead:
        n = self._next()
        lead = Lead(
            org_id=cli.org_id,
            client_id=cli.id,
            leadgen_id=leadgen_id or f"leadgen-{n}",
            form_data=(
                form_data if form_data is not None else {"full_name": f"Prospecto {n}"}
            ),
            status=status,
            assigned_to_id=assigned_to.id if assigned_to else None,
            notes=notes,
            received_at=received_at or datetime.now(timezone.utc) - timedelta(minutes=n),
        )
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def audit(
        self,
        lead: Lead,
        *,
        user: User | None = None,
        action: str = "status_changed",
        old_value: str | None = "nuevo",
        new_value: str = "contactado",
    ) -> LeadAudit:
        row = LeadAudit(
            lead_id=lead.id,
            user_id=user.id if user else None,
            action=action,
            old_value=old_value,
            new_value=new_value,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def orphan(self, page_id: str, *, form_data: dict | None = None) -> OrphanLead:
        n = self._next()
        orphan = OrphanLead(
            leadgen_id=f"huerfano-{n}",
            page_id=page_id,
            form_data=(
                form_data if form_data is not None else {"full_name": f"Huerfano {n}"}
            ),
        )
        self.db.add(orphan)
        self.db.commit()
        self.db.refresh(orphan)
        return orphan


@pytest.fixture()
def factory(db: Session) -> Factory:
    return Factory(db)


class Tenant:
    """Una organización montada de punta a punta, para no repetir el andamiaje."""

    def __init__(self, factory: Factory, name: str) -> None:
        self.org = factory.org(name)
        self.owner = factory.user(self.org, UserRole.owner)
        self.admin = factory.user(self.org, UserRole.admin)
        self.member = factory.user(self.org, UserRole.member)
        self.client = factory.client_of(self.org, f"Cliente de {name}")
        self.page = factory.page(self.client)


@pytest.fixture()
def tenant_a(factory: Factory) -> Tenant:
    return Tenant(factory, "Agencia A")


@pytest.fixture()
def tenant_b(factory: Factory) -> Tenant:
    return Tenant(factory, "Agencia B")
