"""
Hueco 4: `ON DELETE CASCADE` de `clients.id` a nivel de BASE, no de ORM.

Por qué NO alcanza con lo que ya prueba `test_cascadas.py`
------------------------------------------------------------
`Client` declara sus relaciones con `cascade="all, delete-orphan"`
(app/models/__init__.py). Eso es SQLAlchemy borrando en Python: cuando el
código hace `db.delete(client)` (como hace `DELETE /clients/{id}` — ver
app/api/routes/clients.py), la sesión emite un DELETE explícito por cada
`AdAccount`, `ClientPage` y `Lead` colgando de ese cliente ANTES de borrar la
fila del cliente. Si mañana alguien quita el `ondelete="CASCADE"` de las
columnas en un modelo o en una migración, TODAS las pruebas de
`test_cascadas.py` seguirían pasando exactamente igual, porque nunca llegan
a ejercer la cascada de la base — el ORM ya hizo el trabajo antes.

Lo que este archivo prueba es la otra mitad: que la propia base, sin ayuda
del ORM, también sabe borrar en cascada. Es la garantía real para cualquier
DELETE que no pase por SQLAlchemy (una migración de datos, un script de
mantenimiento, un `psql` de emergencia) — casos donde `cascade=` del modelo
no participa para nada, sólo la restricción `ON DELETE CASCADE` del propio
esquema.

Por qué se corre contra Postgres y no contra SQLite
------------------------------------------------------
Técnicamente SQLite con `PRAGMA foreign_keys=ON` (activo en toda la suite,
ver `tests/test_fk_enforcement.py`) también podría demostrar esto con un
DELETE en SQL crudo. Pero declarar cerrado este hueco sobre SQLite dejaría
sin comprobar que el esquema que REALMENTE corre en producción —el que
generan las migraciones de Alembic contra Postgres, no `create_all()`— tiene
las mismas cascadas. `test_migracion_vs_modelo.py` ya vigila que ambos
esquemas coincidan; esta prueba, sumada a esa, cierra el círculo sobre el
motor real.

Cómo se bypasea el ORM
------------------------
`db.execute(text("DELETE FROM clients WHERE id = :id"), ...)` en vez de
`db.delete(client)`: SQLAlchemy no ve un objeto `Client` cargado y por lo
tanto no dispara ningún cascade de sesión. Lo único que puede borrar las
filas hijas, si algo las borra, es la restricción de la base.
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import AdAccount, Client, ClientPage, Lead, LeadAudit


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def test_delete_sql_crudo_de_un_cliente_arrastra_sus_hijos_por_cascade_de_la_base(
    require_postgres: str, factory, tenant_a, db: Session
) -> None:
    """Un DELETE que el ORM nunca ve también debe llevarse leads, bitácora,
    páginas y cuentas publicitarias — porque lo hace la base, no Python.
    """
    lead_uno = factory.lead(tenant_a.client)
    lead_dos = factory.lead(tenant_a.client)
    factory.audit(lead_uno, user=tenant_a.admin)
    factory.audit(lead_dos, user=None)
    factory.ad_account(tenant_a.client)
    client_id = tenant_a.client.id
    # Capturados ANTES del borrado: tras el DELETE + expire_all() de más abajo,
    # `lead_uno`/`lead_dos` quedan expirados y su fila ya no existe, así que
    # releer `.id` sobre ellos dispara un refresh que revienta con
    # ObjectDeletedError en vez de dejar fallar limpiamente el assert.
    lead_uno_id, lead_dos_id = lead_uno.id, lead_dos.id

    # Montaje real antes de actuar: si estos conteos fueran 0 los asertos de
    # abajo no comprobarían ninguna cascada, sólo un borrado vacío.
    assert _count(db, Lead, Lead.client_id == client_id) == 2
    assert _count(db, LeadAudit, LeadAudit.lead_id.in_([lead_uno_id, lead_dos_id])) == 2
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 1
    assert _count(db, AdAccount, AdAccount.client_id == client_id) == 1

    # Expira los objetos que la sesión ya trae cargados en memoria: sin esto
    # SQLAlchemy podría "recordar" el Client como todavía presente y opacar
    # lo que la base hizo de verdad.
    db.expire_all()

    # El bypass: SQL crudo, ningún objeto `Client` cargado en la Session, por
    # lo tanto ningún cascade de `relationship(cascade=...)` puede disparar.
    db.execute(text("DELETE FROM clients WHERE id = :id"), {"id": client_id})
    db.commit()

    db.expire_all()
    assert _count(db, Client, Client.id == client_id) == 0, "el cliente no se borró"
    assert _count(db, Lead, Lead.client_id == client_id) == 0, (
        "la base NO se llevó los leads del cliente borrado: el ON DELETE "
        "CASCADE de leads.client_id no está aplicado en el esquema real."
    )
    assert _count(db, LeadAudit, LeadAudit.lead_id.in_([lead_uno_id, lead_dos_id])) == 0, (
        "la bitácora sobrevivió a sus leads borrados: la cascada encadenada "
        "leads -> lead_audits no llegó hasta el final en la base."
    )
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 0, (
        "las páginas del cliente sobrevivieron: el ON DELETE CASCADE de "
        "client_pages.client_id no está aplicado en el esquema real."
    )
    assert _count(db, AdAccount, AdAccount.client_id == client_id) == 0, (
        "las cuentas publicitarias sobrevivieron: el ON DELETE CASCADE de "
        "ad_accounts.client_id no está aplicado en el esquema real."
    )


def test_delete_sql_crudo_de_un_cliente_sin_leads_no_falla(
    require_postgres: str, tenant_a, db: Session
) -> None:
    """Caso base: borrar un cliente sin leads no debe reventar. `tenant_a` ya
    trae una `ClientPage`, y esa sí debe arrastrarse por la misma cascada.
    """
    client_id = tenant_a.client.id
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 1

    db.execute(text("DELETE FROM clients WHERE id = :id"), {"id": client_id})
    db.commit()

    db.expire_all()
    assert _count(db, Client, Client.id == client_id) == 0
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 0
