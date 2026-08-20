# Rediseño de front-end — Fase 1 (base visual + navegación) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar la identidad visual de VaoVao Intelligence (tokens, tipografía, shell de navegación) por la propuesta nueva, dejar 4 rutas placeholder ocultas listas para fases futuras, y levantar ambientes de prueba (dev) en Vercel y Railway.

**Architecture:** Se mantiene CSS plano con variables (`app/globals.css`) — no se introduce Tailwind. Los cambios de paleta se hacen **reasignando los valores de las variables CSS existentes** (no renombrándolas), así todas las páginas que ya usan `var(--orange)`, `var(--muted2)`, `var(--gradient)`, etc. heredan el look nuevo sin tocar su código. Se agrega un `ClientProvider` (mismo patrón que `AuthProvider`) para el selector de cliente activo, reutilizable por fases futuras.

**Tech Stack:** Next.js 14 (App Router), React 18, CSS plano, `next/font/google`, Vercel CLI, Railway CLI.

## Global Constraints

- No introducir Tailwind ni CSS-in-JS — extender el sistema de variables CSS existente.
- Las variables CSS existentes (`--orange`, `--gradient`, `--muted2`, `--border2`, `--signal`, `--warn`, `--danger`, `--line`) mantienen su **nombre** — solo cambia su valor. Ningún archivo `.jsx` que ya las use debe editarse por este motivo.
- Las 4 rutas nuevas (`/resumen`, `/analitica`, `/leads`, `/ajustes`) existen como páginas pero **no se enlazan desde ningún lugar de la UI** (ni sidebar, ni menú de usuario) hasta que se aprueben en su propia fase.
- No se reutiliza `ENCRYPTION_KEY` ni `SECRET_KEY` de producción en el ambiente dev de Railway — se regeneran.
- La base Postgres del ambiente dev de Railway se crea vacía.
- No repetir en el chat, en commits, ni en ningún archivo del repo los valores de las variables de entorno de producción.

---

### Task 1: Preparar la rama `dev`

**Files:**
- Modify: `intelligence-web/.gitignore`

**Interfaces:**
- Produces: rama local y remota `dev` en el mismo estado que `main`, lista para recibir los commits de esta fase.

- [ ] **Step 1: Verificar working tree limpio en main**

Run: `git status`
Expected: `nothing to commit, working tree clean` (si hay cambios sin commitear, detenerse y preguntar antes de continuar).

- [ ] **Step 2: Traer refs remotas actualizadas**

Run: `git fetch origin`

- [ ] **Step 3: Resetear dev local al estado de main**

```bash
git checkout dev
git reset --hard main
```

- [ ] **Step 4: Agregar `.vercel` al gitignore del frontend**

En `intelligence-web/.gitignore`, agregar una línea `.vercel` (al final del archivo).

- [ ] **Step 5: Commit del gitignore**

```bash
git add intelligence-web/.gitignore
git commit -m "chore: ignora la carpeta .vercel del proyecto de frontend"
```

- [ ] **Step 6: Force-push de dev a origin**

Run: `git push --force-with-lease origin dev`
Expected: la rama remota `dev` queda igual a `main` + el commit del gitignore. `--force-with-lease` (no `--force` a secas) evita pisar un push ajeno que no se haya visto todavía.

- [ ] **Step 7: Confirmar**

Run: `git log --oneline -3` y `git status`
Expected: HEAD en `dev`, working tree limpio, mensaje del commit del Step 5 arriba de todo.

---

### Task 2: Fundamento visual — tokens y tipografía

**Files:**
- Modify: `intelligence-web/app/globals.css:8-35` (bloque `:root`)
- Modify: `intelligence-web/app/layout.jsx`

**Interfaces:**
- Consumes: nada (es la base).
- Produces: variables CSS `--bg`, `--surface`, `--surface2`, `--border`, `--border2`, `--border3`, `--text`, `--muted`, `--muted2`, `--accent` (alias de `--orange`), `--accent-bg`, `--accent-border`, `--gradient` (ahora color plano), `--radius`, `--radius-sm`, `--radius-pill`; variables de fuente `--font-unbounded`, `--font-inter` disponibles vía `next/font`.

