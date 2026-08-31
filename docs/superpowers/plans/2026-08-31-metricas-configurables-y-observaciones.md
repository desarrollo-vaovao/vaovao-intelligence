# Métricas configurables y observaciones en reportes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dentro del formulario de Reportes, quien genera el PDF puede — por
campaña — elegir qué métricas mostrar (de un catálogo fijo, no solo las
automáticas del objetivo) y escribir observaciones, además de una observación
general del período. Todo efímero: vive solo en esa generación puntual, sin
persistir en base de datos, y es retrocompatible (si nadie personaliza nada,
el reporte sale idéntico a hoy).

**Architecture:** Un catálogo de métricas (`METRIC_REGISTRY`) en
`pdf_generator.py` reemplaza el `if/elif` por objetivo con una tabla
clave→(label, extractor), de la que `metrics_by_objective` (comportamiento de
siempre) y el nuevo `metrics_for_campaign` (con override opcional) se derivan.
Un endpoint nuevo (`GET /reports/campaigns/{account_id}`) trae la lista de
campañas del período para que el frontend arme el panel de selección antes de
generar. `ReportRequest` gana tres campos opcionales que viajan hasta
`report_builder` y de ahí al HTML del PDF — sin tabla nueva, sin migración.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (backend), Next.js/React
(frontend), pytest (tests backend).

## Global Constraints

- Nada de esto se persiste en base de datos — vive solo en la petición que
  genera ese PDF puntual (ver spec, sección "Fuera de alcance").
- Retrocompatible por defecto: si `campaign_metrics`/`campaign_comments`/
  `general_comment` no vienen en `ReportRequest` (los tres son opcionales,
  default `None`), el reporte generado debe ser byte-idéntico al de antes de
  este cambio.
- La selección de métricas identifica campañas por su **id de Meta como
  string** (`str(campaign["id"])`), la misma clave en ambos lados
  (`campaign_metrics`/`campaign_comments` y lo que devuelve
  `GET /reports/campaigns/{account_id}`).
- Texto libre (`general_comment`, cada entrada de `campaign_comments`) se
  escapa con `html.escape()` antes de insertarse en el HTML del PDF — es la
  única entrada de este módulo que es texto arbitrario tecleado por una
  persona, a diferencia de nombres de campaña que vienen de Meta.
- Limitación conocida y aceptada (no se corrige en este plan): Meta solo
  incluye el campo `actions` (de donde salen `conversations`/`engagement`/
  `followers`) en la petición a la Graph API cuando AL MENOS una campaña de
  la cuenta tiene objetivo MESSAGES/POST_ENGAGEMENT/PAGE_LIKES
  (`meta_api._fields_for_campaigns`, ver comentario ahí sobre por qué pedirlo
  siempre dispara rate limiting). Si una cuenta no tiene NINGUNA campaña con
  esos objetivos, elegir "Conversaciones" para una campaña de otro objetivo
  en esa cuenta siempre mostrará "—", aunque en teoría Meta pudiera tener el
  dato. No se toca `_fields_for_campaigns` para no reintroducir ese riesgo.

---

## File Structure

- **Modify** `intelligence-backend/app/services/pdf_generator.py` — catálogo
  de métricas, selección por campaña, render de observaciones.
- **Modify** `intelligence-backend/app/schemas/__init__.py` — tres campos
  nuevos en `ReportRequest`.
- **Modify** `intelligence-backend/app/services/report_builder.py` — pasa los
  tres campos hasta el `report_data`/campañas.
- **Modify** `intelligence-backend/app/api/routes/reports.py` — endpoint
  nuevo `GET /reports/campaigns/{account_id}`; los tres endpoints existentes
  que generan reportes (`/generate`, `/summary`, y el job en segundo plano)
  leen y reenvían los campos nuevos.
- **Create** `intelligence-backend/tests/test_metricas_configurables.py` —
  toda la cobertura nueva de este módulo (crece en cada tarea backend).
- **Modify** `intelligence-web/lib/api.js` — llamada al endpoint de preview.
- **Modify** `intelligence-web/app/reportes/page.jsx` — panel plegable de
  personalización.

---

## Task 1: Catálogo de métricas y selección por campaña (lógica pura)

**Files:**
- Modify: `intelligence-backend/app/services/pdf_generator.py:79-129`
- Test: `intelligence-backend/tests/test_metricas_configurables.py` (crear)

**Interfaces:**
- Produces: `pdf_generator.METRIC_REGISTRY: dict[str, dict]` (clave →
  `{"label": str, "value": callable(insights: dict, currency_symbol: str) -> str}`).
  Claves: `impressions`, `reach`, `frequency`, `clicks`, `ctr`, `cpc`, `cpm`,
  `conversations`, `cost_per_conversation`, `engagement`,
  `cost_per_engagement`, `followers`, `cost_per_follower`.
- Produces: `pdf_generator.default_metric_keys(objective: str | None) -> list[str]`.
- Produces: `pdf_generator.metrics_for_campaign(campaign: dict, currency_symbol: str = "$", selected_keys: list[str] | None = None) -> list[dict]`
  (cada item `{"label": str, "value": str}`).
- Mantiene: `pdf_generator.metrics_by_objective(objective, insights, currency_symbol="$") -> list[dict]`
  con el mismo comportamiento externo de siempre (ahora implementada sobre el
  registro).

- [ ] **Step 1: Escribir las pruebas que fallan (regresión + comportamiento nuevo)**

Crear `intelligence-backend/tests/test_metricas_configurables.py`:

