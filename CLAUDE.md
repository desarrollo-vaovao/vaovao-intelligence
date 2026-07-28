# CLAUDE.md — VaoVao Intelligence

Contexto permanente del proyecto para Claude Code. Léelo antes de hacer cambios.

## Qué es

Plataforma **interna** de VaoVao (agencia de marketing en Guatemala) para gestionar
clientes y generar reportes de campañas de **Meta Ads** en PDF. Reemplaza una
reportería anterior hecha en Node donde los clientes estaban "quemados" en código
(`clients.js`); ahora todo vive en base de datos, con usuarios, roles y conexión a Meta.

Es de uso interno para el equipo (no es un producto público), aunque la arquitectura
es multi-tenant por si algún día se abre.

## Arquitectura

Dos proyectos hermanos, cada uno con su propio repo:

- **`intelligence-backend/`** — API. Python 3.11+, FastAPI, SQLAlchemy 2.0,
  base de datos PostgreSQL (en local: SQLite `dev.db`). Se despliega en Railway.
- **`intelligence-web/`** — Consola. Next.js 14 (App Router), JavaScript (no TS).
  Consume el API. Se despliega en Vercel.

## Cómo correr (local, Windows/PowerShell)

Backend (terminal 1):
```
cd intelligence-backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload      # http://localhost:8000  (docs en /docs)
```

Frontend (terminal 2):
```
cd intelligence-web
npm run dev                        # http://localhost:3000
```

Importante:
- El `.env` **no** se recarga solo: al cambiarlo, reinicia uvicorn.
- La generación de PDF usa **Playwright**: requiere `pip install playwright` y
  `playwright install chromium` una vez.

## Backend — estructura

```
app/
├── main.py                     # arranque, CORS, routers, create_all al inicio
├── core/
│   ├── config.py               # settings (pydantic-settings, lee .env)
│   ├── database.py             # engine + SessionLocal + Base + get_db
│   ├── security.py             # bcrypt (hash password) + JWT (PyJWT)
│   └── crypto.py               # Fernet: cifra/descifra tokens sensibles
├── models/__init__.py          # Organization, User, Client, AdAccount, FacebookConnection
├── schemas/__init__.py         # Pydantic (request/response)
├── api/
│   ├── deps.py                 # get_current_user (JWT) + require_roles(...)
│   └── routes/
│       ├── auth.py             # register, login, me
│       ├── clients.py          # CRUD clientes + ad accounts (aislado por org)
│       ├── users.py            # gestión de usuarios y roles (owner/admin)
│       ├── organization.py     # token central de Meta (System User), cifrado
│       ├── facebook.py         # OAuth "Conectar con Facebook" (por usuario)
│       └── reports.py          # status, generate (PDF), check-access
└── services/
    ├── meta_api.py             # llama a la Graph API: datos, verificación, list_ad_accounts
    ├── pdf_generator.py        # arma el HTML del reporte y lo pasa a PDF (Playwright)
    └── report_builder.py       # pegamento: meta_api → estructura → pdf_generator
```

## Frontend — estructura

```
app/
├── globals.css                 # TODO el tema vive aquí (ver "Diseño")
├── layout.jsx                  # fuente Poppins + AuthProvider
├── login/page.jsx
├── clientes/page.jsx           # clientes + cuentas + "Probar acceso"
├── reportes/page.jsx           # formulario centrado + DateRangePicker
├── usuarios/page.jsx
└── conexion/page.jsx           # Facebook (arriba) + token central (alternativa)
lib/
├── api.js                      # cliente HTTP (token en localStorage 'vv_token')
├── auth.jsx                    # AuthProvider / useAuth
├── Shell.jsx                   # layout con sidebar + guardia de sesión
├── FacebookConnect.jsx         # tarjeta "Conectar con Facebook"
└── DateRangePicker.jsx         # calendario estilo Meta (rango azul) + presets
```

## Conexión con Meta — DECISIÓN CLAVE

Hay **dos formas** de acceder a Meta, y la plataforma prefiere la primera:

1. **Por usuario (recomendado, es lo que se usa):** cada persona hace clic en
   "Conectar con Facebook" (OAuth / Facebook Login for Business) y la plataforma
   guarda **su** token de larga duración, cifrado, en `FacebookConnection`. Sus
   reportes usan su propio acceso. Así no se depende de una sola cuenta central ni
   de asignaciones administrativas. Esto destrabó el proyecto (antes, con el token
   central, las cuentas de cliente daban "Not Found" por falta de asignación).

