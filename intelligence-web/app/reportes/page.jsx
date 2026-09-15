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
  // El switcher de arriba (ver lib/clients.jsx) ya elige un ACTIVO
  // comercial puntual — un cliente con varias cuentas (ej. varias
  // estaciones) ya tiene una entrada por activo ahí, así que esta pantalla
  // no necesita su propio selector "de qué activo del cliente" como antes.
  const { account } = useClient() || {};
  const accountId = account?.id ?? null;
  const { user } = useAuth() || {};
  const exchangeRate = useExchangeRate();

  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  const [reportType, setReportType] = useState("quincenal");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [countryCode, setCountryCode] = useState("");
  const [countries, setCountries] = useState([]);
  const [loadingCountries, setLoadingCountries] = useState(false);
  const [countriesError, setCountriesError] = useState("");
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

  // Reportes ya generados de este activo. Volver a bajar uno no cuesta ni
  // una llamada a Meta ni un render de Chromium: el archivo ya está
  // guardado (ver models.GeneratedReport en el backend).
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [downloadingJob, setDownloadingJob] = useState(null);

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
  // Separado del efecto de abajo para que el botón "Reintentar" pueda
  // volver a llamarlo sin resetear el país ya elegido. Antes, un fallo acá
  // (típicamente Meta: "User request limit reached") se tragaba en
  // silencio — countries quedaba en [] sin ningún aviso, así que el
  // selector se veía "atascado" en "Todos los países" sin explicar por
  // qué nunca aparecían las demás opciones.
  async function cargarPaises(id) {
    setLoadingCountries(true);
    setCountriesError("");
    try {
      const response = await request(`/reports/countries/${id}`);
      setCountries(response.countries || []);
    } catch (e) {
      setCountriesError(e.message);
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

  async function cargarHistorial(id) {
    setLoadingHistory(true);
    setHistoryError("");
    try {
      setHistory(await api.reportHistory(id));
    } catch (e) {
      setHistoryError(e.message);
      setHistory([]);
    } finally {
      setLoadingHistory(false);
    }
  }

  // Vuelve a bajar un reporte del historial. No pasa por `generate()` a
  // propósito: ese camino arranca un job nuevo (Meta + Chromium) y aquí el
  // archivo ya existe, así que es solo la descarga.
  async function descargarDelHistorial(jobId) {
    setErr(""); setInfo(""); setDownloadingJob(jobId);
    try {
      const filename = await api.downloadReport(jobId);
      setInfo(`Reporte descargado: ${filename}`);
      if (accountId) cargarHistorial(accountId);  // refresca el contador de descargas
    } catch (e) {
      setErr(e.message);
      // Un 410 significa que la retención ya se llevó el archivo. Recargar
      // deja la fila marcada como no descargable en vez de seguir
      // ofreciendo un botón que ya no puede funcionar.
      if (accountId) cargarHistorial(accountId);
    } finally {
      setDownloadingJob(null);
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

  // Al cambiar el ACTIVO comercial activo (switcher de arriba): su país
  // seleccionado y su listado de países ya no aplican al activo nuevo.
  useEffect(() => {
    setCountryCode("");
    setCountries([]);
    setCountriesError("");
    setHistory([]);
    setHistoryError("");
    if (accountId) {
      cargarPaises(accountId);
      cargarHistorial(accountId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId]);

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
    } finally {
      setBusy(false);
      // Tanto si salió bien como si falló: la generación ya dejó su fila
      // en el historial y hay que mostrarla. Un intento fallido también
      // aparece ahí, con su error — así queda claro que se intentó.
      if (accountId) cargarHistorial(accountId);
    }
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
          {/* El activo comercial ya se elige en el switcher de arriba (ver
              lib/clients.jsx) — un cliente con varias cuentas tiene una
              entrada por activo ahí, así que esta pantalla ya no repite el
              selector, solo confirma cuál está activo. */}
          <div className="field">
            <label>Activo comercial</label>
            <input
              className="input"
              value={account ? account.displayName : "Selecciona un activo comercial en el menú lateral"}
              disabled
              readOnly
            />
          </div>

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
              {countriesError && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--error)" }}>
                    No se pudieron cargar los países: {countriesError}
                  </span>
                  <button
                    type="button" className="btn btn-ghost" style={{ padding: "3px 10px", fontSize: 11 }}
                    onClick={() => cargarPaises(accountId)}
                  >
                    Reintentar
                  </button>
                </div>
              )}
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

        {accountId && (
          <ReportHistoryPanel
            entries={history}
            loading={loadingHistory}
            error={historyError}
            downloadingJob={downloadingJob}
            onDownload={descargarDelHistorial}
            onRetry={() => cargarHistorial(accountId)}
          />
        )}

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

// ── Historial de reportes ────────────────────────────────────────
const MESES_CORTOS = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

// "2026-01-01" → "1 ene". Se parte el string a mano en vez de usar
// new Date("2026-01-01"): eso lo interpreta como UTC medianoche y en
// cualquier zona al oeste (la nuestra) se muestra el día ANTERIOR — el
// período "1 al 15" se vería como "31 dic al 14 ene".
function diaCorto(iso) {
  const [, mes, dia] = iso.split("-").map(Number);
  return `${dia} ${MESES_CORTOS[mes - 1]}`;
}

function periodoLegible(desde, hasta) {
  const [anioDesde] = desde.split("-").map(Number);
  const [anioHasta] = hasta.split("-").map(Number);
  const sufijo = anioDesde === anioHasta ? ` ${anioHasta}` : "";
  return `${diaCorto(desde)} – ${diaCorto(hasta)}${sufijo}`;
}

function generadoHace(iso) {
  // El backend serializa en UTC; el navegador lo pasa a la hora local.
  const cuando = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const minutos = Math.round((Date.now() - cuando.getTime()) / 60000);
  if (minutos < 1) return "hace un momento";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  const dias = Math.round(horas / 24);
  if (dias === 1) return "ayer";
  if (dias < 30) return `hace ${dias} días`;
  // Más de un mes: la fecha exacta. Se arma con el mismo mes corto que el
  // resto del panel en vez de toLocaleDateString(), que sin locale sigue el
  // idioma del navegador y colaba un "2/27/2026" en una interfaz en español.
  return `${cuando.getDate()} ${MESES_CORTOS[cuando.getMonth()]} ${cuando.getFullYear()}`;
}

function pesoLegible(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

/**
 * Los reportes ya generados de este activo comercial.
 *
 * POR QUÉ ESTÁ AQUÍ
 * Generar es la parte cara (traer todo de Meta y renderizar el PDF en
 * Chromium); volver a bajar algo que ya se generó no cuesta nada. Sin
 * esta lista, la única forma de recuperar el reporte de la quincena
 * pasada era volver a generarlo completo — y con varias personas
 * haciendo eso a la vez, pagándolo varias veces.
 */
function ReportHistoryPanel({ entries, loading, error, downloadingJob, onDownload, onRetry }) {
  return (
    <div className="card" style={{ padding: 24, marginTop: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div>
          <h2 style={{ fontSize: 13, margin: 0 }}>Reportes generados</h2>
          <p style={{ fontSize: 11, color: "var(--muted)", margin: "3px 0 0" }}>
            Vuelve a descargarlos sin generarlos de nuevo.
          </p>
        </div>
        {loading && <span className="loading-dots"><span /><span /><span /></span>}
      </div>

      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--error)" }}>
            No se pudo cargar el historial: {error}
          </span>
          <button type="button" className="btn btn-ghost" onClick={onRetry} style={{ fontSize: 11 }}>
            Reintentar
          </button>
        </div>
      )}

      {!error && !loading && entries.length === 0 && (
        <p style={{ fontSize: 11, color: "var(--muted)", margin: 0 }}>
          Todavía no se ha generado ningún reporte de este activo.
        </p>
      )}

      {entries.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {entries.map((r) => {
            const bajando = downloadingJob === r.job_id;
            return (
              <div
                key={r.job_id}
                style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 0", borderBottom: "1px solid var(--border)",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 500 }}>
                    {periodoLegible(r.date_from, r.date_to)}
                    <span style={{ color: "var(--muted2)", fontWeight: 400 }}>
                      {" · "}{r.currency === "GTQ" ? "Q" : "$"}
                      {r.country_code ? ` · ${r.country_code}` : ""}
                    </span>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>
                    {generadoHace(r.created_at)}
                    {r.size_bytes ? ` · ${pesoLegible(r.size_bytes)}` : ""}
                    {r.download_count > 0 ? ` · ${r.download_count} descarga${r.download_count === 1 ? "" : "s"}` : ""}
                  </div>
                </div>

                {r.status === "processing" && (
                  <span className="badge badge-neutral">
                    Generando<span className="loading-dots"><span /><span /><span /></span>
                  </span>
                )}

                {r.status === "error" && (
                  <span className="badge badge-warn" title={r.error || ""}>Falló</span>
                )}

                {r.status === "done" && !r.downloadable && (
                  // La retención del backend ya se llevó el archivo. Se
                  // deja la entrada visible para no borrar el registro de
                  // que ese reporte existió, pero sin botón que no funcione.
                  <span className="badge badge-neutral" title="Los reportes se conservan 90 días.">
                    Expirado
                  </span>
                )}

                {r.status === "done" && r.downloadable && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => onDownload(r.job_id)}
                    disabled={bajando}
                    style={{ fontSize: 11, flexShrink: 0 }}
                  >
                    {bajando ? (
                      <>Bajando<span className="loading-dots"><span /><span /><span /></span></>
                    ) : (
                      <>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" strokeWidth="1.8">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        Descargar
                      </>
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
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