```python
"""
Métricas configurables por campaña y observaciones en reportes — ver
docs/superpowers/specs/2026-08-31-metricas-configurables-y-observaciones-design.md

Todo lo que se personaliza aquí es efímero: vive solo en la petición que
genera ese PDF puntual, no se persiste en la base de datos.
"""
from __future__ import annotations

from app.services import pdf_generator


# ── metrics_by_objective sigue igual (regresión) ──────────────────────
def test_metrics_by_objective_messages_no_cambia():
    insights = {"impressions": 1000, "spend": 50,
                "messaging_conversation_started_7d": 10}
    result = pdf_generator.metrics_by_objective("MESSAGES", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "1,000"},
        {"label": "Conversaciones", "value": "10"},
        {"label": "Costo / conv.", "value": "$5.00"},
    ]


def test_metrics_by_objective_reach_no_cambia():
    insights = {"impressions": 2000, "reach": 1500, "frequency": 1.33, "cpm": 4.2}
    result = pdf_generator.metrics_by_objective("REACH", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "2,000"},
        {"label": "Alcance", "value": "1,500"},
        {"label": "Frecuencia", "value": "1.33"},
        {"label": "CPM", "value": "$4.20"},
    ]


def test_metrics_by_objective_default_no_cambia():
    insights = {"impressions": 500, "clicks": 25, "ctr": 5.0, "cpc": 0.8}
    result = pdf_generator.metrics_by_objective("LINK_CLICKS", insights, "$")
    assert result == [
        {"label": "Impresiones", "value": "500"},
        {"label": "Clics", "value": "25"},
        {"label": "CTR", "value": "5.00%"},
        {"label": "CPC", "value": "$0.80"},
    ]


# ── default_metric_keys ────────────────────────────────────────────
def test_default_metric_keys_por_objetivo():
    assert pdf_generator.default_metric_keys("MESSAGES") == [
        "impressions", "conversations", "cost_per_conversation",
    ]
    assert pdf_generator.default_metric_keys("PAGE_LIKES") == [
        "impressions", "followers", "cost_per_follower",
    ]


def test_default_metric_keys_objetivo_desconocido_cae_en_default():
    assert pdf_generator.default_metric_keys("ALGO_QUE_META_INVENTE_MANANA") == [
        "impressions", "clicks", "ctr", "cpc",
    ]
    assert pdf_generator.default_metric_keys(None) == [
        "impressions", "clicks", "ctr", "cpc",
    ]


# ── metrics_for_campaign: control total, sin importar el objetivo ─────
def test_metrics_for_campaign_sin_seleccion_usa_el_automatico():
    campaign = {"objective": "MESSAGES",
                "insights": {"impressions": 1000, "spend": 50,
                             "messaging_conversation_started_7d": 10}}
    assert (pdf_generator.metrics_for_campaign(campaign, "$")
            == pdf_generator.metrics_by_objective("MESSAGES", campaign["insights"], "$"))


def test_metrics_for_campaign_con_seleccion_explicita_quita_y_agrega():
    """Una campaña de Alcance (REACH) pidiendo Clics y CTR en vez del set
    automático (Impresiones/Alcance/Frecuencia/CPM) — el caso central de
    'quitar las que no sirven, agregar las que sí' que pidió el usuario."""
    campaign = {"objective": "REACH",
                "insights": {"impressions": 2000, "reach": 1500,
                             "clicks": 40, "ctr": 2.0}}
    result = pdf_generator.metrics_for_campaign(
        campaign, "$", selected_keys=["clicks", "ctr"]
    )
    assert result == [
        {"label": "Clics", "value": "40"},
        {"label": "CTR", "value": "2.00%"},
    ]


def test_metrics_for_campaign_metrica_sin_dato_muestra_raya():
    """Pedir 'Conversaciones' en una campaña que nunca tuvo ese dato: '—',
    no un error — el mismo criterio que ya aplica a cualquier campo ausente."""
    campaign = {"objective": "REACH", "insights": {"impressions": 2000}}
    result = pdf_generator.metrics_for_campaign(
        campaign, "$", selected_keys=["conversations", "cost_per_conversation"]
    )
    assert result == [
        {"label": "Conversaciones", "value": "—"},
        {"label": "Costo / conv.", "value": "—"},
    ]


def test_metrics_for_campaign_sin_insights_no_revienta():
    campaign = {"objective": "MESSAGES"}  # sin la clave "insights"
    result = pdf_generator.metrics_for_campaign(campaign, "$", selected_keys=["impressions"])
    assert result == [{"label": "Impresiones", "value": "—"}]
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: FAIL — `AttributeError: module 'app.services.pdf_generator' has no
attribute 'default_metric_keys'` (y similares para `metrics_for_campaign`).

- [ ] **Step 3: Reemplazar el bloque `_find_like` + `metrics_by_objective` por el registro**

En `intelligence-backend/app/services/pdf_generator.py`, reemplazar las
líneas 79-129 (desde `def _find_like(insights: dict):` hasta el final de
`metrics_by_objective`) por:

```python
def _find_like(insights: dict):
    for a in (insights.get("actions") or []):
        if a.get("action_type") == "like":
            return a.get("value")
    return None


def _cost_per(insights: dict, count_field: str, currency_symbol: str) -> str:
    spend = insights.get("spend")
    count = insights.get(count_field)
    if spend and count:
        try:
            return fmt_currency(float(spend) / float(count), currency_symbol)
        except (TypeError, ValueError, ZeroDivisionError):
            return "—"
    return "—"


def _cost_per_follower(insights: dict, currency_symbol: str) -> str:
    spend = insights.get("spend")
    likes = _find_like(insights)
    if spend and likes:
        try:
            return fmt_currency(float(spend) / float(likes), currency_symbol)
        except (TypeError, ValueError, ZeroDivisionError):
            return "—"
    return "—"


# Catálogo de TODAS las métricas que un reporte puede mostrar, sin importar
# el objetivo de la campaña — la base del "mostrar/ocultar por campaña" que
# elige quien arma el reporte (ver metrics_for_campaign). Cada entrada sabe
# extraer y formatear su propio valor desde `insights`; una clave que no
# aplica al objetivo real de la campaña simplemente no tiene el dato y se
# muestra "—", igual que ya pasaba con campos ausentes antes de este catálogo.
METRIC_REGISTRY: dict[str, dict] = {
    "impressions": {
        "label": "Impresiones",
        "value": lambda ins, cur: fmt_number(ins.get("impressions")),
    },
    "reach": {
        "label": "Alcance",
        "value": lambda ins, cur: fmt_number(ins.get("reach")),
    },
    "frequency": {
        "label": "Frecuencia",
        "value": lambda ins, cur: (
            f"{float(ins['frequency']):.2f}" if ins.get("frequency") else "—"
        ),
    },
    "clicks": {
        "label": "Clics",
        "value": lambda ins, cur: fmt_number(ins.get("clicks")),
    },
    "ctr": {
        "label": "CTR",
        "value": lambda ins, cur: fmt_percent(ins.get("ctr")),
    },
    "cpc": {
        "label": "CPC",
        "value": lambda ins, cur: fmt_currency(ins.get("cpc"), cur),
    },
    "cpm": {
        "label": "CPM",
        "value": lambda ins, cur: fmt_currency(ins.get("cpm"), cur),
    },
    "conversations": {
        "label": "Conversaciones",
        "value": lambda ins, cur: fmt_number(ins.get("messaging_conversation_started_7d")),
    },
    "cost_per_conversation": {
        "label": "Costo / conv.",
        "value": lambda ins, cur: _cost_per(ins, "messaging_conversation_started_7d", cur),
    },
    "engagement": {
        "label": "Interacciones",
        "value": lambda ins, cur: fmt_number(ins.get("post_engagement")),
    },
    "cost_per_engagement": {
        "label": "Costo / int.",
        "value": lambda ins, cur: _cost_per(ins, "post_engagement", cur),
    },
    "followers": {
        "label": "Seguidores",
        "value": lambda ins, cur: fmt_number(_find_like(ins)),
    },
    "cost_per_follower": {
        "label": "Costo / seg.",
        "value": lambda ins, cur: _cost_per_follower(ins, cur),
    },
}

