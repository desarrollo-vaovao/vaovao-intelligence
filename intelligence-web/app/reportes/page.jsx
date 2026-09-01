"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Shell from "@/lib/Shell";
import { api, request } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useClient } from "@/lib/clients";
import DateRangePicker, { periodoMensual, periodoQuincenal } from "@/lib/DateRangePicker";
import { useExchangeRate, exchangeFactor } from "@/lib/useExchangeRate";
import { objectiveLabel } from "@/lib/objectives";

// Mismas claves que pdf_generator.METRIC_REGISTRY (backend) — si se agrega
// una métrica nueva ahí, se agrega aquí también.
const METRIC_CATALOG = [
  { key: "impressions", label: "Impresiones" },
  { key: "reach", label: "Alcance" },
  { key: "frequency", label: "Frecuencia" },
  { key: "clicks", label: "Clics" },
  { key: "ctr", label: "CTR" },
  { key: "cpc", label: "CPC" },
  { key: "cpm", label: "CPM" },
  { key: "conversations", label: "Conversaciones" },
  { key: "cost_per_conversation", label: "Costo / conv." },
  { key: "engagement", label: "Interacciones" },
  { key: "cost_per_engagement", label: "Costo / int." },
  { key: "followers", label: "Seguidores" },
  { key: "cost_per_follower", label: "Costo / seg." },
];

