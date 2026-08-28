"""
POST /organization/meta-credentials ya NO crea un Client automáticamente.

Se probó (un portafolio de Meta ~1:1 con un cliente), pero contaminaba el
switcher de cliente del sidebar con nombres de portafolios sin ningún
activo comercial configurado — clientes fantasma. Dar de alta un cliente
sigue siendo manual, en Clientes.
"""
from __future__ import annotations

from app.models import Client


def test_agregar_token_no_crea_cliente(client, login, tenant_a, db):
    login(tenant_a.owner)
    clientes_antes = db.query(Client).filter(Client.org_id == tenant_a.org.id).count()

    r = client.post("/organization/meta-credentials", json={
        "label": "Portafolio Nuevo",
        "system_user_token": "token-de-prueba-suficientemente-largo",
    })

    assert r.status_code == 201
    clientes_despues = db.query(Client).filter(Client.org_id == tenant_a.org.id).count()
    assert clientes_despues == clientes_antes
    assert not any(c.name == "Portafolio Nuevo" for c in db.query(Client).all())