- [ ] **Step 1: Reemplazar el bloque `:root` en `globals.css`**

Reemplazar las líneas 8-35 (desde `:root {` hasta el `}` que cierra ese bloque) por:

```css
:root {
  --bg:        #0F0F0E;
  --surface:   #161614;
  --surface2:  #1C1C19;
  --surface3:  #131311;
  --border:    #262622;
  --border2:   #2E2E29;
  --border3:   #35352F;
  --text:      #F5F5F2;
  --muted:     #8A8A82;
  --muted2:    #57574F;

  --orange:    #FF4422;
  --red:       #FD1D1D;
  --purple:    #833AB4;
  --gradient:  #FF4422;

  --success:   #4ade80;
  --error:     #f87171;
  --warn:      #FF4422;

  /* Alias usados por los componentes */
  --line:      var(--border);
  --accent:    var(--orange);
  --accent-bg:     #1E100C;
  --accent-border: #3A1A10;
  --signal:    var(--success);
  --danger:    var(--error);

  --radius:      14px;
  --radius-sm:   9px;
  --radius-pill: 999px;
}
```

- [ ] **Step 2: Cargar Unbounded + Inter en `layout.jsx`**

Reemplazar el contenido completo de `intelligence-web/app/layout.jsx` por:

```jsx
import "./globals.css";
import { Unbounded, Inter } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import { ClientProvider } from "@/lib/clients";

const unbounded = Unbounded({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-unbounded",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata = {
  title: "VaoVao Intelligence",
  description: "Consola de operaciones — VaoVao",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body className={`${unbounded.variable} ${inter.variable}`}>
        <AuthProvider>
          <ClientProvider>{children}</ClientProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
```

Nota: `ClientProvider` todavía no existe — se crea en el Task 3. Este archivo queda con un import roto hasta ese task; es intencional (van en la misma rama, antes del primer build real).

- [ ] **Step 3: Actualizar `font-family` del body en `globals.css`**

En la regla `body { ... }` de `globals.css`, cambiar:

```css
  font-family: 'Poppins', system-ui, sans-serif;
```

por:

```css
  font-family: var(--font-inter), system-ui, sans-serif;
```

- [ ] **Step 4: Usar Unbounded en headings**

En la regla `h1, h2, h3 { ... }` de `globals.css`, agregar la línea `font-family: var(--font-unbounded), sans-serif;` dentro del bloque.

- [ ] **Step 5: Commit**

(Se commitea junto con el Task 3, porque `layout.jsx` queda con un import roto hasta que exista `lib/clients.jsx`. No ejecutar este commit todavía — continuar directo al Task 3.)

---

### Task 3: `ClientProvider` — selector de cliente activo

**Files:**
- Create: `intelligence-web/lib/clients.jsx`

**Interfaces:**
- Consumes: `useAuth()` de `lib/auth.jsx` (para saber si hay usuario logueado), `api.listClients()` de `lib/api.js` (devuelve `[{ id, name, type, ad_accounts: [...] }]`).
- Produces: `ClientProvider` (componente) y hook `useClient()` que devuelve `{ client, clients, setClient, loading }`. `client`: objeto del cliente activo o `null`. `clients`: array completo o `null` mientras carga. `setClient(clientObj)`: cambia el cliente activo y lo persiste. `loading`: booleano.

- [ ] **Step 1: Crear `lib/clients.jsx`**

