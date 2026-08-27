# Panel de Leads (Frontend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the leads management panel — Kanban + List views, detail modal with edit and audit log, CSV export — on top of the existing backend API.

**Architecture:** Single file `leads/page.jsx` with private subcomponents (same pattern as `clientes/page.jsx`). API methods added to `lib/api.js`. New CSS classes appended to `globals.css`. One small fix in `clientes/page.jsx` for the 409 on client deletion.

**Tech Stack:** Next.js 14.2.5 (app router), React 18, vanilla CSS, no external libraries.

## Global Constraints

- No new dependencies — React hooks + CSS global only.
- Follow patterns from `clientes/page.jsx` and `reportes/page.jsx` exactly.
- All text in Spanish (the app is in Spanish).
- Use `"use client"` directive at top of page files.
- Import the HTTP client as `import { api } from "@/lib/api"`.
- Import Shell as `import Shell from "@/lib/Shell"`.
- Import client context as `import { useClient } from "@/lib/clients"`.
- Import auth context as `import { useAuth } from "@/lib/auth"`.
- The backend enforces RBAC and multi-tenant isolation; the frontend must not reimplement it.
- `form_data` is a free-form dict from Meta lead forms — keys vary per form.

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `intelligence-web/lib/api.js` | Modify (add methods) | 6 new lead API methods |
| `intelligence-web/app/globals.css` | Modify (append classes) | Kanban, stage badges, timeline CSS |
| `intelligence-web/app/leads/page.jsx` | Rewrite (replace placeholder) | Entire leads panel |
| `intelligence-web/app/clientes/page.jsx` | Modify (fix DeleteClientModal) | Handle 409 with leads message |

---

### Task 1: API client methods + CSS foundation

**Files:**
- Modify: `intelligence-web/lib/api.js:34-122` (add methods to the `api` object)
- Modify: `intelligence-web/app/globals.css:349` (append new classes at end of file)

**Produces:**
- `api.listLeads(params)` → `Promise<{total, page, size, items}>` — params is a plain object converted to query string
- `api.getLead(id)` → `Promise<LeadResponse>` with `audit_log`
- `api.updateLead(id, body)` → `Promise<LeadResponse>` — body can have `status`, `assigned_to_id`, `notes`
- `api.leadsStatus()` → `Promise<LeadsModuleStatus>`
- `api.exportLeadsCsv(params)` → `Promise<string>` (filename) — triggers browser download
- `api.reconcileOrphans(pageId)` → `Promise<{page_id, recovered, still_pending}>`
- CSS classes: `.kanban`, `.kanban-col`, `.kanban-card`, `.badge-stage-nuevo`, `.badge-stage-contactado`, `.badge-stage-calificado`, `.badge-stage-propuesta`, `.badge-stage-ganado`, `.badge-stage-perdido`, `.lead-detail-field`, `.timeline`, `.timeline-entry`, `.metric-grid`, `.metric-card`

- [ ] **Step 1: Add lead API methods to `lib/api.js`**

Add these methods inside the `api` object, after the `fbDisconnect` line (line 121) and before the closing `};`:

```js
  // Leads
  listLeads: (params = {}) => {
    const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ""));
    return request(`/leads?${new URLSearchParams(clean)}`);
  },
  getLead: (id) => request(`/leads/${id}`),
  updateLead: (id, body) => request(`/leads/${id}`, { method: "PATCH", body }),
  leadsStatus: () => request("/leads/status"),
  exportLeadsCsv: async (params = {}) => {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ""));
    const qs = new URLSearchParams(clean).toString();
    const res = await fetch(`${BASE}/leads/export/csv${qs ? `?${qs}` : ""}`, { headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo exportar.");
    }
    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "leads.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    return filename;
  },
  reconcileOrphans: (pageId) =>
    request(`/leads/orphans/${pageId}/reconcile`, { method: "POST" }),
```

- [ ] **Step 2: Append CSS classes to `globals.css`**

Add at the end of the file (after line 349):

