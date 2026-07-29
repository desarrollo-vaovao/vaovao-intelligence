"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import FacebookConnect from "@/lib/FacebookConnect";

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

export default function ConexionPage() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");

  const [appId, setAppId] = useState("");
  const [savingAppId, setSavingAppId] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [accountsTarget, setAccountsTarget] = useState(null);

  async function load() {
    try { const s = await api.getMeta(); setStatus(s); setAppId(s.meta_app_id || ""); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function saveAppId() {
    setErr(""); setSavingAppId(true);
    try { await api.setMetaAppId({ meta_app_id: appId }); await load(); }
    catch (e) { setErr(e.message); }
    finally { setSavingAppId(false); }
  }

  const connected = status?.configured;
  const tokens = status?.tokens || [];

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Conexión Meta</h1>
          <p>Conecta tu Facebook (recomendado) o usa tokens de System User centrales.</p>
        </div>
      </div>

      <FacebookConnect />

      <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: "1px", margin: "26px auto 12px", maxWidth: 620 }}>
        Alternativa — tokens centrales (System User)
      </div>

      {err && <div className="err" style={{ maxWidth: 620, margin: "0 auto 14px" }}>{err}</div>}
      {note && <div className="notice" style={{ maxWidth: 620, margin: "0 auto 14px" }}><div>{note}</div></div>}

      <div className="card" style={{ padding: 22, maxWidth: 620, margin: "0 auto 20px" }}>
        <div className="row" style={{ marginBottom: 14 }}>
          <span className={`pulse ${connected ? "on" : "off"}`} />
          <h3 style={{ fontSize: 16 }}>
            {status === null ? "Comprobando…" : connected ? "Conectado a Meta" : "Sin conectar"}
          </h3>
          <div className="spacer" />
          {connected && <span className="badge badge-signal">Listo para reportes</span>}
        </div>

        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
          Un solo System User no puede ver activos de un portafolio que no es el suyo — por eso
          puede haber varios tokens, uno por portafolio. Se guardan cifrados y nunca se muestran
          completos.
        </p>

        <div className="field" style={{ marginBottom: 0 }}>
          <label>App ID (la misma app de Meta para todos los tokens)</label>
          <div className="row" style={{ gap: 8 }}>
            <input className="input mono" value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="1234567890" />
            <button className="btn btn-ghost" onClick={saveAppId} disabled={savingAppId || !appId.trim()}>
              {savingAppId ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 940, margin: "0 auto" }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--muted)" }}>
            Portafolios{tokens.length > 0 ? ` (${tokens.length})` : ""}
          </label>
          <div className="spacer" />
          <button className="btn btn-primary" onClick={() => setShowAdd(true)} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <PlusIcon /> Agregar portafolio
          </button>
        </div>

        {tokens.length === 0 ? (
          <div className="card" style={{ padding: 28, textAlign: "center", color: "var(--muted)" }}>
            Todavía no hay tokens centrales. Cada uno representa un portafolio comercial de Meta.
          </div>
        ) : (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 12,
          }}>
            {tokens.map((t) => (
              <div key={t.id} className="card" style={{ padding: 16, background: "var(--surface2)" }}>
                <div className="row" style={{ marginBottom: 8, gap: 8 }}>
                  <span className="pulse on" />
                  <strong style={{ fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.label}</strong>
                  <div className="spacer" />
                  <button
                    className="icon-btn icon-btn-danger"
                    title="Eliminar token"
                    aria-label="Eliminar token"
                    onClick={() => setDeleteTarget(t)}
                  >
                    <TrashIcon />
                  </button>
                </div>
                <div className="mono" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 12 }}>{t.token_masked}</div>
                <button className="btn btn-ghost" style={{ width: "100%", fontSize: 13 }} onClick={() => setAccountsTarget(t)}>
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
    </Shell>
  );
}
