"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import ConexionMetaPanel from "@/lib/ConexionMetaPanel";

const TABS = [
  ["general", "General"],
  ["conexion", "Conexión Meta"],
];

function OrgSettingsCard({ canEdit }) {
  const [rate, setRate] = useState("");
  const [saved, setSaved] = useState(null);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getOrgSettings()
      .then((s) => { setSaved(s.exchange_rate_usd_gtq); setRate(s.exchange_rate_usd_gtq ?? ""); })
      .catch((e) => setErr(e.message));
  }, []);

  async function save() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const s = await api.updateOrgSettings({ exchange_rate_usd_gtq: Number(rate) });
      setSaved(s.exchange_rate_usd_gtq);
      setInfo("Guardado.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const dirty = rate !== "" && Number(rate) !== saved;

  return (
    <div className="card" style={{ padding: 24, maxWidth: 440, marginTop: 20 }}>
      <h3 style={{ fontSize: 15, marginBottom: 6 }}>Tipo de cambio USD → GTQ</h3>
      <p style={{ color: "var(--muted)", fontSize: 12, margin: "0 0 16px" }}>
        Se usa para convertir el gasto de las cuentas de Meta que reportan en
        dólares cuando alguien elige ver un reporte en quetzales. Es un valor
        fijo, no una tasa en vivo — actualízalo cuando cambie de forma
        relevante.
      </p>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}
      {saved === null && !err && (
        <div className="notice" style={{ marginBottom: 14 }}>
          <div>Todavía no está configurado. Mientras tanto se usa un valor aproximado de respaldo (Q7.75).</div>
        </div>
      )}
      <div className="field">
        <label>Quetzales por dólar</label>
        <input
          className="input mono" type="number" step="0.01" min="0"
          placeholder="Ej. 7.80" value={rate}
          onChange={(e) => setRate(e.target.value)}
          disabled={!canEdit}
        />
      </div>
      {canEdit ? (
        <button className="btn btn-primary" onClick={save} disabled={busy || !rate || !dirty}>
          {busy ? "Guardando…" : "Guardar"}
        </button>
      ) : (
        <p style={{ color: "var(--muted)", fontSize: 11.5, margin: 0 }}>
          Solo un owner o admin puede cambiar este valor.
        </p>
      )}
    </div>
  );
}

export default function AjustesPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState("general");
  const canEditOrg = user?.role === "owner" || user?.role === "admin";

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
        <>
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

          <OrgSettingsCard canEdit={canEditOrg} />
        </>
      )}

      {tab === "conexion" && <ConexionMetaPanel />}
    </Shell>
  );
}