# El set automático por objetivo, expresado como claves de METRIC_REGISTRY —
# única fuente de verdad tanto para metrics_by_objective (comportamiento de
# siempre) como para el `default_metrics` que ve el panel de personalización
# del frontend (GET /reports/campaigns/{account_id}).
OBJECTIVE_DEFAULT_METRIC_KEYS: dict[str, list[str]] = {
    "MESSAGES": ["impressions", "conversations", "cost_per_conversation"],
    "POST_ENGAGEMENT": ["impressions", "engagement", "cost_per_engagement"],
    "PAGE_LIKES": ["impressions", "followers", "cost_per_follower"],
    "REACH": ["impressions", "reach", "frequency", "cpm"],
    "BRAND_AWARENESS": ["impressions", "reach", "frequency", "cpm"],
    "DEFAULT": ["impressions", "clicks", "ctr", "cpc"],
}


def default_metric_keys(objective: str | None) -> list[str]:
    """Claves de METRIC_REGISTRY que se mostrarían para este objetivo si
    nadie personaliza nada — el mismo set que ya se calculaba antes de este
    cambio, ahora expuesto como claves en vez de solo como render final."""
    obj = (objective or "").upper()
    return OBJECTIVE_DEFAULT_METRIC_KEYS.get(obj, OBJECTIVE_DEFAULT_METRIC_KEYS["DEFAULT"])


def _resolve_metrics(keys: list[str], insights: dict, currency_symbol: str) -> list[dict]:
    out = []
    for key in keys:
        entry = METRIC_REGISTRY.get(key)
        if entry is None:
            continue
        out.append({"label": entry["label"], "value": entry["value"](insights, currency_symbol)})
    return out


def metrics_by_objective(objective: str, insights: dict, currency_symbol: str = "$") -> list[dict]:
    return _resolve_metrics(default_metric_keys(objective), insights, currency_symbol)


def metrics_for_campaign(campaign: dict, currency_symbol: str = "$",
                         selected_keys: list[str] | None = None) -> list[dict]:
    """
    Métricas a mostrar en la tarjeta de esta campaña. Con `selected_keys`
    (lista de claves de METRIC_REGISTRY elegidas a mano) se usa exactamente
    esa selección, sin importar el objetivo — es el mecanismo de
    "mostrar/ocultar por campaña" del panel de personalización. Sin
    `selected_keys` (None) cae en el set automático de siempre
    (`default_metric_keys`) — comportamiento idéntico al de antes de que
    existiera esta función.
    """
    insights = campaign.get("insights") or {}
    keys = selected_keys if selected_keys is not None else default_metric_keys(campaign.get("objective"))
    return _resolve_metrics(keys, insights, currency_symbol)
```

- [ ] **Step 4: Correr las pruebas para verificar que pasan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: PASS (9 pruebas).

- [ ] **Step 5: Correr la suite completa (regresión del resto del backend)**

Run: `cd intelligence-backend && pytest -v`
Expected: PASS — en particular cualquier prueba existente que use
`pdf_generator.metrics_by_objective` o `render_campaign_card` debe seguir en
verde sin cambios.

- [ ] **Step 6: Commit**

```bash
git add intelligence-backend/app/services/pdf_generator.py intelligence-backend/tests/test_metricas_configurables.py
git commit -m "feat(reportes): catalogo de metricas y seleccion por campana

METRIC_REGISTRY reemplaza el if/elif de metrics_by_objective con una
tabla clave->extractor; metrics_for_campaign permite elegir cualquier
metrica del catalogo por campana, sin importar su objetivo automatico.
metrics_by_objective conserva exactamente el mismo comportamiento
externo de siempre.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Observaciones en el PDF (tarjeta de campaña + sección general)

**Files:**
- Modify: `intelligence-backend/app/services/pdf_generator.py:1-16` (import),
  `:151-212` (`render_campaign_card`), `:216-327` (`render_report_page`)
- Test: `intelligence-backend/tests/test_metricas_configurables.py`

**Interfaces:**
- Consumes: `pdf_generator.metrics_for_campaign` (Task 1).
- Produces: `render_campaign_card` ahora lee `campaign.get("selected_metrics")`
  y `campaign.get("comment")`. `render_report_page` ahora lee
  `report_data.get("general_comment")`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `intelligence-backend/tests/test_metricas_configurables.py`:

```python
# ── Render: comentario por campaña ─────────────────────────────────
def test_render_campaign_card_sin_comentario_no_agrega_seccion():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "reach": 90}, "ads": []}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "Observaciones" not in html_out


def test_render_campaign_card_con_comentario_lo_muestra():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "reach": 90}, "ads": [],
                "comment": "Buen desempeño esta quincena"}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "Observaciones" in html_out
    assert "Buen desempeño esta quincena" in html_out


def test_render_campaign_card_escapa_html_del_comentario():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100}, "ads": [],
                "comment": "<script>alert(1)</script>"}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_campaign_card_usa_selected_metrics():
    campaign = {"name": "Campaña X", "objective": "REACH",
                "insights": {"impressions": 100, "clicks": 5, "ctr": 5.0}, "ads": [],
                "selected_metrics": ["clicks", "ctr"]}
    html_out = pdf_generator.render_campaign_card(campaign, "$")
    assert "Clics" in html_out
    assert "Alcance" not in html_out  # métrica automática de REACH, no elegida


# ── Render: observación general del período ────────────────────────
def test_render_report_page_sin_general_comment_no_agrega_seccion():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "Observaciones del período" not in html_out


def test_render_report_page_con_general_comment_lo_muestra():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0,
                    "general_comment": "El período tuvo buen desempeño en general."}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "Observaciones del período" in html_out
    assert "El período tuvo buen desempeño en general." in html_out


def test_render_report_page_escapa_html_del_general_comment():
    report_data = {"client_name": "Cliente", "period": "1-15 ene 2026",
                    "campaigns": [], "total_spend": 0,
                    "general_comment": "<b>negrita</b> & cosas"}
    html_out = pdf_generator.render_report_page(report_data, "$")
    assert "<b>negrita</b>" not in html_out
    assert "&lt;b&gt;negrita&lt;/b&gt; &amp; cosas" in html_out
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v -k "comment or general_comment or selected_metrics"`
Expected: FAIL — `render_campaign_card`/`render_report_page` no conocen
`comment`/`selected_metrics`/`general_comment` todavía.

- [ ] **Step 3: Agregar el import de `html`**

En `intelligence-backend/app/services/pdf_generator.py`, línea 15
(`from datetime import datetime`), agregar debajo:

```python
import html
```