```jsx
"use client";
import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

const ClientCtx = createContext(null);
const STORAGE_KEY = "vv_active_client";

export function ClientProvider({ children }) {
  const { user } = useAuth();
  const [clients, setClients] = useState(null);
  const [client, setClientState] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      setClients(null);
      setClientState(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api.listClients()
      .then((list) => {
        if (cancelled) return;
        setClients(list);
        const savedId = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
        const restored = list.find((c) => String(c.id) === savedId);
        setClientState(restored || list[0] || null);
      })
      .catch(() => {
        if (!cancelled) { setClients([]); setClientState(null); }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user]);

  const setClient = useCallback((next) => {
    setClientState(next);
    if (typeof window !== "undefined") {
      if (next) localStorage.setItem(STORAGE_KEY, String(next.id));
      else localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return (
    <ClientCtx.Provider value={{ client, clients, setClient, loading }}>
      {children}
    </ClientCtx.Provider>
  );
}

export const useClient = () => useContext(ClientCtx);
```

- [ ] **Step 2: Verificar que el proyecto compila**

Run: `cd intelligence-web && npm run build`
Expected: build exitoso, sin errores de import (el `ClientProvider` del Task 2 ya resuelve).

- [ ] **Step 3: Commit (incluye Task 2 y Task 3 juntos)**

```bash
git add intelligence-web/app/globals.css intelligence-web/app/layout.jsx intelligence-web/lib/clients.jsx
git commit -m "feat: nueva paleta/tipografía VaoVao y ClientProvider para selector de cliente activo"
```

---

### Task 4: Rediseño de `Shell.jsx` (sidebar + header)

**Files:**
- Modify: `intelligence-web/lib/Shell.jsx` (reescritura completa)
- Modify: `intelligence-web/app/globals.css` (agrega clases nuevas al final del archivo, no toca las existentes)

**Interfaces:**
- Consumes: `useAuth()` (`user.full_name`, `user.email`, `user.role`, `logout()`), `useClient()` (`client`, `clients`, `setClient`, `loading`) del Task 3.
- Produces: mismo export por default `Shell` que ya usan `app/clientes/page.jsx`, `app/reportes/page.jsx`, `app/usuarios/page.jsx`, `app/conexion/page.jsx` — misma firma `<Shell>{children}</Shell>`, sin cambios de props.

- [ ] **Step 1: Agregar clases nuevas al final de `globals.css`**

```css
/* ── Sidebar: selector de cliente ── */
.sidebar-switcher { position: relative; padding: 12px 8px 4px; }
.switcher-btn {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 8px 9px; border-radius: 10px; cursor: pointer;
  background: transparent; border: 1px solid transparent; text-align: left;
}
.switcher-btn:hover { background: var(--surface2); }
.switcher-avatar {
  width: 26px; height: 26px; border-radius: 50%; background: var(--accent);
  color: var(--bg); display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; flex: none;
}
.switcher-name { flex: 1; min-width: 0; font-size: 12.5px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.switcher-caret { flex: none; transition: transform .15s; color: var(--muted2); }
.switcher-caret.open { transform: rotate(180deg); }
.switcher-menu {
  position: absolute; left: 8px; right: 8px; top: 100%; z-index: 40; margin-top: 4px;
  background: var(--surface2); border: 1px solid var(--border2); border-radius: 12px;
  padding: 6px; box-shadow: 0 18px 40px rgba(0,0,0,.5);
}
.switcher-item { display: flex; align-items: center; gap: 9px; padding: 8px 9px; border-radius: 8px; cursor: pointer; font-size: 12px; color: var(--text); }
.switcher-item:hover { background: var(--surface); }
.switcher-item .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted2); flex: none; }
.switcher-item.active .dot { background: var(--accent); }
.switcher-item small { margin-left: auto; color: var(--muted2); font-size: 9.5px; }
.switcher-new { display: flex; align-items: center; gap: 8px; padding: 9px; border-radius: 8px; font-size: 12px; color: var(--accent); cursor: pointer; margin-top: 4px; }
.switcher-new:hover { background: var(--surface); }

/* ── Sidebar: estado de sincronización ── */
.sync-card { margin: 10px 8px; padding: 10px 11px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface2); font-size: 11px; color: var(--muted); }
.sync-card .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); display: inline-block; margin-right: 7px; animation: vv-pulse 2.4s ease-in-out infinite; }
@keyframes vv-pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .sync-card .dot { animation: none; } }

/* ── Sidebar: colapsar ── */
.collapse-btn { display: flex; align-items: center; justify-content: center; padding: 9px; margin: 6px 8px 0; border-radius: 9px; cursor: pointer; color: var(--muted); }
.collapse-btn:hover { background: var(--surface2); color: var(--text); }
.sidebar.collapsed .switcher-name,
.sidebar.collapsed .nav-item span,
.sidebar.collapsed .sync-card,
.sidebar.collapsed .brand small,
.sidebar.collapsed .switcher-caret { display: none; }
.sidebar.collapsed .switcher-btn,
.sidebar.collapsed .brand { justify-content: center; }

/* ── Header superior ── */
.header-bar {
  position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 14px;
  padding: 14px 30px; background: rgba(10,10,9,.86); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}
.header-crumb { font-family: var(--font-unbounded), sans-serif; font-size: 9px; letter-spacing: .18em; text-transform: uppercase; color: var(--muted2); }
.header-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.currency-toggle { display: flex; height: 32px; border: 1px solid var(--border2); border-radius: 9px; overflow: hidden; }
.currency-toggle button { border: none; background: transparent; color: var(--muted); font-family: 'Inter', sans-serif; font-size: 11.5px; padding: 0 12px; cursor: pointer; }
.currency-toggle button.active { background: var(--surface2); color: var(--text); }
.bell-btn { width: 32px; height: 32px; border: 1px solid var(--border2); border-radius: 9px; background: var(--surface); display: flex; align-items: center; justify-content: center; cursor: pointer; color: var(--muted); }
.bell-btn:hover { border-color: var(--border3); }
```

