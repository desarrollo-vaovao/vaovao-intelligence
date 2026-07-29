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

export default function ConexionPage() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");

  const [appId, setAppId] = useState("");
  const [savingAppId, setSavingAppId] = useState(false);

  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [addingToken, setAddingToken] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

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

  async function addToken() {
    setErr(""); setAddingToken(true);
    try {
      await api.addMetaToken({ label, system_user_token: token });
      setLabel(""); setToken(""); await load();
    } catch (e) { setErr(e.message); }
    finally { setAddingToken(false); }
  }

  async function removeToken(id) {
    setErr(""); setDeletingId(id);
    try { await api.deleteMetaToken(id); await load(); }
    catch (e) { setErr(e.message); }
    finally { setDeletingId(null); }
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

      <div className="card" style={{ padding: 22, maxWidth: 620, margin: "0 auto" }}>
        <div className="row" style={{ marginBottom: 18 }}>
          <span className={`pulse ${connected ? "on" : "off"}`} />
          <h3 style={{ fontSize: 16 }}>
            {status === null ? "Comprobando…" : connected ? "Conectado a Meta" : "Sin conectar"}
          </h3>
          <div className="spacer" />
          {connected && <span className="badge badge-signal">Listo para reportes</span>}
        </div>

        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 0 }}>
          Cada portafolio comercial independiente de Meta (ej. "Vao Vao", "Menos Pausa")
          necesita su propio System User Token — un solo System User no puede ver activos
          de un portafolio que no es el suyo. Se guardan cifrados y nunca se muestran completos.
        </p>

        <div className="field">
          <label>App ID (la misma app de Meta para todos los tokens)</label>
          <div className="row" style={{ gap: 8 }}>
            <input className="input mono" value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="1234567890" />
            <button className="btn btn-ghost" onClick={saveAppId} disabled={savingAppId || !appId.trim()}>
              {savingAppId ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>

        <div className="row" style={{ marginBottom: tokens.length ? 8 : 0, marginTop: 18 }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--muted)" }}>Tokens centrales</label>
        </div>

        {tokens.length > 0 && (
          <table className="table" style={{ marginBottom: 14 }}>
            <thead>
              <tr><th>Portafolio</th><th>Token</th><th></th></tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr key={t.id}>
                  <td>{t.label}</td>
                  <td className="mono" style={{ fontSize: 13, color: "var(--muted)" }}>{t.token_masked}</td>
                  <td>
                    <button
                      className="icon-btn icon-btn-danger"
                      title="Eliminar token"
                      aria-label="Eliminar token"
                      onClick={() => removeToken(t.id)}
                      disabled={deletingId === t.id}
                    >
                      <TrashIcon />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="field">
          <label>Portafolio (etiqueta para identificarlo)</label>
          <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ej. Vao Vao, Menos Pausa" />
        </div>
        <div className="field">
          <label>System User Token</label>
          <input className="input mono" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="EAAG…" />
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <div className="spacer" />
          <button
            className="btn btn-primary"
            onClick={addToken}
            disabled={addingToken || !label.trim() || token.length < 10}
          >
            {addingToken ? "Agregando…" : "Agregar token"}
          </button>
        </div>
      </div>
    </Shell>
  );
}