- [ ] **Step 4: `render_campaign_card` — usar `metrics_for_campaign` y agregar el comentario**

Cambiar la primera línea de la función (línea 152):

```python
    metrics = metrics_by_objective(campaign.get("objective"), campaign.get("insights", {}), currency_symbol)
```

por:

```python
    metrics = metrics_for_campaign(campaign, currency_symbol, campaign.get("selected_metrics"))
```

Antes del `return` de la función (justo después de donde se arma
`ads_section`, línea ~196), agregar:

```python
    comment = (campaign.get("comment") or "").strip()
    comment_section = ""
    if comment:
        comment_section = (
            '<div style="border-top:0.5px solid #e0e0e0;padding-top:7px;margin-top:7px;">'
            '<div style="font-size:9px;color:#aaa;margin-bottom:3px;">Observaciones</div>'
            f'<div style="font-size:10px;color:#333;line-height:1.4;">{html.escape(comment)}</div></div>'
        )
```

Y en el `return f"""..."""`, dentro del `<div style="flex:1;">` donde hoy
está `{ads_section}`, agregar `{comment_section}` justo después:

```python
        <div style="flex:1;">
          <div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap;">{metrics_html}</div>
          {ads_section}
          {comment_section}
        </div>
```

- [ ] **Step 5: `render_report_page` — sección de observaciones generales**

Al inicio de la función, junto a las demás variables leídas de `report_data`
(línea ~222, junto a `country_code = report_data.get("country_code")`),
agregar:

```python
    general_comment = (report_data.get("general_comment") or "").strip()
```

Después de armar `pct_block` (antes del bloque `table_rows`), agregar:

```python
    observaciones_block = ""
    if general_comment:
        observaciones_block = f"""
            <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>
            <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Observaciones del período</div>
            <div style="font-size:11px;color:#333;line-height:1.5;">{html.escape(general_comment)}</div>"""
```

Y en el `return f"""..."""` de la función, reemplazar:

```python
        <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>

        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Campañas activas</div>
```

por:

```python
        {observaciones_block}

        <div style="border-top:0.5px solid #e0e0e0;margin:16px 0;"></div>

        <div style="font-size:10px;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Campañas activas</div>
```

(Esa cadena aparece una sola vez en el archivo — es el divisor justo antes
de la tabla de campañas.)

- [ ] **Step 6: Correr las pruebas para verificar que pasan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: PASS (16 pruebas en total entre Task 1 y Task 2).

- [ ] **Step 7: Correr la suite completa**

Run: `cd intelligence-backend && pytest -v`
Expected: PASS sin regresiones.

- [ ] **Step 8: Commit**

```bash
git add intelligence-backend/app/services/pdf_generator.py intelligence-backend/tests/test_metricas_configurables.py
git commit -m "feat(reportes): observaciones por campana y del periodo en el PDF

render_campaign_card usa metrics_for_campaign (respeta selected_metrics
si viene) y agrega la seccion de comentario si campaign['comment'] no
esta vacio. render_report_page agrega 'Observaciones del periodo' si
general_comment no esta vacio. Todo texto libre se escapa con
html.escape antes de insertarse en el HTML del PDF.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `ReportRequest` + `report_builder` — pasar la personalización

**Files:**
- Modify: `intelligence-backend/app/schemas/__init__.py:192-199`
- Modify: `intelligence-backend/app/services/report_builder.py:129-211`
- Test: `intelligence-backend/tests/test_metricas_configurables.py`

**Interfaces:**
- Consumes: nada nuevo de tareas anteriores (usa el `campaign["id"]`/
  `campaign["comment"]`/`campaign["selected_metrics"]` que ya consume Task 2
  en el render).
- Produces: `ReportRequest.campaign_metrics: dict[str, list[str]] | None`,
  `.campaign_comments: dict[str, str] | None`, `.general_comment: str | None`
  (los tres opcionales, default `None`).
- Produces: `report_builder.build_report_data(..., campaign_metrics=None, campaign_comments=None, general_comment=None)`
  y `report_builder.build_pdf(..., campaign_metrics=None, campaign_comments=None, general_comment=None)`
  — parámetros nuevos al final de la firma, no rompen llamadores existentes.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `intelligence-backend/tests/test_metricas_configurables.py`:

```python
# ── report_builder: pasa la personalización hasta report_data ──────
import asyncio
from datetime import date

from app.services import meta_api, report_builder


def _fake_campaign(cid: str, objective: str = "REACH") -> dict:
    return {
        "id": cid, "name": f"Campaña {cid}", "objective": objective,
        "status": "ACTIVE", "spend": 10.0,
        "insights": {"impressions": 100, "reach": 90, "clicks": 5, "ctr": 5.0},
        "ads": [],
    }


def test_build_report_data_sin_personalizacion_no_agrega_claves(monkeypatch, tenant_a, factory):
    """Regresión: sin campaign_metrics/campaign_comments/general_comment, el
    resultado es el mismo de antes de este cambio."""
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1")], "total_spend": 10.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
    ))
    assert "selected_metrics" not in result["campaigns"][0]
    assert "comment" not in result["campaigns"][0]
    assert result.get("general_comment") is None


def test_build_report_data_con_personalizacion_adjunta_por_campana(monkeypatch, tenant_a, factory):
    account = factory.ad_account(tenant_a.client)

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1"), _fake_campaign("2")], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    result = asyncio.run(report_builder.build_report_data(
        account, ["token"], date(2026, 1, 1), date(2026, 1, 15),
        campaign_metrics={"1": ["clicks", "ctr"]},
        campaign_comments={"1": "Buen mes"},
        general_comment="Resumen del período",
    ))

    campanas = {c["id"]: c for c in result["campaigns"]}
    assert campanas["1"]["selected_metrics"] == ["clicks", "ctr"]
    assert campanas["1"]["comment"] == "Buen mes"
    # La campaña "2" no tiene entrada en ninguno de los dos dicts: intacta.
    assert "selected_metrics" not in campanas["2"]
    assert "comment" not in campanas["2"]
    assert result["general_comment"] == "Resumen del período"
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v -k build_report_data`
Expected: FAIL — `build_report_data() got an unexpected keyword argument 'campaign_metrics'`.

- [ ] **Step 3: Extender `ReportRequest`**

En `intelligence-backend/app/schemas/__init__.py`, dentro de `class
ReportRequest(BaseModel):` (línea 192-199), agregar al final de los campos
existentes:

```python
    campaign_metrics: dict[str, list[str]] | None = None    # campaign_id (Meta) -> claves de pdf_generator.METRIC_REGISTRY
    campaign_comments: dict[str, str] | None = None          # campaign_id (Meta) -> observación de esa campaña
    general_comment: str | None = None                       # observación general del período