- [ ] **Step 2: Reescribir `lib/Shell.jsx`**

```jsx
"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "./auth";
import { useClient } from "./clients";

const NAV = [
  {
    href: "/clientes", label: "Clientes",
    icon: (
      <>
        <circle cx="9" cy="9" r="3.4"></circle>
        <path d="M3.5 19c.6-3.2 2.9-4.8 5.5-4.8s4.9 1.6 5.5 4.8"></path>
        <circle cx="17.5" cy="10" r="2.4"></circle>
        <path d="M16 14.6c2.4-.3 4.2 1.1 4.5 4.4"></path>
      </>
    ),
  },
  {
    href: "/reportes", label: "Reportes",
    icon: (
      <>
        <rect x="5" y="3" width="14" height="18" rx="2.5"></rect>
        <path d="M9 8h6"></path>
        <path d="M9 12h6"></path>
        <path d="M9 16h3"></path>
      </>
    ),
  },
  {
    href: "/usuarios", label: "Usuarios", roles: ["owner", "admin"],
    icon: (
      <>
        <circle cx="12" cy="8" r="3.6"></circle>
        <path d="M5 20c.8-3.9 3.6-5.8 7-5.8s6.2 1.9 7 5.8"></path>
      </>
    ),
  },
  {
    href: "/conexion", label: "Conexión Meta", roles: ["owner", "admin"],
    icon: (
      <>
        <circle cx="7" cy="12" r="3.2"></circle>
        <circle cx="17" cy="7" r="2.6"></circle>
        <circle cx="17" cy="17" r="2.6"></circle>
        <path d="M9.8 10.6 14.5 8.2"></path>
        <path d="M9.8 13.4l4.7 2.4"></path>
      </>
    ),
  },
];

// Incluye las secciones que todavía no están en NAV, para que el
// breadcrumb funcione también si se entra por URL directa (rutas ocultas).
const LABELS = {
  "/resumen": "Resumen",
  "/analitica": "Analítica",
  "/leads": "Leads",
  "/reportes": "Reportes",
  "/clientes": "Clientes",
  "/usuarios": "Usuarios",
  "/conexion": "Conexión Meta",
  "/ajustes": "Ajustes",
};

const CURRENCY_KEY = "vv_currency";
const COLLAPSE_KEY = "vv_sidebar_collapsed";

export default function Shell({ children }) {
  const { user, loading, logout } = useAuth();
  const clientCtx = useClient() || {};
  const { client, clients, setClient, loading: clientsLoading } = clientCtx;
  const pathname = usePathname();
  const router = useRouter();

  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [currency, setCurrency] = useState("USD");
  const switcherRef = useRef(null);
  const userMenuRef = useRef(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    setCurrency(localStorage.getItem(CURRENCY_KEY) || "USD");
  }, []);

  useEffect(() => {
    function onClickOutside(e) {
      if (switcherRef.current && !switcherRef.current.contains(e.target)) setSwitcherOpen(false);
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function toggleCollapse() {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      return !c;
    });
  }

  function pickCurrency(next) {
    setCurrency(next);
    localStorage.setItem(CURRENCY_KEY, next);
  }

  if (loading || !user) {
    return <div style={{ display: "grid", placeItems: "center", height: "100vh", color: "var(--muted)" }}>Cargando…</div>;
  }

  const items = NAV.filter((n) => !n.roles || n.roles.includes(user.role));
  const totalAccounts = (clients || []).reduce((n, c) => n + (c.ad_accounts?.length || 0), 0);
  const initials = (user.full_name || "").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();

  return (
    <div className="shell" style={{ gridTemplateColumns: collapsed ? "76px 1fr" : "230px 1fr", transition: "grid-template-columns .15s" }}>
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="brand">
          VAO<span style={{ color: "var(--accent)" }}>VAO</span>
          <small>Intelligence</small>
        </div>

        <div className="sidebar-switcher" ref={switcherRef}>
          <button type="button" className="switcher-btn" onClick={() => setSwitcherOpen((o) => !o)} title={client?.name || "Sin clientes"}>
            <span className="switcher-avatar">{client?.name?.[0]?.toUpperCase() || "–"}</span>
            <span className="switcher-name">{clientsLoading ? "Cargando…" : client?.name || "Sin clientes"}</span>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`switcher-caret${switcherOpen ? " open" : ""}`}><path d="m6 9 6 6 6-6"></path></svg>
          </button>
          {switcherOpen && (
            <div className="switcher-menu">
              {(clients || []).map((c) => (
                <div key={c.id} className={`switcher-item${client?.id === c.id ? " active" : ""}`} onClick={() => { setClient(c); setSwitcherOpen(false); }}>
                  <span className="dot"></span>
                  <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
                  <small>{c.ad_accounts?.length || 0}</small>
                </div>
              ))}
              <Link href="/clientes" className="switcher-new" onClick={() => setSwitcherOpen(false)}>+ Nuevo cliente</Link>
            </div>
          )}
        </div>

        <nav style={{ display: "flex", flexDirection: "column", gap: 4, padding: "6px 8px 12px" }}>
          {items.map((n) => (
            <Link key={n.href} href={n.href} className={`nav-item ${pathname === n.href ? "active" : ""}`} title={n.label}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" style={{ flex: "none" }}>{n.icon}</svg>
              <span>{n.label}</span>
            </Link>
          ))}
        </nav>

        <div className="sync-card">
          <span className="dot"></span>Meta API conectada
          <div style={{ marginTop: 4, color: "var(--muted2)" }}>{totalAccounts} cuenta{totalAccounts === 1 ? "" : "s"} en total</div>
        </div>

        <div className="collapse-btn" onClick={toggleCollapse} title={collapsed ? "Expandir" : "Colapsar"}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="4" width="18" height="16" rx="2.5"></rect><path d="M10 4v16"></path></svg>
        </div>

        <div className="sidebar-foot">
          <div className="sidebar-user">
            <b>{user.full_name}</b>
            <span className="mono" style={{ fontSize: 12 }}>{user.role}</span>
          </div>
          <div className="signout" onClick={logout}>Cerrar sesión</div>
        </div>
      </aside>

      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header className="header-bar">
          <span className="header-crumb">{LABELS[pathname] || ""}</span>
          <div className="header-actions">
            <div className="currency-toggle">
              <button type="button" className={currency === "USD" ? "active" : ""} onClick={() => pickCurrency("USD")}>$ USD</button>
              <button type="button" className={currency === "GTQ" ? "active" : ""} onClick={() => pickCurrency("GTQ")}>Q GTQ</button>
            </div>
            <button type="button" className="bell-btn" title="Notificaciones">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M18 9a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7"></path><path d="M10.5 20a2 2 0 0 0 3 0"></path></svg>
            </button>
            <div style={{ position: "relative" }} ref={userMenuRef}>
              <button type="button" className="switcher-avatar" style={{ cursor: "pointer", border: "none" }} onClick={() => setUserMenuOpen((o) => !o)} title={user.full_name}>
                {initials}
              </button>
              {userMenuOpen && (
                <div className="switcher-menu" style={{ left: "auto", right: 0, width: 220 }}>
                  <div style={{ padding: "8px 9px 12px" }}>
                    <div style={{ fontSize: 12.5, fontWeight: 500 }}>{user.full_name}</div>
                    <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 3 }}>{user.email}</div>
                    <span className="badge badge-role" style={{ marginTop: 8, display: "inline-flex" }}>{user.role}</span>
                  </div>
                  <div style={{ height: 1, background: "var(--border)", margin: "0 4px 6px" }}></div>
                  <div className="switcher-item" onClick={logout} style={{ color: "var(--error)" }}>Cerrar sesión</div>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build**

Run: `cd intelligence-web && npm run build`
Expected: build exitoso.

- [ ] **Step 4: Lint**

Run: `npm run lint`
Expected: sin errores (warnings preexistentes, si los hay, no bloquean).

- [ ] **Step 5: Commit**

```bash
git add intelligence-web/lib/Shell.jsx intelligence-web/app/globals.css
git commit -m "feat: rediseña el Shell con selector de cliente, header y colapso de sidebar"
```

---

### Task 5: Rutas placeholder ocultas

**Files:**
- Create: `intelligence-web/lib/ComingSoon.jsx`
- Create: `intelligence-web/app/resumen/page.jsx`
- Create: `intelligence-web/app/analitica/page.jsx`
- Create: `intelligence-web/app/leads/page.jsx`
- Create: `intelligence-web/app/ajustes/page.jsx`

**Interfaces:**
- Consumes: `Shell` (Task 4).
- Produces: `ComingSoon({ title, description })` — componente compartido, sin estado, usado por las 4 páginas.

- [ ] **Step 1: Crear `lib/ComingSoon.jsx`**

```jsx
import Shell from "./Shell";

