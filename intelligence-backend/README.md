# VaoVao Intelligence

Base de la plataforma multi-tenant de VaoVao, en **Python / FastAPI / PostgreSQL**.
Mismo stack que el Lead Tracker, pensada para crecer y unir todo en un solo lugar.

Esta es la **fundación**: organizaciones, usuarios con login real (JWT), y clientes
con sus cuentas publicitarias viviendo en la base de datos (lo que reemplaza el
`clients.js` hardcodeado de la reportería). El Tracker y la Reportería se enchufan
después sobre este cimiento.

## Qué incluye hoy

- **Auth real con JWT** — registro, login, contraseñas con bcrypt.
- **Multi-tenant de verdad** — todo cuelga de una organización; cada usuario solo ve
  los datos de la suya (probado: una org no puede leer clientes de otra).
- **Dominio base** — Clientes (single / multi-station) y sus Cuentas Publicitarias de Meta.
- **Gestión de usuarios y roles** — owner/admin/member, con guardas (no quedarte sin owner,
  no desactivarte a ti mismo, solo owner crea owner).
- **Conexión Meta preparada** — el token de System User se guarda **cifrado** (Fernet),
  nunca se expone por el API. Listo para conectar cuando lo tengas.
- **CORS** configurable para el frontend.
- **Docs automáticas** — Swagger en `/docs`.

## Estructura

```
app/
├── main.py              ← arranque, rutas, health
├── core/
│   ├── config.py        ← variables de entorno
│   ├── database.py      ← conexión PostgreSQL
│   └── security.py      ← bcrypt + JWT
├── models/__init__.py   ← tablas: Organization, User, Client, AdAccount
├── schemas/__init__.py  ← validación de entrada/salida (Pydantic)
└── api/
    ├── deps.py          ← get_current_user (el guardia multi-tenant)
    └── routes/
        ├── auth.py      ← /auth/register, /auth/login, /auth/me
        └── clients.py   ← /clients y /clients/{id}/ad-accounts
```

## Correr en local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edita .env: pon tu DATABASE_URL y genera una SECRET_KEY (openssl rand -hex 32)

uvicorn app.main:app --reload
```

Abre http://localhost:8000/docs para probar todo desde el navegador.

> Para local rápido sin Postgres puedes usar `DATABASE_URL=sqlite:///./dev.db`.
> Para producción siempre PostgreSQL.

## Deploy en Railway

1. Sube el repo a GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. Agrega un PostgreSQL al proyecto (New → Database → PostgreSQL).
4. En Variables del servicio:
   - `DATABASE_URL = ${{Postgres.DATABASE_URL}}`
   - `SECRET_KEY = ...` (genera una fuerte)
   - `ENVIRONMENT = production`
5. Railway usa el `Procfile` y levanta con uvicorn. No configures `PORT` (lo inyecta solo).

## Endpoints

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | /health | — | Estado del servicio |
| POST | /auth/register | — | Crea organización + usuario dueño |
| POST | /auth/login | — | Devuelve un JWT |
| GET | /auth/me | JWT | Usuario actual |
| GET | /clients | JWT | Lista clientes de tu organización |
| POST | /clients | JWT | Crea un cliente |
| GET | /clients/{id} | JWT | Detalle de un cliente |
| POST | /clients/{id}/ad-accounts | JWT | Registra un activo comercial (hereda el nombre de Meta) |
| POST | /clients/{id}/ad-accounts/{account_id}/refresh-name | JWT | Vuelve a traer el nombre desde Meta |
| GET | /users | owner/admin | Lista usuarios de la organización |
| POST | /users | owner/admin | Crea un usuario |
| PATCH | /users/{id} | owner/admin | Activa/desactiva o cambia rol |
| GET | /organization/meta-credentials | owner/admin | Estado de la conexión Meta (enmascarado) |
| PUT | /organization/meta-credentials | owner/admin | Guarda el token (cifrado) |
| DELETE | /organization/meta-credentials | owner/admin | Borra la conexión Meta |

## Siguientes pasos (roadmap)

1. **Migraciones con Alembic** — hoy las tablas se crean al arrancar (`create_all`);
   cuando el esquema se estabilice, pasar a migraciones para no perder datos.
2. **Roles y permisos** — distinguir qué puede hacer owner/admin/member.
3. **Módulo Reportería** — portar la lógica de Meta Ads (de la versión Node) a un
   servicio Python que lea las cuentas desde esta base, y generar PDF con Playwright.
4. **Módulo Tracker** — conectar el Lead Tracker para que los leads vivan aquí también.
5. **Frontend** — dashboard (Next.js) que consuma este API.
```
