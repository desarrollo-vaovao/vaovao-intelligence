"""
B. Aislamiento multi-tenant — que una agencia no vea ni toque los leads de otra.

Es el peor fallo posible del módulo, y también uno de los más silenciosos: un
filtro `org_id` que se cae de una query no rompe nada, sólo empieza a devolver
de más. Todas las pruebas montan DOS organizaciones con datos reales en ambas y
comprueban primero que el dato ajeno existe: si el montaje estuviera vacío, un
`assert ... not in ...` pasaría sin comprobar nada.

`OrphanLead` no tiene `org_id` a propósito (es justo el dato que falta), así que
su aislamiento se apoya en el dueño de la `ClientPage`; eso es lo que prueba
`test_reconciliar_una_pagina_ajena_...`.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import Lead, LeadAudit, OrphanLead

TERMINO_EXCLUSIVO_DE_B = "Zanzibarunicornio"


def test_el_listado_no_incluye_leads_de_otra_organizacion(
    client, login, factory, tenant_a, tenant_b
):
    """Si esto falla, la bandeja de una agencia muestra los leads de otra."""
    mio = factory.lead(tenant_a.client)
    ajeno = factory.lead(tenant_b.client)

    login(tenant_b.admin)
    del_otro = client.get("/leads").json()
    assert [i["id"] for i in del_otro["items"]] == [ajeno.id], (
        "montaje inválido: el lead de B no existe o no es visible para B"
    )

    login(tenant_a.admin)
    respuesta = client.get("/leads")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    ids = [item["id"] for item in cuerpo["items"]]
    assert ids == [mio.id]
    assert cuerpo["total"] == 1


def test_la_busqueda_no_alcanza_los_leads_de_otra_organizacion(
    client, login, factory, tenant_a, tenant_b
):
    """El filtro de búsqueda se aplica DESPUÉS del org_id, nunca en su lugar."""
    ajeno = factory.lead(
        tenant_b.client,
        form_data={"full_name": f"Cliente {TERMINO_EXCLUSIVO_DE_B}", "phone": "555"},
    )
    factory.lead(tenant_a.client, form_data={"full_name": "Alguien Mas"})

    # El término SÍ encuentra al lead cuando lo busca su propia organización.
    login(tenant_b.admin)
    propio = client.get("/leads", params={"search": TERMINO_EXCLUSIVO_DE_B}).json()
    assert [i["id"] for i in propio["items"]] == [ajeno.id]

    login(tenant_a.admin)
    respuesta = client.get("/leads", params={"search": TERMINO_EXCLUSIVO_DE_B})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 0
    assert cuerpo["items"] == []


def test_el_detalle_de_un_lead_ajeno_responde_404_y_no_403(
    client, login, factory, tenant_a, tenant_b
):
    """404 y no 403: un 403 confirmaría que ese id existe en alguna organización."""
    ajeno = factory.lead(tenant_b.client)

    login(tenant_b.admin)
    assert client.get(f"/leads/{ajeno.id}").status_code == 200, (
        "montaje inválido: el lead ni siquiera es legible por su dueño"
    )

    login(tenant_a.admin)
    respuesta = client.get(f"/leads/{ajeno.id}")

    assert respuesta.status_code == 404


def test_un_patch_a_un_lead_ajeno_no_lo_modifica(
    client, login, factory, tenant_a, tenant_b, db
):
    """El 404 tiene que llegar ANTES de escribir, no después."""
    ajeno = factory.lead(tenant_b.client, status="nuevo", notes=None)
    lead_id = ajeno.id

    login(tenant_a.owner)
    respuesta = client.patch(
        f"/leads/{lead_id}", json={"status": "ganado", "notes": "tocado por A"}
    )

    assert respuesta.status_code == 404
    db.expire_all()
    intacto = db.get(Lead, lead_id)
    assert intacto.status == "nuevo"
    assert intacto.notes is None
    assert (
        db.scalar(
            select(func.count()).select_from(LeadAudit).where(LeadAudit.lead_id == lead_id)
        )
        == 0
    ), "se escribió bitácora de un cambio que no debía ocurrir"


def test_reconciliar_una_pagina_ajena_es_rechazado_y_no_convierte_nada(
    client, login, factory, tenant_a, tenant_b, db
):
    """Reconciliar es una ESCRITURA en la bandeja del dueño de la página.

    Sin la comprobación de propiedad, un admin de A convertiría los huérfanos
    de una página de B en leads —y se los quedaría en su propia organización,
    porque el cliente lo decide la página—. Esto vigila que el rechazo no sólo
    devuelva 404 sino que además no escriba nada.
    """
    huerfano = factory.orphan(tenant_b.page.page_id)
    page_id = tenant_b.page.page_id

    pendientes_antes = db.scalar(
        select(func.count()).select_from(OrphanLead).where(OrphanLead.resolved_at.is_(None))
    )
    assert pendientes_antes == 1, "montaje inválido: no hay huérfano que robar"
    leads_antes = db.scalar(select(func.count()).select_from(Lead))

    login(tenant_a.admin)
    respuesta = client.post(f"/leads/orphans/{page_id}/reconcile")

    assert respuesta.status_code == 404
    db.expire_all()
    assert db.get(OrphanLead, huerfano.id).resolved_at is None
    assert db.scalar(select(func.count()).select_from(Lead)) == leads_antes


def test_la_exportacion_csv_solo_contiene_leads_de_la_organizacion(
    client, login, factory, tenant_a, tenant_b
):
    """El CSV usa el mismo CRUD que el listado; si alguien lo desvía, se filtra todo."""
    mio = factory.lead(tenant_a.client, leadgen_id="leadgen-de-A")
    ajeno = factory.lead(tenant_b.client, leadgen_id="leadgen-de-B")

    login(tenant_b.admin)
    csv_de_b = client.get("/leads/export/csv").text
    assert ajeno.leadgen_id in csv_de_b, "montaje inválido: B no exporta su propio lead"

    login(tenant_a.admin)
    respuesta = client.get("/leads/export/csv")

    assert respuesta.status_code == 200
    cuerpo = respuesta.text
    assert mio.leadgen_id in cuerpo
    assert ajeno.leadgen_id not in cuerpo
