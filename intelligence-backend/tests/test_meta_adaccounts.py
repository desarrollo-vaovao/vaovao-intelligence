"""
GET /clients/meta-adaccounts — la lista que alimenta el selector de "Agregar
activo" en Clientes, para no copiar act_XXXXXXXXXX a mano desde Business
Manager.

Junta TODOS los tokens disponibles (resolve_tokens: Facebook personal +
tokens centrales de la organización) y deduplica por id de cuenta, porque la
misma cuenta puede ser visible por más de un token (acceso directo Y
compartida con un portafolio).
"""
from __future__ import annotations

import app.api.routes.clients as clients_routes
from app.services import meta_api


def _cuenta(id_: str, name: str) -> dict:
    return {"id": id_, "name": name}


def test_junta_cuentas_de_varios_tokens_sin_duplicar(client, login, tenant_a, monkeypatch):
    """Dos tokens ven cuentas distintas, y una en común: la de la lista final
    aparece una sola vez."""
    login(tenant_a.owner)
    monkeypatch.setattr(
        clients_routes, "resolve_tokens", lambda current, db: (["token-a", "token-b"], None)
    )

    async def fake_list_ad_accounts(token):
        if token == "token-a":
            return {"accounts": [_cuenta("act_1", "Cuenta Uno"), _cuenta("act_2", "Compartida")], "warnings": []}
        return {"accounts": [_cuenta("act_2", "Compartida (otro nombre)"), _cuenta("act_3", "Cuenta Tres")], "warnings": []}

    monkeypatch.setattr(meta_api, "list_ad_accounts", fake_list_ad_accounts)

    r = client.get("/clients/meta-adaccounts")
    assert r.status_code == 200
    body = r.json()
    ids = sorted(a["id"] for a in body["accounts"])
    assert ids == ["act_1", "act_2", "act_3"]
    # La primera copia gana; no importa cuál, pero no debe haber dos filas.
    assert len([a for a in body["accounts"] if a["id"] == "act_2"]) == 1


def test_sin_tokens_devuelve_503(client, login, tenant_a, monkeypatch):
    """Sin Facebook conectado ni tokens centrales, no hay nada que listar."""
    login(tenant_a.owner)
    monkeypatch.setattr(
        clients_routes, "resolve_tokens",
        lambda current, db: ([], "No has conectado tu Facebook y no hay tokens centrales (Conexión Meta)."),
    )
    r = client.get("/clients/meta-adaccounts")
    assert r.status_code == 503


def test_un_token_que_falla_no_tumba_la_lista(client, login, tenant_a, monkeypatch):
    """Si un token da error (permiso revocado, etc.), sus cuentas se pierden
    pero las del resto de los tokens siguen apareciendo — igual que
    meta_api.list_ad_accounts es tolerante a fallos por fuente."""
    login(tenant_a.owner)
    monkeypatch.setattr(
        clients_routes, "resolve_tokens", lambda current, db: (["token-malo", "token-bueno"], None)
    )

    async def fake_list_ad_accounts(token):
        if token == "token-malo":
            raise meta_api.MetaApiError("token expirado")
        return {"accounts": [_cuenta("act_9", "Cuenta Nueve")], "warnings": []}

    monkeypatch.setattr(meta_api, "list_ad_accounts", fake_list_ad_accounts)

    r = client.get("/clients/meta-adaccounts")
    assert r.status_code == 200
    body = r.json()
    assert [a["id"] for a in body["accounts"]] == ["act_9"]
    assert any("token expirado" in w for w in body["warnings"])


def test_cualquier_rol_puede_listar(client, login, tenant_a, monkeypatch):
    """Igual que agregar un activo, no está restringido a owner/admin."""
    monkeypatch.setattr(
        clients_routes, "resolve_tokens", lambda current, db: (["token"], None)
    )

    async def fake_list_ad_accounts(token):
        return {"accounts": [_cuenta("act_1", "Cuenta")], "warnings": []}

    monkeypatch.setattr(meta_api, "list_ad_accounts", fake_list_ad_accounts)

    login(tenant_a.member)
    assert client.get("/clients/meta-adaccounts").status_code == 200


def test_orden_alfabetico_por_nombre(client, login, tenant_a, monkeypatch):
    """El frontend no reordena: el orden lo define este endpoint."""
    login(tenant_a.owner)
    monkeypatch.setattr(clients_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_list_ad_accounts(token):
        return {
            "accounts": [_cuenta("act_2", "Zebra"), _cuenta("act_1", "Alfa")],
            "warnings": [],
        }

    monkeypatch.setattr(meta_api, "list_ad_accounts", fake_list_ad_accounts)

    r = client.get("/clients/meta-adaccounts")
    names = [a["name"] for a in r.json()["accounts"]]
    assert names == ["Alfa", "Zebra"]
