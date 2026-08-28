"use client";
import { useState } from "react";
import Shell from "@/lib/Shell";
import { useAuth } from "@/lib/auth";
import ConexionMetaPanel from "@/lib/ConexionMetaPanel";

const TABS = [
  ["general", "General"],
  ["conexion", "Conexión Meta"],
];

export default function AjustesPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState("general");

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Ajustes</h1>
          <p>Preferencias de la cuenta y la organización.</p>
        </div>
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 24, borderBottom: "1px solid var(--border)", paddingBottom: 14 }}>
        {TABS.map(([val, label]) => {
          const activo = tab === val;
          return (
            <button
              key={val}
              type="button"
              onClick={() => setTab(val)}
              style={{
                padding: "8px 16px", borderRadius: "var(--radius-sm)", cursor: "pointer",
                fontFamily: "inherit", fontSize: 12.5, fontWeight: activo ? 500 : 400,
                background: activo ? "var(--surface2)" : "transparent",
                border: `1px solid ${activo ? "var(--orange)" : "var(--border2)"}`,
                color: activo ? "var(--orange)" : "var(--muted)",
                transition: "all .15s",
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {tab === "general" && (
        <div className="card" style={{ padding: 24, maxWidth: 440 }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>Mi cuenta</h3>
          <div className="field">
            <label>Nombre</label>
            <input className="input" value={user?.full_name || ""} disabled readOnly />
          </div>
          <div className="field">
            <label>Correo</label>
            <input className="input" value={user?.email || ""} disabled readOnly />
          </div>
          <div className="field">
            <label>Rol</label>
            <span className="badge badge-role" style={{ display: "inline-flex" }}>{user?.role}</span>
          </div>
        </div>
      )}

      {tab === "conexion" && <ConexionMetaPanel />}
    </Shell>
  );
}
