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
  const [refreshing, setRefreshing] = useState(null); // id de cuenta refrescando nombre

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

  async function refrescarNombre(clientId, accountId) {
    setErr(""); setRefreshing(accountId);
    try {
      await api.refreshAdAccountName(clientId, accountId);
      await load();
    } catch (e) { setErr(e.message); }
    finally { setRefreshing(null); }
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Clientes</h1>
          <p>Portafolios que gestionas y sus activos comerciales de Meta.</p>
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
                <span className="badge badge-neutral">
                  {c.ad_accounts.length} activo{c.ad_accounts.length === 1 ? "" : "s"}
                </span>
                <div className="spacer" />
                <button className="icon-btn" title="Agregar activo" aria-label="Agregar activo" onClick={() => setAdFor(c)}>
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
                    <tr><th>Activo comercial</th><th>ID de cuenta</th><th>Destinatarios</th><th>Acceso Meta</th><th></th><th></th></tr>
                  </thead>
                  <tbody>
                    {c.ad_accounts.map((a) => {
                      const res = access[a.id];
                      return (
                        <tr key={a.id}>
                          <td>
                            {a.label}
                            <button
                              className="btn btn-ghost"
                              style={{ padding: "3px 8px", fontSize: 11.5, marginLeft: 8 }}
                              title="Volver a traer el nombre desde Meta"
                              onClick={() => refrescarNombre(c.id, a.id)}
                              disabled={refreshing === a.id}
                            >
                              {refreshing === a.id ? "…" : "Actualizar nombre"}
                            </button>
                          </td>
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
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    try { await api.updateClient(client.id, { name }); onDone(); }
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
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    try { const client = await api.createClient({ name }); onDone(client); }
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
        <h2>Eliminar activo</h2>
        {err && <div className="err">{err}</div>}
        <p style={{ color: "var(--muted)" }}>
          ¿Eliminar el activo <strong style={{ color: "var(--text)" }}>{account.label}</strong>
          {" "}(<span className="mono">{account.meta_ad_account_id}</span>) de {client.name}?
          Esta acción no se puede deshacer.
        </p>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-danger" onClick={confirmDelete} disabled={busy}>
            {busy ? "Eliminando…" : "Eliminar activo"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditAdAccountModal({ client, account, onClose, onDone }) {
  const [accId, setAccId] = useState(account.meta_ad_account_id);
  const [emails, setEmails] = useState(account.recipient_emails.join(", "));
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const idCambio = accId.trim() !== account.meta_ad_account_id;
  async function save() {
    setErr(""); setBusy(true);
    const recipient_emails = emails.split(",").map((s) => s.trim()).filter(Boolean);
    // El ID solo se manda si cambió: mandarlo igual dispararía una llamada a
    // Meta para reheredar un nombre que ya tenemos.
    const body = { recipient_emails };
    if (idCambio) body.meta_ad_account_id = accId;
    try {
      await api.updateAdAccount(client.id, account.id, body);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Editar activo — {client.name}</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Activo comercial</label>
          <input className="input" value={account.label} disabled readOnly />
          <NombreHeredadoNota />
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
          <button className="btn btn-primary" onClick={save} disabled={busy || !accId.trim()}>
            {busy ? (idCambio ? "Verificando en Meta…" : "Guardando…") : "Guardar cambios"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdAccountModal({ client, onClose, onDone }) {
  const [accId, setAccId] = useState("");
  const [emails, setEmails] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  // Lista de cuentas de Meta para elegir en vez de copiar act_XXXXXXXXXX a
  // mano. Es un plus, no un requisito: si falla o viene vacía, el campo de
  // abajo sigue aceptando el ID escrito directamente.
  const [metaAccounts, setMetaAccounts] = useState(null); // null = cargando
  const [metaError, setMetaError] = useState("");
  const [modoManual, setModoManual] = useState(false);

  useEffect(() => {
    api.listMetaAdAccounts()
      .then((r) => setMetaAccounts(r.accounts || []))
      .catch((e) => { setMetaAccounts([]); setMetaError(e.message); });
  }, []);

  async function save() {
    setErr(""); setBusy(true);
    const recipient_emails = emails.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      await api.addAdAccount(client.id, { meta_ad_account_id: accId, recipient_emails });
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const hayOpciones = Array.isArray(metaAccounts) && metaAccounts.length > 0;
  const mostrarSelect = hayOpciones && !modoManual;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Activo comercial — {client.name}</h2>
        {err && <div className="err">{err}</div>}
        <div className="field">
          <label>Cuenta publicitaria</label>
          {metaAccounts === null ? (
            <input className="input" value="Cargando cuentas de Meta…" disabled readOnly />
          ) : mostrarSelect ? (
            <select className="input mono" value={accId} onChange={(e) => setAccId(e.target.value)}>
              <option value="">— Selecciona una cuenta —</option>
              {metaAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name ? `${a.name} — ${a.id}` : a.id}
                </option>
              ))}
            </select>
          ) : (
            <input className="input mono" value={accId} onChange={(e) => setAccId(e.target.value)} placeholder="act_1234567890" />
          )}
          {hayOpciones && (
            <button
              type="button"
              onClick={() => setModoManual((v) => !v)}
              style={{
                background: "none", border: "none", padding: 0, marginTop: 6,
                color: "var(--orange)", fontSize: 12, cursor: "pointer",
              }}
            >
              {modoManual ? "Elegir de la lista" : "No la encuentro, escribir el ID a mano"}
            </button>
          )}
          {metaAccounts !== null && !hayOpciones && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
              {metaError || "No se encontraron cuentas conectadas a Meta — escribe el ID directamente."}
            </div>
          )}
          <NombreHeredadoNota />
        </div>
        <div className="field">
          <label>Correos que reciben el reporte (separados por coma)</label>
          <input className="input" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="cliente@correo.com, traf@vaovao.co" />
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !accId.trim()}>
            {busy ? "Verificando en Meta…" : "Agregar activo"}
          </button>
        </div>
      </div>
    </div>
  );
}

function NombreHeredadoNota() {
  return (
    <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
      El nombre del activo se toma automáticamente de Meta. Si la cuenta no se
      puede leer con las credenciales conectadas, no se guarda.
    </div>
  );
}