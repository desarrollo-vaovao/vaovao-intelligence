"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import DateRangePicker, { periodoMensual, periodoQuincenal } from "@/lib/DateRangePicker";

export default function ReportesPage() {
  const [clients, setClients] = useState([]);
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  const [clientId, setClientId] = useState("");
  const [reportType, setReportType] = useState("quincenal");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [cl, st] = await Promise.all([api.listClients(), api.reportStatus()]);
        setClients(cl); setStatus(st);
      } catch (e) { setErr(e.message); }
    })();
    // Período inicial: la quincena actual
    const q = periodoQuincenal(0);
    setDateFrom(q.from); setDateTo(q.to);
  }, []);

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
  const incompleto = !clientId || !dateFrom || !dateTo;

  async function generate() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const filename = await api.generateReport({
        client_id: Number(clientId),
        report_type: reportType,
        date_from: dateFrom,
        date_to: dateTo,
        budget: budget ? Number(budget) : null,
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

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Reportes</h1>
          <p>Genera el reporte de campañas de Meta de un cliente.</p>
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
          <div className="field">
            <label>Cliente</label>
            <select className="input" value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">— Selecciona un cliente —</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.type === "multi_station" ? " (multi-estación)" : ""}
                </option>
              ))}
            </select>
          </div>

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
            {busy ? "Generando…" : ready ? "Generar y descargar PDF" : "Generar (bloqueado)"}
          </button>
        </div>
      </div>
    </Shell>
  );
}