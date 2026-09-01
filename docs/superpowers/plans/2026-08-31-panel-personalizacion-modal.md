# Panel de personalización como modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar la sección plegable "Personalizar métricas y
observaciones" (que hoy estira la página de Reportes en línea) por un modal
con scroll propio, buscador por nombre de campaña, y cada campaña colapsada
por defecto — sin tocar el backend ni el payload que ya se manda a generar
el reporte.

**Architecture:** Cambio puramente de UI dentro de un único archivo,
`intelligence-web/app/reportes/page.jsx`. El estado de personalización
(`campaignMetrics`, `campaignComments`, `generalComment`, `campaignsPreview`)
sigue viviendo en `ReportesPage`, exactamente igual que hoy — el modal es un
componente nuevo en el mismo archivo que solo lee y escribe ese estado vía
props. Cerrar el modal no lo descarta.

**Tech Stack:** Next.js/React (frontend). Sin cambios de backend, sin
migraciones, sin suite de pruebas de frontend en este proyecto (verificación
manual, igual que el resto de este archivo).

## Global Constraints

- No se toca ningún archivo de `intelligence-backend/` — este es un cambio
  100% de frontend sobre trabajo ya desplegado (ver spec
  [2026-08-31-panel-personalizacion-modal-design.md](../specs/2026-08-31-panel-personalizacion-modal-design.md)).
- El payload que arma `generate()` hacia `api.generateReport` no cambia de
  forma — sigue incluyendo `campaign_metrics`/`campaign_comments`/
  `general_comment` solo cuando `showCustomize && campaignsPreview.length > 0`
  (la misma condición de retrocompatibilidad de siempre).
- Cerrar el modal (botón "Listo", tecla Escape, o clic en el fondo) **nunca
  descarta el estado ya escrito** — solo oculta el modal.
- Cada campaña arranca colapsada; una sola puede estar expandida a la vez
  (expandir otra colapsa la que estaba abierta).
- El buscador filtra por nombre, insensible a mayúsculas
  (`.toLowerCase()` sobre ambos lados, sin normalización de acentos —
  igual que el resto de buscadores de esta app).
- Reutilizar los tokens/clases visuales que ya existen en este archivo
  (`.card`, `.input`, `.btn`, `.field`, `var(--muted)`, `var(--border2)`,
  `var(--orange)`, `var(--surface2)`) — nada de un sistema visual nuevo.

---

## File Structure

- **Modify** `intelligence-web/app/reportes/page.jsx` — único archivo que
  cambia: nuevo estado (`campaignSearch`, `expandedCampaignId`), nuevo
  componente `CustomizeReportModal` en el mismo archivo, y la sección
  plegable actual se reemplaza por un botón que abre el modal.

---

## Task 1: Modal de personalización

**Files:**
- Modify: `intelligence-web/app/reportes/page.jsx`

**Interfaces:**
- No expone nada a otros archivos — todo el cambio es interno a
  `reportes/page.jsx`. `CustomizeReportModal` es un componente privado de
  este archivo, no exportado.

- [ ] **Step 1: Agregar el estado nuevo**

En `intelligence-web/app/reportes/page.jsx`, justo después de la línea
existente:

```js
  const [generalComment, setGeneralComment] = useState("");
```

agregar:

```js
  const [campaignSearch, setCampaignSearch] = useState("");
  const [expandedCampaignId, setExpandedCampaignId] = useState(null);
```

- [ ] **Step 2: Reemplazar `toggleCustomize` por `openCustomize`/`closeCustomize`**

Reemplazar la función existente:

```js
  function toggleCustomize() {
    const next = !showCustomize;
    setShowCustomize(next);
    if (next && campaignsPreview.length === 0) {
      loadCampaignsPreview();
    }
  }
```

por:

```js
  function openCustomize() {
    setShowCustomize(true);
    if (campaignsPreview.length === 0) {
      loadCampaignsPreview();
    }
  }

  function closeCustomize() {
    setShowCustomize(false);
  }
```

(El botón que llamaba a `toggleCustomize` ya no necesita alternar: al estar
el modal cerrado, la única acción posible del botón es abrirlo — cerrarlo
es responsabilidad del propio modal, ver Step 5.)

- [ ] **Step 3: Incluir los campos nuevos en el `useEffect` que invalida la selección**

Reemplazar:

```js
  useEffect(() => {
    setCampaignsPreview([]);
    setCampaignMetrics({});
    setCampaignComments({});
    setShowCustomize(false);
  }, [accountId, dateFrom, dateTo, countryCode]);
```

por:

```js
  useEffect(() => {
    setCampaignsPreview([]);
    setCampaignMetrics({});
    setCampaignComments({});
    setShowCustomize(false);
    setCampaignSearch("");
    setExpandedCampaignId(null);
  }, [accountId, dateFrom, dateTo, countryCode]);
```

