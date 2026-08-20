"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import Shell from "@/lib/Shell";
import { useClient } from "@/lib/clients";
import { api } from "@/lib/api";
import DateRangePicker, { periodoQuincenal } from "@/lib/DateRangePicker";

const BUDGET_KEY = "vv_resumen_budget";
const CURRENCY_KEY = "vv_resumen_currency";

function money(n, symbol) {
  const v = Number(n) || 0;
  return `${symbol}${v.toLocaleString("es-GT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Junta las campañas de un resumen (single o multi-estación) en una sola
// lista ordenada por gasto, para el ranking — mismos datos que ve Reportes.
function flattenCampaigns(summary) {
  if (!summary) return [];
  const rows = summary.type === "multi-station"
    ? summary.stations.flatMap((s) => s.campaigns.map((c) => ({ ...c, station: s.station_label })))
    : (summary.campaigns || []).map((c) => ({ ...c, station: null }));
  return rows.sort((a, b) => b.spend - a.spend);
}

export default function ResumenPage() {
  const { client, loading: clientLoading } = useClient() || {};

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("USD");

  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const q = periodoQuincenal(0);
    setDateFrom(q.from); setDateTo(q.to);
    setBudget(localStorage.getItem(BUDGET_KEY) || "");
    setCurrency(localStorage.getItem(CURRENCY_KEY) || "USD");
  }, []);

  useEffect(() => {
    if (!client || !dateFrom || !dateTo) { setSummary(null); return; }
    let cancelled = false;
    setBusy(true); setErr(""); setSummary(null);
    api.reportSummary({
      client_id: client.id,
      date_from: dateFrom,
      date_to: dateTo,
      budget: budget ? Number(budget) : null,
      currency,
    }).then((data) => { if (!cancelled) setSummary(data); })
      .catch((e) => { if (!cancelled) setErr(e.message); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [client, dateFrom, dateTo, budget, currency]);

  function onBudgetChange(v) {
    setBudget(v);
    localStorage.setItem(BUDGET_KEY, v);
  }

  function onCurrencyChange(v) {
    setCurrency(v);
    localStorage.setItem(CURRENCY_KEY, v);
  }

  const symbol = summary?.currency_symbol || (currency === "GTQ" ? "Q" : "$");
  const totalSpend = summary
    ? (summary.type === "multi-station"
        ? summary.stations.reduce((n, s) => n + s.total_spend, 0)
        : summary.total_spend)
    : 0;
  const budgetNum = budget ? Number(budget) : null;
  const pctUsed = budgetNum ? Math.min(100, Math.round((totalSpend / budgetNum) * 100)) : null;
  const topCampaigns = flattenCampaigns(summary).slice(0, 5);

  if (clientLoading) {
    return <Shell><div className="empty"><h3>Cargando…</h3></div></Shell>;
  }

  if (!client) {
    return (
      <Shell>
        <div className="page-head"><div><h1>Resumen</h1></div></div>
        <div className="empty">
          <h3>Sin cliente seleccionado</h3>
          <p>Creá un cliente para ver su resumen de gasto.</p>
          <Link href="/clientes" className="btn btn-primary" style={{ marginTop: 14 }}>Ir a Clientes</Link>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Resumen</h1>
          <p>Gasto y presupuesto de {client.name} en el período.</p>
        </div>
      </div>

      <div className="row" style={{ gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
        <DateRangePicker from={dateFrom} to={dateTo} onChange={(f, t) => { setDateFrom(f); setDateTo(t); }} />
        <input
          className="input mono" type="number" placeholder="Presupuesto"
          value={budget} onChange={(e) => onBudgetChange(e.target.value)}
          style={{ maxWidth: 160 }}
        />
        <div style={{ display: "flex", gap: 4 }}>
          {["USD", "GTQ"].map((c) => (
            <button
              key={c} type="button" onClick={() => onCurrencyChange(c)}
              className="btn" style={{
                background: currency === c ? "var(--surface2)" : "transparent",
                border: `1px solid ${currency === c ? "var(--orange)" : "var(--border2)"}`,
                color: currency === c ? "var(--orange)" : "var(--muted)",
                padding: "9px 14px",
              }}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {err && <div className="err">{err}</div>}

      {busy && (
        <div className="empty">
          <h3>Cargando datos de Meta<span className="loading-dots"><span /><span /><span /></span></h3>
        </div>
      )}

      {!busy && !err && summary && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14, marginBottom: 24 }}>
            <div className="card" style={{ padding: 18 }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Gasto total</div>
              <div style={{ fontSize: 22, fontWeight: 600 }} className="mono">{money(totalSpend, symbol)}</div>
            </div>
            <div className="card" style={{ padding: 18 }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Presupuesto</div>
              <div style={{ fontSize: 22, fontWeight: 600 }} className="mono">
                {budgetNum ? money(budgetNum, symbol) : "—"}
              </div>
            </div>
            <div className="card" style={{ padding: 18 }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>% usado</div>
              <div style={{ fontSize: 22, fontWeight: 600 }} className="mono">
                {pctUsed !== null ? `${pctUsed}%` : "—"}
              </div>
            </div>
            <div className="card" style={{ padding: 18 }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Campañas activas</div>
              <div style={{ fontSize: 22, fontWeight: 600 }} className="mono">{flattenCampaigns(summary).length}</div>
            </div>
          </div>

          {summary.type === "multi-station" && (
            <div className="card" style={{ padding: 0, marginBottom: 24, overflow: "hidden" }}>
              <table className="table">
                <thead>
                  <tr><th>Cuenta</th><th>Gasto</th><th>Presupuesto</th></tr>
                </thead>
                <tbody>
                  {summary.stations.map((s) => (
                    <tr key={s.station_label}>
                      <td>{s.station_label}</td>
                      <td className="mono">{money(s.total_spend, symbol)}</td>
                      <td className="mono">{s.budget ? money(s.budget, symbol) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 style={{ fontSize: 13, marginBottom: 10 }}>Top campañas por gasto</h3>
          {topCampaigns.length === 0 ? (
            <div className="empty"><h3>Sin actividad en el período</h3></div>
          ) : (
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Campaña</th>
                    {summary.type === "multi-station" && <th>Cuenta</th>}
                    <th>Objetivo</th>
                    <th>Gasto</th>
                  </tr>
                </thead>
                <tbody>
                  {topCampaigns.map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}</td>
                      {summary.type === "multi-station" && <td>{c.station}</td>}
                      <td>{c.objective}</td>
                      <td className="mono">{money(c.spend, symbol)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Shell>
  );
}
