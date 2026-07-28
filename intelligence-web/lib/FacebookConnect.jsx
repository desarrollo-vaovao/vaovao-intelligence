"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function FacebookConnect() {
  const [status, setStatus] = useState(null);
  const [data, setData] = useState(null); // {accounts, businesses, warnings}
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try { setStatus(await api.fbStatus()); }
    catch (e) { setErr(e.message); }
  }

  useEffect(() => {
    load();
    // Mensaje de regreso del login de Facebook (?fb=ok / ?fb=error)
    const p = new URLSearchParams(window.location.search).get("fb");
    if (p === "ok") setNote("Facebook conectado correctamente.");
    if (p === "error") setErr("No se pudo conectar con Facebook. Intenta de nuevo.");
    if (p) window.history.replaceState({}, "", window.location.pathname);
  }, []);

  async function connect() {
    setErr(""); setBusy(true);
    try {
      const { auth_url } = await api.fbLogin();
      window.location.href = auth_url; // manda al login de Meta
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  async function verAccounts() {
    setErr(""); setBusy(true);
    try { setData(await api.fbAccounts()); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    setErr(""); setBusy(true);
    try { await api.fbDisconnect(); setData(null); await load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const connected = status?.connected;

  return (
    <div className="card" style={{ padding: 22, maxWidth: 620, marginBottom: 22, marginLeft: "auto", marginRight: "auto" }}>
      <div className="row" style={{ marginBottom: 14 }}>
        <span className={`pulse ${connected ? "on" : "off"}`} />
        <h3 style={{ fontSize: 16 }}>
          {status === null ? "Comprobando…" : connected ? `Conectado como ${status.fb_name}` : "Conectar con Facebook"}
        </h3>
        <div className="spacer" />
        {connected && <span className="badge badge-signal">Tu sesión</span>}
      </div>

      {note && <div className="notice" style={{ marginBottom: 14 }}><div>{note}</div></div>}
      {err && <div className="err">{err}</div>}

      {!connected ? (
        <>
          <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 0 }}>
            Conecta tu cuenta de Facebook para usar <b>tu propio acceso</b> a las cuentas
            publicitarias que ya administras. Así no se depende de una sola cuenta central.
          </p>
          <button className="btn btn-primary" onClick={connect} disabled={busy}>
            {busy ? "Redirigiendo…" : "Conectar con Facebook"}
          </button>
        </>
      ) : (
        <>
          {status.expires_at && (
            <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Acceso válido hasta <span className="mono">{status.expires_at.slice(0, 10)}</span>
            </div>
          )}
          <div className="row" style={{ gap: 10, marginBottom: data ? 14 : 0 }}>
            <button className="btn btn-ghost" onClick={verAccounts} disabled={busy}>
              {busy ? "Cargando…" : "Ver mis cuentas"}
            </button>
            <button className="btn btn-danger" onClick={disconnect} disabled={busy}>Desconectar</button>
          </div>

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
                  Tu sesión no tiene cuentas publicitarias accesibles.
                </div>
              ) : (
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
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}