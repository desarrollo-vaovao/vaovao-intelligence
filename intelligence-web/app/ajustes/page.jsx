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
    <p style={{ color: "var(--muted)", fontSize: 12, margin: "12px 0 0" }}>
      {timezones.length === 1 ? (
        <>Las cuentas de Meta de <b>{client.name}</b> reportan en <b>{timezones[0]}</b>.</>
      ) : (
        <>
          Las cuentas de Meta de <b>{client.name}</b> reportan en distintas zonas horarias:{" "}
          {conTimezone.map((a) => `${a.label} (${a.timezone_name})`).join(", ")}.
        </>
      )}
    </p>
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
    <div className="card" style={{ padding: 24, maxWidth: 480, marginTop: 20 }}>
      <h3 style={{ fontSize: 15, marginBottom: 6 }}>Preferencias de reporte</h3>
      <p style={{ color: "var(--muted)", fontSize: 12, margin: "0 0 16px" }}>
        Valores por defecto al abrir Resumen y Reportes.
      </p>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}

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

      <ZonaHorariaInfo />

      <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
        <div className="field">
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

        <div className="field">
          <label>Tipo de cambio USD → GTQ</label>
          <input
            className="input mono" type="number" step="0.01" min="0"
            placeholder="Ej. 7.80" value={exchangeRate}
            onChange={(e) => setExchangeRate(e.target.value)}
            disabled={!canEditOrg}
          />
          {loaded && savedRate === null && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
              Sin configurar: se usa un valor aproximado de respaldo (Q7.75).
            </div>
          )}
        </div>

        <p style={{ color: "var(--muted)", fontSize: 11.5, margin: 0 }}>
          {canEditOrg
            ? "Estas dos afectan los reportes de toda la organización."
            : "Solo un owner o admin puede cambiar la atribución y el tipo de cambio."}
        </p>
      </div>

      <button
        className="btn btn-primary"
        onClick={save}
        disabled={busy || !dirty}
        style={{ marginTop: 18 }}
      >
        {busy ? "Guardando…" : "Guardar preferencias"}
      </button>
    </div>
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
    <div style={{ marginTop: 14 }}>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}
      <div className="field">
        <label>Contraseña actual</label>
        <input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
      </div>
      <div className="field">
        <label>Contraseña nueva (mínimo 8 caracteres)</label>
        <input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
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
    <div className="card" style={{ padding: 24, maxWidth: 440 }}>
      <h3 style={{ fontSize: 15, marginBottom: 16 }}>Perfil</h3>
      {err && <div className="err">{err}</div>}
      {info && <div className="notice" style={{ marginBottom: 14 }}><div>{info}</div></div>}

      <div className="field">
        <label>Nombre</label>
        <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </div>
      <div className="field">
        <label>Correo</label>
        <input className="input" value={user?.email || ""} disabled readOnly />
      </div>
      <div className="field">
        <label>Cargo</label>
        <input
          className="input" value={jobTitle} placeholder="Ej. Traficker, Director"
          onChange={(e) => setJobTitle(e.target.value)}
        />
      </div>
      <div className="field">
        <label>Rol</label>
        <span className="badge badge-role" style={{ display: "inline-flex" }}>{user?.role}</span>
      </div>

      <button className="btn btn-primary" onClick={save} disabled={busy || !dirty || !fullName.trim()}>
        {busy ? "Guardando…" : "Guardar cambios"}
      </button>

      <div style={{ marginTop: 20, paddingTop: 20, borderTop: "1px solid var(--border)" }}>
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
        <>
          <PerfilCard />
          <PreferenciasReporteCard canEditOrg={canEditOrg} />
        </>
      )}

      {tab === "conexion" && <ConexionMetaPanel />}
    </Shell>
  );
}