```css
/* ── Leads: métricas ── */
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin-bottom: 24px; }
.metric-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; display: flex; flex-direction: column; gap: 6px;
}
.metric-card .metric-label { font-family: var(--font-unbounded), sans-serif; font-size: 11px; font-weight: 400; color: var(--muted); letter-spacing: .02em; }
.metric-card .metric-value { font-size: 26px; font-weight: 600; letter-spacing: -.02em; }
.metric-card .metric-delta { font-size: 11px; font-variant-numeric: tabular-nums; }
.metric-card .metric-sub { font-size: 11px; color: var(--muted2); }

/* ── Leads: Kanban ── */
.kanban { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; }
.kanban-col {
  min-width: 220px; flex: 1; display: flex; flex-direction: column; gap: 8px;
  background: var(--surface3); border-radius: var(--radius); padding: 14px 10px;
}
.kanban-col-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 4px 10px; border-bottom: 1px solid var(--border); margin-bottom: 4px;
}
.kanban-col-head h3 { font-size: 12px; font-weight: 500; }
.kanban-card {
  background: var(--surface2); border: 1px solid var(--border); border-radius: 12px;
  padding: 13px 14px; cursor: pointer; transition: border-color .15s;
}
.kanban-card:hover { border-color: var(--border3); }

/* ── Leads: badges de etapa ── */
.badge-stage { font-size: 10px; font-weight: 600; padding: 3px 9px; border-radius: 99px; display: inline-flex; align-items: center; letter-spacing: .2px; }
.badge-stage-nuevo     { background: rgba(255,68,34,.12); color: var(--orange); }
.badge-stage-contactado { background: var(--surface2); color: var(--text); }
.badge-stage-calificado { background: var(--surface2); color: var(--text); }
.badge-stage-propuesta { background: var(--surface2); color: var(--muted); }
.badge-stage-ganado    { background: rgba(74,222,128,.10); color: var(--success); }
.badge-stage-perdido   { background: var(--surface2); color: var(--muted2); }

/* ── Leads: detalle ── */
.lead-detail-field { display: flex; flex-direction: column; gap: 2px; }
.lead-detail-field dt { font-size: 10px; color: var(--muted2); text-transform: uppercase; letter-spacing: .5px; }
.lead-detail-field dd { font-size: 12.5px; margin: 0; word-break: break-word; }

/* ── Leads: bitácora ── */
.timeline { display: flex; flex-direction: column; gap: 0; border-left: 2px solid var(--border); margin-left: 8px; padding-left: 18px; }
.timeline-entry { position: relative; padding: 10px 0; }
.timeline-entry::before {
  content: ""; position: absolute; left: -23px; top: 14px;
  width: 8px; height: 8px; border-radius: 50%; background: var(--border2);
}
.timeline-entry:first-child::before { background: var(--orange); }
.timeline-entry .tl-action { font-size: 12px; font-weight: 500; }
.timeline-entry .tl-detail { font-size: 11px; color: var(--muted); margin-top: 3px; }
.timeline-entry .tl-time { font-size: 10px; color: var(--muted2); margin-top: 4px; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 3: Verify the API client is syntactically valid**

Open the app dev server or run a basic syntax check. The `api` object must parse without errors.

```bash
cd intelligence-web && node -e "require('./lib/api.js')" 2>&1 || echo "Syntax error"
```

If this fails because of ESM/JSX, open the page in the browser instead — the import chain will surface any syntax error in the dev console.

- [ ] **Step 4: Commit**

```bash
git add intelligence-web/lib/api.js intelligence-web/app/globals.css
git commit -m "feat(leads): API client methods and CSS foundation for leads panel"
```

---

### Task 2: Leads page — helpers, state, layout shell, and metric cards

**Files:**
- Rewrite: `intelligence-web/app/leads/page.jsx` (replace the 5-line placeholder)

**Consumes:** `api.listLeads`, `api.leadsStatus`, `api.listUsers` from Task 1. CSS classes `.metric-grid`, `.metric-card` from Task 1.

**Produces:**
- `LeadsPage` component (default export) with state, data fetching, layout shell, metric cards.
- Helper functions `leadName(lead)`, `leadContact(lead)`, `relativeTime(dateStr)`, `StageBadge({status})` used by Tasks 3 and 4.
- Exposes `load()` refetch function used by the detail modal after edits.

- [ ] **Step 1: Write the page shell with helpers, state, and metric cards**

Replace the entire contents of `intelligence-web/app/leads/page.jsx` with:

```jsx
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

      {/* Active view — Tasks 3 and 4 add KanbanBoard and LeadTable here */}
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
```

This references `KanbanBoard`, `LeadTable`, and `LeadDetailModal` which don't exist yet — they'll be added as private functions in the same file in Tasks 3, 4, and 5. For now, add minimal stubs at the bottom of the file so it renders:

```jsx
// ── Stubs (replaced in Tasks 3–5) ───────────────────────────────
function KanbanBoard({ leads, onSelect }) {
  return <div className="empty">Kanban — en construcción</div>;
}

