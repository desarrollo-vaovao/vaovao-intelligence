# Métricas configurables y observaciones en reportes

**Fecha:** 2026-08-31
**Estado:** aprobado, pendiente de plan de implementación

## Problema

El motor de reportes (`report_builder.py`, `pdf_generator.py`) genera un PDF con
una plantilla rígida: `metrics_by_objective` decide, sin posibilidad de
cambiarlo, qué 3-4 métricas se muestran por tarjeta de campaña según su
objetivo (MESSAGES → conversaciones, REACH → frecuencia, etc.). Quien arma el
reporte no puede:

1. Quitar una métrica automática que no le sirve a ese cliente, ni agregar una
   que sí necesita aunque no corresponda al objetivo detectado.
2. Escribir observaciones o comentarios cualitativos sobre lo visto en el
   período — hoy el reporte es 100% cifras, sin ningún espacio para el
   análisis de quien lo arma.

Este es el primer recorte de una idea más grande ("reportes más robustos y
funcionales": métricas configurables, observaciones, gráficas, datos de
leads). Las demás piezas quedan fuera de este spec — se abordarán como
proyectos independientes.

## Objetivo

Dentro de una sección opcional del formulario de Reportes, quien genera el
reporte puede, **por campaña**, elegir qué métricas mostrar (de un catálogo
fijo, no solo las automáticas de su objetivo) y escribir un comentario. También
puede escribir una observación general del período. Todo esto es efímero: se
escribe en el momento de generar ese PDF puntual y no se guarda en la base de
datos. Si el usuario no abre la sección, el reporte sale exactamente igual que
hoy — retrocompatible por defecto.

## Diseño

### 1. Catálogo de métricas (backend)

`pdf_generator.py` reemplaza la función `metrics_by_objective` (selección
implícita por objetivo) por un registro explícito:

```python
METRIC_REGISTRY = {
    "impressions":   {"label": "Impresiones", ...},
    "reach":         {"label": "Alcance", ...},
    "frequency":     {"label": "Frecuencia", ...},
    "clicks":        {"label": "Clics", ...},
    "ctr":           {"label": "CTR", ...},
    "cpc":           {"label": "CPC", ...},
    "cpm":           {"label": "CPM", ...},
    "conversations": {"label": "Conversaciones", ...},
    "cost_per_conversation": {"label": "Costo / conv.", ...},
    "engagement":    {"label": "Interacciones", ...},
    "cost_per_engagement":   {"label": "Costo / int.", ...},
    "followers":     {"label": "Seguidores", ...},
    "cost_per_follower":     {"label": "Costo / seg.", ...},
}
```

Cada entrada sabe extraer y formatear su valor desde `insights` (mismo cálculo
que hoy vive disperso en `metrics_by_objective`/`ad_main_metric`/
`ad_cost_metric`). Cuando el dato no aplica a ese objetivo (ej. "Frecuencia" en
una campaña de Mensajes), se muestra "—", igual que ya pasa hoy con campos
ausentes.

`metrics_by_objective(objective, insights, currency_symbol)` se conserva tal
cual para seguir dando el set automático **por defecto** (se usa como
`default_metrics` en el nuevo endpoint de preview, y como fallback cuando no
hay override). Se agrega `metrics_for_campaign(campaign, currency_symbol,
selected_keys=None)`: si `selected_keys` viene, arma la lista resolviendo esas
claves contra `METRIC_REGISTRY`; si no, delega en `metrics_by_objective` con el
comportamiento de siempre.

### 2. Preview de campañas — `GET /reports/campaigns`

Nuevo endpoint en `reports.py`, mismo patrón de autorización que
`/reports/countries/{account_id}` (`_get_owned_account` + `resolve_tokens`).

**Query params:** `ad_account_id`, `date_from`, `date_to`, `country_code`
(opcional).

Reutiliza `meta_api.get_account_data_with_fallback` (mismo fetch que ya hace
`/reports/summary`) y, si aplica, `report_builder._filter_campaigns_by_country`.
Devuelve solo lo liviano — nada de `ads` ni datos de imagen:

```json
{
  "campaigns": [
    {"id": "12345", "name": "Campaña Q3", "objective": "MESSAGES",
     "default_metrics": ["impressions", "conversations", "cost_per_conversation"]}
  ]
}
```