```

- [ ] **Step 4: `report_builder.py` — helper y firmas nuevas**

En `intelligence-backend/app/services/report_builder.py`, agregar, después
de `_filter_campaigns_by_country` (después de la línea 126, antes de
`build_report_data`):

```python
def _apply_customization(campaigns: list[dict], campaign_metrics: dict[str, list[str]] | None,
                         campaign_comments: dict[str, str] | None) -> list[dict]:
    """Adjunta selected_metrics/comment a cada campaña, buscando por su id de
    Meta (clave de ambos dicts, como string — ver GET /reports/campaigns).
    Campañas sin entrada en ninguno de los dos quedan intactas: su render
    sigue usando el set automático de metrics_by_objective."""
    campaign_metrics = campaign_metrics or {}
    campaign_comments = campaign_comments or {}
    out = []
    for c in campaigns:
        cid = str(c.get("id"))
        entry = dict(c)
        if cid in campaign_metrics:
            entry["selected_metrics"] = campaign_metrics[cid]
        if cid in campaign_comments:
            entry["comment"] = campaign_comments[cid]
        out.append(entry)
    return out
```

Cambiar la firma de `build_report_data` (línea 129-134) de:

```python
async def build_report_data(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD",
                            country_code: str | None = None,
                            source_currency: str = "USD",
                            exchange_rate: float | None = None,
                            attribution_window: str | None = None) -> dict:
```

a:

```python
async def build_report_data(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                            budget: float | None = None, currency: str = "USD",
                            country_code: str | None = None,
                            source_currency: str = "USD",
                            exchange_rate: float | None = None,
                            attribution_window: str | None = None,
                            campaign_metrics: dict[str, list[str]] | None = None,
                            campaign_comments: dict[str, str] | None = None,
                            general_comment: str | None = None) -> dict:
```

Justo antes del `return {...}` de `build_report_data` (línea 171), agregar:

```python
    if campaign_metrics or campaign_comments:
        campaigns = _apply_customization(campaigns, campaign_metrics, campaign_comments)
```

Y en el `return {...}`, agregar la clave nueva:

```python
    return {
        "client_name": account.label,
        "period": format_period(date_from, date_to),
        "campaigns": campaigns,
        "total_spend": total_spend,
        "budget": budget,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "country_code": country_code,
        "general_comment": general_comment,
    }
```

Cambiar la firma de `build_pdf` (línea 182-187) de:

```python
async def build_pdf(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD",
                    country_code: str | None = None,
                    source_currency: str = "USD",
                    exchange_rate: float | None = None,
                    attribution_window: str | None = None) -> tuple[bytes, str]:
```

a:

```python
async def build_pdf(account: AdAccount, tokens: list[str], date_from: date, date_to: date,
                    budget: float | None = None, currency: str = "USD",
                    country_code: str | None = None,
                    source_currency: str = "USD",
                    exchange_rate: float | None = None,
                    attribution_window: str | None = None,
                    campaign_metrics: dict[str, list[str]] | None = None,
                    campaign_comments: dict[str, str] | None = None,
                    general_comment: str | None = None) -> tuple[bytes, str]:
```

Y dentro de `build_pdf`, la llamada a `build_report_data` (línea 201-204) de:

```python
        report_data = await build_report_data(
            account, tokens, date_from, date_to, budget, currency, country_code,
            source_currency, exchange_rate, attribution_window,
        )
```

a:

```python
        report_data = await build_report_data(
            account, tokens, date_from, date_to, budget, currency, country_code,
            source_currency, exchange_rate, attribution_window,
            campaign_metrics, campaign_comments, general_comment,
        )
```

- [ ] **Step 5: Correr las pruebas para verificar que pasan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: PASS (18 pruebas en total).

- [ ] **Step 6: Correr la suite completa**

Run: `cd intelligence-backend && pytest -v`
Expected: PASS sin regresiones — en particular
`test_atribucion_meta.py::test_build_report_data_traduce_la_preferencia_guardada`
y `test_build_report_data_sin_preferencia_no_manda_nada`, que llaman
`build_report_data` con los parámetros posicionales/nombrados de antes.

- [ ] **Step 7: Commit**

```bash
git add intelligence-backend/app/schemas/__init__.py intelligence-backend/app/services/report_builder.py intelligence-backend/tests/test_metricas_configurables.py
git commit -m "feat(reportes): ReportRequest y report_builder pasan la personalizacion

Tres campos opcionales nuevos en ReportRequest (campaign_metrics,
campaign_comments, general_comment), todos default None. report_builder
los adjunta a cada campana por su id de Meta via _apply_customization,
sin tocar campanas que no tienen entrada en ninguno de los dos dicts.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `GET /reports/campaigns/{account_id}` — preview de campañas

**Files:**
- Modify: `intelligence-backend/app/api/routes/reports.py:1-45` (imports),
  agregar endpoint nuevo cerca de `/reports/countries/{account_id}` (línea
  324+)
- Test: `intelligence-backend/tests/test_metricas_configurables.py`

**Interfaces:**
- Consumes: `pdf_generator.default_metric_keys` (Task 1),
  `report_builder._filter_campaigns_by_country` (ya existe),
  `meta_api.get_account_data_with_fallback` (ya existe).
- Produces: `GET /reports/campaigns/{account_id}?date_from=&date_to=&country_code=`
  → `{"campaigns": [{"id": str, "name": str, "objective": str, "default_metrics": list[str]}]}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `intelligence-backend/tests/test_metricas_configurables.py`:

```python
# ── GET /reports/campaigns/{account_id} ─────────────────────────────
import app.api.routes.reports as reports_routes


def test_get_campaigns_devuelve_nombre_objetivo_y_default_metrics(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("111", "MESSAGES")], "total_spend": 10.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 200
    body = r.json()
    assert body["campaigns"] == [{
        "id": "111", "name": "Campaña 111", "objective": "MESSAGES",
        "default_metrics": ["impressions", "conversations", "cost_per_conversation"],
    }]


