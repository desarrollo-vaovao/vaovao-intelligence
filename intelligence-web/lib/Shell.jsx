"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import Link from "next/link";
import { useAuth } from "./auth";

const NAV = [
  { href: "/clientes", label: "Clientes" },
  { href: "/reportes", label: "Reportes" },
  { href: "/usuarios", label: "Usuarios", roles: ["owner", "admin"] },
  { href: "/conexion", label: "Conexión Meta", roles: ["owner", "admin"] },
];

export default function Shell({ children }) {
  const { user, loading, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return <div style={{ display: "grid", placeItems: "center", height: "100vh", color: "var(--muted)" }}>Cargando…</div>;
  }

  const items = NAV.filter((n) => !n.roles || n.roles.includes(user.role));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          VAO<span style={{ color: "var(--orange)" }}>VAO</span>
          <small>Intelligence</small>
        </div>
        {items.map((n) => (
          <Link key={n.href} href={n.href} className={`nav-item ${pathname === n.href ? "active" : ""}`}>
            {n.label}
          </Link>
        ))}
        <div className="sidebar-foot">
          <div className="sidebar-user">
            <b>{user.full_name}</b>
            <span className="mono" style={{ fontSize: 12 }}>{user.role}</span>
          </div>
          <div className="signout" onClick={logout}>Cerrar sesión</div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}