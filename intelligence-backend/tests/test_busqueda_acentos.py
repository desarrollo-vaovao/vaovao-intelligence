"""
Búsqueda con acentos, insensible a mayúsculas — corre en cualquier motor.

Historia de este archivo (por qué ya NO requiere Postgres)
------------------------------------------------------------
La hipótesis original era que esto era un límite de SQLite: su `lower()`
es ASCII-only, así que "JOSÉ".lower() en SQLite da "josÉ" (la É no baja), y
por eso una búsqueda en mayúsculas de un término acentuado fallaría ahí. La
prueba se escribió gateada con `require_postgres`, asumiendo que en
Postgres el ILIKE nativo sí resolvería el acento.

Al correrla contra un Postgres real por primera vez, siguió fallando. La
causa real no tenía nada que ver con el motor: `_search_condition()`
(`app/crud/leads.py`) busca contra el JSON ya serializado con
`json.dumps(..., ensure_ascii=True)`, así que "José" queda escrito en la
columna como `Jos\\u00e9`. "É" (U+00C9) escapa a `\\u00c9`; "é" (U+00E9)
escapa a `\\u00e9`. Esos dos dígitos hexadecimales, `c` y `e`, NO son una
letra en dos mayúsculas — son dos caracteres distintos. Ningún ILIKE ni
collation de ningún motor pliega `c` sobre `e`, porque ahí no hay
mayúscula/minúscula que resolver: esa información ya se perdió al escapar.

El fix real fue en `_like_patterns()`: generar también `term.lower()` y
`term.upper()` del término COMPLETO antes de escapar, no después. Buscar
"JOSÉ" ahora también prueba el escapado de "josé", que sí es
`jos\\u00e9` — coincide con lo guardado salvo por la J/j inicial, que ILIKE
pliega sin problema por ser ASCII puro. Verificado que esto ya funciona
igual en SQLite que en Postgres, así que el test no necesita
`require_postgres`: no era un hueco de motor, era un bug de Python.
"""
from __future__ import annotations

from app.crud.leads import list_leads_for_user


def test_busqueda_encuentra_nombre_acentuado_en_mayusculas(factory, tenant_a, db) -> None:
    """"JOSÉ" (mayúsculas, con acento) debe encontrar al lead de "José Muñoz"."""
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
    factory, tenant_a, db
) -> None:
    """Control negativo: que el test de arriba no esté pasando por casualidad.

    "jose" (sin tilde) NO debe encontrar "José" — el plegado de mayúsculas
    no implica plegado de acentos; son cosas distintas.
    """
    factory.lead(
        tenant_a.client,
        form_data={"full_name": "José Muñoz", "phone": "555-0001"},
    )

    total, items = list_leads_for_user(db, tenant_a.owner, search="jose")

    assert total == 0, (
        "la búsqueda encontró 'José' buscando 'jose' sin tilde — eso NO es lo "
        "que _search_condition() promete (insensible a mayúsculas, NO a "
        "acentos salvo por las variantes NFC/NFD explícitas de _like_patterns)."
    )


def test_busqueda_con_variante_nfd_del_acento_tambien_encuentra_en_mayusculas(
    factory, tenant_a, db
) -> None:
    """El término de búsqueda puede llegar en NFD (macOS) y el lead en NFC (Windows).

    Combinado con el plegado de mayúsculas, "MUÑOZ" escrito en NFD debe
    encontrar un "Muñoz" guardado en NFC.
    """
    import unicodedata

    nombre_nfc = unicodedata.normalize("NFC", "Muñoz")
    factory.lead(tenant_a.client, form_data={"full_name": f"Ana {nombre_nfc}"})

    termino_nfd = unicodedata.normalize("NFD", "MUÑOZ")
    total, items = list_leads_for_user(db, tenant_a.owner, search=termino_nfd)

    assert total == 1
    assert "Muñoz" in items[0].form_data["full_name"]