- [ ] **Step 4: Reemplazar la sección plegable en línea por un botón + el modal**

Reemplazar todo este bloque (el `{accountId && dateFrom && dateTo && (...)}`
que hoy contiene el botón Y la sección plegable con las tarjetas de
campaña):

```jsx
          {accountId && dateFrom && dateTo && (
            <div className="field">
              <button
                type="button"
                onClick={toggleCustomize}
                style={{
                  display: "flex", alignItems: "center", gap: 6, background: "none",
                  border: "none", padding: 0, cursor: "pointer", color: "var(--muted)",
                  fontSize: 12, fontFamily: "inherit",
                }}
              >
                <span>{showCustomize ? "▾" : "▸"}</span>
                Personalizar métricas y observaciones (opcional)
              </button>

              {showCustomize && (
                <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 14 }}>
                  {loadingCampaigns && (
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>Cargando campañas…</div>
                  )}

                  {!loadingCampaigns && campaignsPreview.length === 0 && (
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>
                      No se encontraron campañas con datos en este período.
                    </div>
                  )}

                  {campaignsPreview.map((c) => (
                    <div key={c.id} className="card" style={{ padding: 12 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                        {c.name}{" "}
                        <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                          · {objectiveLabel(c.objective)}
                        </span>
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                        {METRIC_CATALOG.map((m) => (
                          <label key={m.key} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                            <input
                              type="checkbox"
                              checked={(campaignMetrics[c.id] || []).includes(m.key)}
                              onChange={() => toggleMetric(c.id, m.key)}
                            />
                            {m.label}
                          </label>
                        ))}
                      </div>
                      <textarea
                        className="input"
                        placeholder="Observaciones de esta campaña (opcional)"
                        value={campaignComments[c.id] || ""}
                        onChange={(e) => setCampaignComment(c.id, e.target.value)}
                        maxLength={2000}
                        style={{ width: "100%", minHeight: 50, resize: "vertical", fontSize: 12 }}
                      />
                    </div>
                  ))}

                  {campaignsPreview.length > 0 && (
                    <div className="field" style={{ margin: 0 }}>
                      <label>Observaciones generales del período</label>
                      <textarea
                        className="input"
                        value={generalComment}
                        onChange={(e) => setGeneralComment(e.target.value)}
                        maxLength={2000}
                        style={{ width: "100%", minHeight: 70, resize: "vertical" }}
                        placeholder="Lo que vieron en el mes…"
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
```

por:

```jsx
          {accountId && dateFrom && dateTo && (
            <div className="field">
              <button
                type="button"
                onClick={openCustomize}
                style={{
                  display: "flex", alignItems: "center", gap: 6, background: "none",
                  border: "none", padding: 0, cursor: "pointer", color: "var(--muted)",
                  fontSize: 12, fontFamily: "inherit",
                }}
              >
                <span>▸</span>
                Personalizar métricas y observaciones (opcional)
              </button>
            </div>
          )}
```

- [ ] **Step 5: Renderizar el modal (condicionalmente) y agregar el componente**

Justo después del `</div>` que cierra `<div className="card" style={{ padding: 24 }}>`
(el que envuelve todo el formulario — busca la línea `</div>` que precede
al `</div>` de cierre de `<div style={{ maxWidth: 560, margin: "0 auto" }}>`),
agregar la llamada al modal:

```jsx
        </div>

        {showCustomize && (
          <CustomizeReportModal
            campaigns={campaignsPreview}
            loading={loadingCampaigns}
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
```

(El `</div>\n      </div>\n    </Shell>\n  );\n}` de cierre ya existe al
final del archivo — este step inserta el bloque `{showCustomize && (...)}`
justo antes de esos cierres finales, dentro del `<div style={{ maxWidth: 560 ...}}>`
pero fuera del `<div className="card">` del formulario, para que el modal
no herede el `maxWidth: 560` del formulario — se posiciona `fixed` de
cualquier forma, así que el contenedor padre no importa visualmente, pero
mantenerlo fuera de la tarjeta del formulario deja la jerarquía del JSX más
clara.)

Después del cierre de la función `ReportesPage` (después de la llave `}`
final que cierra `export default function ReportesPage() { ... }`), agregar
el nuevo componente:

