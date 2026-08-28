"""
PATCH /users/me y POST /users/me/password — Ajustes > Cuenta.

La página de Ajustes era de solo lectura (nombre, correo, rol) más el tipo
de cambio. Estas dos rutas la vuelven funcional: cada quien edita su propio
perfil y preferencias de reporte, y puede cambiar su contraseña sin pasar
por un owner/admin.
"""
from __future__ import annotations

from app.core.security import hash_password, verify_password
from app.models import User


def test_puedo_editar_mi_propio_perfil(client, login, tenant_a):
    login(tenant_a.member)
    r = client.patch("/users/me", json={
        "full_name": "Nuevo Nombre",
        "job_title": "Traficker",
        "default_currency": "GTQ",
        "default_cadence": "mensual",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Nuevo Nombre"
    assert body["job_title"] == "Traficker"
    assert body["default_currency"] == "GTQ"
    assert body["default_cadence"] == "mensual"


def test_actualizacion_parcial_no_toca_lo_que_no_viene(client, login, tenant_a):
    """Solo mandar job_title no debe borrar default_currency ya guardada."""
    login(tenant_a.member)
    client.patch("/users/me", json={"default_currency": "USD"})
    r = client.patch("/users/me", json={"job_title": "Director"})
    assert r.status_code == 200
    assert r.json()["job_title"] == "Director"
    assert r.json()["default_currency"] == "USD"


def test_un_input_vacio_borra_el_cargo_en_vez_de_guardar_texto_vacio(client, login, tenant_a):
    login(tenant_a.member)
    client.patch("/users/me", json={"job_title": "Traficker"})
    r = client.patch("/users/me", json={"job_title": "   "})
    assert r.status_code == 200
    assert r.json()["job_title"] is None


def test_moneda_invalida_se_rechaza(client, login, tenant_a):
    login(tenant_a.member)
    r = client.patch("/users/me", json={"default_currency": "EUR"})
    assert r.status_code == 422


def test_cadencia_invalida_se_rechaza(client, login, tenant_a):
    login(tenant_a.member)
    r = client.patch("/users/me", json={"default_cadence": "semanal"})
    assert r.status_code == 422


def test_no_puedo_tocar_el_perfil_de_otro_usuario(client, login, tenant_a):
    """No existe ninguna ruta PATCH /users/me?user_id=X — el propio JWT
    determina de quién es el perfil, así que esto ni se puede intentar."""
    login(tenant_a.member)
    r = client.patch("/users/me", json={"full_name": "Suplantado"})
    assert r.status_code == 200

    login(tenant_a.admin)
    assert client.get("/auth/me").json()["full_name"] != "Suplantado"


def test_cambiar_contrasena_exitosamente(client, login, tenant_a, db):
    tenant_a.member.hashed_password = hash_password("clave-original-2026")
    db.commit()

    login(tenant_a.member)
    r = client.post("/users/me/password", json={
        "current_password": "clave-original-2026",
        "new_password": "clave-nueva-segura-2026",
    })
    assert r.status_code == 204

    db.refresh(tenant_a.member)
    assert verify_password("clave-nueva-segura-2026", tenant_a.member.hashed_password)
    assert not verify_password("clave-original-2026", tenant_a.member.hashed_password)


def test_cambiar_contrasena_con_la_actual_incorrecta_se_rechaza(client, login, tenant_a, db):
    tenant_a.member.hashed_password = hash_password("clave-original-2026")
    db.commit()

    login(tenant_a.member)
    r = client.post("/users/me/password", json={
        "current_password": "esta-no-es-la-actual",
        "new_password": "clave-nueva-segura-2026",
    })
    assert r.status_code == 401

    db.refresh(tenant_a.member)
    assert verify_password("clave-original-2026", tenant_a.member.hashed_password)


def test_contrasena_nueva_corta_se_rechaza(client, login, tenant_a, db):
    tenant_a.member.hashed_password = hash_password("clave-original-2026")
    db.commit()

    login(tenant_a.member)
    r = client.post("/users/me/password", json={
        "current_password": "clave-original-2026",
        "new_password": "corta",
    })
    assert r.status_code == 422
