"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "./auth";
import { useClient } from "./clients";

const NAV = [
  {
    href: "/resumen", label: "Resumen",
    icon: (
      <>
        <rect x="3.5" y="3.5" width="7" height="7" rx="1.6"></rect>
        <rect x="13.5" y="3.5" width="7" height="7" rx="1.6"></rect>
        <rect x="3.5" y="13.5" width="7" height="7" rx="1.6"></rect>
        <rect x="13.5" y="13.5" width="7" height="7" rx="1.6"></rect>
      </>
    ),
  },
  {
    href: "/analitica", label: "Analítica",
    icon: (
      <>
        <path d="M4 20V10"></path>
        <path d="M11 20V4"></path>
        <path d="M18 20v-7"></path>
      </>
    ),
  },
  {
    href: "/leads", label: "Leads",
    icon: (
      <>
        <path d="M4 5h16"></path>
        <path d="M7 12h10"></path>
        <path d="M10.5 19h3"></path>
      </>
    ),
  },
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
  {
    href: "/ajustes", label: "Ajustes", roles: ["owner", "admin"],
    icon: (
      <>
        <circle cx="12" cy="12" r="3"></circle>
        <path d="M12 3v2.4M12 18.6V21M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M3 12h2.4M18.6 12H21M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7"></path>
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
    <div className="shell" style={{ "--sidebar-w": collapsed ? "76px" : "230px" }}>
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="brand">
          <span className="brand-short">V</span>
          <span className="brand-full">VAO<span style={{ color: "var(--accent)" }}>VAO</span></span>
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
                <button type="button" key={c.id} className={`switcher-item${client?.id === c.id ? " active" : ""}`} onClick={() => { setClient(c); setSwitcherOpen(false); }}>
                  <span className="dot"></span>
                  <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
                  <small>{c.ad_accounts?.length || 0}</small>
                </button>
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

        <button type="button" className="collapse-btn" onClick={toggleCollapse} title={collapsed ? "Expandir" : "Colapsar"}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="4" width="18" height="16" rx="2.5"></rect><path d="M12 4v16"></path></svg>
        </button>

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
                  <button type="button" className="switcher-item" onClick={logout} style={{ color: "var(--error)" }}>Cerrar sesión</button>
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