export default function ComingSoon({ title, description }) {
  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>
      <div className="card empty">
        <h3>Próximamente</h3>
        <p>Esta sección todavía no está disponible.</p>
      </div>
    </Shell>
  );
}
```

- [ ] **Step 2: Crear las 4 páginas**

`intelligence-web/app/resumen/page.jsx`:
```jsx
import ComingSoon from "@/lib/ComingSoon";

export default function ResumenPage() {
  return <ComingSoon title="Resumen" description="Panel de rendimiento consolidado por cliente." />;
}
```

`intelligence-web/app/analitica/page.jsx`:
```jsx
import ComingSoon from "@/lib/ComingSoon";

export default function AnaliticaPage() {
  return <ComingSoon title="Analítica" description="Métricas por cuenta, ubicación y creativo." />;
}
```

`intelligence-web/app/leads/page.jsx`:
```jsx
import ComingSoon from "@/lib/ComingSoon";

export default function LeadsPage() {
  return <ComingSoon title="Leads" description="Seguimiento de leads generados por campaña." />;
}
```

`intelligence-web/app/ajustes/page.jsx`:
```jsx
import ComingSoon from "@/lib/ComingSoon";

export default function AjustesPage() {
  return <ComingSoon title="Ajustes" description="Preferencias de la cuenta y la organización." />;
}
```

- [ ] **Step 3: Build**

Run: `cd intelligence-web && npm run build`
Expected: build exitoso, aparecen `/resumen`, `/analitica`, `/leads`, `/ajustes` en el resumen de rutas generadas.

- [ ] **Step 4: Confirmar que quedan ocultas del sidebar**

Run: `grep -rn "resumen\|analitica\|/leads\|ajustes" intelligence-web/lib/Shell.jsx`
Expected: sin resultados (el array `NAV` de `Shell.jsx` no las menciona).

- [ ] **Step 5: Commit**

```bash
git add intelligence-web/lib/ComingSoon.jsx intelligence-web/app/resumen intelligence-web/app/analitica intelligence-web/app/leads intelligence-web/app/ajustes
git commit -m "feat: agrega rutas placeholder ocultas (Resumen, Analítica, Leads, Ajustes)"
```

---

### Task 6: Verificación visual y push de `dev`

**Files:** ninguno (solo verificación).

**Interfaces:**
- Consumes: todo lo de Tasks 2-5.
- Produces: confirmación de que las páginas existentes heredan el look nuevo sin romperse, y `dev` actualizado en `origin`.

- [ ] **Step 1: Levantar el dev server**

Run: `cd intelligence-web && npm run dev` (en background o en otra terminal)
Expected: sirve en `http://localhost:3000`.