function LeadTable({ leads, total, page, totalPages, search, onSearchChange, onSelect, onPageChange }) {
  return <div className="empty">Lista — en construcción</div>;
}

function LeadDetailModal({ leadId, users, onClose, onUpdated }) {
  return null;
}
```

- [ ] **Step 2: Start the dev server and verify the page renders**

```bash
cd intelligence-web && npm run dev
```

Open `http://localhost:3000/leads` in the browser. Verify:
- Shell renders with sidebar, "Leads" is the active nav item.
- Page head shows title, subtitle with client name, Pipeline/Lista toggle, Export CSV button.
- 4 metric cards render (first one shows total or "—", others show "—").
- Toggle switches between "Kanban — en construcción" and "Lista — en construcción".
- No console errors.

- [ ] **Step 3: Commit**

```bash
git add intelligence-web/app/leads/page.jsx
git commit -m "feat(leads): page shell with state, helpers, metric cards, and view toggle"
```

---

### Task 3: Kanban board (Pipeline view)

**Files:**
- Modify: `intelligence-web/app/leads/page.jsx` (replace `KanbanBoard` stub)

**Consumes:** `PIPELINE_STAGES`, `leadName`, `leadContact`, `relativeTime`, `StageBadge` from Task 2. CSS classes `.kanban`, `.kanban-col`, `.kanban-col-head`, `.kanban-card`, `.badge-stage-*` from Task 1.

**Produces:** `KanbanBoard({ leads, onSelect })` — renders leads grouped by stage in 5 columns.

- [ ] **Step 1: Replace the KanbanBoard stub**

Find the `KanbanBoard` stub function and replace it with the full implementation:

```jsx
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
```

- [ ] **Step 2: Verify in the browser**

Open `http://localhost:3000/leads`. Switch to Pipeline view. Verify:
- 5 columns render: Nuevo, Contactado, Calificado, Propuesta, Ganado.
- Each column header shows count badge.
- Lead cards show name, campaign, relative time, assigned user if any.
- Leads with status "perdido" do NOT appear (correct — no Perdido column).
- Clicking a card does nothing visible yet (modal stub returns null).
- Columns scroll horizontally on narrow viewports.

- [ ] **Step 3: Commit**

```bash
git add intelligence-web/app/leads/page.jsx
git commit -m "feat(leads): Kanban board with 5 pipeline columns"
```

---

### Task 4: List view with search and pagination

**Files:**
- Modify: `intelligence-web/app/leads/page.jsx` (replace `LeadTable` stub)

**Consumes:** `leadName`, `leadContact`, `relativeTime`, `StageBadge`, `SearchIcon`, `PAGE_SIZE` from Task 2.

**Produces:** `LeadTable({ leads, total, page, totalPages, search, onSearchChange, onSelect, onPageChange })` — table with search, stage badges, and pagination.

- [ ] **Step 1: Replace the LeadTable stub**

Find the `LeadTable` stub function and replace it with:

```jsx
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
```

- [ ] **Step 2: Verify in the browser**

Switch to Lista view. Verify:
- Table renders with 5 columns: Lead, Campaña, Etapa, Responsable, Ingreso.
- Each lead row shows name, contact info below, campaign, stage badge with correct color, assigned user or "Sin asignar", relative timestamp.
- Search input works with debounce — typing filters after 400ms.
- Counter shows total (e.g., "128 leads").
- Pagination controls appear if total > 50, prev/next work.
- Clicking a row does nothing visible yet (detail modal is still a stub).

