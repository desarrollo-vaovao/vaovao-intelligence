# Panel de Leads — Diseño

Fecha: 2026-08-26
Estado: aprobado

## Contexto

El backend del módulo de leads está terminado, probado y fusionado en `dev`. La API
expone listado paginado, detalle con bitácora, edición (etapa, responsable, notas),
exportación CSV, estado del módulo y reconciliación de huérfanos. El frontend
(`intelligence-web/app/leads/page.jsx`) es hoy un placeholder de 5 líneas con
`<ComingSoon />`.

Stack: Next.js 14.2.5 (app router), React 18. Cliente HTTP: `lib/api.js`. Token en
`localStorage` como `vv_token`.

## Decisiones de arquitectura

### Archivo único

Todo en `leads/page.jsx`, con subcomponentes como funciones privadas en el mismo
archivo. Sigue el patrón exacto de `clientes/page.jsx` (446 líneas). Si durante la
implementación el archivo supera ~900 líneas, se extrae la parte más pesada en markup
a un componente hermano, pero solo si es necesario.

### Sin librerías adicionales

Sin drag-and-drop, sin librerías de gráficas, sin state management externo. React
hooks + CSS global, igual que el resto del proyecto.

### RBAC

El frontend no esconde controles de edición según rol. El backend devuelve 403 si un
`member` intenta editar un lead que no tiene asignado; el frontend muestra el error.
Consistente con la regla: "el frontend refleja, no reimplementa" el RBAC.

## Endpoints que se consumen

| Método | Ruta | Uso |
|--------|------|-----|
| GET | `/leads?page=&size=&client_id=&status=&search=` | Listado paginado |
| GET | `/leads/{id}` | Detalle + bitácora |
| PATCH | `/leads/{id}` | Editar etapa, responsable, notas |
| GET | `/leads/export/csv?client_id=` | Descarga CSV |
| GET | `/leads/status` | Estado + huérfanos pendientes |
| POST | `/leads/orphans/{page_id}/reconcile` | Reconciliar (admin/owner) |
| GET | `/users` | Lista de usuarios (para selector de responsable) |

## Cambios en `lib/api.js`

6 métodos nuevos:

- `listLeads(params)` — GET con query params, respuesta JSON.
- `getLead(id)` — GET detalle.
- `updateLead(id, body)` — PATCH.
- `leadsStatus()` — GET status del módulo.
- `exportLeadsCsv(params)` — fetch directo (blob), descarga automática vía anchor.
  Patrón idéntico a `generateReport` para el PDF.
- `reconcileOrphans(pageId)` — POST.

## Estado del componente principal

```
leads         — items de la página actual, o null (cargando)
total         — total para el paginador
page          — página actual (empieza en 1)
view          — "pipeline" | "lista"
search        — string del buscador (solo vista lista, debounce 400ms)
statusFilter  — filtro de etapa o null
err           — mensaje de error o ""
detailLead    — lead seleccionado para modal de detalle, o null
users         — lista de usuarios (para selector de responsable)
moduleStatus  — respuesta de /leads/status
exporting     — boolean
```

El `client` activo viene de `useClient()`. Cuando cambia, se recarga el listado.

## Layout

```
<Shell>
  page-head: título + subtítulo con nombre del cliente + toggle Pipeline/Lista + botón Exportar CSV
  err (condicional)
  MetricCards (grid responsive)
  Vista activa: KanbanBoard | LeadTable
  LeadDetailModal (condicional)
</Shell>
```

## Tarjetas de métricas

Grid `repeat(auto-fit, minmax(210px, 1fr))`. 4 tarjetas:

1. **Leads del período** — funcional (usa `total` del listado).
2. **Costo por lead** — placeholder "—" (requiere endpoint de métricas).
3. **Tasa de contacto** — placeholder "—".
4. **Cierre** — placeholder "—".

Las gráficas (leads/día, origen) se omiten en esta versión. Se agregan cuando exista
`GET /leads/metrics`.

## Vista Pipeline (Kanban)