- [ ] **Step 2: Revisión visual en navegador**

Con el navegador (Claude Browser o el navegador del usuario), visitar en `http://localhost:3000`: `/login`, `/clientes`, `/reportes`, `/usuarios`, `/conexion`, y las 4 ocultas `/resumen`, `/analitica`, `/leads`, `/ajustes`.
Expected en cada una: paleta oscura nueva (`#0F0F0E`/`#FF4422`), tipografía Unbounded en headings, Inter en cuerpo, sidebar con selector de cliente funcionando (si hay clientes cargados), sin colores del gradiente viejo visibles, sin errores en la consola del navegador.

- [ ] **Step 3: Probar el colapso de sidebar y el selector de cliente**

Click en el botón de colapsar (ícono abajo del sidebar) → el sidebar se angosta y las etiquetas desaparecen; click de nuevo → vuelve. Click en el selector de cliente arriba del sidebar → despliega la lista de clientes reales; seleccionar uno distinto → el avatar/nombre cambian y persisten al recargar la página (`localStorage`).

- [ ] **Step 4: Responsive**

Con `resize_window` (o devtools) a 375px de ancho, confirmar que el sidebar pasa a fila horizontal (breakpoint `max-width: 720px` ya existente) sin overlaps.

- [ ] **Step 5: Push de dev**

