"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { useAuth } from "@/lib/auth";
import { useClient } from "@/lib/clients";
import { api } from "@/lib/api";
import ConexionMetaPanel from "@/lib/ConexionMetaPanel";

const TABS = [
  ["cuenta", "Cuenta"],
  ["conexion", "Conexión Meta"],
];

const MONEDAS = [
  ["USD", "$ Dólares"],
  ["GTQ", "Q Quetzales"],
];

const CADENCIAS = [
  ["quincenal", "Quincenal"],
  ["mensual", "Mensual"],
];

// value=null → "sin configurar": Meta usa el default de cada cuenta
// publicitaria, igual que antes de que existiera esta preferencia.
const ATRIBUCIONES = [
  [null, "Predeterminada de la cuenta"],
  ["1d_click", "1 día clic"],
  ["7d_click", "7 días clic"],
  ["7d_click_1d_view", "7 días clic o 1 día vista"],
];

function iniciales(nombre) {
  return (nombre || "")
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

// Zona horaria real de las cuentas de Meta del cliente activo. Informativo,
// no editable: Meta agrupa "por día" según la zona horaria de CADA cuenta
// publicitaria y eso no se puede sobreescribir por parámetro — un selector
// aquí estaría mintiendo (ver ad_accounts.timezone_name en el backend).
function ZonaHorariaInfo() {
  const { client } = useClient() || {};
  const cuentas = client?.ad_accounts || [];
  const conTimezone = cuentas.filter((a) => a.timezone_name);

  if (!client || conTimezone.length === 0) return null;

  const timezones = [...new Set(conTimezone.map((a) => a.timezone_name))];

  return (
    <p style={{ color: "var(--muted)", fontSize: 11.5, margin: "14px 0 0", lineHeight: 1.6 }}>
      {timezones.length === 1 ? (
        <>Las cuentas de Meta de <b style={{ color: "var(--text)" }}>{client.name}</b> reportan en{" "}
          <b style={{ color: "var(--text)" }}>{timezones[0]}</b>.</>
      ) : (
        <>
          Las cuentas de Meta de <b style={{ color: "var(--text)" }}>{client.name}</b> reportan en
          distintas zonas horarias: {conTimezone.map((a) => `${a.label} (${a.timezone_name})`).join(", ")}.
        </>
      )}
    </p>
  );
}

function PasswordForm({ onClose }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      await api.changeMyPassword({ current_password: current, new_password: next });
      setInfo("Contraseña actualizada.");
      setCurrent(""); setNext("");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginTop: 16 }}>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}
      <div className="field">
        <label>Contraseña actual</label>
        <input
          className="input" type="password" value={current}
          onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password"
        />
      </div>
      <div className="field">
        <label>Contraseña nueva (mínimo 8 caracteres)</label>
        <input
          className="input" type="password" value={next}
          onChange={(e) => setNext(e.target.value)} autoComplete="new-password"
        />
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy || !current || next.length < 8}>
          {busy ? "Guardando…" : "Cambiar contraseña"}
        </button>
        <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}

function PerfilCard() {
  const { user, refreshUser } = useAuth();
  const [fullName, setFullName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    setFullName(user?.full_name || "");
    setJobTitle(user?.job_title || "");
  }, [user]);

  const dirty = fullName.trim() !== (user?.full_name || "") || jobTitle !== (user?.job_title || "");

  async function save() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      await api.updateMyProfile({ full_name: fullName.trim(), job_title: jobTitle });
      await refreshUser();
      setInfo("Guardado.");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 26 }}>
      {/* Encabezado de identidad: mismo patrón de avatar+nombre+rol que el
          menú del avatar en el Shell, para que esta tarjeta se sienta "esta
          soy yo" en vez de un formulario burocrático suelto. */}
      <div className="row" style={{ gap: 14, marginBottom: 22 }}>
        <span className="switcher-avatar" style={{ width: 44, height: 44, fontSize: 16, borderRadius: 12 }}>
          {iniciales(fullName || user?.full_name) || "–"}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
            {user?.full_name || "—"}
          </div>
          <span className="badge badge-role" style={{ marginTop: 5, display: "inline-flex" }}>
            {user?.role}
          </span>
        </div>
      </div>

      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}

      <div className="field">
        <label>Nombre</label>
        <input
          className="input" value={fullName} autoComplete="name"
          onChange={(e) => setFullName(e.target.value)}
        />
      </div>
      <div className="field">
        <label>Correo</label>
        <input className="input" value={user?.email || ""} autoComplete="email" disabled readOnly />
      </div>
      <div className="field">
        <label>Cargo</label>
        <input
          className="input" value={jobTitle} placeholder="Ej. Traficker, Director"
          onChange={(e) => setJobTitle(e.target.value)}
          // El valor correcto (y no un "off" cualquiera) importa de verdad
          // aquí: sin decirle al navegador QUÉ es este campo, Chrome lo
          // confundía con el de Correo (viene justo antes) y lo
          // autorellenaba con el email guardado.
          autoComplete="organization-title"
        />
      </div>

      <button className="btn btn-primary" onClick={save} disabled={busy || !dirty || !fullName.trim()}>
        {busy ? "Guardando…" : "Guardar cambios"}
      </button>

      <div style={{ marginTop: 22, paddingTop: 20, borderTop: "1px solid var(--border)" }}>
        {!showPassword ? (
          <button type="button" className="btn btn-ghost" onClick={() => setShowPassword(true)}>
            Cambiar contraseña
          </button>
        ) : (
          <PasswordForm onClose={() => setShowPassword(false)} />
        )}
      </div>
    </div>
  );
}