- Contenedor flex con scroll horizontal.
- 5 columnas: Nuevo, Contactado, Calificado, Propuesta, Ganado.
- Perdido NO tiene columna (es terminal). Se ve en vista Lista y se marca desde el
  modal de detalle.
- Header de columna: nombre + conteo en badge.
- Tarjetas: nombre del lead, campaña, edad relativa desde `received_at`.
- Sin drag-and-drop. Cambio de etapa desde el modal.
- Click en tarjeta abre modal de detalle.

### Extracción de nombre desde `form_data`

Buscar en orden: `full_name`, `nombre_completo`, `nombre`, `name`,
`first_name` + `last_name`. Si ninguno existe, primer valor string no vacío del dict.
Fallback: `leadgen_id` truncado.

Para contacto: `phone_number`, `telefono`, `teléfono`, `phone`, `email`, `correo`,
`correo_electronico`. Mostrar el primero que exista.

## Vista Lista

- Buscador con placeholder "Buscar nombre, teléfono o correo". Debounce 400ms. Al lado,
  contador "{total} leads".
- Tabla: Lead (nombre + contacto), Campaña, Etapa (badge con color), Responsable,
  Ingreso (fecha relativa).
- Paginador: Anterior/Siguiente, "Página X de Y". `size=50`.
- Click en fila abre modal de detalle.

## Modal de detalle

Se abre al clic. Hace `GET /leads/{id}` para traer detalle completo con bitácora.

### Contenido

**Encabezado**: nombre + badge de etapa.

**Datos del formulario**: todos los pares clave-valor de `form_data` en lista `<dl>`.
Campaña si existe.

**Campos editables**:
- Etapa: `<select>` con 6 opciones. PATCH al cambiar.
- Responsable: `<select>` con usuarios de `api.listUsers()`. "Sin asignar" manda
  `assigned_to_id: null`. PATCH al cambiar.
- Notas: `<textarea>`. Botón "Guardar notas" que hace PATCH.

**Bitácora**: timeline vertical, orden cronológico inverso. Cada entrada: acción,
usuario (o "Sistema" si null), old → new, timestamp relativo.

**Pie**: botón "Cerrar".

## Fix del 409 en `clientes/page.jsx`

`DeleteClientModal` hoy muestra el error del 409 (cuando el cliente tiene leads) como
`<div className="err">`, que es rojo y genérico. El backend ya manda un mensaje
descriptivo.

Cambio: detectar si el error contiene "leads", mostrarlo en
`<div className="notice">` (naranja, informativo) en vez de `<div className="err">`.

## CSS nuevo en `globals.css`

Clases mínimas:
- `.badge-stage-*` para los colores de cada etapa del pipeline (nuevo=naranja,
  contactado/calificado=neutral, propuesta=muted, ganado=verde, perdido=gris).
- `.kanban` container flex con overflow-x auto.
- `.kanban-col` para columnas.
- `.kanban-card` para tarjetas.
- `.lead-detail-field` para pares clave-valor en el modal.
- `.timeline` para la bitácora.

## Backend pendiente (no bloquea esta entrega)

`GET /leads/metrics?client_id=&date_from=&date_to=` — necesario para las 3 tarjetas
de métricas que quedan en placeholder y para las gráficas. Shape esperada:

```json
{
  "leads_count": 128,
  "leads_previous": 104,
  "cost_per_lead": 9.85,
  "contact_rate": 0.78,
  "close_rate": 0.14,
  "by_day": [{"date": "2026-08-16", "nuevos": 12, "calificados": 5}],
  "by_source": [{"campaign_name": "Conversiones Ago", "count": 52}]
}
```

## Entregables

1. `lib/api.js` — 6 métodos nuevos de leads.
2. `leads/page.jsx` — página completa: Kanban, Lista, toggle, modal de detalle con
   edición y bitácora, exportación CSV, métrica funcional + 3 placeholder.
3. `clientes/page.jsx` — fix del 409 en DeleteClientModal.
4. `globals.css` — clases CSS nuevas para el Kanban, badges de etapa, timeline.