```bash
git push origin dev
```

---

### Task 7: Ambiente `dev` en Railway

**Files:** ninguno (solo infraestructura vía CLI).

**Interfaces:**
- Consumes: proyecto Railway `vaovao-intelligence` ya linkeado en `intelligence-backend/`.
- Produces: ambiente `dev` con servicio backend + Postgres propio, URL pública de dev.

- [ ] **Step 1: Confirmar el link actual**

Run: `cd intelligence-backend && railway status`
Expected: proyecto `vaovao-intelligence`, ambiente `production`.

- [ ] **Step 2: Revisar el comando exacto para crear ambiente**

Run: `railway environment --help`
Expected: confirma si el subcomando es `railway environment new <nombre>` o equivalente en la versión instalada (5.41.2). Usar el que reporte el help.

- [ ] **Step 3: Crear el ambiente `dev`**

Ejecutar el comando confirmado en el Step 2 para crear un ambiente llamado `dev` dentro del proyecto `vaovao-intelligence`.
Expected: nuevo ambiente listado en `railway status` / dashboard.

- [ ] **Step 4: Agregar Postgres al ambiente dev**

Cambiar al ambiente `dev` (`railway environment dev` o el comando que corresponda) y agregar una base Postgres nueva desde el dashboard de Railway (Add → Database → PostgreSQL) o `railway add` si el CLI lo soporta en esta versión — queda vacía, sin copiar datos de producción.