```jsx

function CustomizeReportModal({
  campaigns, loading, search, onSearchChange,
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
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000, padding: 20,
      }}
    >
      <div
        className="card"
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

        <div style={{ overflowY: "auto", flex: 1, padding: "0 20px" }}>
          {loading && (
            <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
              Cargando campañas…
            </div>
          )}

          {!loading && campaigns.length === 0 && (
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
                      alignItems: "center", padding: 12, background: "none", border: "none",
                      cursor: "pointer", fontFamily: "inherit", textAlign: "left",
                    }}
                  >
                    <span style={{ fontSize: 12, fontWeight: 500 }}>
                      {c.name}{" "}
                      <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                        · {objectiveLabel(c.objective)}
                      </span>
                    </span>
                    <span style={{ color: "var(--muted)" }}>{expanded ? "▾" : "▸"}</span>
                  </button>

                  {expanded && (
                    <div style={{ padding: "0 12px 12px" }}>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                        {METRIC_CATALOG.map((m) => (
                          <label key={m.key} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                            <input
                              type="checkbox"
                              checked={(campaignMetrics[c.id] || []).includes(m.key)}
                              onChange={() => onToggleMetric(c.id, m.key)}
                            />
                            {m.label}
                          </label>
                        ))}
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
```

- [ ] **Step 6: Verificar que compila**

Run: `cd intelligence-web && npm run build`
Expected: compila sin errores ni warnings nuevos (mismo resultado que antes
de este cambio — 11 rutas estáticas generadas).

- [ ] **Step 7: Verificación manual (dev server, sin backend real disponible)**

Run: `cd intelligence-web && npm run dev`

Sin un backend con datos reales de Meta conectado, esto NO reemplaza la
verificación en staging (ver Step 8) — solo confirma que no hay errores de
React/consola al montar la página y al abrir/cerrar el modal con el estado
vacío:

1. Abrir `/reportes` en el navegador (puede redirigir a login si no hay
   sesión — normal, confirma que la página no revienta).
2. Si hay forma de autenticarse y llegar al formulario en este entorno: con
   un activo comercial y período seleccionados, hacer clic en "Personalizar
   métricas y observaciones (opcional)" y confirmar que el modal abre sin
   error de consola, incluso con `campaignsPreview` vacío (estado de carga
   o "No se encontraron campañas").
3. Si no hay forma de autenticarse en este entorno, decirlo explícitamente
   en el reporte en vez de reclamar una verificación que no se pudo hacer.

- [ ] **Step 8: Nota para verificación en staging (no ejecutable aquí)**

Este step documenta lo que falta verificar contra datos reales — no es
algo que el entorno de esta tarea pueda ejecutar, pero debe quedar
explícito en el reporte final como pendiente:

En staging, con la cuenta de muchas campañas que expuso el problema
original:
- Abrir el modal, confirmar que el scroll queda contenido dentro del modal
  (la página de fondo no se estira).
- Buscar por nombre y confirmar que filtra en vivo.
- Expandir una campaña, elegir métricas, escribir un comentario; expandir
  otra — confirmar que la primera se colapsa sola.
- Escribir la observación general, cerrar con "Listo".
- Cerrar y volver a abrir el modal (sin cambiar activo/período/país):
  confirmar que lo ya elegido/escrito sigue ahí (el estado vive en
  `ReportesPage`, no se pierde al cerrar).
- Generar el PDF y confirmar que refleja las métricas y observaciones
  elegidas — igual que la verificación ya pendiente del spec anterior.
- Cambiar de activo comercial o período con el modal cerrado: confirmar
  que al volver a abrir el panel, la búsqueda y la campaña expandida
  también se reiniciaron (no solo la selección de métricas).

- [ ] **Step 9: Commit**

```bash
git add intelligence-web/app/reportes/page.jsx
git commit -m "$(cat <<'EOF'
feat(reportes): panel de personalizacion como modal

La seccion en linea, probada en staging con una cuenta de muchas
campanas, estiraba demasiado la pagina (espacio/scroll, rendimiento
percibido). Se mueve a un modal con scroll propio: buscador por
nombre, cada campana colapsada por defecto (una expandida a la vez),
observacion general dentro del mismo modal. El estado y el payload
que se manda a generar el reporte no cambian -- solo la superficie
visual.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Cobertura del spec:**
- Modal en vez de sección en línea → Step 4-5.
- Scroll propio del modal, no de la página → Step 5 (`overflowY: "auto"`
  en el contenedor de la lista, `maxHeight: "85vh"` en el modal).
- Buscador por nombre → Step 5 (`search`/`onSearchChange`, filtro con
  `.toLowerCase()`).
- Cada campaña colapsada por defecto, una expandida a la vez →
  `expandedCampaignId` (Step 1) + `onToggleExpand` (Step 5).
- Observación general dentro del modal → Step 5 (textarea al fondo del
  modal).
- Cerrar (Escape, clic afuera, botón "Listo") no descarta nada → Step 5
  (`onClose` solo llama `setShowCustomize(false)`, ningún otro estado se
  toca al cerrar).
- Invalidación al cambiar activo/período/país incluye ahora también
  búsqueda y campaña expandida → Step 3.
- Sin cambios de backend → confirmado, ningún task toca
  `intelligence-backend/`.
- Testing manual (no hay suite de frontend) → Steps 6-8.
