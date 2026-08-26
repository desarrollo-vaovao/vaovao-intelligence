"""
A. Borrados destructivos — lo que se pierde en silencio.

Estas son las regresiones más caras del módulo porque no hacen ruido: no hay
excepción, no hay log, sólo un historial comercial que dejó de existir. Cada
prueba comprueba el estado de las filas DESPUÉS de la acción, no sólo el código
HTTP: un endpoint que devolviera 409 y además borrara todo pasaría una prueba
que sólo mirara el status.

Todas verifican primero que las filas que deberían sobrevivir EXISTEN antes de
actuar. Sin ese aserto previo, un `assert count == 0` posterior podría estar
midiendo un montaje vacío en vez de una protección que funciona.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AdAccount, Client, ClientPage, Lead, LeadAudit, User


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


# ── DELETE /clients/{id} ─────────────────────────────────────────
def test_borrar_cliente_con_leads_es_rechazado_con_409(client, login, factory, tenant_a):
    """Si esto falla, un DELETE de cliente vuelve a ser un borrado en cascada."""
    factory.lead(tenant_a.client)
    login(tenant_a.owner)

    response = client.delete(f"/clients/{tenant_a.client.id}")

    assert response.status_code == 409


def test_borrar_cliente_con_leads_no_destruye_leads_bitacora_ni_paginas(
    client, login, factory, tenant_a, db
):
    """El 409 tiene que ser un rechazo, no un 409 después de haber borrado.

    Se cuentan las tres cosas que el CASCADE de `clients.id` se llevaría por
    delante: los leads, su bitácora (que cuelga de los leads) y las páginas de
    Facebook del cliente.
    """
    lead_uno = factory.lead(tenant_a.client)
    lead_dos = factory.lead(tenant_a.client)
    factory.audit(lead_uno, user=tenant_a.admin)
    factory.audit(lead_dos, user=None)
    factory.ad_account(tenant_a.client)
    client_id = tenant_a.client.id

    # El montaje tiene que ser real: si estos conteos fueran 0, los asertos de
    # abajo pasarían sin comprobar ninguna protección.
    assert _count(db, Lead, Lead.client_id == client_id) == 2
    assert _count(db, LeadAudit, LeadAudit.lead_id.in_([lead_uno.id, lead_dos.id])) == 2
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 1
    assert _count(db, AdAccount, AdAccount.client_id == client_id) == 1

    login(tenant_a.owner)
    response = client.delete(f"/clients/{client_id}")
    assert response.status_code == 409

    db.expire_all()
    assert _count(db, Client, Client.id == client_id) == 1
    assert _count(db, Lead, Lead.client_id == client_id) == 2
    assert _count(db, LeadAudit, LeadAudit.lead_id.in_([lead_uno.id, lead_dos.id])) == 2
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 1
    assert _count(db, AdAccount, AdAccount.client_id == client_id) == 1


def test_borrar_cliente_sin_leads_sigue_funcionando(client, login, tenant_a, db):
    """La protección no puede haber convertido el borrado en imposible."""
    client_id = tenant_a.client.id
    assert _count(db, Lead, Lead.client_id == client_id) == 0
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 1

    login(tenant_a.owner)
    response = client.delete(f"/clients/{client_id}")

    assert response.status_code == 204
    db.expire_all()
    assert _count(db, Client, Client.id == client_id) == 0
    assert _count(db, ClientPage, ClientPage.client_id == client_id) == 0


# ── Borrado de un User (ondelete="SET NULL", migración 0003) ─────
def test_borrar_usuario_conserva_su_bitacora_con_user_id_null(factory, tenant_a, db):
    """Una bitácora que desaparece con quien la escribió no es una bitácora.

    `lead_audits.user_id` es `ON DELETE SET NULL`: la fila se degrada a
    "atribuida al sistema" en vez de borrarse. Si alguien lo cambiara a
    CASCADE, este conteo caería a 0.
    """
    lead = factory.lead(tenant_a.client)
    autor = factory.user(tenant_a.org)
    fila = factory.audit(lead, user=autor, new_value="contactado")
    audit_id = fila.id

    assert _count(db, LeadAudit, LeadAudit.id == audit_id) == 1
    assert db.get(LeadAudit, audit_id).user_id == autor.id

    db.delete(autor)
    db.commit()

    db.expire_all()
    assert _count(db, User, User.id == autor.id) == 0
    superviviente = db.get(LeadAudit, audit_id)
    assert superviviente is not None, "la bitácora se borró con su autor"
    assert superviviente.user_id is None
    assert superviviente.new_value == "contactado"


def test_borrar_usuario_desasigna_su_lead_en_vez_de_borrarlo(factory, tenant_a, db):
    """`leads.assigned_to_id` es SET NULL: se pierde el responsable, no el lead."""
    responsable = factory.user(tenant_a.org)
    lead = factory.lead(tenant_a.client, assigned_to=responsable)
    lead_id = lead.id

    assert db.get(Lead, lead_id).assigned_to_id == responsable.id

    db.delete(responsable)
    db.commit()

    db.expire_all()
    sobreviviente = db.get(Lead, lead_id)
    assert sobreviviente is not None, "el lead se borró junto con su responsable"
    assert sobreviviente.assigned_to_id is None


def test_detalle_del_lead_renderiza_una_bitacora_de_usuario_borrado(
    client, login, factory, tenant_a, db
):
    """`user: null` en la bitácora no puede reventar la serialización del detalle.

    Es el otro lado del SET NULL: sin esto, borrar a un usuario dejaría el
    detalle de sus leads devolviendo 500 para siempre.
    """
    lead = factory.lead(tenant_a.client)
    autor = factory.user(tenant_a.org, full_name="Se Va A Ir")
    factory.audit(lead, user=autor, action="status_changed", new_value="contactado")
    factory.audit(lead, user=None, action="created", old_value=None, new_value="nuevo")

    db.delete(autor)
    db.commit()
    db.expire_all()

    login(tenant_a.admin)
    response = client.get(f"/leads/{lead.id}")

    assert response.status_code == 200
    bitacora = response.json()["audit_log"]
    assert len(bitacora) == 2, "la bitácora perdió filas al borrarse el usuario"
    assert all(entrada["user"] is None for entrada in bitacora)
