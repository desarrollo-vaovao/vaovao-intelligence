"""
Capa CRUD del módulo de leads.

Dos reglas que NO se negocian en este archivo:

1. Aislamiento multi-tenant: toda query de listado filtra por `org_id`.
   Una fuga entre organizaciones es el peor fallo posible de este módulo,
   así que el filtro no es opcional ni "lo pone el router": vive aquí.

2. RBAC de visibilidad: `owner` y `admin` ven todos los leads de su
   organización; `member` ve únicamente los leads asignados a él mismo.
   Se aplica en `_visibility_conditions()`, un solo lugar, y tanto el
   conteo como la página de resultados lo comparten — no hay dos
   funciones de listado con la cadena de filtros duplicada.

Estilo: SQLAlchemy 2.0 síncrono (`select()` + `db.scalar/db.scalars`),
igual que app/api/routes/clients.py y users.py.
"""
from __future__ import annotations

import enum
import json
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Lead, LeadAudit, User, UserRole

# Tope duro de tamaño de página: nadie pide 100.000 leads de un jalón.
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 50

# Campos que `update_lead()` acepta modificar. Todo lo demás (org_id,
# client_id, leadgen_id, received_at...) es inmutable desde el API.
UPDATABLE_FIELDS = frozenset({"status", "assigned_to_id", "notes"})

# Carácter de escape para los LIKE/ILIKE con término de búsqueda libre.
_LIKE_ESCAPE = "\\"


# ── Helpers internos ─────────────────────────────────────────────
def _enum_value(value: Any) -> Any:
    """Convierte un miembro de Enum a su valor crudo.

    `Lead.status` es `String(32)`, no un Enum de base de datos (ver
    app/models/__init__.py), así que lo que se guarda debe ser el string.
    Los schemas de Task 3 entregan `LeadStatus`, que es un `str` Enum:
    guardarlo directo "funcionaría", pero deja el miembro del Enum en la
    sesión y el objeto en memoria deja de parecerse a lo que hay en disco.
    """
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _like_patterns(term: str) -> list[str]:
    """Patrones ILIKE para buscar `term` dentro del JSON serializado.

    Genera hasta cuatro variantes del término (ver `_search_condition`),
    deduplicadas — para un término ASCII puro como "jose" queda una sola:

    * el literal, y su forma escapada como la escribe `json.dumps()`
      (`José` -> `Jos\\u00e9`), porque el JSON se guarda con
      `ensure_ascii=True`;
    * lo mismo para las dos normalizaciones Unicode del término, NFC y
      NFD. "ñ" se puede escribir como un solo punto de código (U+00F1,
      NFC) o como "n" + tilde combinante (U+006E U+0303, NFD). Las dos se
      ven idénticas en pantalla pero son bytes distintos, y de qué forma
      llegan depende del sistema operativo de quien llenó el formulario
      (macOS entrega NFD) y del teclado de quien busca. Sin esto, un
      "Muñoz" tecleado en Windows no encuentra al "Muñoz" que Meta mandó
      desde un iPhone.
    """
    variants: list[str] = []
    for form in (term, unicodedata.normalize("NFC", term), unicodedata.normalize("NFD", term)):
        # json.dumps("José") -> '"Jos\\u00e9"'; se quitan las comillas externas.
        for variant in (form, json.dumps(form, ensure_ascii=True)[1:-1]):
            if variant not in variants:
                variants.append(variant)

    patterns: list[str] = []
    for variant in variants:
        # El término lo escribe un humano en una caja de texto: un '%' o
        # un '_' suyo debe buscarse literal, no como comodín SQL.
        safe = (
            variant.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
            .replace("%", _LIKE_ESCAPE + "%")
            .replace("_", _LIKE_ESCAPE + "_")
        )
        patterns.append("%" + safe + "%")
    return patterns


