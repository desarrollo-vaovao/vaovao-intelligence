"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import { useClient } from "@/lib/clients";
import { useAuth } from "@/lib/auth";

const STAGES = [
  { key: "nuevo", label: "Nuevo" },
  { key: "contactado", label: "Contactado" },
  { key: "calificado", label: "Calificado" },
  { key: "propuesta", label: "Propuesta" },
  { key: "ganado", label: "Ganado" },
  { key: "perdido", label: "Perdido" },
];
const PIPELINE_STAGES = STAGES.filter((s) => s.key !== "perdido");
const PAGE_SIZE = 50;

// ── Helpers ──────────────────────────────────────────────────────
const NAME_KEYS = ["full_name", "nombre_completo", "nombre", "name"];
const CONTACT_KEYS = ["phone_number", "telefono", "teléfono", "phone", "email", "correo", "correo_electronico"];

function leadName(lead) {
  const d = lead.form_data || {};
  for (const k of NAME_KEYS) {
    if (d[k]) return String(d[k]);
  }
  if (d.first_name) return [d.first_name, d.last_name].filter(Boolean).join(" ");
  const first = Object.values(d).find((v) => typeof v === "string" && v.trim());
  return first || lead.leadgen_id?.slice(0, 12) || "Lead";
}

function leadContact(lead) {
  const d = lead.form_data || {};
  for (const k of CONTACT_KEYS) {
    if (d[k]) return String(d[k]);
  }
  return null;
}

function relativeTime(dateStr) {
  if (!dateStr) return "";
  const now = new Date();
  const then = new Date(dateStr);
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "ahora";
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `hace ${hours}h`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "ayer";
  if (days < 30) return `hace ${days}d`;
  return then.toLocaleDateString("es-GT", { day: "numeric", month: "short" });
}

function StageBadge({ status }) {
  const stage = STAGES.find((s) => s.key === status);
  return (
    <span className={`badge-stage badge-stage-${status}`}>
      {stage?.label || status}
    </span>
  );
}

function DownloadIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function LeadsPage() {
  const clientCtx = useClient() || {};
  const { client } = clientCtx;
  const { user } = useAuth();

  const [leads, setLeads] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [view, setView] = useState("pipeline");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [err, setErr] = useState("");
  const [detailLead, setDetailLead] = useState(null);
  const [users, setUsers] = useState([]);
  const [exporting, setExporting] = useState(false);

  const searchTimer = useRef(null);

  const load = useCallback(async () => {
    if (!client) return;
    setErr("");
    try {
      const params = { page, size: PAGE_SIZE, client_id: client.id };
      if (appliedSearch) params.search = appliedSearch;
      const res = await api.listLeads(params);
      setLeads(res.items);
      setTotal(res.total);
    } catch (e) {
      setErr(e.message);
    }
  }, [client, page, appliedSearch]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.listUsers().then(setUsers).catch(() => {});
  }, []);

  useEffect(() => {
    setPage(1);
    setLeads(null);
  }, [client]);

  function onSearchChange(val) {
    setSearch(val);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setAppliedSearch(val);
      setPage(1);
    }, 400);
  }

  async function exportCsv() {
    if (!client) return;
    setExporting(true);
    setErr("");
    try {
      await api.exportLeadsCsv({ client_id: client.id });
    } catch (e) {
      setErr(e.message);
    } finally {
      setExporting(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Leads</h1>
          <p>
            Contactos capturados desde los formularios de Meta
            {client ? ` de ${client.name}` : ""}.
          </p>
        </div>
        <div className="row">
          <div style={{ display: "flex", border: "1px solid var(--border2)", borderRadius: 12, background: "var(--surface3)", overflow: "hidden" }}>
            <button
              type="button"
              onClick={() => setView("pipeline")}
              style={{
                padding: "8px 16px", border: "none", cursor: "pointer",
                fontFamily: "inherit", fontSize: 12, fontWeight: view === "pipeline" ? 500 : 400,
                background: view === "pipeline" ? "var(--surface2)" : "transparent",
                color: view === "pipeline" ? "var(--orange)" : "var(--muted)",
              }}
            >
              Pipeline
            </button>
            <button
              type="button"
              onClick={() => setView("lista")}
              style={{
                padding: "8px 16px", border: "none", cursor: "pointer",
                fontFamily: "inherit", fontSize: 12, fontWeight: view === "lista" ? 500 : 400,
                background: view === "lista" ? "var(--surface2)" : "transparent",
                color: view === "lista" ? "var(--orange)" : "var(--muted)",
              }}
            >
              Lista
            </button>
          </div>
          <button className="btn btn-ghost" onClick={exportCsv} disabled={exporting || !client}>
            <DownloadIcon />
            {exporting ? "Exportando…" : "Exportar CSV"}
          </button>
        </div>
      </div>

      {err && <div className="err">{err}</div>}

      {/* Metric cards */}
      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-label">Leads del período</span>
          <span className="metric-value">{leads === null ? "—" : total}</span>
          <span className="metric-sub">{client?.name || ""}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Costo por lead</span>
          <span className="metric-value" style={{ color: "var(--muted2)" }}>—</span>
          <span className="metric-sub">Requiere endpoint de métricas</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Tasa de contacto</span>
          <span className="metric-value" style={{ color: "var(--muted2)" }}>—</span>
          <span className="metric-sub">Requiere endpoint de métricas</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Cierre</span>
          <span className="metric-value" style={{ color: "var(--muted2)" }}>—</span>
          <span className="metric-sub">Requiere endpoint de métricas</span>
        </div>
      </div>

      {/* Active view */}
      {leads === null ? (
        <div className="empty">Cargando…</div>
      ) : leads.length === 0 ? (
        <div className="card empty">
          <h3>Sin leads</h3>
          <p>Aún no hay leads capturados{client ? ` para ${client.name}` : ""}.</p>
        </div>
      ) : view === "pipeline" ? (
        <KanbanBoard leads={leads} onSelect={setDetailLead} />
      ) : (
        <LeadTable
          leads={leads} total={total} page={page} totalPages={totalPages}
          search={search} onSearchChange={onSearchChange}
          onSelect={setDetailLead} onPageChange={setPage}
        />
      )}

      {detailLead && (
        <LeadDetailModal
          leadId={detailLead.id}
          users={users}
          onClose={() => setDetailLead(null)}
          onUpdated={load}
        />
      )}
    </Shell>
  );
}

// ── Kanban (Pipeline view) ───────────────────────────────────────
function KanbanBoard({ leads, onSelect }) {
  const grouped = {};
  for (const s of PIPELINE_STAGES) grouped[s.key] = [];
  for (const lead of leads) {
    if (grouped[lead.status]) grouped[lead.status].push(lead);
  }

  return (
    <div className="kanban">
      {PIPELINE_STAGES.map((stage) => (
        <div className="kanban-col" key={stage.key}>
          <div className="kanban-col-head">
            <h3>{stage.label}</h3>
            <span className="badge badge-neutral">{grouped[stage.key].length}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {grouped[stage.key].map((lead) => (
              <div className="kanban-card" key={lead.id} onClick={() => onSelect(lead)}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                    {leadName(lead)}
                  </span>
                </div>
                {lead.campaign_name && (
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {lead.campaign_name}
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10 }}>
                  <span style={{ fontSize: 11, color: "var(--muted2)" }}>
                    {relativeTime(lead.received_at)}
                  </span>
                  {lead.assigned_to && (
                    <span style={{ fontSize: 10, color: "var(--muted)", background: "var(--surface)", borderRadius: 99, padding: "2px 7px" }}>
                      {lead.assigned_to.full_name}
                    </span>
                  )}
                </div>
              </div>
            ))}
            {grouped[stage.key].length === 0 && (
              <div style={{ fontSize: 11, color: "var(--muted2)", textAlign: "center", padding: "20px 0" }}>
                Sin leads
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── List view ────────────────────────────────────────────────────
function LeadTable({ leads, total, page, totalPages, search, onSearchChange, onSelect, onPageChange }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, background: "var(--surface2)", border: "1px solid var(--border2)", borderRadius: "var(--radius-sm)", padding: "8px 12px" }}>
          <SearchIcon />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Buscar nombre, teléfono o correo"
            style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--text)", fontFamily: "inherit", fontSize: 12 }}
          />
        </div>
        <span style={{ fontSize: 11.5, color: "var(--muted2)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
          {total} lead{total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ minWidth: 700 }}>
            <thead>
              <tr>
                <th>Lead</th>
                <th>Campaña</th>
                <th>Etapa</th>
                <th>Responsable</th>
                <th>Ingreso</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id} onClick={() => onSelect(lead)} style={{ cursor: "pointer" }}>
                  <td>
                    <div style={{ fontWeight: 500, fontSize: 12.5 }}>{leadName(lead)}</div>
                    {leadContact(lead) && (
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>{leadContact(lead)}</div>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: "var(--muted)" }}>{lead.campaign_name || "—"}</td>
                  <td><StageBadge status={lead.status} /></td>
                  <td style={{ fontSize: 12, color: lead.assigned_to ? "var(--text)" : "var(--muted2)" }}>
                    {lead.assigned_to?.full_name || "Sin asignar"}
                  </td>
                  <td style={{ fontSize: 11.5, color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
                    {relativeTime(lead.received_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="row" style={{ justifyContent: "center", marginTop: 18, gap: 14 }}>
          <button className="btn btn-ghost" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
            ← Anterior
          </button>
          <span style={{ fontSize: 12, color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
            Página {page} de {totalPages}
          </span>
          <button className="btn btn-ghost" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}>
            Siguiente →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Detail modal ─────────────────────────────────────────────────
function LeadDetailModal({ leadId, users, onClose, onUpdated }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);

  useEffect(() => {
    setErr("");
    api.getLead(leadId)
      .then((d) => { setDetail(d); setNotes(d.notes || ""); })
      .catch((e) => setErr(e.message));
  }, [leadId]);

  async function patchField(body) {
    setErr(""); setSaving(true);
    try {
      const updated = await api.updateLead(leadId, body);
      setDetail(updated);
      setNotes(updated.notes || "");
      setNotesDirty(false);
      if (onUpdated) onUpdated();
    } catch (e) {
      setErr(e.message);
    } finally { setSaving(false); }
  }

  const AUDIT_LABELS = {
    created: "Lead creado",
    status_changed: "Etapa cambiada",
    assigned: "Responsable cambiado",
    notes_added: "Notas agregadas",
    notes_changed: "Notas editadas",
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540, maxHeight: "85vh", overflowY: "auto" }}>
        {!detail && !err && <div style={{ padding: 20, textAlign: "center", color: "var(--muted)" }}>Cargando…</div>}
        {err && <div className="err">{err}</div>}
        {detail && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
              <h2 style={{ flex: 1, fontSize: 15 }}>{leadName(detail)}</h2>
              <StageBadge status={detail.status} />
            </div>

            {/* Form data from Meta */}
            {detail.form_data && Object.keys(detail.form_data).length > 0 && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 10, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 10 }}>
                  Datos del formulario
                </div>
                <dl style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 16px" }}>
                  {Object.entries(detail.form_data).map(([k, v]) => (
                    <div className="lead-detail-field" key={k}>
                      <dt>{k.replace(/_/g, " ")}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            {detail.campaign_name && (
              <div className="lead-detail-field" style={{ marginBottom: 16 }}>
                <dt style={{ fontSize: 10, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: ".5px" }}>Campaña</dt>
                <dd style={{ fontSize: 12.5 }}>{detail.campaign_name}</dd>
              </div>
            )}

            {/* Editable fields */}
            <div style={{ display: "flex", gap: 14, marginBottom: 16 }}>
              <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                <label>Etapa</label>
                <select
                  className="input"
                  value={detail.status}
                  onChange={(e) => patchField({ status: e.target.value })}
                  disabled={saving}
                >
                  {STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                <label>Responsable</label>
                <select
                  className="input"
                  value={detail.assigned_to?.id ?? ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    patchField({ assigned_to_id: val === "" ? null : Number(val) });
                  }}
                  disabled={saving}
                >
                  <option value="">Sin asignar</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.full_name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field">
              <label>Notas</label>
              <textarea
                className="input"
                rows={3}
                value={notes}
                onChange={(e) => { setNotes(e.target.value); setNotesDirty(true); }}
                placeholder="Agregar notas sobre este lead…"
                style={{ resize: "vertical" }}
              />
              {notesDirty && (
                <button
                  className="btn btn-primary"
                  style={{ alignSelf: "flex-end", marginTop: 6 }}
                  onClick={() => patchField({ notes: notes || null })}
                  disabled={saving}
                >
                  {saving ? "Guardando…" : "Guardar notas"}
                </button>
              )}
            </div>

            {/* Audit log */}
            {detail.audit_log && detail.audit_log.length > 0 && (
              <div style={{ marginTop: 20, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
                <div style={{ fontSize: 10, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 12 }}>
                  Bitácora
                </div>
                <div className="timeline">
                  {detail.audit_log.map((entry, i) => (
                    <div className="timeline-entry" key={i}>
                      <div className="tl-action">
                        {AUDIT_LABELS[entry.action] || entry.action}
                      </div>
                      <div className="tl-detail">
                        {entry.user ? entry.user.full_name : "Sistema"}
                        {entry.old_value && entry.action === "status_changed" && (
                          <> · {entry.old_value} → {entry.new_value}</>
                        )}
                        {entry.action === "assigned" && (
                          <> · {entry.old_value || "sin asignar"} → {entry.new_value}</>
                        )}
                      </div>
                      <div className="tl-time">{relativeTime(entry.timestamp)}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="row" style={{ marginTop: 20, justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={onClose}>Cerrar</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
