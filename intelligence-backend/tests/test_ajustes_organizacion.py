"""
GET/PATCH /organization/settings — el tipo de cambio USD->GTQ que la
organización configura en Ajustes > General.

Es distinto del resto de rutas de /organization (tokens de Meta): no hay
nada sensible que ocultar aquí, así que GET es para cualquier usuario
autenticado (lo necesita el frontend para convertir el presupuesto al
cambiar de moneda en Resumen/Reportes, sin importar el rol). PATCH sí se
restringe — afecta el gasto en GTQ que ve todo el equipo, no es una
preferencia personal de quien la cambia.
"""
from __future__ import annotations


def test_sin_configurar_devuelve_null_no_cero(client, login, tenant_a):
    """None y 0 significan cosas muy distintas aquí: 0 sería un tipo de
    cambio absurdo que además el backend usaría de verdad para convertir.
    El frontend necesita distinguir "no configurado" de "configurado en 0"."""
    login(tenant_a.owner)
    respuesta = client.get("/organization/settings")

    assert respuesta.status_code == 200
    assert respuesta.json()["exchange_rate_usd_gtq"] is None


def test_cualquier_rol_puede_leer(client, login, tenant_a):
    for user in (tenant_a.owner, tenant_a.admin, tenant_a.member):
        login(user)
        assert client.get("/organization/settings").status_code == 200


def test_owner_puede_configurar_el_tipo_de_cambio(client, login, tenant_a):
    login(tenant_a.owner)
    respuesta = client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 7.8})

    assert respuesta.status_code == 200
    assert respuesta.json()["exchange_rate_usd_gtq"] == 7.8
    # Y que de verdad haya quedado guardado, no solo en la respuesta.
    assert client.get("/organization/settings").json()["exchange_rate_usd_gtq"] == 7.8


def test_admin_tambien_puede_configurarlo(client, login, tenant_a):
    login(tenant_a.admin)
    respuesta = client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 7.9})
    assert respuesta.status_code == 200


def test_member_no_puede_configurarlo(client, login, tenant_a):
    """Ve el valor (test_cualquier_rol_puede_leer) pero no lo cambia:
    afecta los reportes de toda la organización, no solo los suyos."""
    login(tenant_a.member)
    respuesta = client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 99.0})
    assert respuesta.status_code == 403


def test_rechaza_un_tipo_de_cambio_cero_o_negativo(client, login, tenant_a):
    """Un tipo de cambio <= 0 no es un error de tipeo cualquiera: convertiría
    todo el gasto en cero o negativo en cada reporte en GTQ de la
    organización hasta que alguien lo notara."""
    login(tenant_a.owner)

    assert client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 0}).status_code == 422
    assert client.patch("/organization/settings", json={"exchange_rate_usd_gtq": -5}).status_code == 422


def test_no_afecta_a_otra_organizacion(client, login, tenant_a, tenant_b):
    """Cada organización tiene su propio tipo de cambio — no es un ajuste
    global de la aplicación."""
    login(tenant_a.owner)
    client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 7.5})

    login(tenant_b.owner)
    respuesta = client.get("/organization/settings")

    assert respuesta.json()["exchange_rate_usd_gtq"] is None


# ── Ventana de atribución (Ajustes > Preferencias de reporte) ─────
# Mismo RBAC que el tipo de cambio y por la misma razón: cambia los números
# que ve TODO el equipo en cada reporte, no es una preferencia personal.


def test_atribucion_sin_configurar_devuelve_null(client, login, tenant_a):
    login(tenant_a.owner)
    assert client.get("/organization/settings").json()["attribution_window"] is None


def test_owner_puede_configurar_la_atribucion(client, login, tenant_a):
    login(tenant_a.owner)
    r = client.patch("/organization/settings", json={"attribution_window": "7d_click"})
    assert r.status_code == 200
    assert r.json()["attribution_window"] == "7d_click"
    assert client.get("/organization/settings").json()["attribution_window"] == "7d_click"


def test_member_no_puede_configurar_la_atribucion(client, login, tenant_a):
    login(tenant_a.member)
    r = client.patch("/organization/settings", json={"attribution_window": "7d_click"})
    assert r.status_code == 403


def test_ventana_de_atribucion_invalida_se_rechaza(client, login, tenant_a):
    """Solo las que report_builder sabe traducir a parámetros reales de
    Meta (ver schemas.ATTRIBUTION_WINDOWS) — cualquier otra cosa se
    rechaza en vez de mandarse tal cual a la API de Meta."""
    login(tenant_a.owner)
    r = client.patch("/organization/settings", json={"attribution_window": "30d_click"})
    assert r.status_code == 422


def test_cambiar_solo_la_atribucion_no_borra_el_tipo_de_cambio(client, login, tenant_a):
    """PATCH es parcial: cada preferencia se cambia en su propio momento sin
    que el frontend tenga que conocer siempre el valor actual de la otra."""
    login(tenant_a.owner)
    client.patch("/organization/settings", json={"exchange_rate_usd_gtq": 7.75})

    r = client.patch("/organization/settings", json={"attribution_window": "1d_click"})

    assert r.status_code == 200
    assert r.json()["exchange_rate_usd_gtq"] == 7.75
    assert r.json()["attribution_window"] == "1d_click"


def test_atribucion_no_se_filtra_entre_organizaciones(client, login, tenant_a, tenant_b):
    login(tenant_a.owner)
    client.patch("/organization/settings", json={"attribution_window": "7d_click_1d_view"})

    login(tenant_b.owner)
    assert client.get("/organization/settings").json()["attribution_window"] is None
