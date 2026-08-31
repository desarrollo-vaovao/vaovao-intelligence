# Panel de personalización de reportes como modal

**Fecha:** 2026-08-31
**Estado:** aprobado, pendiente de plan de implementación

## Problema

El panel "Personalizar métricas y observaciones" (ver spec
[2026-08-31-metricas-configurables-y-observaciones-design.md](2026-08-31-metricas-configurables-y-observaciones-design.md))
se implementó como una sección plegable **dentro de la misma página** de
Reportes: al abrirla, cada campaña del período aparece como una tarjeta con
su checklist completo de métricas y su textarea de comentario, una debajo de
otra, en el flujo normal del documento.

Probado en staging con una cuenta real: con cuentas que tienen decenas de
campañas activas en el período, esto estira la página de forma incómoda —
mucho scroll, y renderizar todos los checklists de una sola vez se siente
pesado. Es un problema de espacio/scroll y de percepción de rendimiento, no
de datos incorrectos — la funcionalidad en sí (elegir métricas, escribir
observaciones) funciona bien.

## Objetivo

Mover la personalización a un **modal** con scroll interno propio (no
estira la página de Reportes), con:
- Un buscador/filtro por nombre de campaña.
- Cada campaña **colapsada por defecto** (solo nombre + objetivo + flecha);
  se expande al hacer clic para mostrar su checklist de métricas y su
  comentario. Con esto, aunque haya 100 campañas, lo único que se renderiza
  de entrada es una fila de texto por cada una — no 100 grids de checkboxes.
- La observación general del período se mueve dentro del mismo modal.

El estado (qué se eligió, qué se escribió) sigue viviendo en el componente
`ReportesPage` de siempre — el modal es solo la superficie visual. Cerrar el
modal no descarta nada; el botón "Generar y descargar PDF" de la página
sigue funcionando exactamente igual que hoy, sin un paso de "guardar"
intermedio.

## Diseño

### Qué NO cambia

- El endpoint `GET /reports/campaigns/{account_id}` (backend, ya construido).
- El catálogo de métricas (`METRIC_CATALOG` en frontend, `METRIC_REGISTRY`
  en backend).
- El payload que se manda a `generateReport` (`campaign_metrics`,
  `campaign_comments`, `general_comment`) — se sigue armando igual, a partir
  del mismo estado de React.
- La condición de retrocompatibilidad: si nunca se abrió el panel
  (`showCustomize` nunca pasó a `true` con campañas cargadas), el payload no
  incluye esos tres campos.
- El `useEffect` que invalida la selección cargada cuando cambian activo
  comercial, período o país (ver spec anterior) — sigue limpiando el mismo
  estado, ahora también cerrando el modal si estaba abierto.

### Qué cambia en `intelligence-web/app/reportes/page.jsx`

**El botón deja de desplegar una sección — abre el modal.**

`toggleCustomize()` deja de alternar `showCustomize` como "sección
visible/oculta en el documento" y pasa a controlar si el modal está
montado. La carga de campañas (`loadCampaignsPreview`, ya existente) se
sigue disparando la primera vez que se abre, igual que hoy.

Estado nuevo, además del que ya existe (`campaignsPreview`,
`campaignMetrics`, `campaignComments`, `generalComment`):
- `campaignSearch: string` — texto del buscador.
- `expandedCampaignId: string | null` — qué campaña está expandida dentro
  del modal (una a la vez; abrir otra colapsa la anterior — evita que con
  varias campañas expandidas el modal vuelva a tener el mismo problema de
  scroll que se está resolviendo).

**Filtrado del buscador:** insensible a mayúsculas/acentos simple
(`.toLowerCase()` sobre nombre de campaña y término de búsqueda — no hace
falta normalización de acentos más sofisticada, el resto de buscadores de
la app no la tiene).

**El botón "Personalizar métricas y observaciones" del formulario principal**
se conserva (mismo texto, mismo lugar), pero ahora abre el modal en vez de
desplegar contenido en línea. Mientras `loadingCampaigns` es `true`, el
modal igual se abre y muestra su propio estado de carga adentro (no hay
por qué esperar a tener los datos para mostrar el modal).

### El modal

Componente nuevo `CustomizeReportModal`, en el mismo archivo
`reportes/page.jsx` (el resto de componentes de esta página ya viven en un
solo archivo — no hay precedente de extraer a archivos separados en este
módulo, y el componente es chico).

Estructura:
1. **Header:** título "Personalizar métricas y observaciones", botón de
   cerrar (✕).
2. **Buscador:** input de texto, filtra `campaignsPreview` por nombre en
   vivo.
3. **Lista de campañas** (contenedor con `overflow-y: auto` y una altura
   máxima — el scroll vive AQUÍ, no en la página): cada campaña es una fila
   colapsada (nombre + objetivo + flecha) que, al hacer clic, se expande
   in-place mostrando su checklist de métricas y su textarea de comentario
   — exactamente el mismo contenido que ya se armaba por campaña en el
   diseño anterior, solo que ahora oculto hasta que se expande. Si el
   buscador no encuentra ninguna campaña, mensaje "Sin resultados para
   '{término}'".
4. **Observación general del período:** textarea, fija debajo de la lista
   de campañas (fuera del área con scroll, siempre visible).
5. **Footer:** un botón "Listo" que cierra el modal (no descarta nada — el
   estado ya vive en `ReportesPage`, cerrar es solo ocultar el modal).

Cerrar con la tecla Escape o haciendo clic fuera del modal tiene el mismo
efecto que "Listo": oculta el modal, conserva el estado.

### Accesibilidad y estilo

Reutiliza los tokens de color/tipografía que ya usa el resto de la página
(`var(--surface2)`, `var(--border2)`, `var(--orange)`, clases `.card`/
`.input` ya existentes) — mismo criterio que el resto del módulo de
Reportes, nada de un sistema visual nuevo. El overlay del modal usa un
fondo semitransparente oscuro estándar; cerrar al hacer clic en el overlay
(no en el contenido) y al presionar Escape.

## Fuera de alcance

- Paginación o carga incremental de campañas desde el backend — el
  endpoint sigue devolviendo la lista completa de una vez; el colapso por
  fila ya resuelve el problema de renderizado percibido para los tamaños de
  cuenta actuales. Si en el futuro una cuenta tiene cientos (no decenas) de
  campañas, ahí sí se revisita.
- Cualquier cambio al backend — este spec es puramente de UI sobre trabajo
  ya construido y desplegado.

## Testing

No hay suite de pruebas de frontend en este proyecto (igual que el resto
de `reportes/page.jsx`) — verificación manual:
- `npm run build` limpio.
- En staging, con la misma cuenta de muchas campañas que expuso el
  problema original: abrir el modal, buscar por nombre, expandir/colapsar
  varias campañas, escribir observaciones, cerrar con "Listo", generar el
  PDF y confirmar que el resultado refleja lo elegido — igual que la
  verificación manual ya pendiente del spec anterior.
- Confirmar que cerrar con Escape / clic afuera no pierde lo ya escrito
  (el estado sigue en `ReportesPage`, no en el modal).