Se paga una llamada extra a Meta, pero solo cuando el usuario abre la sección
de personalización — no en el flujo simple de "generar y ya".

### 3. Payload extendido — `ReportRequest`

Tres campos nuevos, todos opcionales (default `None`), sin tocar los
existentes:

```python
campaign_metrics: dict[str, list[str]] | None = None   # campaign_id -> claves de METRIC_REGISTRY
campaign_comments: dict[str, str] | None = None         # campaign_id -> texto libre
general_comment: str | None = None
```

### 4. `report_builder.py`

`build_report_data` y `build_pdf` reciben los tres campos nuevos (parámetros
opcionales, default `None`, al final de la firma para no romper llamadores
existentes) y:

- A cada campaña le adjunta `selected_metrics = campaign_metrics.get(campaign["id"])`
  (o `None` si no vino) y `comment = campaign_comments.get(campaign["id"], "")`.
- Al `report_data` le adjunta `general_comment`.

### 5. `pdf_generator.py` — render

- `render_campaign_card` llama `metrics_for_campaign(campaign, currency_symbol,
  campaign.get("selected_metrics"))` en vez de `metrics_by_objective`
  directamente, y agrega un bloque de comentario (mismo estilo visual que la
  sección de "Anuncios" dentro de la tarjeta) si `campaign.get("comment")`
  no está vacío.
- `render_report_page` agrega una sección nueva "Observaciones del período"
  (mismo patrón visual que "Resumen de inversión") entre el resumen de
  inversión y la tabla de campañas, solo si `report_data.get("general_comment")`
  no está vacío.

### 6. Frontend — `reportes/page.jsx`

- Sección plegable nueva, **"Personalizar métricas y observaciones
  (opcional)"**, debajo del período. Se despliega solo con clic; al abrirla por
  primera vez dispara `GET /reports/campaigns` con el activo+período+país ya
  elegidos.
- Por cada campaña devuelta: nombre, badge de objetivo (reutiliza
  `OBJECTIVE_LABELS`/colores ya usados en el PDF, portados a JS o vía un
  pequeño endpoint/constante compartida), checklist de métricas (catálogo fijo
  igual a las claves de `METRIC_REGISTRY`, pre-marcadas según
  `default_metrics`), y un textarea de comentario por campaña.
- Un textarea "Observaciones generales del período" siempre visible una vez
  cargada la sección.
- Si cambia el activo comercial o el período después de haber cargado la
  sección, se limpia la selección y hay que volver a desplegarla (evita mandar
  IDs de campaña que ya no corresponden al nuevo período).
- Al generar: si la sección nunca se abrió, el payload no incluye los tres
  campos nuevos (idéntico al comportamiento de hoy). Si se abrió, se arman
  `campaign_metrics`/`campaign_comments`/`general_comment` a partir del estado
  del formulario y se agregan al payload de `api.generateReport`.

## Fuera de alcance (este spec)

- Gráficas.
- Reportes de datos de leads.
- Ingesta de datos numéricos externos a Meta (caso "B" discutido y descartado
  para esta fase).
- Persistencia de comentarios/selección de métricas — es efímero, vive solo en
  la sesión de generación de ese PDF puntual.

## Testing

**Backend**

- `GET /reports/campaigns`: devuelve campañas del período correcto, respeta
  filtro de país, 404 si el activo no es de la organización del usuario, 503
  si no hay tokens.
- `metrics_for_campaign`: con `selected_keys` explícito arma exactamente esas
  métricas (incluyendo alguna que no correspondería al objetivo, mostrando
  "—"); sin `selected_keys` cae en el comportamiento automático de hoy
  (`metrics_by_objective`), verificado campaña por campaña para no regresar el
  comportamiento actual.
- `build_report_data`/`build_pdf`: con los tres campos nuevos ausentes, el
  resultado es idéntico al de antes de este cambio (test de regresión). Con
  ellos presentes, `general_comment` y los comentarios/métricas por campaña
  aparecen en el HTML generado.

**Manual en staging**

- Reporte sin abrir la sección nueva → debe verse pixel-idéntico al de hoy.
- Reporte abriendo la sección, personalizando métricas de 2-3 campañas
  distintas y escribiendo observación general + por campaña → verificar en el
  PDF resultante.
- Cambiar de activo comercial o período después de cargar la sección → la
  selección se limpia, no se manda un `campaign_id` de otro período.
