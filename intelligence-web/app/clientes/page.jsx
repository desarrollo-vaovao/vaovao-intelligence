"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import { useClient } from "@/lib/clients";

export default function ClientesPage() {
  const clientCtx = useClient() || {};
  const { refresh: refreshActiveClient } = clientCtx;
  const [clients, setClients] = useState(null);
  const [err, setErr] = useState("");
  const [showClient, setShowClient] = useState(false);
  const [adFor, setAdFor] = useState(null); // cliente al que se le agrega cuenta
  const [deleteTarget, setDeleteTarget] = useState(null); // cliente a eliminar
  const [editTarget, setEditTarget] = useState(null); // cliente a editar
  const [deleteAccountTarget, setDeleteAccountTarget] = useState(null); // { client, account } a eliminar
  const [editAccountTarget, setEditAccountTarget] = useState(null); // { client, account } a editar
  const [access, setAccess] = useState({}); // resultado de "Probar acceso" por cuenta
  const [testing, setTesting] = useState(null); // id de cuenta que se está probando

  async function load() {
    try { setClients(await api.listClients()); }
    catch (e) { setErr(e.message); }
    // Mantiene sincronizado el cliente activo del ClientProvider (usado en
    // el switcher del Shell) con cualquier cambio hecho aquí.
    if (refreshActiveClient) refreshActiveClient();
  }
  useEffect(() => { load(); }, []);

  async function probar(accountId) {
    setTesting(accountId);
    setAccess((a) => ({ ...a, [accountId]: undefined }));
    try {
      const r = await api.checkAccess(accountId);
      setAccess((a) => ({ ...a, [accountId]: r }));
    } catch (e) {
      setAccess((a) => ({ ...a, [accountId]: { ok: false, detail: e.message } }));
    } finally { setTesting(null); }
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Clientes</h1>
          <p>Marcas que gestionas y sus cuentas publicitarias de Meta.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowClient(true)}>+ Nuevo cliente</button>
      </div>

      {err && <div className="err">{err}</div>}

      {clients === null ? (
        <div className="empty">Cargando…</div>
      ) : clients.length === 0 ? (
        <div className="card empty">
          <h3>Aún no hay clientes</h3>
          <p>Crea el primero para empezar a registrar sus cuentas de Meta.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {clients.map((c) => (
            <div className="card" key={c.id} style={{ padding: 18 }}>
              <div className="row" style={{ marginBottom: c.ad_accounts.length ? 14 : 0 }}>
                <h3 style={{ fontSize: 17 }}>{c.name}</h3>
                <span className={`badge ${c.type === "multi_station" ? "badge-neutral" : "badge-neutral"}`}>
                  {c.type === "multi_station" ? "Multi-estación" : "Único"}
                </span>
                <div className="spacer" />
                <button className="icon-btn" title="Agregar cuenta" aria-label="Agregar cuenta" onClick={() => setAdFor(c)}>
                  <PlusIcon />
                </button>
                <button className="icon-btn" title="Editar cliente" aria-label="Editar cliente" onClick={() => setEditTarget(c)}>
                  <PencilIcon />
                </button>
                <button className="icon-btn icon-btn-danger" title="Eliminar cliente" aria-label="Eliminar cliente" onClick={() => setDeleteTarget(c)}>
                  <TrashIcon />
                </button>
              </div>
              {c.ad_accounts.length > 0 && (
                <table className="table">
                  <thead>
                    <tr><th>Etiqueta</th><th>ID de cuenta</th><th>Destinatarios</th><th>Acceso Meta</th><th></th><th></th></tr>
                  </thead>
                  <tbody>
                    {c.ad_accounts.map((a) => {
                      const res = access[a.id];
                      return (
                        <tr key={a.id}>
                          <td>{a.label}</td>
                          <td className="mono" style={{ fontSize: 13 }}>{a.meta_ad_account_id}</td>
                          <td style={{ color: "var(--muted)", fontSize: 13 }}>
                            {a.recipient_emails.length ? a.recipient_emails.join(", ") : "—"}
                          </td>
                          <td>
                            <div className="row" style={{ gap: 8 }}>
                              <button
                                className="btn btn-ghost"
                                style={{ padding: "5px 10px", fontSize: 13 }}
                                onClick={() => probar(a.id)}
                                disabled={testing === a.id}
                              >
                                {testing === a.id ? "Probando…" : "Probar acceso"}
                              </button>
                              {res && (
                                res.ok
                                  ? <span className="badge badge-signal" title={res.detail}><span className="pulse on" />OK</span>
                                  : <span className="badge badge-warn" title={res.detail}>Sin acceso</span>
                              )}
                            </div>
                            {res && (
                              <div style={{ fontSize: 12, color: res.ok ? "var(--signal)" : "var(--warn)", marginTop: 5 }}>
                                {res.detail}
                              </div>
                            )}
                          </td>
                          <td>
                            <button
                              className="icon-btn"
                              title="Editar cuenta"
                              aria-label="Editar cuenta"
                              onClick={() => setEditAccountTarget({ client: c, account: a })}
                            >
                              <PencilIcon />
                            </button>
                          </td>
                          <td>
                            <button
                              className="icon-btn icon-btn-danger"
                              title="Eliminar cuenta"
                              aria-label="Eliminar cuenta"
                              onClick={() => setDeleteAccountTarget({ client: c, account: a })}
                            >
                              <TrashIcon />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}

      {showClient && (
        <ClientModal
          onClose={() => setShowClient(false)}
          onDone={(client) => { setShowClient(false); load(); setAdFor(client); }}
        />
      )}
      {adFor && <AdAccountModal client={adFor} onClose={() => setAdFor(null)} onDone={() => { setAdFor(null); load(); }} />}
      {editTarget && (
        <EditClientModal
          client={editTarget}
          onClose={() => setEditTarget(null)}
          onDone={() => { setEditTarget(null); load(); }}
        />
      )}
      {deleteTarget && (
        <DeleteClientModal
          client={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDone={() => { setDeleteTarget(null); load(); }}
        />
      )}
      {deleteAccountTarget && (
        <DeleteAdAccountModal
          client={deleteAccountTarget.client}
          account={deleteAccountTarget.account}
          onClose={() => setDeleteAccountTarget(null)}
          onDone={() => { setDeleteAccountTarget(null); load(); }}
        />
      )}
      {editAccountTarget && (
        <EditAdAccountModal
          client={editAccountTarget.client}
          account={editAccountTarget.account}
          onClose={() => setEditAccountTarget(null)}
          onDone={() => { setEditAccountTarget(null); load(); }}
        />
      )}
    </Shell>
  );
}

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
        <p style={{ color: "var(--muted)" }}>
          ¿Eliminar <strong style={{ color: "var(--text)" }}>{client.name}</strong>?
          Esto también elimina{client.ad_accounts.length ? ` sus ${client.ad_accounts.length} cuenta(s) de Meta` : ""} y no se puede deshacer.
        </p>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={busy}>
            {busy ? "Eliminando…" : "Eliminar cliente"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="M15 5l4 4" />
    </svg>
  );
}

function EditClientModal({ client, onClose, onDone }) {
  const [name, setName] = useState(client.name);
  const [type, setType] = useState(client.type);
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    try { await api.updateClient(client.id, { name, type }); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Editar cliente</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Nombre</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ej. Rent a Car GT" />
        </div>
        <div className="field">
          <label>Tipo</label>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="single">Único (una cuenta)</option>
            <option value="multi_station">Multi-estación (varias cuentas/países)</option>
          </select>
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !name.trim()}>
            {busy ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ClientModal({ onClose, onDone }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("single");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    try { const client = await api.createClient({ name, type }); onDone(client); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Nuevo cliente</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Nombre</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ej. Rent a Car GT" />
        </div>
        <div className="field">
          <label>Tipo</label>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="single">Único (una cuenta)</option>
            <option value="multi_station">Multi-estación (varias cuentas/países)</option>
          </select>
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !name.trim()}>
            {busy ? "Guardando…" : "Crear cliente"}
          </button>
        </div>
      </div>
    </div>
  );
}

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

function DeleteAdAccountModal({ client, account, onClose, onDone }) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function confirmDelete() {
    setErr(""); setBusy(true);
    try { await api.deleteAdAccount(client.id, account.id); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Eliminar cuenta</h2>
        {err && <div className="err">{err}</div>}
        <p style={{ color: "var(--muted)" }}>
          ¿Eliminar la cuenta <strong style={{ color: "var(--text)" }}>{account.label}</strong>
          {" "}(<span className="mono">{account.meta_ad_account_id}</span>) de {client.name}?
          Esta acción no se puede deshacer.
        </p>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={busy}>
            {busy ? "Eliminando…" : "Eliminar cuenta"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditAdAccountModal({ client, account, onClose, onDone }) {
  const [label, setLabel] = useState(account.label);
  const [accId, setAccId] = useState(account.meta_ad_account_id);
  const [emails, setEmails] = useState(account.recipient_emails.join(", "));
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    const recipient_emails = emails.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      await api.updateAdAccount(client.id, account.id, { label, meta_ad_account_id: accId, recipient_emails });
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Editar cuenta — {client.name}</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Etiqueta</label>
          <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ej. Guatemala, Principal" />
        </div>
        <div className="field">
          <label>ID de cuenta publicitaria</label>
          <input className="input mono" value={accId} onChange={(e) => setAccId(e.target.value)} placeholder="act_1234567890" />
        </div>
        <div className="field">
          <label>Correos que reciben el reporte (separados por coma)</label>
          <input className="input" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="cliente@correo.com, traf@vaovao.co" />
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !label.trim() || !accId.trim()}>
            {busy ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdAccountModal({ client, onClose, onDone }) {
  const [label, setLabel] = useState("");
  const [accId, setAccId] = useState("");
  const [emails, setEmails] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    const recipient_emails = emails.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      await api.addAdAccount(client.id, { label, meta_ad_account_id: accId, recipient_emails });
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Cuenta de Meta — {client.name}</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Etiqueta</label>
          <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ej. Guatemala, Principal" />
        </div>
        <div className="field">
          <label>ID de cuenta publicitaria</label>
          <input className="input mono" value={accId} onChange={(e) => setAccId(e.target.value)} placeholder="act_1234567890" />
        </div>
        <div className="field">
          <label>Correos que reciben el reporte (separados por coma)</label>
          <input className="input" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="cliente@correo.com, traf@vaovao.co" />
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !label.trim() || !accId.trim()}>
            {busy ? "Guardando…" : "Agregar cuenta"}
          </button>
        </div>
      </div>
    </div>
  );
}