export default function ReportesPage() {
  const { client } = useClient() || {};
  const { user } = useAuth() || {};
  const exchangeRate = useExchangeRate();

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

  const [showCustomize, setShowCustomize] = useState(false);
  const [campaignsPreview, setCampaignsPreview] = useState([]);
  const [campaignsError, setCampaignsError] = useState("");
  const [loadingCampaigns, setLoadingCampaigns] = useState(false);
  const [campaignMetrics, setCampaignMetrics] = useState({});
  const [campaignComments, setCampaignComments] = useState({});
  const [generalComment, setGeneralComment] = useState("");
  const [campaignSearch, setCampaignSearch] = useState("");
  const [expandedCampaignId, setExpandedCampaignId] = useState(null);

  useEffect(() => {
    api.reportStatus().then(setStatus).catch((e) => setErr(e.message));
    // Período inicial: la quincena actual
    const q = periodoQuincenal(0);
    setDateFrom(q.from); setDateTo(q.to);
  }, []);

  // Moneda y cadencia con las que abre este formulario, según el perfil de
  // quien lo usa (Ajustes > Preferencias de reporte). Solo una vez, cuando
  // el usuario termina de cargar — así no pisa un cambio manual posterior
  // en esta misma sesión.
  const aplicoDefaultsPerfil = useRef(false);
  useEffect(() => {
    if (aplicoDefaultsPerfil.current || !user) return;
    aplicoDefaultsPerfil.current = true;
    if (user.default_currency) setCurrency(user.default_currency);
    if (user.default_cadence && user.default_cadence !== "quincenal") {
      cambiarTipo(user.default_cadence);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

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

  async function loadCampaignsPreview() {
    if (!accountId || !dateFrom || !dateTo) return;
    setLoadingCampaigns(true);
    setCampaignsError("");
    try {
      const response = await api.reportCampaigns(accountId, dateFrom, dateTo, countryCode || null);
      setCampaignsPreview(response.campaigns || []);
      const initialMetrics = {};
      for (const c of response.campaigns || []) {
        initialMetrics[c.id] = c.default_metrics;
      }
      setCampaignMetrics(initialMetrics);
    } catch (e) {
      setErr(e.message);
      setCampaignsError(e.message);
      setCampaignsPreview([]);
    } finally {
      setLoadingCampaigns(false);
    }
  }

  function openCustomize() {
    setShowCustomize(true);
    if (campaignsPreview.length === 0) {
      loadCampaignsPreview();
    }
  }

  function closeCustomize() {
    setShowCustomize(false);
  }

  function toggleMetric(campaignId, key) {
    setCampaignMetrics((prev) => {
      const current = prev[campaignId] || [];
      const next = current.includes(key)
        ? current.filter((k) => k !== key)
        : [...current, key];
      return { ...prev, [campaignId]: next };
    });
  }

  function setCampaignComment(campaignId, text) {
    setCampaignComments((prev) => ({ ...prev, [campaignId]: text }));
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

  // Si cambia el activo comercial, el período o el filtro de país después de
  // haber cargado el panel de personalización, la selección queda obsoleta
  // (campañas de otro período/país) — se limpia y hay que volver a
  // desplegarlo.
  useEffect(() => {
    setCampaignsPreview([]);
    setCampaignsError("");
    setCampaignMetrics({});
    setCampaignComments({});
    setShowCustomize(false);
    setCampaignSearch("");
    setExpandedCampaignId(null);
  }, [accountId, dateFrom, dateTo, countryCode]);

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

  // El presupuesto lo escribe la persona directamente en la moneda que
  // tiene seleccionada — sin esto, cambiar de USD a GTQ dejaba el mismo
  // número con otro símbolo, como si $50 se hubieran vuelto Q50 solos.
  function changeCurrency(next) {
    if (budget) {
      const factor = exchangeFactor(currency, next, exchangeRate);
      setBudget((Number(budget) * factor).toFixed(2));
    }
    setCurrency(next);
  }

  const ready = status?.generation_available;
  const metaConnected = status?.meta_connected;
  const incompleto = !accountId || !dateFrom || !dateTo;

  async function generate() {
    setErr(""); setInfo(""); setBusy(true);
    try {
      const personalizado = campaignsPreview.length > 0;
      const filename = await api.generateReport({
        ad_account_id: Number(accountId),
        report_type: reportType,
        date_from: dateFrom,
        date_to: dateTo,
        budget: budget ? Number(budget) : null,
        currency,
        country_code: countryCode || null,
        ...(personalizado ? {
          campaign_metrics: campaignMetrics,
          campaign_comments: Object.fromEntries(
            Object.entries(campaignComments).filter(([, v]) => v && v.trim())
          ),
          general_comment: generalComment.trim() || null,
        } : {}),
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

          {accountId && (
            <div className="field">
              <label>País (opcional)</label>
              <select
                className="input"
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value)}
                disabled={loadingCountries}
              >
                <option value="">
                  {loadingCountries ? "Cargando países…" : "— Todos los países —"}
                </option>
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
                    onClick={() => changeCurrency(val)}
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
            <div style={{ position: "relative" }}>
              <span style={{
                position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)",
                color: "var(--muted)", fontSize: 12, pointerEvents: "none",
              }}>
                {currency === "GTQ" ? "Q" : "$"}
              </span>
              <input className="input mono" type="number" value={budget}
                onChange={(e) => setBudget(e.target.value)} placeholder="Ej. 9500"
                style={{ paddingLeft: 22 }} />
            </div>
          </div>

          {accountId && dateFrom && dateTo && (
            <div className="field">
              <button
                type="button"
                onClick={openCustomize}
                className="btn btn-ghost"
                style={{ width: "100%", justifyContent: "center" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <line x1="4" y1="21" x2="4" y2="14"></line>
                  <line x1="4" y1="10" x2="4" y2="3"></line>
                  <line x1="12" y1="21" x2="12" y2="12"></line>
                  <line x1="12" y1="8" x2="12" y2="3"></line>
                  <line x1="20" y1="21" x2="20" y2="16"></line>
                  <line x1="20" y1="12" x2="20" y2="3"></line>
                  <line x1="1" y1="14" x2="7" y2="14"></line>
                  <line x1="9" y1="8" x2="15" y2="8"></line>
                  <line x1="17" y1="16" x2="23" y2="16"></line>
                </svg>
                Personalizar métricas y observaciones (opcional)
              </button>
            </div>
          )}

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

        {showCustomize && (
          <CustomizeReportModal
            campaigns={campaignsPreview}
            loading={loadingCampaigns}
            error={campaignsError}
            search={campaignSearch}
            onSearchChange={setCampaignSearch}
            expandedId={expandedCampaignId}
            onToggleExpand={setExpandedCampaignId}
            campaignMetrics={campaignMetrics}
            onToggleMetric={toggleMetric}
            campaignComments={campaignComments}
            onCampaignComment={setCampaignComment}
            generalComment={generalComment}
            onGeneralComment={setGeneralComment}
            onClose={closeCustomize}
          />
        )}
      </div>
    </Shell>
  );
}

function CustomizeReportModal({
  campaigns, loading, error, search, onSearchChange,
  expandedId, onToggleExpand,
  campaignMetrics, onToggleMetric,
  campaignComments, onCampaignComment,
  generalComment, onGeneralComment,
  onClose,
}) {
  // Cerrar con Escape — el clic en el fondo se maneja en el overlay más abajo.
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const term = search.trim().toLowerCase();
  const filtered = term
    ? campaigns.filter((c) => (c.name || "").toLowerCase().includes(term))
    : campaigns;

  return (
    <div
      className="overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        style={{
          width: "100%", maxWidth: 640, maxHeight: "85vh",
          display: "flex", flexDirection: "column", padding: 0, overflow: "hidden",
        }}
      >
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "16px 20px", borderBottom: "1px solid var(--border2)", flexShrink: 0,
        }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>
            Personalizar métricas y observaciones
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--muted)", fontSize: 16, padding: 4, lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ padding: "12px 20px", flexShrink: 0 }}>
          <input
            className="input"
            placeholder="Buscar campaña por nombre…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ overflowY: "auto", overscrollBehavior: "contain", flex: 1, padding: "0 20px" }}>
          {loading && (
            <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
              Cargando campañas…
            </div>
          )}

          {!loading && error && <div className="err">{error}</div>}

          {!loading && !error && campaigns.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
              No se encontraron campañas con datos en este período.
            </div>
          )}

          {!loading && campaigns.length > 0 && filtered.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
              Sin resultados para &quot;{search}&quot;.
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingBottom: 8 }}>
            {filtered.map((c) => {
              const expanded = expandedId === c.id;
              return (
                <div key={c.id} className="card" style={{ padding: 0, overflow: "hidden" }}>
                  <button
                    type="button"
                    onClick={() => onToggleExpand(expanded ? null : c.id)}
                    style={{
                      width: "100%", display: "flex", justifyContent: "space-between",
                      alignItems: "center", padding: "14px 16px", background: "var(--gradient)",
                      border: "none", cursor: "pointer", fontFamily: "inherit", textAlign: "left",
                    }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <span style={{
                        fontSize: 12, fontWeight: 500, color: "#fff", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {c.name}
                      </span>
                      <span
                        className="badge"
                        style={{ flexShrink: 0, background: "rgba(255,255,255,.22)", color: "#fff" }}
                      >
                        {objectiveLabel(c.objective)}
                      </span>
                    </span>
                    <span style={{ color: "rgba(255,255,255,.85)", flexShrink: 0, marginLeft: 10 }}>
                      {expanded ? "▾" : "▸"}
                    </span>
                  </button>

                  {expanded && (
                    <div style={{ padding: "14px 16px 16px" }}>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
                        {METRIC_CATALOG.map((m) => {
                          const active = (campaignMetrics[c.id] || []).includes(m.key);
                          return (
                            <button
                              key={m.key}
                              type="button"
                              onClick={() => onToggleMetric(c.id, m.key)}
                              style={{
                                padding: "6px 12px", borderRadius: 99, fontSize: 11,
                                fontFamily: "inherit", border: "none", cursor: "pointer",
                                transition: "all .15s", color: "#fff",
                                fontWeight: active ? 500 : 400,
                                background: active ? "rgba(255,255,255,.20)" : "transparent",
                              }}
                            >
                              {m.label}
                            </button>
                          );
                        })}
                      </div>
                      <textarea
                        className="input"
                        placeholder="Observaciones de esta campaña (opcional)"
                        value={campaignComments[c.id] || ""}
                        onChange={(e) => onCampaignComment(c.id, e.target.value)}
                        maxLength={2000}
                        style={{ width: "100%", minHeight: 50, resize: "vertical", fontSize: 12 }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border2)", flexShrink: 0 }}>
          <div className="field" style={{ margin: 0 }}>
            <label>Observaciones generales del período</label>
            <textarea
              className="input"
              value={generalComment}
              onChange={(e) => onGeneralComment(e.target.value)}
              maxLength={2000}
              style={{ width: "100%", minHeight: 60, resize: "vertical" }}
              placeholder="Lo que vieron en el mes…"
            />
          </div>
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border2)", flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onClose}
            style={{ width: "100%", justifyContent: "center" }}
          >
            Listo
          </button>
        </div>
      </div>
    </div>
  );
}