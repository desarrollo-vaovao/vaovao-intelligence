"""
C. RBAC dentro de una misma organización.

`member` es el traficker: ve y edita su propia bandeja. `owner`/`admin` ven la
organización entera y son los únicos que pueden reconciliar huérfanos.

Ojo con la asimetría deliberada entre GET y PATCH, que estas pruebas fijan:
un `member` que PIDE un lead ajeno de su propia organización recibe 404 (no se
le confirma nada), pero si intenta EDITARLO recibe 403 — el lead sí existe y sí
es de su organización, así que negar su existencia sería mentir.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import Lead, LeadAudit


def test_un_member_solo_ve_los_leads_que_tiene_asignados(
    client, login, factory, tenant_a
):
    """Si esto falla, cada traficker ve la bandeja completa del equipo."""
    mio = factory.lead(tenant_a.client, assigned_to=tenant_a.member)
    de_un_companero = factory.lead(tenant_a.client, assigned_to=tenant_a.admin)
    sin_asignar = factory.lead(tenant_a.client)

    login(tenant_a.member)
    respuesta = client.get("/leads")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    ids = [item["id"] for item in cuerpo["items"]]
    assert ids == [mio.id]
    assert cuerpo["total"] == 1
    assert de_un_companero.id not in ids
    assert sin_asignar.id not in ids


def test_un_admin_ve_todos_los_leads_de_su_organizacion(client, login, factory, tenant_a):
    """La contraparte: el filtro por responsable NO se le aplica a owner/admin."""
    uno = factory.lead(tenant_a.client, assigned_to=tenant_a.member)
    dos = factory.lead(tenant_a.client, assigned_to=tenant_a.owner)
    tres = factory.lead(tenant_a.client)

    login(tenant_a.admin)
    cuerpo = client.get("/leads").json()

    assert cuerpo["total"] == 3
    assert {item["id"] for item in cuerpo["items"]} == {uno.id, dos.id, tres.id}


def test_un_member_no_puede_editar_el_lead_de_un_companero(
    client, login, factory, tenant_a, db
):
    """403 —no 404— y, sobre todo, sin escribir: el lead existe y es de su org."""
    ajeno = factory.lead(
        tenant_a.client, assigned_to=tenant_a.admin, status="nuevo", notes=None
    )
    lead_id = ajeno.id

    login(tenant_a.member)
    respuesta = client.patch(f"/leads/{lead_id}", json={"status": "ganado"})

    assert respuesta.status_code == 403
    db.expire_all()
    assert db.get(Lead, lead_id).status == "nuevo"
    assert (
        db.scalar(
            select(func.count()).select_from(LeadAudit).where(LeadAudit.lead_id == lead_id)
        )
        == 0
    )


def test_un_member_si_puede_editar_el_lead_que_tiene_asignado(
    client, login, factory, tenant_a, db
):
    """El 403 de arriba no puede haberse convertido en "nadie edita nada"."""
    mio = factory.lead(tenant_a.client, assigned_to=tenant_a.member, status="nuevo")

    login(tenant_a.member)
    respuesta = client.patch(f"/leads/{mio.id}", json={"status": "contactado"})

    assert respuesta.status_code == 200
    db.expire_all()
    assert db.get(Lead, mio.id).status == "contactado"


def test_un_member_no_puede_disparar_la_reconciliacion_de_huerfanos(
    client, login, factory, tenant_a, db
):
    """Reconciliar escribe leads nuevos en la bandeja de toda la organización."""
    huerfano = factory.orphan(tenant_a.page.page_id)
    leads_antes = db.scalar(select(func.count()).select_from(Lead))

    login(tenant_a.member)
    respuesta = client.post(f"/leads/orphans/{tenant_a.page.page_id}/reconcile")

    assert respuesta.status_code == 403
    db.expire_all()
    assert db.get(type(huerfano), huerfano.id).resolved_at is None
    assert db.scalar(select(func.count()).select_from(Lead)) == leads_antes


def test_un_admin_si_puede_reconciliar_los_huerfanos_de_su_pagina(
    client, login, factory, tenant_a, db
):
    """El 403 de arriba es del rol, no de la función: con admin sí convierte."""
    factory.orphan(tenant_a.page.page_id)

    login(tenant_a.admin)
    respuesta = client.post(f"/leads/orphans/{tenant_a.page.page_id}/reconcile")

    assert respuesta.status_code == 200
    assert respuesta.json()["recovered"] == 1
    db.expire_all()
    assert (
        db.scalar(
            select(func.count()).select_from(Lead).where(Lead.org_id == tenant_a.org.id)
        )
        == 1
    )
