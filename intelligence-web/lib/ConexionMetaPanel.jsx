"use client";
import { useEffect, useState } from "react";
import { api } from "./api";
import FacebookConnect from "./FacebookConnect";

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function AddTokenModal({ onClose, onDone }) {
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setErr(""); setBusy(true);
    try {
      const savedLabel = label.trim();
      await api.addMetaToken({ label: savedLabel, system_user_token: token });
      onDone(savedLabel);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Agregar portafolio</h2>
        {err && <div className="err">{err}</div>}
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
          Cada portafolio comercial independiente de Meta (ej. "Vao Vao", "Menos Pausa")
          necesita su propio System User Token. Se guarda cifrado y nunca se muestra completo.
          Si no existe ya un cliente con este nombre, se crea automáticamente en <b>Clientes</b>.
        </p>
        <div className="field">
          <label>Portafolio (etiqueta para identificarlo)</label>
          <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ej. Vao Vao, Menos Pausa" autoFocus />
        </div>
        <div className="field">
          <label>System User Token</label>
          <input className="input mono" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="EAAG…" />
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !label.trim() || token.length < 10}>
            {busy ? "Agregando…" : "Agregar token"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DeleteTokenModal({ tokenRow, onClose, onDone }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function confirmDelete() {
    setErr(""); setBusy(true);
    try { await api.deleteMetaToken(tokenRow.id); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Eliminar token</h2>
        {err && <div className="err">{err}</div>}
        <p style={{ color: "var(--muted)" }}>
          ¿Eliminar el token del portafolio <strong style={{ color: "var(--text)" }}>{tokenRow.label}</strong>?
          Los reportes que dependían solo de este token dejarán de tener acceso a esas cuentas.
        </p>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={busy}>
            {busy ? "Eliminando…" : "Eliminar token"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AccountsModal({ tokenRow, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.getMetaTokenAdAccounts(tokenRow.id).then(setData).catch((e) => setErr(e.message));
  }, [tokenRow.id]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
        <h2>Cuentas de {tokenRow.label}</h2>
        {err && <div className="err">{err}</div>}

        {!data && !err && <div style={{ color: "var(--muted)", fontSize: 14 }}>Cargando…</div>}

        {data && (
          <>
            {data.businesses?.length > 0 && (
              <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 10 }}>
                Portafolios: {data.businesses.map((b) => b.name).join(", ")}
              </div>
            )}

            {data.warnings?.length > 0 && (
              <div className="notice" style={{ marginBottom: 12 }}>
                <div>
                  <b>Algunas fuentes no se pudieron leer.</b>
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {data.warnings.map((w, i) => <li key={i} style={{ fontSize: 13 }}>{w}</li>)}
                  </ul>
                </div>
              </div>
            )}

            {data.accounts.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--muted)" }}>
                Este token no tiene cuentas publicitarias visibles.
              </div>
            ) : (
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                <table className="table">
                  <thead><tr><th>Cuenta</th><th>ID</th><th>Origen</th></tr></thead>
                  <tbody>
                    {data.accounts.map((a) => (
                      <tr key={a.id}>
                        <td>{a.name || "—"}</td>
                        <td className="mono" style={{ fontSize: 13 }}>{a.id}</td>
                        <td style={{ fontSize: 12, color: "var(--muted)" }}>
                          {(a.sources || []).join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </div>
  );
}

// Contenido de Conexión Meta, sin Shell/page-head propios: lo usa tanto
// /conexion (ruta directa, enlazada desde Leads y Reportes cuando Meta no
// está conectado) como la pestaña "Conexión Meta" dentro de /ajustes.
export default function ConexionMetaPanel() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");

  const [showAdd, setShowAdd] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [accountsTarget, setAccountsTarget] = useState(null);

  async function load() {
    try { setStatus(await api.getMeta()); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  const connected = status?.configured;
  const tokens = status?.tokens || [];

  return (
    <>
      <FacebookConnect />

      <div className="row" style={{ margin: "28px 0 18px", gap: 14 }}>
        <div style={{ height: 1, background: "var(--border)", flex: 1 }} />
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: "1px", whiteSpace: "nowrap" }}>
          Alternativa — tokens centrales (System User)
        </span>
        <div style={{ height: 1, background: "var(--border)", flex: 1 }} />
      </div>

      {err && <div className="err">{err}</div>}
      {note && <div className="notice" style={{ marginBottom: 16 }}><div>{note}</div></div>}
      {status?.undecryptable_count > 0 && (
        <div className="notice" style={{ marginBottom: 16 }}>
          <div>
            Hay {status.undecryptable_count} credencial(es) de Meta guardadas que el servidor
            no pudo leer (la llave de cifrado del servidor no coincide con la que se usó para
            guardarlas). Revisa <code>ENCRYPTION_KEY</code> — los datos siguen ahí, no se perdieron.
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 24, marginBottom: 24 }}>
        <div className="row">
          <span className={`pulse ${connected ? "on" : "off"}`} />
          <h3 style={{ fontSize: 16 }}>
            {status === null ? "Comprobando…" : connected ? "Conectado a Meta" : "Sin conectar"}
          </h3>
          <div className="spacer" />
          {connected && <span className="badge badge-signal">Listo para reportes</span>}
        </div>
      </div>

      <div>
        <div className="row" style={{ marginBottom: 18, alignItems: "flex-start" }}>
          <div>
            <div className="row" style={{ gap: 8 }}>
              <h3 style={{ fontSize: 16 }}>Portafolios</h3>
              {tokens.length > 0 && <span className="badge badge-neutral">{tokens.length}</span>}
            </div>
            <p style={{ color: "var(--muted)", fontSize: 12, margin: "4px 0 0" }}>
              Un token de System User por cada portafolio comercial de Meta.
            </p>
          </div>
          <div className="spacer" />
          <button className="btn btn-primary" onClick={() => setShowAdd(true)} style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            <PlusIcon /> Agregar portafolio
          </button>
        </div>

        {tokens.length === 0 ? (
          <div className="card empty">
            <h3>Todavía no hay portafolios</h3>
            <p>Agrega un token de System User por cada portafolio comercial de Meta que administres.</p>
          </div>
        ) : (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
            gap: 14,
          }}>
            {tokens.map((t) => (
              <div key={t.id} className="portfolio-card">
                <div className="row" style={{ marginBottom: 14, gap: 10, alignItems: "flex-start" }}>
                  <div style={{
                    width: 34, height: 34, borderRadius: 9, background: "var(--gradient)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 14, fontWeight: 700, color: "#fff", flexShrink: 0,
                  }}>
                    {t.label.trim().charAt(0).toUpperCase() || "?"}
                  </div>
                  <div style={{ minWidth: 0, flex: 1, paddingTop: 2 }}>
                    <strong style={{ fontSize: 14, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.label}>
                      {t.label}
                    </strong>
                    <div className="row" style={{ gap: 5, marginTop: 3 }}>
                      <span className="pulse on" />
                      <span style={{ fontSize: 11, color: "var(--success)" }}>Activo</span>
                    </div>
                  </div>
                  <button
                    className="icon-btn icon-btn-danger"
                    title="Eliminar token"
                    aria-label="Eliminar token"
                    onClick={() => setDeleteTarget(t)}
                    style={{ flexShrink: 0 }}
                  >
                    <TrashIcon />
                  </button>
                </div>

                <div className="portfolio-token-chip mono" style={{ marginBottom: 14 }}>
                  <span className="dot" />{t.token_masked}
                </div>

                <button className="btn btn-ghost" style={{ width: "100%", justifyContent: "center" }} onClick={() => setAccountsTarget(t)}>
                  Ver cuentas
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {showAdd && (
        <AddTokenModal
          onClose={() => setShowAdd(false)}
          onDone={(savedLabel) => {
            setShowAdd(false);
            setNote(`Token agregado. Revisa Clientes: "${savedLabel}" ya debería aparecer ahí.`);
            load();
          }}
        />
      )}

      {deleteTarget && (
        <DeleteTokenModal
          tokenRow={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDone={() => { setDeleteTarget(null); load(); }}
        />
      )}

      {accountsTarget && (
        <AccountsModal tokenRow={accountsTarget} onClose={() => setAccountsTarget(null)} />
      )}
    </>
  );
}