def test_get_campaigns_404_si_no_es_de_la_organizacion(client, login, tenant_a, tenant_b, factory):
    login(tenant_a.owner)
    account_ajena = factory.ad_account(tenant_b.client)
    r = client.get(f"/reports/campaigns/{account_ajena.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 404


def test_get_campaigns_503_sin_tokens(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(
        reports_routes, "resolve_tokens",
        lambda current, db: ([], "No has conectado tu Facebook y no hay tokens centrales."),
    )
    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15")
    assert r.status_code == 503


def test_get_campaigns_respeta_filtro_de_pais(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    con_pais = _fake_campaign("1", "REACH")
    con_pais["ads"] = [{"id": "ad1", "name": "Anuncio", "insights": {}, "countries": ["GT"]}]
    sin_pais_pedido = _fake_campaign("2", "REACH")
    sin_pais_pedido["ads"] = [{"id": "ad2", "name": "Anuncio", "insights": {}, "countries": ["US"]}]

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [con_pais, sin_pais_pedido], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.get(f"/reports/campaigns/{account.id}?date_from=2026-01-01&date_to=2026-01-15&country_code=GT")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["campaigns"]]
    assert ids == ["1"]
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v -k get_campaigns`
Expected: FAIL con 404 "Not Found" (la ruta todavía no existe).

- [ ] **Step 3: Agregar el import de `date` y de `pdf_generator`**

En `intelligence-backend/app/api/routes/reports.py`, línea 21-23:

```python
import asyncio
import time
import uuid
```

agregar debajo:

```python
from datetime import date
```

Y en la línea 42 (`from app.services import meta_api, report_builder`),
cambiar a:

```python
from app.services import meta_api, pdf_generator, report_builder
```

- [ ] **Step 4: Agregar el endpoint**

Después de `get_available_countries` (final del archivo, línea 364), agregar:

```python
@router.get("/campaigns/{account_id}")
async def get_report_campaigns(
    account_id: int,
    date_from: date,
    date_to: date,
    country_code: str | None = None,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Preview liviano de las campañas del período: nombre, objetivo y el set de
    métricas que se mostraría automáticamente (`default_metrics`, claves de
    pdf_generator.METRIC_REGISTRY). Alimenta el panel "Personalizar métricas y
    observaciones" del formulario de Reportes — sin anuncios ni imágenes, eso
    solo lo necesita el PDF final.
    """
    account = _get_owned_account(account_id, current, db)

    if date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de inicio no puede ser posterior a la de fin.",
        )

    tokens, error = resolve_tokens(current, db)
    if not tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)

    org = db.get(Organization, current.org_id)
    attribution_windows = ATTRIBUTION_WINDOWS.get(org.attribution_window if org else None)

    try:
        data = await meta_api.get_account_data_with_fallback(
            tokens, account.meta_ad_account_id,
            date_from.isoformat(), date_to.isoformat(),
            attribution_windows,
        )
    except meta_api.MetaApiError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Meta: {e}")

    campaigns, _ = report_builder._filter_campaigns_by_country(data["campaigns"], country_code)

    return {
        "campaigns": [
            {
                "id": str(c["id"]),
                "name": c.get("name") or "",
                "objective": c.get("objective") or "DEFAULT",
                "default_metrics": pdf_generator.default_metric_keys(c.get("objective")),
            }
            for c in campaigns
        ]
    }
```

- [ ] **Step 5: Correr las pruebas para verificar que pasan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: PASS (22 pruebas en total).

- [ ] **Step 6: Correr la suite completa**

Run: `cd intelligence-backend && pytest -v`
Expected: PASS sin regresiones.

- [ ] **Step 7: Commit**

```bash
git add intelligence-backend/app/api/routes/reports.py intelligence-backend/tests/test_metricas_configurables.py
git commit -m "feat(reportes): GET /reports/campaigns/{account_id} para el panel de personalizacion

Preview liviano (id, nombre, objetivo, default_metrics) de las campanas
del periodo, sin anuncios ni imagenes -- solo se paga esta llamada
extra a Meta cuando el usuario abre el panel de personalizacion, no en
el flujo simple de generar y listo.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `/generate` y `/summary` reenvían la personalización

**Files:**
- Modify: `intelligence-backend/app/api/routes/reports.py:74-101`
  (`_run_report_job`), `:173-222` (`generate_report`), `:252-301`
  (`report_summary`)
- Test: `intelligence-backend/tests/test_metricas_configurables.py`

**Interfaces:**
- Consumes: `report_builder.build_pdf`/`build_report_data` con los tres
  parámetros nuevos (Task 3).

- [ ] **Step 1: Escribir la prueba que falla**

Agregar a `intelligence-backend/tests/test_metricas_configurables.py`:

```python
# ── POST /reports/summary reenvía la personalización ────────────────
def test_summary_reenvia_campaign_metrics_y_comentarios(client, login, tenant_a, factory, monkeypatch):
    login(tenant_a.owner)
    account = factory.ad_account(tenant_a.client)
    monkeypatch.setattr(reports_routes, "resolve_tokens", lambda current, db: (["token"], None))

    async def fake_get_account_data_with_fallback(tokens, ad_account_id, date_from, date_to,
                                                   attribution_windows=None):
        return {"campaigns": [_fake_campaign("1"), _fake_campaign("2")], "total_spend": 20.0}

    monkeypatch.setattr(meta_api, "get_account_data_with_fallback", fake_get_account_data_with_fallback)

    r = client.post("/reports/summary", json={
        "ad_account_id": account.id,
        "date_from": "2026-01-01", "date_to": "2026-01-15",
        "currency": "USD",
        "campaign_metrics": {"1": ["clicks"]},
        "campaign_comments": {"1": "Buen mes"},
        "general_comment": "Resumen del período",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["general_comment"] == "Resumen del período"
    campanas = {c["id"]: c for c in body["campaigns"]}
    assert campanas["1"]["selected_metrics"] == ["clicks"]
    assert campanas["1"]["comment"] == "Buen mes"
    assert "selected_metrics" not in campanas["2"]
```

- [ ] **Step 2: Correr la prueba para verificar que falla**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v -k reenvia_campaign_metrics`
Expected: FAIL — `body["general_comment"]` es `KeyError` o el valor no
llega (el endpoint todavía no lee esos campos del `ReportRequest`).

- [ ] **Step 3: `_run_report_job` — parámetros nuevos**

En `intelligence-backend/app/api/routes/reports.py`, cambiar la firma de
`_run_report_job` (línea 74-79) de:

```python
async def _run_report_job(
    job_id: str, account: AdAccount, tokens: list[str],
    date_from, date_to, budget, currency: str, country_code: str | None = None,
    source_currency: str = "USD", exchange_rate: float | None = None,
    attribution_window: str | None = None,
) -> None:
```

a:

```python
async def _run_report_job(
    job_id: str, account: AdAccount, tokens: list[str],
    date_from, date_to, budget, currency: str, country_code: str | None = None,
    source_currency: str = "USD", exchange_rate: float | None = None,
    attribution_window: str | None = None,
    campaign_metrics: dict[str, list[str]] | None = None,
    campaign_comments: dict[str, str] | None = None,
    general_comment: str | None = None,
) -> None:
```

Y su llamada a `report_builder.build_pdf` (línea 82-85) de:

```python
            pdf_bytes, filename = await report_builder.build_pdf(
                account, tokens, date_from, date_to, budget, currency, country_code,
                source_currency, exchange_rate, attribution_window,
            )
```

a:

```python
            pdf_bytes, filename = await report_builder.build_pdf(
                account, tokens, date_from, date_to, budget, currency, country_code,
                source_currency, exchange_rate, attribution_window,
                campaign_metrics, campaign_comments, general_comment,
            )
```

- [ ] **Step 4: `generate_report` — leer y reenviar**

En `generate_report`, el `asyncio.create_task(...)` (línea 218-221), cambiar:

```python
    asyncio.create_task(_run_report_job(
        job_id, account, tokens, data.date_from, data.date_to, data.budget, data.currency.value,
        data.country_code, source_currency, exchange_rate, attribution_window,
    ))
```

a:

```python
    asyncio.create_task(_run_report_job(
        job_id, account, tokens, data.date_from, data.date_to, data.budget, data.currency.value,
        data.country_code, source_currency, exchange_rate, attribution_window,
        data.campaign_metrics, data.campaign_comments, data.general_comment,
    ))
```

- [ ] **Step 5: `report_summary` — leer y reenviar**

En `report_summary`, la llamada a `report_builder.build_report_data` (línea
292-297), cambiar:

```python
        return await report_builder.build_report_data(
            account, tokens, data.date_from, data.date_to, data.budget,
            data.currency.value, data.country_code,
            source_currency, exchange_rate, attribution_window,
        )
```

a:

```python
        return await report_builder.build_report_data(
            account, tokens, data.date_from, data.date_to, data.budget,
            data.currency.value, data.country_code,
            source_currency, exchange_rate, attribution_window,
            data.campaign_metrics, data.campaign_comments, data.general_comment,
        )
```

- [ ] **Step 6: Correr las pruebas para verificar que pasan**

Run: `cd intelligence-backend && pytest tests/test_metricas_configurables.py -v`
Expected: PASS (23 pruebas en total).

- [ ] **Step 7: Correr la suite completa del backend**

Run: `cd intelligence-backend && pytest -v`
Expected: PASS — sin ninguna regresión en el resto del módulo de reportes
(`test_ajustes_organizacion.py`, `test_atribucion_meta.py`, etc).

- [ ] **Step 8: Commit**

```bash
git add intelligence-backend/app/api/routes/reports.py intelligence-backend/tests/test_metricas_configurables.py
git commit -m "feat(reportes): /generate y /summary reenvian metricas y observaciones

Los tres campos nuevos de ReportRequest llegan hasta report_builder en
el job en segundo plano (/generate) y en el resumen sincrono (/summary).
Backend del modulo completo: preview de campanas, seleccion de
metricas y observaciones, de punta a punta.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Frontend — panel de personalización en Reportes

**Files:**
- Modify: `intelligence-web/lib/api.js`
- Modify: `intelligence-web/app/reportes/page.jsx`

**Interfaces:**
- Consumes: `GET /reports/campaigns/{account_id}` (Task 4),
  `ReportRequest.campaign_metrics/campaign_comments/general_comment` (Task 3).

- [ ] **Step 1: `api.js` — llamada al preview**

En `intelligence-web/lib/api.js`, después de la línea `reportStatus: () =>
request("/reports/status"),`, agregar:

```js
  reportCampaigns: (accountId, dateFrom, dateTo, countryCode) => {
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
    if (countryCode) params.set("country_code", countryCode);
    return request(`/reports/campaigns/${accountId}?${params.toString()}`);
  },
```

- [ ] **Step 2: `reportes/page.jsx` — catálogo de métricas y objetivos (JS)**

En `intelligence-web/app/reportes/page.jsx`, después de los imports (línea
9), agregar:

```js
// Mismas claves que pdf_generator.METRIC_REGISTRY (backend) — si se agrega
// una métrica nueva ahí, se agrega aquí también.
const METRIC_CATALOG = [
  { key: "impressions", label: "Impresiones" },
  { key: "reach", label: "Alcance" },
  { key: "frequency", label: "Frecuencia" },
  { key: "clicks", label: "Clics" },
  { key: "ctr", label: "CTR" },
  { key: "cpc", label: "CPC" },
  { key: "cpm", label: "CPM" },
  { key: "conversations", label: "Conversaciones" },
  { key: "cost_per_conversation", label: "Costo / conv." },
  { key: "engagement", label: "Interacciones" },
  { key: "cost_per_engagement", label: "Costo / int." },
  { key: "followers", label: "Seguidores" },
  { key: "cost_per_follower", label: "Costo / seg." },
];

const OBJECTIVE_LABELS = {
  LINK_CLICKS: "Tráfico", TRAFFIC: "Tráfico", MESSAGES: "Mensajes",
  POST_ENGAGEMENT: "Interacción", PAGE_LIKES: "Seguidores", REACH: "Alcance",
  BRAND_AWARENESS: "Reconocimiento", VIDEO_VIEWS: "Vistas de video",
  LEAD_GENERATION: "Leads", CONVERSIONS: "Conversiones",
};
function objectiveLabel(obj) {
  return OBJECTIVE_LABELS[obj] || obj || "—";
}
```

- [ ] **Step 3: Estado y funciones del panel**

Dentro de `ReportesPage`, después de `const [busy, setBusy] = useState(false);`
(línea 37), agregar:

```js
  const [showCustomize, setShowCustomize] = useState(false);
  const [campaignsPreview, setCampaignsPreview] = useState([]);
  const [loadingCampaigns, setLoadingCampaigns] = useState(false);
  const [campaignMetrics, setCampaignMetrics] = useState({});
  const [campaignComments, setCampaignComments] = useState({});
  const [generalComment, setGeneralComment] = useState("");
```

Después de la función `cambiarActivo` (línea 78), agregar:

```js
  async function loadCampaignsPreview() {
    if (!accountId || !dateFrom || !dateTo) return;
    setLoadingCampaigns(true);
    try {
      const response = await api.reportCampaigns(accountId, dateFrom, dateTo, countryCode || null);
      setCampaignsPreview(response.campaigns || []);
      const initialMetrics = {};
      for (const c of response.campaigns || []) {
        initialMetrics[c.id] = c.default_metrics;
      }
      setCampaignMetrics(initialMetrics);
    } catch (e) {
      setErr(e.message);
      setCampaignsPreview([]);
    } finally {
      setLoadingCampaigns(false);
    }
  }

  function toggleCustomize() {
    const next = !showCustomize;
    setShowCustomize(next);
    if (next && campaignsPreview.length === 0) {
      loadCampaignsPreview();
    }
  }

  function toggleMetric(campaignId, key) {
    setCampaignMetrics((prev) => {
      const current = prev[campaignId] || [];
      const next = current.includes(key)
        ? current.filter((k) => k !== key)
        : [...current, key];
      return { ...prev, [campaignId]: next };
    });
  }

  function setCampaignComment(campaignId, text) {
    setCampaignComments((prev) => ({ ...prev, [campaignId]: text }));
  }
```

Después del `useEffect` que carga activos al cambiar de cliente (línea
86-93), agregar uno nuevo que limpia la personalización si cambia el activo
o el período ya cargados:

```js
  // Si cambia el activo comercial o el período después de haber cargado el
  // panel de personalización, la selección queda obsoleta (campañas de otro
  // período) — se limpia y hay que volver a desplegarlo.
  useEffect(() => {
    setCampaignsPreview([]);
    setCampaignMetrics({});
    setCampaignComments({});
    setShowCustomize(false);
  }, [accountId, dateFrom, dateTo]);
```

- [ ] **Step 4: Incluir la personalización al generar**

En la función `generate` (línea 122-138), cambiar:

```js
  async function generate() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const filename = await api.generateReport({
        ad_account_id: Number(accountId),
        report_type: reportType,
        date_from: dateFrom,
        date_to: dateTo,
        budget: budget ? Number(budget) : null,
        currency,
        country_code: countryCode || null,
      });
      setInfo(`Reporte descargado: ${filename}`);
    } catch (e) {
      setErr(e.message);
    } finally { setBusy(false); }
  }
```

a:

```js
  async function generate() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const personalizado = showCustomize && campaignsPreview.length > 0;
      const filename = await api.generateReport({
        ad_account_id: Number(accountId),
        report_type: reportType,
        date_from: dateFrom,
        date_to: dateTo,
        budget: budget ? Number(budget) : null,
        currency,
        country_code: countryCode || null,
        ...(personalizado ? {
          campaign_metrics: campaignMetrics,
          campaign_comments: Object.fromEntries(
            Object.entries(campaignComments).filter(([, v]) => v && v.trim())
          ),
          general_comment: generalComment.trim() || null,
        } : {}),
      });
      setInfo(`Reporte descargado: ${filename}`);
    } catch (e) {
      setErr(e.message);
    } finally { setBusy(false); }
  }
```

- [ ] **Step 5: El panel plegable en el JSX**

En el JSX, después del `</div>` que cierra el `field` del "Presupuesto
aprobado del período" (línea 306, justo antes del `<button className="btn
btn-primary"`), agregar:

```jsx
          {accountId && dateFrom && dateTo && (
            <div className="field">
              <button
                type="button"
                onClick={toggleCustomize}
                style={{
                  display: "flex", alignItems: "center", gap: 6, background: "none",
                  border: "none", padding: 0, cursor: "pointer", color: "var(--muted)",
                  fontSize: 12, fontFamily: "inherit",
                }}
              >
                <span>{showCustomize ? "▾" : "▸"}</span>
                Personalizar métricas y observaciones (opcional)
              </button>

              {showCustomize && (
                <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 14 }}>
                  {loadingCampaigns && (
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>Cargando campañas…</div>
                  )}

                  {!loadingCampaigns && campaignsPreview.length === 0 && (
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>
                      No se encontraron campañas con datos en este período.
                    </div>
                  )}

                  {campaignsPreview.map((c) => (
                    <div key={c.id} className="card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                        {c.name}{" "}
                        <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                          · {objectiveLabel(c.objective)}
                        </span>
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                        {METRIC_CATALOG.map((m) => (
                          <label key={m.key} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                            <input
                              type="checkbox"
                              checked={(campaignMetrics[c.id] || []).includes(m.key)}
                              onChange={() => toggleMetric(c.id, m.key)}
                            />
                            {m.label}
                          </label>
                        ))}
                      </div>
                      <textarea
                        className="input"
                        placeholder="Observaciones de esta campaña (opcional)"
                        value={campaignComments[c.id] || ""}
                        onChange={(e) => setCampaignComment(c.id, e.target.value)}
                        style={{ width: "100%", minHeight: 50, resize: "vertical", fontSize: 12 }}
                      />
                    </div>
                  ))}

                  {campaignsPreview.length > 0 && (
                    <div className="field" style={{ margin: 0 }}>
                      <label>Observaciones generales del período</label>
                      <textarea
                        className="input"
                        value={generalComment}
                        onChange={(e) => setGeneralComment(e.target.value)}
                        style={{ width: "100%", minHeight: 70, resize: "vertical" }}
                        placeholder="Lo que vieron en el mes…"
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

```

- [ ] **Step 6: Verificación manual en staging**

No hay suite de pruebas de frontend en este proyecto — se verifica a mano,
igual que el resto de los cambios de `reportes/page.jsx` (ver
`git log --oneline -- intelligence-web/app/reportes/page.jsx`).

1. `cd intelligence-web && npm run build` — confirmar que compila sin errores.
2. Desplegar a **staging** (no producción — ver acuerdo con el usuario).
3. En staging: generar un reporte **sin** abrir el panel nuevo → debe verse
   pixel-idéntico al de antes de este cambio (mismas métricas automáticas,
   sin sección de "Observaciones").
4. Abrir "Personalizar métricas y observaciones", quitar una métrica
   automática y agregar una que no correspondía al objetivo en 2-3 campañas
   distintas, escribir una observación por campaña y una general → generar
   → confirmar en el PDF resultante que:
   - Cada tarjeta de campaña muestra exactamente las métricas marcadas.
   - Cada comentario de campaña aparece dentro de su tarjeta.
   - La observación general aparece en la sección "Observaciones del
     período".
5. Cambiar de activo comercial (o de período) después de haber cargado el
   panel → confirmar que la selección se limpia y el panel vuelve a
   "plegado".

- [ ] **Step 7: Commit**

```bash
git add intelligence-web/lib/api.js intelligence-web/app/reportes/page.jsx
git commit -m "feat(reportes): panel de personalizacion de metricas y observaciones

Seccion opcional/plegada en el formulario de Reportes: por campana,
elegir que metricas del catalogo mostrar (no solo las automaticas del
objetivo) y escribir una observacion; mas una observacion general del
periodo. Si nunca se abre, el reporte sale igual que antes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Cobertura del spec:**
- Show/hide de métricas existentes, control total por campaña → Task 1
  (`METRIC_REGISTRY`, `metrics_for_campaign`), Task 6 (checklist en UI).
- Observaciones generales y por campaña, efímeras → Task 2 (render), Task 3
  (payload), Task 6 (textareas).
- Panel opcional/plegado (no automático) → Task 6, Step 5.
- Retrocompatibilidad cuando no se personaliza → cubierto explícitamente en
  Task 1 (regresión de `metrics_by_objective`), Task 3 (test
  `test_build_report_data_sin_personalizacion_no_agrega_claves`).
- Preview de campañas antes de generar → Task 4.
- Testing manual en staging → Task 6, Step 6.
- Fuera de alcance (gráficas, leads, datos externos, persistencia) →
  ninguna tarea los toca; consistente con el spec.
