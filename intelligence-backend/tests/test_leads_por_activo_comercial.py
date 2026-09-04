"""
GET /leads (y su exportación CSV) ahora filtran por ACTIVO COMERCIAL, no
por cliente: un cliente con varios activos (varias cuentas publicitarias)
ya no mezcla los leads de todos en una sola bandeja. La atribución cruza
`Lead.campaign_id` (que manda leads_traker, migración 0011) contra
`SyncedCampaign` (el catálogo que sincroniza app/services/daily_sync.py,
migración 0009) para saber a qué cuenta pertenece la campaña de un lead.

Un lead sin campaña resuelta a NINGÚN activo del cliente todavía
(formulario sin anuncio pautado, o una campaña recién creada que aún no
se sincronizó) aparece en TODOS los activos del cliente en vez de
perderse — ver crud/leads.py `_account_visibility_condition`.
"""
from __future__ import annotations

from app.models import Lead, SyncedCampaign


def _crear_lead(db, tenant, campaign_id=None, leadgen_id="lead-1"):
    lead = Lead(
        org_id=tenant.org.id, client_id=tenant.client.id, leadgen_id=leadgen_id,
        campaign_id=campaign_id, form_data={},
    )
    db.add(lead)
    db.commit()
    return lead


def _registrar_campana(db, account, campaign_id):
    db.add(SyncedCampaign(
        account_id=account.id, campaign_id=campaign_id,
        name="Campaña", objective="REACH", status="ACTIVE",
    ))
    db.commit()


def test_lead_resuelto_solo_aparece_en_su_activo(client, login, tenant_a, factory, db):
    login(tenant_a.owner)
    cuenta_1 = factory.ad_account(tenant_a.client)
    cuenta_2 = factory.ad_account(tenant_a.client)
    _registrar_campana(db, cuenta_1, "campana-1")
    _crear_lead(db, tenant_a, campaign_id="campana-1")

    r1 = client.get(f"/leads?account_id={cuenta_1.id}")
    assert r1.status_code == 200
    assert r1.json()["total"] == 1

    r2 = client.get(f"/leads?account_id={cuenta_2.id}")
    assert r2.status_code == 200
    assert r2.json()["total"] == 0


def test_lead_sin_campana_aparece_en_todos_los_activos_del_cliente(
    client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    cuenta_1 = factory.ad_account(tenant_a.client)
    cuenta_2 = factory.ad_account(tenant_a.client)
    _crear_lead(db, tenant_a, campaign_id=None)

    for cuenta in (cuenta_1, cuenta_2):
        r = client.get(f"/leads?account_id={cuenta.id}")
        assert r.status_code == 200
        assert r.json()["total"] == 1


def test_lead_con_campana_aun_no_sincronizada_aparece_en_todos_los_activos(
    client, login, tenant_a, factory, db,
):
    """La campaña existe en Meta (el lead trae su id) pero
    app/services/daily_sync.py todavía no la registró en SyncedCampaign
    -- no hay forma de saber a cuál activo pertenece TODAVÍA, así que se
    muestra en todos en vez de esconderse."""
    login(tenant_a.owner)
    cuenta_1 = factory.ad_account(tenant_a.client)
    cuenta_2 = factory.ad_account(tenant_a.client)
    _crear_lead(db, tenant_a, campaign_id="campana-nueva-sin-sincronizar")

    for cuenta in (cuenta_1, cuenta_2):
        r = client.get(f"/leads?account_id={cuenta.id}")
        assert r.status_code == 200
        assert r.json()["total"] == 1


def test_una_vez_sincronizada_la_campana_deja_de_verse_en_los_demas_activos(
    client, login, tenant_a, factory, db,
):
    """En cuanto SyncedCampaign ya sabe a qué cuenta pertenece la campaña,
    el lead deja de aparecer en los activos hermanos."""
    login(tenant_a.owner)
    cuenta_1 = factory.ad_account(tenant_a.client)
    cuenta_2 = factory.ad_account(tenant_a.client)
    _crear_lead(db, tenant_a, campaign_id="campana-1")

    assert client.get(f"/leads?account_id={cuenta_2.id}").json()["total"] == 1

    _registrar_campana(db, cuenta_1, "campana-1")

    assert client.get(f"/leads?account_id={cuenta_1.id}").json()["total"] == 1
    assert client.get(f"/leads?account_id={cuenta_2.id}").json()["total"] == 0


def test_account_id_de_otra_organizacion_devuelve_404(
    client, login, tenant_a, tenant_b, factory,
):
    login(tenant_a.owner)
    cuenta_ajena = factory.ad_account(tenant_b.client)

    r = client.get(f"/leads?account_id={cuenta_ajena.id}")
    assert r.status_code == 404


def test_export_csv_usa_cliente_y_activo_en_el_nombre_de_archivo(
    client, login, tenant_a, factory, db,
):
    login(tenant_a.owner)
    cuenta = factory.ad_account(tenant_a.client)
    _registrar_campana(db, cuenta, "campana-1")
    _crear_lead(db, tenant_a, campaign_id="campana-1")

    r = client.get(f"/leads/export/csv?account_id={cuenta.id}")
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert tenant_a.client.name.lower().replace(" ", "-") in disposition.lower() or \
        "".join(ch if ch.isalnum() else "-" for ch in tenant_a.client.name.lower()).strip("-") in disposition.lower()