- [ ] **Step 3: Commit**

```bash
git add intelligence-web/app/leads/page.jsx
git commit -m "feat(leads): list view with search, stage badges, and pagination"
```

---

### Task 5: Lead detail modal with edit and audit log

**Files:**
- Modify: `intelligence-web/app/leads/page.jsx` (replace `LeadDetailModal` stub)

**Consumes:** `api.getLead`, `api.updateLead` from Task 1. `STAGES`, `StageBadge`, `leadName`, `relativeTime` from Task 2. CSS classes `.lead-detail-field`, `.timeline`, `.timeline-entry` from Task 1.

**Produces:** `LeadDetailModal({ leadId, users, onClose, onUpdated })` — modal that fetches lead detail, shows form data, editable stage/assignee/notes, and audit timeline.

- [ ] **Step 1: Replace the LeadDetailModal stub**

Find the `LeadDetailModal` stub and replace it with:

```jsx
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
```

- [ ] **Step 2: Remove the stub comments**

Delete the `// ── Stubs (replaced in Tasks 3–5)` comment line — all stubs are now replaced.

- [ ] **Step 3: Verify in the browser**

Open `http://localhost:3000/leads`. Test both views:

1. **Pipeline view:** Click a Kanban card → modal opens with lead detail, form data, campaign, editable stage/assignee/notes, and audit timeline. Change the stage via dropdown → the badge updates, the card moves to the new column after closing. Close modal.

2. **List view:** Click a table row → same modal opens. Change the assignee → "Sin asignar" or a team member. Type new notes, click "Guardar notas" → saves. Close and verify the list reflects changes.

3. **Error handling:** If the user is a `member` trying to edit someone else's lead, the backend returns 403 and the error displays in the modal.

4. **CSV export:** Click "Exportar CSV" → file downloads (or error if no leads).

- [ ] **Step 4: Commit**

```bash
git add intelligence-web/app/leads/page.jsx
git commit -m "feat(leads): detail modal with form data, edit controls, and audit timeline"
```

---

### Task 6: Fix 409 handling in client deletion

**Files:**
- Modify: `intelligence-web/app/clientes/page.jsx:210-236` (the `DeleteClientModal` function)

**Consumes:** Nothing from other tasks.

**Produces:** `DeleteClientModal` that displays the 409 "client has leads" error as an informative notice (orange) instead of a generic error (red).

- [ ] **Step 1: Update the DeleteClientModal error handling**

In `intelligence-web/app/clientes/page.jsx`, find the `DeleteClientModal` function (line 210). Replace its current `catch` clause and error display:

Change the function from:

```jsx
function DeleteClientModal({ client, onClose, onDone }) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function confirmDelete() {
    setErr(""); setBusy(true);
    try { await api.deleteClient(client.id); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Eliminar cliente</h2>
        {err && <div className="err">{err}</div>}
```

To:

```jsx
function DeleteClientModal({ client, onClose, onDone }) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const hasLeadsConflict = err.includes("leads");
  async function confirmDelete() {
    setErr(""); setBusy(true);
    try { await api.deleteClient(client.id); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Eliminar cliente</h2>
        {err && (
          hasLeadsConflict
            ? <div className="notice" style={{ marginBottom: 14 }}><div>{err}</div></div>
            : <div className="err">{err}</div>
        )}
```

The rest of the modal (the `<p>`, the buttons) stays exactly as is. No other changes.

- [ ] **Step 2: Verify in the browser**

Open `http://localhost:3000/clientes`. Try deleting a client that has leads:
- The modal should show the backend's message in an orange notice box (not red error).
- The message text is from the backend: "No puedes borrar este cliente: tiene N leads y borrarlo eliminaría todo su historial, incluida la bitácora. Exporta los leads a CSV antes de borrar el cliente."
- Deleting a client with 0 leads still works normally.
- A non-409 error (e.g., network failure) still shows as red.

- [ ] **Step 3: Commit**

```bash
git add intelligence-web/app/clientes/page.jsx
git commit -m "fix(clientes): show 409 leads-conflict as informative notice, not error"
```

---