function PreferenciasReporteCard({ canEditOrg }) {
  const { user, refreshUser } = useAuth();

  const [currency, setCurrency] = useState("USD");
  const [cadence, setCadence] = useState("quincenal");
  const [exchangeRate, setExchangeRate] = useState("");
  const [attribution, setAttribution] = useState("");
  const [savedRate, setSavedRate] = useState(null);
  const [savedAttribution, setSavedAttribution] = useState(null);

  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!user) return;
    setCurrency(user.default_currency || "USD");
    setCadence(user.default_cadence || "quincenal");
  }, [user]);

  useEffect(() => {
    api.getOrgSettings()
      .then((s) => {
        setSavedRate(s.exchange_rate_usd_gtq);
        setExchangeRate(s.exchange_rate_usd_gtq ?? "");
        setSavedAttribution(s.attribution_window);
        setAttribution(s.attribution_window ?? "");
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoaded(true));
  }, []);

  const dirtyPersonal =
    currency !== (user?.default_currency || "USD") || cadence !== (user?.default_cadence || "quincenal");
  const dirtyOrg =
    canEditOrg &&
    (String(exchangeRate) !== String(savedRate ?? "") || (attribution || null) !== (savedAttribution ?? null));
  const dirty = dirtyPersonal || dirtyOrg;

  async function save() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      if (dirtyPersonal) {
        await api.updateMyProfile({ default_currency: currency, default_cadence: cadence });
        await refreshUser();
      }
      if (dirtyOrg) {
        const body = {};
        if (String(exchangeRate) !== String(savedRate ?? "")) {
          body.exchange_rate_usd_gtq = exchangeRate ? Number(exchangeRate) : null;
        }
        if ((attribution || null) !== (savedAttribution ?? null)) {
          body.attribution_window = attribution || null;
        }
        const s = await api.updateOrgSettings(body);
        setSavedRate(s.exchange_rate_usd_gtq);
        setSavedAttribution(s.attribution_window);
      }
      setInfo("Guardado.");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 26 }}>
      <h3 style={{ fontSize: 15, marginBottom: 6 }}>Preferencias de reporte</h3>
      <p style={{ color: "var(--muted)", fontSize: 12, margin: "0 0 20px" }}>
        Valores por defecto al abrir Resumen y Reportes.
      </p>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div className="field">
          <label>Moneda por defecto</label>
          <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {MONEDAS.map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Cadencia por defecto</label>
          <select className="input" value={cadence} onChange={(e) => setCadence(e.target.value)}>
            {CADENCIAS.map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>
        </div>
      </div>

      <ZonaHorariaInfo />

      {/* Límite visual explícito: a partir de aquí, lo que se cambie no es
          personal — lo ve todo el equipo en cada reporte. Antes esto era
          solo una frase al final; ahora es un contorno que se nota antes
          de tocar el primer campo. */}
      <div
        style={{
          marginTop: 20, padding: 18, borderRadius: "var(--radius-sm)",
          background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
        }}
      >
        <p style={{ fontSize: 11, fontWeight: 600, color: "var(--orange)", margin: "0 0 14px", letterSpacing: ".2px" }}>
          {canEditOrg ? "Afecta los reportes de toda la organización" : "Solo un owner o admin puede cambiar esto"}
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Atribución</label>
            <select
              className="input"
              value={attribution}
              onChange={(e) => setAttribution(e.target.value)}
              disabled={!canEditOrg}
            >
              {ATRIBUCIONES.map(([val, label]) => (
                <option key={val ?? "default"} value={val ?? ""}>{label}</option>
              ))}
            </select>
          </div>

          <div className="field" style={{ marginBottom: 0 }}>
            <label>Tipo de cambio USD → GTQ</label>
            <input
              className="input mono" type="number" step="0.01" min="0"
              placeholder="Ej. 7.80" value={exchangeRate}
              onChange={(e) => setExchangeRate(e.target.value)}
              disabled={!canEditOrg}
            />
          </div>
        </div>

        {loaded && savedRate === null && (
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 10 }}>
            Tipo de cambio sin configurar: se usa un valor aproximado de respaldo (Q7.75).
          </div>
        )}
      </div>

      <button
        className="btn btn-primary"
        onClick={save}
        disabled={busy || !dirty}
        style={{ marginTop: 20 }}
      >
        {busy ? "Guardando…" : "Guardar preferencias"}
      </button>
    </div>
  );
}

export default function AjustesPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState("cuenta");
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

      {tab === "cuenta" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 20, alignItems: "start" }}>
          <PerfilCard />
          <PreferenciasReporteCard canEditOrg={canEditOrg} />
        </div>
      )}

      {tab === "conexion" && <ConexionMetaPanel />}
    </Shell>
  );
}
