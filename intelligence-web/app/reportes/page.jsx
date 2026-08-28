"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import Shell from "@/lib/Shell";
import { api, request } from "@/lib/api";
import { useClient } from "@/lib/clients";
import DateRangePicker, { periodoMensual, periodoQuincenal } from "@/lib/DateRangePicker";

export default function ReportesPage() {
  const { client } = useClient() || {};

  // Los activos comerciales del CLIENTE ACTIVO únicamente (el que se elige
  // en el sidebar) — nunca de toda la organización. La mayoría de clientes
  // son `single` (un solo ad account); `multi_station` puede tener varios
  // (una franquicia con una cuenta por país/estación), de ahí que siga
  // haciendo falta un selector, pero acotado a este cliente.
  const accounts = [...(client?.ad_accounts || [])].sort((a, b) =>
    a.label.localeCompare(b.label, "es")
  );
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  const [accountId, setAccountId] = useState("");
  const [reportType, setReportType] = useState("quincenal");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [countryCode, setCountryCode] = useState("");
  const [countries, setCountries] = useState([]);
  const [loadingCountries, setLoadingCountries] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.reportStatus().then(setStatus).catch((e) => setErr(e.message));
    // Período inicial: la quincena actual
    const q = periodoQuincenal(0);
    setDateFrom(q.from); setDateTo(q.to);
  }, []);

  // Al cambiar el activo comercial, cargar los países disponibles
  async function cambiarActivo(id) {
    setAccountId(id);
    setCountryCode("");
    setCountries([]);
    if (!id) return;

    setLoadingCountries(true);
    try {
      const response = await request(`/reports/countries/${id}`);
      setCountries(response.countries || []);
    } catch (e) {
      console.error("Error loading countries:", e);
      setCountries([]);
    } finally {
      setLoadingCountries(false);
    }
  }

  // Al cambiar el CLIENTE activo (sidebar): sus cuentas son las únicas
  // válidas para reportar, así que cualquier selección de un cliente
  // anterior queda descartada. Si el cliente activo tiene una sola cuenta
  // (el caso común, ClientType.single), se autoselecciona y el selector
  // no le pide nada al usuario; con varias (multi_station) sigue haciendo
  // falta elegir, pero solo entre las de este cliente.
  useEffect(() => {
    if (accounts.length === 1) {
      cambiarActivo(String(accounts[0].id));
    } else {
      cambiarActivo("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client?.id]);

  // Al cambiar el tipo de reporte, se llenan las fechas solas
  function cambiarTipo(tipo) {
    setReportType(tipo);
    if (tipo === "quincenal") {
      const q = periodoQuincenal(0);
      setDateFrom(q.from); setDateTo(q.to);
    } else if (tipo === "mensual") {
      const m = periodoMensual(0);
      setDateFrom(m.from); setDateTo(m.to);
    }
  }

  const ready = status?.generation_available;
  const metaConnected = status?.meta_connected;
  const incompleto = !accountId || !dateFrom || !dateTo;

  async function generate() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const filename = await api.generateReport({
        ad_account_id: Number(accountId),
        report_type: reportType,
        date_from: dateFrom,
        date_to: dateTo,
        budget: budget ? Number(budget) : null,
        currency,
        country_code: countryCode || null,
      });
      setInfo(`Reporte descargado: ${filename}`);
    } catch (e) {
      setErr(e.message);
    } finally { setBusy(false); }
  }

  const TIPOS = [
    ["quincenal", "Quincenal"],
    ["mensual", "Mensual"],
    ["personalizado", "Personalizado"],
  ];

  const MONEDAS = [
    ["USD", "$ Dólares"],
    ["GTQ", "Q Quetzales"],
  ];

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Reportes</h1>
          <p>Genera el reporte de campañas de Meta de un activo comercial.</p>
        </div>
      </div>

      <div style={{ maxWidth: 560, margin: "0 auto" }}>

        {status && !metaConnected && (
          <div className="notice" style={{ marginBottom: 18 }}>
            <span className="pulse off" />
            <div>
              <b>Meta no está conectado.</b>{" "}
              <Link href="/conexion" style={{ color: "var(--orange)", textDecoration: "underline" }}>
                Conectar ahora →
              </Link>
            </div>
          </div>
        )}

        {err && <div className="err">{err}</div>}
        {info && <div className="notice" style={{ marginBottom: 18 }}><div>{info}</div></div>}

        <div className="card" style={{ padding: 24 }}>
          {accounts.length === 0 && (
            <div className="field">
              <label>Activo comercial</label>
              <input
                className="input"
                value={client ? "Este cliente no tiene una cuenta de Meta conectada" : "Selecciona un cliente en el menú lateral"}
                disabled
                readOnly
              />
            </div>
          )}

          {accounts.length === 1 && (
            <div className="field">
              <label>Activo comercial</label>
              <input className="input" value={accounts[0].label} disabled readOnly />
            </div>
          )}

          {accounts.length > 1 && (
            <div className="field">
              <label>Activo comercial</label>
              <select className="input" value={accountId} onChange={(e) => cambiarActivo(e.target.value)}>
                <option value="">— Selecciona un activo comercial de {client.name} —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {accountId && countries.length > 0 && (
            <div className="field">
              <label>País (opcional)</label>
              <select
                className="input"
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value)}
                disabled={loadingCountries}
              >
                <option value="">— Todos los países —</option>
                {countries.map((country) => (
                  <option key={country} value={country}>
                    {country}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="field">
            <label>Tipo de reporte</label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
              {TIPOS.map(([val, label]) => {
                const activo = reportType === val;
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => cambiarTipo(val)}
                    style={{
                      padding: "9px 0", borderRadius: "var(--radius-sm)", cursor: "pointer",
                      fontFamily: "inherit", fontSize: 11.5, fontWeight: activo ? 500 : 400,
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
          </div>

          <div className="field">
            <label>Período</label>
            <DateRangePicker
              from={dateFrom}
              to={dateTo}
              onChange={(f, t) => { setDateFrom(f); setDateTo(t); setReportType("personalizado"); }}
            />
          </div>

          <div className="field">
            <label>Moneda</label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6 }}>
              {MONEDAS.map(([val, label]) => {
                const activo = currency === val;
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setCurrency(val)}
                    style={{
                      padding: "9px 0", borderRadius: "var(--radius-sm)", cursor: "pointer",
                      fontFamily: "inherit", fontSize: 11.5, fontWeight: activo ? 500 : 400,
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
          </div>

          <div className="field">
            <label>Presupuesto aprobado del período (opcional)</label>
            <input className="input mono" type="number" value={budget}
              onChange={(e) => setBudget(e.target.value)} placeholder="Ej. 9500" />
          </div>

          <button
            className="btn btn-primary"
            onClick={generate}
            disabled={busy || !ready || incompleto}
            style={{ width: "100%", justifyContent: "center", marginTop: 8 }}
          >
            {busy ? (
              <>
                Generando
                <span className="loading-dots"><span /><span /><span /></span>
              </>
            ) : ready ? "Generar y descargar PDF" : "Generar (bloqueado)"}
          </button>
        </div>
      </div>
    </Shell>
  );
}