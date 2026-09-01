"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Shell from "@/lib/Shell";
import { useAuth } from "@/lib/auth";
import { useClient } from "@/lib/clients";
import { api } from "@/lib/api";
import DateRangePicker, { periodoQuincenal } from "@/lib/DateRangePicker";
import { useExchangeRate, exchangeFactor } from "@/lib/useExchangeRate";
import { objectiveLabel, statusLabel } from "@/lib/objectives";

const BUDGET_KEY = "vv_resumen_budget";
const CURRENCY_KEY = "vv_resumen_currency";
const SUMMARY_CACHE_PREFIX = "vv_resumen_cache_";

// Último resumen que sí llegó a cargar, por activo comercial — sobrevive a
// un F5 o a volver a entrar a la pestaña. Sin esto, cada carga de página
// arrancaba desde cero (summary=null) y mostraba el loader a pantalla
// completa aunque un segundo antes ya se hubiera visto el mismo resumen;
// con la caché, esa pantalla de "Cargando…" solo aparece la primera vez
// que se consulta un activo comercial en este navegador.
function loadCachedSummary(accountId) {
  try {
    const raw = localStorage.getItem(SUMMARY_CACHE_PREFIX + accountId);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveCachedSummary(accountId, data) {
  try {
    localStorage.setItem(SUMMARY_CACHE_PREFIX + accountId, JSON.stringify(data));
  } catch {
    // localStorage lleno o inaccesible (modo privado, etc.) — no es
    // crítico, el resumen simplemente no sobrevive un refresh en ese caso.
  }
}

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
  const { user } = useAuth() || {};
  const exchangeRate = useExchangeRate();

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

  // La moneda con la que abre esta pantalla la primera vez: si la persona
  // ya la cambió antes (queda en localStorage, arriba), esa gana siempre.
  // Solo aplica la de su perfil (Ajustes) cuando todavía no hay nada
  // guardado — y solo la primera vez que el usuario carga, para no pisar
  // un cambio que haga en esta misma sesión.
  const aplicoMonedaDefault = useRef(false);
  useEffect(() => {
    if (aplicoMonedaDefault.current || !user) return;
    aplicoMonedaDefault.current = true;
    if (!localStorage.getItem(CURRENCY_KEY) && user.default_currency) {
      setCurrency(user.default_currency);
    }
  }, [user]);

  // El backend reporta por activo comercial (ad_account_id), no por
  // cliente — ver el mismo ajuste ya hecho en reportes/page.jsx. Un
  // cliente `single` tiene una sola cuenta; se usa esa. Un `multi_station`
  // puede tener varias: por ahora se resume solo con la primera, ya que
  // esta pantalla no tiene selector de activo (a diferencia de Reportes).
  const accountId = client?.ad_accounts?.[0]?.id ?? null;

  // `summary` solo se reemplaza por el de la CACHÉ (nunca por null) cuando
  // cambia el activo comercial — así, si ya se consultó antes en este
  // navegador, se ve de inmediato en vez de la pantalla de "Cargando…".
  // Un cambio de fecha/moneda/presupuesto sobre el MISMO activo deja el
  // resumen anterior en pantalla mientras llega el nuevo — antes se
  // borraba todo de inmediato y la pantalla completa se reemplazaba por
  // "Cargando…" en cada ajuste, como si la página entera se hubiera
  // recargado.
  const prevAccountId = useRef(null);
  useEffect(() => {
    if (!client || !dateFrom || !dateTo || !accountId) { setSummary(null); return; }
    let cancelled = false;
    if (prevAccountId.current !== accountId) {
      prevAccountId.current = accountId;
      setSummary(loadCachedSummary(accountId));
    }
    setBusy(true); setErr("");
    api.reportSummary({
      ad_account_id: accountId,
      date_from: dateFrom,
      date_to: dateTo,
      budget: budget ? Number(budget) : null,
      currency,
    }).then((data) => {
      if (cancelled) return;
      setSummary(data);
      saveCachedSummary(accountId, data);
    })
      .catch((e) => { if (!cancelled) setErr(e.message); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [client, accountId, dateFrom, dateTo, budget, currency]);

  function onBudgetChange(v) {
    setBudget(v);
    localStorage.setItem(BUDGET_KEY, v);
  }

  function onCurrencyChange(next) {
    // El presupuesto lo escribe la persona directamente en la moneda que
    // tiene seleccionada — sin esto, cambiar de USD a GTQ dejaba el mismo
    // número con otro símbolo, como si $50 se hubieran vuelto Q50 solos.
    if (budget) {
      const factor = exchangeFactor(currency, next, exchangeRate);
      const converted = (Number(budget) * factor).toFixed(2);
      setBudget(converted);
      localStorage.setItem(BUDGET_KEY, converted);
    }
    setCurrency(next);
    localStorage.setItem(CURRENCY_KEY, next);
  }

  const symbol = summary?.currency_symbol || (currency === "GTQ" ? "Q" : "$");
  const totalSpend = summary
    ? (summary.type === "multi-station"
        ? summary.stations.reduce((n, s) => n + s.total_spend, 0)
        : summary.total_spend)
    : 0;
  const budgetNum = budget ? Number(budget) : null;
  const pctUsed = budgetNum ? Math.min(100, Math.round((totalSpend / budgetNum) * 100)) : null;
  // Todas las campañas activas/pausadas del período, no solo un "top 5":
  // /reports/summary las trae con include_inactive=True (ver backend), así
  // que una campaña sigue apareciendo aquí aunque no haya gastado nada
  // en el rango de fechas elegido — la idea es tener un panel estable en
  // vez de que las campañas aparezcan y desaparezcan según la fecha.
  const campaigns = flattenCampaigns(summary);

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

  if (!accountId) {
    return (
      <Shell>
        <div className="page-head"><div><h1>Resumen</h1></div></div>
        <div className="empty">
          <h3>{client.name} no tiene una cuenta de Meta conectada</h3>
          <p>Agrega un activo comercial en Clientes para ver su resumen de gasto.</p>
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
        <div style={{ position: "relative", maxWidth: 160 }}>
          <span style={{
            position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)",
            color: "var(--muted)", fontSize: 12, pointerEvents: "none",
          }}>
            {currency === "GTQ" ? "Q" : "$"}
          </span>
          <input
            className="input mono" type="number" placeholder="Presupuesto"
            value={budget} onChange={(e) => onBudgetChange(e.target.value)}
            style={{ paddingLeft: 22 }}
          />
        </div>
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

      {/* Loader a pantalla completa SOLO en la carga inicial (sin datos
          previos que mostrar). En cualquier refresco posterior (cambio de
          fecha, moneda, presupuesto) el resumen anterior se queda visible
          y este aviso chico aparece arriba, para no sentir que la página
          entera se recargó por ajustar un filtro. */}
      {busy && !summary && (
        <div className="empty">
          <h3>Cargando datos de Meta<span className="loading-dots"><span /><span /><span /></span></h3>
        </div>
      )}

      {!err && summary && (
        <>
          {busy && (
            <div className="row" style={{ gap: 8, color: "var(--muted)", fontSize: 11.5, marginBottom: 16 }}>
              <span className="loading-dots"><span /><span /><span /></span>
              Actualizando…
            </div>
          )}

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
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Campañas</div>
              <div style={{ fontSize: 22, fontWeight: 600 }} className="mono">{campaigns.length}</div>
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

          <h3 style={{ fontSize: 13, marginBottom: 10 }}>Campañas</h3>
          {campaigns.length === 0 ? (
            <div className="empty"><h3>Sin campañas activas o pausadas</h3></div>
          ) : (
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Campaña</th>
                    {summary.type === "multi-station" && <th>Cuenta</th>}
                    <th>Objetivo</th>
                    <th>Estado</th>
                    <th>Gasto</th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}</td>
                      {summary.type === "multi-station" && <td>{c.station}</td>}
                      <td>{objectiveLabel(c.objective)}</td>
                      <td>
                        <span className={`badge ${c.status === "ACTIVE" ? "badge-signal" : "badge-neutral"}`}>
                          {statusLabel(c.status)}
                        </span>
                      </td>
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