2. **Token central (System User), alternativa:** un token único a nivel de
   organización, guardado cifrado en `Organization.meta_token_encrypted`. Queda como
   respaldo (`_resolve_token` en reports.py usa Facebook del usuario primero, luego
   el central).

### App de Meta
- App tipo **Business**: "Vaovao Reporteria", App ID `1000050136112118`.
- El `FB_APP_SECRET` va en `.env` (nunca en Git).
- Redirect URI registrado: `http://localhost:8000/auth/facebook/callback`.
- Scopes: `ads_read,business_management,public_profile`.
  `business_management` es necesario para ver cuentas del **portafolio comercial**
  (`owned_ad_accounts` / `client_ad_accounts`), no solo las de rol directo.
- La app está en **modo desarrollo**: solo funciona para personas agregadas en
  "Roles de la app". No requiere App Review para uso interno. Pendiente: agregar al
  equipo de marketing como testers/admins para que puedan conectarse.
- Si cambian los scopes, hay que **desconectar y reconectar** para reautorizar.

## Motor de reportes

Flujo al generar (endpoint `POST /reports/generate`):
1. `_resolve_token` obtiene el token (Facebook del usuario, o central).
2. `report_builder.build_pdf(client, token, ...)`:
   - `meta_api.get_account_data()` trae campañas → adsets → anuncios → insights.
   - `pdf_generator` arma el HTML (diseño VaoVao) y lo renderiza a PDF con Playwright.
3. El endpoint devuelve el PDF como descarga (`Content-Disposition: attachment`).

- Soporta cliente de **cuenta única** (1 página) y **multi-estación** (1 página por cuenta).
- Métricas se adaptan al objetivo de la campaña (MESSAGES, TRAFFIC, PAGE_LIKES, etc.).
- `GENERATION_AVAILABLE = True` en reports.py (el motor ya está activo).
- Graph API version configurable: `META_API_VERSION` (default `v23.0`).

## Seguridad

- Passwords con bcrypt; sesión con JWT (`SECRET_KEY`).
- Tokens de Meta (Facebook y central) cifrados con Fernet (`ENCRYPTION_KEY`).
  Nunca se devuelven completos por el API (enmascarados).
- Multi-tenant: TODA query filtra por `org_id` / pertenencia del usuario. Verificado
  que una organización no puede ver datos de otra.

## Diseño (tema)

Todo el tema vive en `app/globals.css` con nombres de clase genéricos
(`.card`, `.btn`, `.input`, `.sidebar`, `.table`…), así un cambio de identidad es
un solo archivo. Identidad actual (tomada del panel de reportería original):

- Tema **oscuro**: fondo `#0c0c0c`, superficies `#141414`, texto `#f0f0f0`.
- Fuente **Poppins**.
- Acento y botones primarios: **gradiente de Meta** morado→rojo→naranja
  (`#833AB4 → #FD1D1D → #FCB045`), con el naranja `#FCB045` como color de marca.
- Logo: **VAO**<naranja>**VAO**</naranja>. Misma familia visual que el PDF.
- Contenido centrado: `.main` con `max-width: 940px; margin: 0 auto`.
- El calendario de fechas usa el **azul de Meta** `#1877F2` para el rango.

## Estado — hecho vs pendiente

Hecho: auth + roles, multi-tenant, clientes/cuentas, conexión Meta por usuario
(con portafolios), verificación de acceso, motor de PDF con datos reales, tema visual.

Pendiente:
1. **Envío por correo (Brevo)** — hoy el reporte se descarga; falta mandarlo a los
   destinatarios de cada cuenta. Usar la **API HTTP de Brevo**, NO SMTP
   (Railway bloquea SMTP saliente — ya se sufrió en el Lead Tracker).
2. **Migraciones (Alembic)** — hoy las tablas se crean con `create_all`. Antes de
   producción, pasar a Alembic para no perder datos.
3. **Despliegue** — backend a Railway, frontend a Vercel. Recordar CORS_ORIGINS.
4. **Agregar al equipo** en Roles de la app de Meta.

## Convenciones / gotchas

- Frontend en **JavaScript** (.jsx), no TypeScript.
- No usar `localStorage`/`sessionStorage` fuera de `api.js`/`auth.jsx` (el token va ahí).
- Al agregar una ruta nueva al backend, registrarla en `main.py`.
- SQLite en local no maneja algunos tipos como Postgres; el código usa tipos genéricos
  de SQLAlchemy para funcionar en ambos.
- Mantener el aislamiento por `org_id` en cualquier query nueva.
