"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import FacebookConnect from "@/lib/FacebookConnect";

export default function ConexionPage() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");
  const [appId, setAppId] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  async function load() {
    try { const s = await api.getMeta(); setStatus(s); setAppId(s.meta_app_id || ""); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function save() {
    setErr(""); setBusy(true);
    try {
      await api.setMeta({ meta_app_id: appId, system_user_token: token });
      setToken(""); setEditing(false); load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    setErr(""); setBusy(true);
    try { await api.clearMeta(); setToken(""); load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const connected = status?.configured;

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Conexión Meta</h1>
          <p>Conecta tu Facebook (recomendado) o usa un token de System User central.</p>
        </div>
      </div>

      <FacebookConnect />

      <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted2)", textTransform: "uppercase", letterSpacing: "1px", margin: "26px auto 12px", maxWidth: 620 }}>
        Alternativa — token central (System User)
      </div>

      {err && <div className="err">{err}</div>}

      <div className="card" style={{ padding: 22, maxWidth: 620, margin: "0 auto" }}>
        <div className="row" style={{ marginBottom: 18 }}>
          <span className={`pulse ${connected ? "on" : "off"}`} />
          <h3 style={{ fontSize: 16 }}>
            {status === null ? "Comprobando…" : connected ? "Conectado a Meta" : "Sin conectar"}
          </h3>
          <div className="spacer" />
          {connected && !editing && (
            <span className="badge badge-signal">Listo para reportes</span>
          )}
        </div>

        {connected && !editing ? (
          <>
            <div className="field">
              <label>App ID</label>
              <div className="mono" style={{ fontSize: 14 }}>{status.meta_app_id}</div>
            </div>
            <div className="field">
              <label>Token (oculto)</label>
              <div className="mono" style={{ fontSize: 14, color: "var(--muted)" }}>{status.token_masked}</div>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn btn-ghost" onClick={() => setEditing(true)}>Reemplazar token</button>
              <button className="btn btn-danger" onClick={disconnect} disabled={busy}>Desconectar</button>
            </div>
          </>
        ) : (
          <>
            <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 0 }}>
              Genera el token de System User en el Business Manager de VaoVao con permiso <span className="mono">ads_read</span>.
              Se guarda cifrado y nunca se vuelve a mostrar completo.
            </p>
            <div className="field">
              <label>App ID</label>
              <input className="input mono" value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="1234567890" />
            </div>
            <div className="field">
              <label>System User Token</label>
              <input className="input mono" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="EAAG…" />
            </div>
            <div className="row" style={{ marginTop: 6 }}>
              {editing && <button className="btn btn-ghost" onClick={() => { setEditing(false); setToken(""); }}>Cancelar</button>}
              <div className="spacer" />
              <button className="btn btn-primary" onClick={save} disabled={busy || !appId.trim() || token.length < 10}>
                {busy ? "Guardando…" : "Guardar conexión"}
              </button>
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}