def _search_condition(term: str) -> ColumnElement[bool]:
    """Condición de búsqueda de texto libre dentro de `form_data`.

    Por qué NO se buscan claves concretas
    -------------------------------------
    `form_data` guarda tal cual lo que trajo el formulario de Meta, y ese
    formulario lo define el cliente: un lead puede traer `full_name`,
    otro `nombre`, otro `nombre_completo`; el teléfono puede venir como
    `phone_number`, `telefono` o `teléfono`. Cualquier lista de claves
    adivinadas deja leads fuera del buscador de forma silenciosa. Aquí no
    se adivina ninguna clave: se busca en el documento completo.

    Por qué NO se usa `.astext`
    ---------------------------
    `Lead.form_data` es `sqlalchemy.JSON` genérico, no
    `postgresql.JSONB`. `.astext` sólo existe en el comparador del
    dialecto de PostgreSQL: sobre esta columna revienta con AttributeError
    (no "devuelve cero filas"), y ataría el módulo a Postgres, cuando las
    pruebas corren sobre SQLite.

    Qué se hace en su lugar
    -----------------------
    `CAST(form_data AS TEXT) ILIKE '%term%'`. El CAST a texto existe en
    ambos motores (Postgres lo resuelve por conversión de E/S; en SQLite
    el JSON ya vive como TEXT), así que la misma query corre en
    producción y en pruebas.

    El detalle de los patrones múltiples: SQLAlchemy serializa el JSON con
    `json.dumps(..., ensure_ascii=True)`, de modo que en la columna un
    "José" quedó escrito como `Jos\\u00e9`. Buscar el literal "José"
    contra ese texto no encuentra nada. Por eso se emite un OR de las
    variantes que arma `_like_patterns()` — literal y escapada, en NFC y
    en NFD — y así "José" y "Muñoz" sí se encuentran. Para un término
    ASCII (la mayoría: teléfonos, correos) las variantes colapsan en una
    sola y el OR desaparece.

    Limitaciones (declaradas, no escondidas)
    ----------------------------------------
    * Busca en el JSON entero, o sea también en los NOMBRES de las
      claves: buscar "phone" hace match con todo lead cuyo formulario
      tenga un campo `phone_number`, aunque el valor no contenga "phone".
      Es un falso positivo aceptable para nombres, teléfonos y correos —
      que es lo que un operador teclea — pero es real.
    * No usa índice: es un scan de la tabla ya filtrada por `org_id`
      (+ cliente/estado si vinieron). A la escala de esta plataforma —
      miles de leads por organización — es correcto; si algún día pesa,
      la salida es un índice GIN de trigramas sobre la expresión en
      Postgres, sin cambiar esta interfaz.
    * En SQLite el ILIKE se traduce a `lower() LIKE lower()` y `lower()`
      de SQLite es sólo ASCII, así que ahí la búsqueda no es insensible a
      mayúsculas para acentos ("JOSÉ" no encuentra "José"). En Postgres,
      que es producción, ILIKE sí lo resuelve.
    """
    haystack = cast(Lead.form_data, Text)
    return or_(
        *[haystack.ilike(pattern, escape=_LIKE_ESCAPE) for pattern in _like_patterns(term)]
    )


def _visibility_conditions(user: User) -> list[ColumnElement[bool]]:
    """Lo que este usuario tiene permitido ver. Multi-tenant + RBAC.

    Siempre acota a la organización del usuario. Además, si es `member`,
    lo acota a los leads que tiene asignados: un traficker ve su bandeja,
    no la de todo el equipo. `owner` y `admin` ven la organización entera.
    """
    conditions: list[ColumnElement[bool]] = [Lead.org_id == user.org_id]

    role = getattr(user.role, "value", user.role)
    if role == UserRole.member.value:
        conditions.append(Lead.assigned_to_id == user.id)

    return conditions


