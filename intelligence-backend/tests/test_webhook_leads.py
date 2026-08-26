"""
B. `POST /leads/sync-webhook` — la única puerta abierta a Internet sin JWT.

Tres familias de regresión viven aquí, y las tres son silenciosas:

1. **Autenticación.** El endpoint no tiene JWT: lo defiende un secreto
   compartido y nada más. Una comparación que se degrade a `==` o a un
   chequeo de largo no rompe ninguna prueba de negocio — sigue aceptando el
   token bueno. Por eso se prueba explícitamente el token equivocado DEL
   MISMO LARGO: es el único caso que distingue "compara" de "mide".

2. **Fuga del secreto.** El token viaja en el cuerpo, y FastAPI devuelve el
   cuerpo dentro de `input` en su 422 por defecto. Un payload con token
   VÁLIDO al que le falte otro campo devolvía el secreto en texto plano a
   quien lo mandó (y a cualquier proxy o log de acceso en el camino). Lo
   cierra `_LeadsRoute`; quitarla no rompería ninguna otra prueba.

3. **El código de estado.** Quien llama reintenta ante cualquier no-2xx. Un
   código mal elegido no produce un error visible: produce un bucle infinito
   o un lead perdido en silencio. Por eso ninguna prueba de este archivo se
   conforma con el status: siempre comprueba además QUÉ FILA quedó en la
   base. Un endpoint que respondiera 200 y no guardara nada es exactamente
   el fallo de "pérdida silenciosa" y pasaría una prueba que sólo mirara el
   código.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ClientPage, Lead, LeadAudit, OrphanLead
from tests.conftest import TEST_SYNC_TOKEN

WEBHOOK = "/leads/sync-webhook"


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _payload(
    page_id: str,
    leadgen_id: str = "leadgen-webhook-1",
    *,
    token: str = TEST_SYNC_TOKEN,
    **extra,
) -> dict:
    """Cuerpo completo y válido; `extra` sobrescribe o agrega campos."""
    body = {
        "leadgen_id": leadgen_id,
        "page_id": page_id,
        "form_id": "form-123",
        "campaign_name": "Campaña de prueba",
        "form_data": {"full_name": "Ana Pérez", "phone": "+502 5541 2290"},
        "token": token,
    }
    body.update(extra)
    return body


# ═════════════════════════════════════════════════════════════════
#  1. Autenticación por secreto compartido
# ═════════════════════════════════════════════════════════════════
def test_el_token_valido_es_aceptado_y_el_lead_queda_guardado(client, tenant_a, db):
    """Si esto falla, el webhook dejó de recibir leads: la entrada se cerró."""
    assert _count(db, Lead) == 0

    response = client.post(WEBHOOK, json=_payload(tenant_a.page.page_id))

    assert response.status_code == 200
    assert response.json()["action"] == "created"
    db.expire_all()
    assert _count(db, Lead, Lead.leadgen_id == "leadgen-webhook-1") == 1


def test_un_token_equivocado_recibe_401_y_no_escribe_nada(client, tenant_a, db):
    """Si esto falla, cualquiera en Internet puede inyectar leads."""
    response = client.post(
        WEBHOOK, json=_payload(tenant_a.page.page_id, token="token-equivocado")
    )

    assert response.status_code == 401
    db.expire_all()
    assert _count(db, Lead) == 0
    assert _count(db, OrphanLead) == 0


def test_un_token_equivocado_del_mismo_largo_tambien_es_rechazado(client, tenant_a, db):
    """La prueba que distingue una comparación real de un chequeo de largo.

    `hmac.compare_digest` recorre siempre todo el largo, así que dos cadenas
    del mismo tamaño y distinto contenido no pasan. Una implementación
    degradada que sólo mirara `len()` —o cualquier atajo que se cuele en una
    refactorización— seguiría aceptando el token bueno y rechazando los
    obviamente cortos: sólo este caso la delata.
    """
    falso = "X" * len(TEST_SYNC_TOKEN)
    # Sin estos asertos la prueba mediría otra cosa: si los largos no
    # coincidieran, un chequeo de largo también rechazaría y el verde no
    # probaría nada.
    assert len(falso) == len(TEST_SYNC_TOKEN)
    assert falso != TEST_SYNC_TOKEN

    response = client.post(WEBHOOK, json=_payload(tenant_a.page.page_id, token=falso))

    assert response.status_code == 401
    db.expire_all()
    assert _count(db, Lead) == 0


def test_un_cuerpo_sin_token_recibe_el_mismo_401_que_uno_equivocado(client, tenant_a):
    """Si esto falla, el 422 de "Field required" delata cuál campo es el token.

    Un cuerpo sin `token` muere en Pydantic antes del endpoint. Sin
    `_is_token_error` saldría como 422 diciendo exactamente qué campo falta,
    que es justo la diferencia entre "no mandaste token" y "mandaste uno
    equivocado" que el 401 genérico existe para esconder.
    """
    sin_token = _payload(tenant_a.page.page_id)
    del sin_token["token"]

    con_token_malo = client.post(
        WEBHOOK, json=_payload(tenant_a.page.page_id, token="nope")
    )
    sin = client.post(WEBHOOK, json=sin_token)

    assert sin.status_code == 401
    assert con_token_malo.status_code == 401
    # Idéntico cuerpo: si difirieran, la diferencia sería la señal.
    assert sin.json() == con_token_malo.json()


def test_el_401_no_revela_por_que_fallo_la_autenticacion(client, tenant_a):
    """Un mensaje que distinga "falta"/"mal formado"/"incorrecto" es media pista."""
    response = client.post(WEBHOOK, json=_payload(tenant_a.page.page_id, token="nope"))

    assert response.status_code == 401
    assert response.json()["detail"] == "No autorizado."


# ═════════════════════════════════════════════════════════════════
#  2. El secreto no vuelve en NINGUNA respuesta
# ═════════════════════════════════════════════════════════════════
def test_el_token_no_aparece_en_la_respuesta_exitosa(client, tenant_a):
    """Si esto falla, cada lead ingresado publica el secreto de vuelta."""
    response = client.post(WEBHOOK, json=_payload(tenant_a.page.page_id))

    assert response.status_code == 200
    assert TEST_SYNC_TOKEN not in response.text


def test_el_token_no_aparece_en_el_401(client, tenant_a):
    """Un 401 que devuelva el token recibido se lo regala a quien lea el log."""
    response = client.post(
        WEBHOOK, json=_payload(tenant_a.page.page_id, token=TEST_SYNC_TOKEN + "x")
    )

    assert response.status_code == 401
    assert TEST_SYNC_TOKEN not in response.text


def test_el_token_valido_no_aparece_en_el_422_de_validacion(client, db):
    """LA regresión que motiva `_LeadsRoute`: el 422 devolvía el secreto en claro.

    El cuerpo trae un token VÁLIDO y le falta `page_id`. Con el manejador por
    defecto de FastAPI la respuesta incluye `input` con el cuerpo completo —
    token adentro— y ese 422 termina en el log de acceso del proxy y en el
    del servicio que llama. Quitar `route_class=_LeadsRoute` del router hace
    fallar exactamente esta prueba.
    """
    cuerpo = _payload("da-igual")
    del cuerpo["page_id"]

    response = client.post(WEBHOOK, json=cuerpo)

    # Precondición: la validación TIENE que haber fallado, y por `page_id`.
    # Si el endpoint aceptara el cuerpo, el aserto de abajo pasaría sin
    # comprobar ningún saneo.
    assert response.status_code == 422
    assert any("page_id" in (err.get("loc") or []) for err in response.json()["detail"])
    # Precondición 2: el token que se busca en el texto es el real.
    assert cuerpo["token"] == TEST_SYNC_TOKEN
    assert TEST_SYNC_TOKEN not in response.text
    db.expire_all()
    assert _count(db, Lead) == 0


def test_un_payload_malformado_responde_422_sin_repetir_el_cuerpo(client, tenant_a):
    """El 422 conserva dónde y qué falló, nunca el valor que llegó.

    `leadgen_id` vacío incumple `min_length=1`. La respuesta debe traer
    `loc`/`msg`/`type` y NADA más: la clave `input` de FastAPI es la que
    filtra el cuerpo.
    """
    response = client.post(WEBHOOK, json=_payload(tenant_a.page.page_id, leadgen_id=""))

    assert response.status_code == 422
    errores = response.json()["detail"]
    assert errores, "sin errores, el aserto de las claves no comprobaría nada"
    for err in errores:
        assert set(err) == {"loc", "msg", "type"}


# ═════════════════════════════════════════════════════════════════
#  3. Semántica de reintento: 200 sólo si reintentar no ayudaría
# ═════════════════════════════════════════════════════════════════
def test_la_reentrega_del_mismo_payload_responde_200_y_no_duplica(client, tenant_a, db):
    """Meta reentrega de rutina. Un 4xx aquí pediría un tercer intento idéntico."""
    cuerpo = _payload(tenant_a.page.page_id)

    primera = client.post(WEBHOOK, json=cuerpo)
    assert primera.status_code == 200
    assert primera.json()["action"] == "created"

    segunda = client.post(WEBHOOK, json=cuerpo)

    assert segunda.status_code == 200
    assert segunda.json()["action"] == "updated"
    db.expire_all()
    assert _count(db, Lead, Lead.leadgen_id == cuerpo["leadgen_id"]) == 1


def test_un_lead_de_pagina_no_configurada_responde_200_y_queda_como_huerfano(client, db):
    """200 + fila huérfana. Comprobar sólo el 200 dejaría pasar la pérdida silenciosa.

    Un endpoint que respondiera 200 y tirara el lead pasaría una prueba que
    sólo mirara el status, y nadie se enteraría: quien llama da el lead por
    entregado y no reintenta. Por eso se afirma también la fila.
    """
    assert _count(db, ClientPage, ClientPage.page_id == "pagina-sin-dueno") == 0

    response = client.post(WEBHOOK, json=_payload("pagina-sin-dueno"))

    assert response.status_code == 200
    assert response.json()["action"] == "orphaned"
    db.expire_all()
    assert _count(db, OrphanLead, OrphanLead.page_id == "pagina-sin-dueno") == 1
    assert _count(db, Lead) == 0


def test_la_reentrega_de_un_huerfano_no_crea_una_segunda_fila(client, db):
    """El huérfano también se deduplica: Meta lo reentrega como a cualquier otro."""
    cuerpo = _payload("pagina-sin-dueno")

    assert client.post(WEBHOOK, json=cuerpo).status_code == 200
    db.expire_all()
    assert _count(db, OrphanLead) == 1

    segunda = client.post(WEBHOOK, json=cuerpo)

    assert segunda.status_code == 200
    assert segunda.json()["action"] == "orphaned"
    db.expire_all()
    assert _count(db, OrphanLead) == 1


# ═════════════════════════════════════════════════════════════════
#  4. La reentrega NO puede pisar el trabajo del equipo comercial
# ═════════════════════════════════════════════════════════════════
def test_una_reentrega_conserva_estado_responsable_y_notas_del_crm(
    client, tenant_a, db
):
    """La regresión más cara del módulo: un negocio cerrado que vuelve a "nuevo".

    La reentrega de Meta trae `status: nuevo` (el default del schema) porque
    Meta no sabe nada del pipeline de VaoVao. Si la ingesta pisara los campos
    que edita un humano, una reentrega rutinaria —que ocurre sola, sin que
    nadie la pida— devolvería a `nuevo` un lead marcado `ganado` y borraría a
    quién estaba asignado y sus notas. Nada lo avisaría.

    La reentrega además cambia `form_data` para que el camino de refresco SÍ
    se ejecute: si no, un `_refresh_from_meta` que no hiciera absolutamente
    nada también pasaría, y no es lo que se quiere probar.
    """
    cuerpo = _payload(tenant_a.page.page_id)
    assert client.post(WEBHOOK, json=cuerpo).status_code == 200

    db.expire_all()
    lead = db.scalar(select(Lead).where(Lead.leadgen_id == cuerpo["leadgen_id"]))
    assert lead is not None
    lead_id = lead.id
    lead.status = "ganado"
    lead.assigned_to_id = tenant_a.member.id
    lead.notes = "Cerrado por teléfono el martes."
    db.commit()

    # Precondición: el trabajo del CRM está puesto ANTES de la reentrega.
    db.expire_all()
    antes = db.get(Lead, lead_id)
    assert antes.status == "ganado"
    assert antes.assigned_to_id == tenant_a.member.id
    assert antes.notes == "Cerrado por teléfono el martes."

    reentrega = dict(cuerpo)
    reentrega["status"] = "nuevo"
    reentrega["form_data"] = {"full_name": "Ana Pérez", "email": "ana@ejemplo.test"}

    response = client.post(WEBHOOK, json=reentrega)

    assert response.status_code == 200
    assert response.json()["action"] == "updated"
    db.expire_all()
    vuelto = db.get(Lead, lead_id)
    assert vuelto.status == "ganado"
    assert vuelto.assigned_to_id == tenant_a.member.id
    assert vuelto.notes == "Cerrado por teléfono el martes."
    # Y el camino de refresco sí corrió: lo que SÍ viene de Meta se actualizó.
    assert vuelto.form_data == reentrega["form_data"]


# ═════════════════════════════════════════════════════════════════
#  5. Ciclo de vida del huérfano
# ═════════════════════════════════════════════════════════════════
def test_al_reconciliar_el_huerfano_se_vuelve_lead_del_cliente_correcto(
    client, login, factory, tenant_a, db
):
    """Un huérfano reconciliado al tenant equivocado es una fuga entre clientes."""
    page_id = "pagina-tardia"
    assert client.post(WEBHOOK, json=_payload(page_id)).status_code == 200
    db.expire_all()
    assert _count(db, OrphanLead, OrphanLead.page_id == page_id) == 1
    assert _count(db, Lead) == 0

    factory.page(tenant_a.client, page_id=page_id)
    login(tenant_a.owner)

    response = client.post(f"/leads/orphans/{page_id}/reconcile")

    assert response.status_code == 200
    assert response.json()["recovered"] == 1
    db.expire_all()
    lead = db.scalar(select(Lead).where(Lead.leadgen_id == "leadgen-webhook-1"))
    assert lead is not None
    assert lead.client_id == tenant_a.client.id
    assert lead.org_id == tenant_a.org.id
    huerfano = db.scalar(select(OrphanLead).where(OrphanLead.page_id == page_id))
    assert huerfano.resolved_at is not None


def test_reconciliar_dos_veces_no_duplica_el_lead(client, login, factory, tenant_a, db):
    """La reconciliación se dispara al dar de alta una página; repetirla es normal."""
    page_id = "pagina-tardia"
    assert client.post(WEBHOOK, json=_payload(page_id)).status_code == 200
    factory.page(tenant_a.client, page_id=page_id)
    login(tenant_a.owner)

    primera = client.post(f"/leads/orphans/{page_id}/reconcile")
    assert primera.status_code == 200
    assert primera.json()["recovered"] == 1
    db.expire_all()
    assert _count(db, Lead, Lead.leadgen_id == "leadgen-webhook-1") == 1

    segunda = client.post(f"/leads/orphans/{page_id}/reconcile")

    assert segunda.status_code == 200
    assert segunda.json()["recovered"] == 0
    db.expire_all()
    assert _count(db, Lead, Lead.leadgen_id == "leadgen-webhook-1") == 1


def test_un_leadgen_id_que_ya_es_lead_nunca_se_guarda_como_huerfano(
    client, factory, tenant_a, db
):
    """La dedup mira `leads` ANTES de resolver la página, y tiene que seguir así.

    Caso real: la `ClientPage` se borró entre una entrega y la siguiente. El
    lead ya existe; mandarlo a `orphan_leads` lo duplicaría y la
    reconciliación tendría que deshacerlo después.
    """
    existente = factory.lead(tenant_a.client, leadgen_id="leadgen-ya-existe")
    assert _count(db, ClientPage, ClientPage.page_id == "pagina-sin-dueno") == 0
    assert _count(db, Lead, Lead.leadgen_id == "leadgen-ya-existe") == 1

    response = client.post(
        WEBHOOK, json=_payload("pagina-sin-dueno", leadgen_id="leadgen-ya-existe")
    )

    assert response.status_code == 200
    assert response.json()["action"] == "updated"
    db.expire_all()
    assert _count(db, OrphanLead) == 0
    assert _count(db, Lead, Lead.leadgen_id == "leadgen-ya-existe") == 1
    assert db.get(Lead, existente.id) is not None


def test_la_reentrega_posterior_al_alta_de_la_pagina_cierra_el_huerfano(
    client, factory, tenant_a, db
):
    """Sin esto, el contador de pendientes de /leads/status miente para siempre.

    El lead quedó huérfano, alguien dio de alta la página y DESPUÉS Meta
    reentregó. La reentrega entra por el camino normal y crea el `Lead` real,
    pero la fila huérfana se quedaba con `resolved_at IS NULL` eternamente:
    `/leads/status` seguiría reportando una página "sin configurar" que ya
    está configurada, y el operador aprendería a ignorar el diagnóstico.
    """
    page_id = "pagina-tardia"
    cuerpo = _payload(page_id)
    assert client.post(WEBHOOK, json=cuerpo).status_code == 200
    db.expire_all()
    huerfano = db.scalar(select(OrphanLead).where(OrphanLead.page_id == page_id))
    # Precondición: nace pendiente. Si ya naciera resuelto, el aserto final
    # no comprobaría el cierre.
    assert huerfano is not None and huerfano.resolved_at is None
    huerfano_id = huerfano.id

    factory.page(tenant_a.client, page_id=page_id)

    response = client.post(WEBHOOK, json=cuerpo)

    assert response.status_code == 200
    assert response.json()["action"] == "created"
    db.expire_all()
    assert _count(db, Lead, Lead.leadgen_id == cuerpo["leadgen_id"]) == 1
    assert db.get(OrphanLead, huerfano_id).resolved_at is not None


# ═════════════════════════════════════════════════════════════════
#  6. Bitácora
# ═════════════════════════════════════════════════════════════════
def test_el_lead_del_webhook_deja_una_fila_created_con_user_id_null(
    client, tenant_a, db
):
    """`user_id IS NULL` es cómo la bitácora dice "lo hizo el sistema".

    El webhook no actúa en nombre de nadie. Hasta que `LeadAudit.user_id` fue
    nullable, la acción `created` no tenía emisor posible y sencillamente no
    se escribía: la línea de tiempo de todo lead entrado por webhook empezaba
    en el aire.
    """
    assert client.post(WEBHOOK, json=_payload(tenant_a.page.page_id)).status_code == 200

    db.expire_all()
    lead = db.scalar(select(Lead).where(Lead.leadgen_id == "leadgen-webhook-1"))
    assert lead is not None
    filas = list(
        db.scalars(
            select(LeadAudit).where(
                LeadAudit.lead_id == lead.id, LeadAudit.action == "created"
            )
        ).all()
    )
    assert len(filas) == 1
    assert filas[0].user_id is None
    assert filas[0].new_value == "nuevo"


def test_una_reentrega_no_escribe_una_segunda_fila_created(client, tenant_a, db):
    """Dos "created" en la bitácora de un mismo lead la vuelven ilegible."""
    cuerpo = _payload(tenant_a.page.page_id)
    assert client.post(WEBHOOK, json=cuerpo).status_code == 200
    db.expire_all()
    lead = db.scalar(select(Lead).where(Lead.leadgen_id == cuerpo["leadgen_id"]))
    assert (
        _count(
            db, LeadAudit, LeadAudit.lead_id == lead.id, LeadAudit.action == "created"
        )
        == 1
    )

    assert client.post(WEBHOOK, json=cuerpo).status_code == 200

    db.expire_all()
    assert (
        _count(
            db, LeadAudit, LeadAudit.lead_id == lead.id, LeadAudit.action == "created"
        )
        == 1
    )
