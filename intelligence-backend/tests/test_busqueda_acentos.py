"""
Hueco 3: búsqueda con acentos, insensible a mayúsculas, en Postgres real.

Por qué NO se puede cerrar esto sobre SQLite
---------------------------------------------
`_search_condition()` (app/crud/leads.py) arma un `CAST(form_data AS TEXT)
ILIKE '%patrón%'` y cubre a propósito CUATRO variantes del término buscado
—literal y su escape `\\uXXXX` de `json.dumps(ensure_ascii=True)`, cada una
en NFC y en NFD— para que "José" encuentre a "José" sin importar cómo haya
llegado el acento. Ese armado de patrones es independiente del motor y ya
se prueba sobre SQLite.

Lo que SQLite no puede probar es el otro lado del ILIKE: `lower()` de SQLite
es ASCII-only. "JOSÉ".lower() en SQLite da "josÉ" (la É no baja), así que
una búsqueda en mayúsculas de un término acentuado falla ahí aunque las
cuatro variantes de `_like_patterns()` estén perfectas — el propio docstring
de `_search_condition()` lo declara como limitación conocida y remite a
Postgres como el motor donde ILIKE sí resuelve el acento. Sobre SQLite,
"probar" esto sería certificar el comportamiento roto como si fuera el
correcto.

Qué hace esta prueba
---------------------
Inserta un lead con un nombre acentuado en `form_data` y busca con
combinaciones de mayúsculas/minúsculas y acentos vía la función real
`list_leads_for_user()` (la misma que usa el endpoint), contra Postgres.
"""
from __future__ import annotations

from app.crud.leads import list_leads_for_user


def test_busqueda_encuentra_nombre_acentuado_en_mayusculas_sobre_postgres(
    require_postgres: str, factory, tenant_a, db
) -> None:
    """"JOSÉ" (mayúsculas, con acento) debe encontrar al lead de "José Muñoz".

    Sobre SQLite esta misma búsqueda falla porque `lower()` no toca la É.
    `require_postgres` hace que la prueba se salte ahí en vez de fingir que
    pasó — ver docstring del módulo.
    """
    factory.lead(
        tenant_a.client,
        form_data={"full_name": "José Muñoz", "phone": "555-0001"},
    )
    factory.lead(
        tenant_a.client,
        form_data={"full_name": "Alguien Sin Relación", "phone": "555-0002"},
    )

    total, items = list_leads_for_user(db, tenant_a.owner, search="JOSÉ")

    assert total == 1, "la búsqueda en mayúsculas con acento no encontró al lead esperado"
    assert items[0].form_data["full_name"] == "José Muñoz"


def test_busqueda_sin_acento_no_encuentra_termino_acentuado_por_accidente(
    require_postgres: str, factory, tenant_a, db
) -> None:
    """Control negativo: que el test de arriba no esté pasando por casualidad.

    "jose" (sin tilde) NO debe encontrar "José" — ILIKE normaliza mayúsculas,
    no acentos. Si este control fallara (encontrara el lead), significaría
    que el aserto de la prueba positiva no está probando lo que dice probar.
    """
    factory.lead(
        tenant_a.client,
        form_data={"full_name": "José Muñoz", "phone": "555-0001"},
    )

    total, items = list_leads_for_user(db, tenant_a.owner, search="jose")

    assert total == 0, (
        "ILIKE encontró 'José' buscando 'jose' sin tilde — eso NO es lo que "
        "_search_condition() promete (insensible a mayúsculas, NO a acentos "
        "salvo por las variantes NFC/NFD explícitas de _like_patterns)."
    )


def test_busqueda_con_variante_nfd_del_acento_tambien_encuentra_en_mayusculas(
    require_postgres: str, factory, tenant_a, db
) -> None:
    """El término de búsqueda puede llegar en NFD (macOS) y el lead en NFC (Windows).

    `_like_patterns()` genera ambas normalizaciones del TÉRMINO buscado; esta
    prueba confirma que, sumado al ILIKE case-insensitive real de Postgres,
    "MUÑOZ" escrito en NFD encuentra un "Muñoz" guardado en NFC.
    """
    import unicodedata

    nombre_nfc = unicodedata.normalize("NFC", "Muñoz")
    factory.lead(tenant_a.client, form_data={"full_name": f"Ana {nombre_nfc}"})

    termino_nfd = unicodedata.normalize("NFD", "MUÑOZ")
    total, items = list_leads_for_user(db, tenant_a.owner, search=termino_nfd)

    assert total == 1
    assert "Muñoz" in items[0].form_data["full_name"]