def _lead_conditions(
    user: User,
    *,
    client_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[ColumnElement[bool]]:
    """El ÚNICO constructor de filtros de leads.

    Tanto el `COUNT(*)` como la página de resultados salen de aquí: si el
    conteo y la lista usaran cadenas de filtros distintas, el total y los
    items se contradirían, y el bug sería invisible hasta producción.
    """
    conditions = _visibility_conditions(user)

    if client_id is not None:
        conditions.append(Lead.client_id == client_id)

    if status is not None:
        conditions.append(Lead.status == _enum_value(status))

    if search:
        term = search.strip()
        if term:
            conditions.append(_search_condition(term))

    return conditions


# ── Creación ─────────────────────────────────────────────────────
def create_lead(
    db: Session,
    *,
    org_id: int,
    client_id: int,
    leadgen_id: str,
    form_data: dict | None = None,
    form_id: str | None = None,
    campaign_name: str | None = None,
    status: str = "nuevo",
    assigned_to_id: int | None = None,
    notes: str | None = None,
    received_at: datetime | None = None,
    commit: bool = True,
) -> Lead:
    """Inserta un lead. `leadgen_id` es único global (dedup del webhook).

    Quien llama debe haber resuelto antes `client_id`/`org_id` a partir
    del `page_id` (vía ClientPage) y haber comprobado con
    `get_lead_by_leadgen_id()` que el lead no exista ya.
    """
    lead = Lead(
        org_id=org_id,
        client_id=client_id,
        leadgen_id=leadgen_id,
        form_id=form_id,
        campaign_name=campaign_name,
        form_data=form_data if form_data is not None else {},
        status=_enum_value(status),
        assigned_to_id=assigned_to_id,
        notes=notes,
    )
    if received_at is not None:
        lead.received_at = received_at

    db.add(lead)
    if commit:
        db.commit()
        db.refresh(lead)
    else:
        db.flush()
    return lead


# ── Lectura puntual ──────────────────────────────────────────────
def get_lead(db: Session, lead_id: int, org_id: int) -> Lead | None:
    """Un lead por id, acotado a su organización. None si no existe o es de otra."""
    return db.scalar(
        select(Lead)
        .where(Lead.id == lead_id, Lead.org_id == org_id)
        .options(selectinload(Lead.assigned_to))
    )


def get_lead_for_user(db: Session, lead_id: int, user: User) -> Lead | None:
    """Igual que `get_lead()` pero aplicando también el RBAC del usuario.

    Un `member` que pida el id de un lead ajeno recibe None (y el router
    responde 404, no 403: no se le confirma que el lead exista).
    """
    return db.scalar(
        select(Lead)
        .where(Lead.id == lead_id, *_visibility_conditions(user))
        .options(selectinload(Lead.assigned_to))
    )


def get_lead_by_leadgen_id(
    db: Session, leadgen_id: str, org_id: int | None = None
) -> Lead | None:
    """Busca por el id de Meta — es la dedup del webhook de sincronización.

    `org_id` es opcional porque el webhook se autentica con el token
    compartido y todavía no sabe de qué organización es el lead (lo
    deduce después por `page_id`). `leadgen_id` es único a nivel global,
    así que no hay ambigüedad. Desde una ruta autenticada hay que pasarle
    `org_id` para no exponer la existencia de leads de otro tenant.
    """
    conditions: list[ColumnElement[bool]] = [Lead.leadgen_id == leadgen_id]
    if org_id is not None:
        conditions.append(Lead.org_id == org_id)
    return db.scalar(select(Lead).where(*conditions))


# ── Listado ──────────────────────────────────────────────────────
def list_leads_for_user(
    db: Session,
    user: User,
    *,
    client_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    size: int = DEFAULT_PAGE_SIZE,
) -> tuple[int, list[Lead]]:
    """Página de leads visibles para `user`, más el total sin paginar.

    Devuelve `(total, items)`. `total` es el conteo de TODO lo que hace
    match con los filtros (para que el front pinte el paginador), `items`
    es sólo la página pedida. Orden: `received_at` descendente (lo más
    nuevo arriba), con desempate por `id` para que la paginación sea
    estable cuando dos leads comparten timestamp.
    """
    page = max(1, int(page))
    size = max(1, min(int(size), MAX_PAGE_SIZE))

    conditions = _lead_conditions(
        user, client_id=client_id, status=status, search=search
    )

    total = db.scalar(select(func.count()).select_from(Lead).where(*conditions)) or 0

    items = list(
        db.scalars(
            select(Lead)
            .where(*conditions)
            .options(selectinload(Lead.assigned_to))
            .order_by(Lead.received_at.desc(), Lead.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
    )

    return total, items


# ── Actualización ────────────────────────────────────────────────
def update_lead(
    db: Session, lead: Lead, changes: Mapping[str, Any], commit: bool = True
) -> Lead:
    """Aplica al lead SÓLO los campos presentes en `changes`.

    `changes` es el diccionario de campos que el cliente mandó de verdad,
    es decir `payload.model_dump(exclude_unset=True)` (ver el docstring de
    `LeadUpdate` en app/schemas/leads.py). Esa es toda la razón de que la
    firma reciba un dict y no una lista de parámetros opcionales:

        data = payload.model_dump(exclude_unset=True)
        update_lead(db, lead, data)

    Con el dict, "no mandaron el campo" (la clave no está) y "mandaron
    null" (la clave está, con valor None) son cosas distintas, así que
    desasignar un lead — `{"assigned_to_id": None}` — o vaciar sus notas
    funcionan. Una firma de parámetros opcionales colapsa ambos casos en
    `None` y obliga al clásico `if x is not None`, que hace imposible
    desasignar.

    Lanza ValueError si viene un campo que no es actualizable: mejor un
    error ruidoso que escribir en silencio sobre `org_id` o `client_id`.
    """
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(
            f"Campos no actualizables en un lead: {sorted(unknown)}. "
            f"Permitidos: {sorted(UPDATABLE_FIELDS)}"
        )

    for field, value in changes.items():
        setattr(lead, field, _enum_value(value))

    if commit:
        db.commit()
        db.refresh(lead)
    else:
        db.flush()
    return lead


# ── Bitácora ─────────────────────────────────────────────────────
def record_audit(
    db: Session,
    *,
    lead_id: int,
    user_id: int,
    action: str,
    new_value: str,
    old_value: str | None = None,
    commit: bool = True,
) -> LeadAudit:
    """Escribe una entrada en la bitácora del lead.

    `action` debe ser un valor de `LeadAuditAction` (app/schemas/leads.py):
    la columna es `String(32)` y la base NO valida el contenido.
    """
    entry = LeadAudit(
        lead_id=lead_id,
        user_id=user_id,
        action=_enum_value(action),
        old_value=old_value,
        new_value=new_value,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def get_audit_log(db: Session, lead_id: int, limit: int | None = None) -> list[LeadAudit]:
    """Bitácora del lead, de lo más reciente a lo más viejo.

    Carga el usuario de cada entrada (`selectinload`) porque `AuditEntry`
    lo serializa: sin eso son N+1 queries para pintar el detalle.
    """
    stmt = (
        select(LeadAudit)
        .where(LeadAudit.lead_id == lead_id)
        .options(selectinload(LeadAudit.user))
        .order_by(LeadAudit.timestamp.desc(), LeadAudit.id.desc())
    )
    if limit is not None:
        stmt = stmt.limit(max(1, min(int(limit), MAX_PAGE_SIZE)))
    return list(db.scalars(stmt).all())