- [ ] **Step 5: Configurar variables del servicio backend en dev**

En el ambiente `dev`, setear (sin reutilizar los valores de producción para `ENCRYPTION_KEY` y `SECRET_KEY` — generar nuevos, por ejemplo con `python -c "import secrets; print(secrets.token_urlsafe(32))"` para cada uno):
- `ENVIRONMENT=development`
- `ENCRYPTION_KEY` (nuevo, regenerado)
- `SECRET_KEY` (nuevo, regenerado)
- `FB_APP_ID`, `FB_APP_SECRET` (mismos que producción — es la misma app de Meta)
- `FB_REDIRECT_URI` (apuntando al dominio público que asigne Railway al servicio en el ambiente dev)
- `FRONTEND_URL` (se completa en el Task 8, después de tener la URL de preview de Vercel)
- `CORS_ORIGINS` (incluye la URL de preview de Vercel del Task 8 + `http://localhost:3000`)

`DATABASE_URL` la inyecta Railway automáticamente al agregar el Postgres del Step 4 — no se setea a mano.

- [ ] **Step 6: Deploy del backend a dev**

Run: `railway up` (desde `intelligence-backend/`, con el ambiente `dev` activo)
Expected: deploy exitoso, `railway status` muestra el servicio Online en el ambiente `dev` con su propia URL pública.

- [ ] **Step 7: Verificar**

Run: `curl https://<url-del-servicio-dev>/docs` (o la ruta de health que exponga FastAPI)
Expected: responde 200.

---

### Task 8: Preview de Vercel para `dev`

**Files:** ninguno (solo infraestructura vía CLI).

**Interfaces:**
- Consumes: proyecto Vercel `vaovao-intelligence` ya linkeado, URL del backend dev de Railway (Task 7).

- [ ] **Step 1: Setear `NEXT_PUBLIC_API_URL` de Preview**

Run: `cd intelligence-web && vercel env rm NEXT_PUBLIC_API_URL preview` (si ya existe un valor viejo) seguido de `vercel env add NEXT_PUBLIC_API_URL preview` y pegar la URL pública del backend dev de Railway (del Task 7, Step 6) cuando lo pida.

- [ ] **Step 2: Deploy preview**

Run: `git checkout dev && vercel deploy` (sin `--prod`)
Expected: CLI devuelve una URL de preview (`https://vaovao-intelligence-<hash>-desarrollo-5437s-projects.vercel.app` o similar).

- [ ] **Step 3: Completar `FRONTEND_URL` y `CORS_ORIGINS` en Railway dev**

Volver al Task 7 Step 5 y completar `FRONTEND_URL` con la URL de preview obtenida en el Step 2, agregarla también a `CORS_ORIGINS`, y redeployar el backend (`railway up`) para que tome las variables nuevas.

- [ ] **Step 4: Verificar end-to-end**

Abrir la URL de preview de Vercel en el navegador, hacer login (si ya hay un usuario en la base dev — si no, crear uno directo contra el backend dev antes de este paso) y confirmar que el sidebar carga clientes reales del backend dev (vacío al inicio, es esperado) sin errores de CORS en la consola.

---

### Task 9: Cierre de fase

**Files:** ninguno.

- [ ] **Step 1: Confirmar estado final**

Run: `git log main..dev --oneline`
Expected: lista los commits de los Tasks 1-5 (gitignore, tokens/fuentes, Shell, placeholders).

- [ ] **Step 2: Resumen para el usuario**

Reportar: URL de preview de Vercel (dev), URL del backend dev de Railway, y que las 4 rutas nuevas están accesibles solo por URL directa hasta su aprobación.
