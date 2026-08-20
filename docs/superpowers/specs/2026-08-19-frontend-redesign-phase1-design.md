# Rediseño de front-end — Fase 1: base visual + navegación

## Contexto

VaoVao trajo una propuesta de diseño nueva para la app (`Vaovao Intelligence.dc.html`, canvas de diseño) con una identidad visual distinta a la actual — Unbounded + Inter, `#0F0F0E`/`#FF4422` plano en vez de Poppins + gradiente Instagram — y 8 secciones de navegación (Resumen, Analítica, Leads, Reportes, Clientes, Usuarios, Conexión Meta, Ajustes), de las cuales hoy solo existen 4 páginas reales (Clientes, Reportes, Usuarios, Conexión Meta).

El cambio completo es demasiado grande para un solo ciclo de spec → plan → implementación, así que se decidió dividirlo en fases. **Esta fase (1) cubre solo la base: tokens visuales, tipografía y el shell de navegación** — no reconstruye el contenido de ninguna pantalla nueva ni el constructor de reportes tipo canvas del mockup.

## No-objetivos de esta fase

- Contenido real de Resumen, Analítica, Leads o Ajustes (quedan como placeholder oculto).
- Reconstrucción del constructor de reportes (biblioteca/constructor/programados) del mockup — Reportes solo recibe el nuevo look, no nueva funcionalidad.
- Cualquier trabajo sobre el módulo de Leads en el backend (fuera de alcance; ver rollback pendiente).
- Migración a un framework de utilidades CSS (Tailwind) — se mantiene el patrón actual de CSS plano con variables.

## Rama de trabajo

`dev` se resetea al estado actual de `main` (descarta los 2 commits del módulo de Leads/Tracker pendientes de rollback) y se fuerza el push a `origin/dev`. Todo el trabajo de esta fase se hace sobre `dev`.

## Arquitectura visual

Se mantiene el patrón existente: variables CSS en `app/globals.css` + clases utilitarias compartidas (`.btn`, `.card`, `.table`, etc.), sin introducir Tailwind ni CSS-in-JS. Es el approach de menor costo y más consistente con el código ya escrito.

**Tokens** (reemplazan los actuales en `:root`):
```
--bg: #0F0F0E        --surface: #161614     --surface2: #1C1C19
--border: #262622     --border2: #35352F     --border3: #45453D
--text: #F5F5F2       --muted: #8A8A82       --muted2: #57574F   --muted3: #66665F
--accent: #FF4422      --accent-hover: #E63912
--accent-bg: #1E100C   --accent-border: #3A1A10
--success: #4ade80 (se mantiene)   --error: #f87171 (se mantiene)
--radius: 14px         --radius-sm: 9px       --radius-pill: 999px
```
Se elimina `--gradient` y todo su uso (botón primario, indicador de nav activo) pasa a `--accent` plano.

**Tipografía**: `next/font/google` carga Unbounded (200/300/400/500/700/900) e Inter (400/500/600/700) como variables CSS (`--font-unbounded`, `--font-inter`), reemplazando Poppins en `layout.jsx`. Unbounded para headings/marca/labels de sección (mayúsculas, tracking amplio, como en el mockup); Inter para texto de cuerpo y datos tabulares (`font-variant-numeric: tabular-nums`).

## Componentes

### `lib/Shell.jsx` (reescritura)
- **Sidebar**: marca (VAOVAO / INTELLIGENCE), selector de cliente activo, nav con las 4 secciones reales, tarjeta de estado de sincronización de Meta, botón de colapsar sidebar (persistido en `localStorage`, ancho con transición CSS).
- **Header**: breadcrumb (nombre de la sección activa), `DateRangePicker` existente reubicado ahí, toggle de moneda USD/GTQ (preferencia visual persistida en `localStorage`, sin lógica de conversión — nada la consume todavía), campana de notificaciones (elemento visual estático, sin backend de notificaciones), menú de usuario (ya existe la data en `useAuth()`).
- Las 4 rutas nuevas **no se agregan al array `NAV`** — existen como páginas pero no aparecen en el sidebar hasta que se aprueben en su propia fase.

### `lib/clients.jsx` (nuevo)
Mismo patrón que `lib/auth.jsx`: `ClientProvider` + hook `useClient()` que expone `{ client, clients, setClient, loading }`. Trae la lista real vía `api.listClients()` una sola vez (se monta dentro de `AuthProvider` en `layout.jsx`, ya que requiere el token), guarda el cliente activo elegido en `localStorage` y lo restaura al recargar. Se construye ahora sin consumidores (ninguna pantalla lo usa aún) para que Fase 2 (Resumen/Analítica) lo consuma directo sin rehacer esta pieza — es la única parte de esta fase donde se adelanta trabajo a propósito, porque es barata y evita duplicar el fetch de clientes más adelante.

La tarjeta de "Meta API sincronizada" en el sidebar muestra la cantidad real de cuentas conectadas (derivada de la data de `useClient()`), pero no un timestamp de "última sincronización" real — el backend no trackea ese dato hoy, así que no se inventa.

### Rutas placeholder (nuevas)
`app/resumen/page.jsx`, `app/analitica/page.jsx`, `app/leads/page.jsx`, `app/ajustes/page.jsx` — cada una envuelta en `Shell`, con un estado "Próximamente" simple (mismo patrón que `.empty` ya existe en CSS). Sirven para poder revisar la navegación completa por URL directa antes de aprobar cada pantalla.

### Páginas existentes (pase de estilo, sin cambios de lógica)
`clientes`, `reportes`, `usuarios`, `conexion`, `login` — ajustan a los tokens y clases nuevas. No se toca el fetching, los modales, ni la estructura de datos de ninguna.

## Infraestructura de ambientes

**Railway**: nuevo ambiente `dev` dentro del proyecto `vaovao-intelligence` existente, con su propio servicio Postgres vacío. Variables clonadas de producción salvo `ENCRYPTION_KEY` y `SECRET_KEY` (se regeneran, nunca se reutilizan las de prod) y `ENVIRONMENT=development`. Deploy manual desde la rama `dev`.

**Vercel**: mismo proyecto (`vaovao-intelligence`, sin integración Git automática hoy), deploy preview manual vía CLI (`vercel deploy`, no `--prod`) desde `dev`, con `NEXT_PUBLIC_API_URL` de Preview apuntando al backend dev de Railway.

**Housekeeping**: se agrega `.vercel` a `intelligence-web/.gitignore` (falta hoy, por eso aparece como untracked).

## Verificación

- `npm run lint` y `npm run build` en `intelligence-web` sin errores.
- Revisión visual en navegador (`npm run dev`) de las 5 páginas reales en las resoluciones desktop y mobile del breakpoint ya existente (`max-width: 720px`), confirmando que el sidebar colapsa a fila horizontal como hoy.
- Confirmar que las 4 rutas placeholder cargan por URL directa y no aparecen en el sidebar.
- Deploy preview en Vercel dev + backend en Railway dev respondiendo antes de dar la fase por cerrada.
