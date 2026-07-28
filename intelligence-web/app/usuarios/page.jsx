"use client";
import { useEffect, useState } from "react";
import Shell from "@/lib/Shell";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function UsuariosPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState(null);
  const [err, setErr] = useState("");
  const [showNew, setShowNew] = useState(false);

  async function load() {
    try { setUsers(await api.listUsers()); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function toggle(u) {
    setErr("");
    try { await api.updateUser(u.id, { is_active: !u.is_active }); load(); }
    catch (e) { setErr(e.message); }
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Usuarios</h1>
          <p>Quién tiene acceso a la consola de tu organización.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNew(true)}>+ Invitar usuario</button>
      </div>

      {err && <div className="err">{err}</div>}

      <div className="card" style={{ overflow: "hidden" }}>
        {users === null ? (
          <div className="empty">Cargando…</div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Nombre</th><th>Correo</th><th>Rol</th><th>Estado</th><th></th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}{u.id === me?.id && <span style={{ color: "var(--muted)" }}> · tú</span>}</td>
                  <td className="mono" style={{ fontSize: 13 }}>{u.email}</td>
                  <td><span className="badge badge-role">{u.role}</span></td>
                  <td>
                    {u.is_active
                      ? <span className="badge badge-signal"><span className="pulse on" />Activo</span>
                      : <span className="badge badge-warn">Inactivo</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {u.id !== me?.id && (
                      <button className={`btn ${u.is_active ? "btn-danger" : "btn-ghost"}`} onClick={() => toggle(u)}>
                        {u.is_active ? "Desactivar" : "Reactivar"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showNew && <NewUserModal isOwner={me?.role === "owner"} onClose={() => setShowNew(false)} onDone={() => { setShowNew(false); load(); }} />}
    </Shell>
  );
}

function NewUserModal({ isOwner, onClose, onDone }) {
  const [full_name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("member");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save() {
    setErr(""); setBusy(true);
    try { await api.createUser({ full_name, email, password, role }); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Invitar usuario</h2>
        {err && <div className="err">{err}</div>}
        <div className="field"><label>Nombre</label>
          <input className="input" value={full_name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label>Correo</label>
          <input className="input mono" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label>Contraseña temporal (mín. 8)</label>
          <input className="input" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        <div className="field"><label>Rol</label>
          <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">Member — uso normal</option>
            <option value="admin">Admin — gestiona clientes y usuarios</option>
            {isOwner && <option value="owner">Owner — control total</option>}
          </select>
        </div>
        <div className="row" style={{ marginTop: 18 }}>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !full_name.trim() || !email.trim() || password.length < 8}>
            {busy ? "Creando…" : "Crear usuario"}
          </button>
        </div>
      </div>
    </div>
  );
}
