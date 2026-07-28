# VaoVao Intelligence — Web

Consola de operaciones (frontend) de VaoVao Intelligence. Next.js 14 (App Router).
Consume el API de FastAPI (`vaovao-intelligence`).

## Qué incluye

- **Login** con JWT contra el API.
- **Clientes** — crear clientes y registrar sus cuentas publicitarias de Meta.
- **Usuarios** — invitar usuarios, asignar roles (owner/admin/member), activar/desactivar.
  (Solo visible para owner/admin.)
- **Conexión Meta** — el "espacio" preparado para guardar el System User token cuando
  lo tengas. Muestra el estado con un indicador en vivo; el token se guarda cifrado y
  nunca se muestra completo. (Solo owner/admin.)

## Correr en local

Primero levanta el backend (`vaovao-intelligence`) en `http://localhost:8000`. Luego:

```bash
npm install
cp .env.local.example .env.local
# Edita .env.local si tu backend está en otra URL
npm run dev
```

Abre http://localhost:3000. La primera vez, registra tu organización desde el API
(`POST /auth/register` en http://localhost:8000/docs) y luego entra con ese correo.

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | URL del backend. Local: `http://localhost:8000`. Prod: tu URL de Railway. |

## Deploy (Vercel)

1. Sube este repo a GitHub.
2. Vercel → Import Project.
3. En Environment Variables, pon `NEXT_PUBLIC_API_URL` con la URL pública de tu backend.
4. Deploy.

> Importante: en el backend, agrega el dominio de Vercel a `CORS_ORIGINS`
> (ej. `CORS_ORIGINS=https://intelligence.vaovao.co`) para que el navegador permita las llamadas.

## Diseño

Consola de "sala de control": barra lateral en tinta oscura, área de trabajo clara.
Tipografía Space Grotesk (display) + IBM Plex Sans (texto) + IBM Plex Mono (IDs, tokens,
cuentas). El estado de la conexión Meta usa un indicador con pulso como elemento distintivo.
Responsive y con foco de teclado visible.
