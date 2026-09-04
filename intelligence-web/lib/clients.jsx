"use client";
import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

const ClientCtx = createContext(null);
const STORAGE_KEY = "vv_active_account";

// Aplana clients -> activos comerciales (cuentas publicitarias): un
// cliente con un solo activo se sigue viendo por su propio nombre (nada
// cambia en el caso normal), pero uno con VARIOS activos (varias
// estaciones/cuentas, ej. OLR) pasa a mostrar cada activo como su propia
// entrada navegable. Antes, Resumen y Leads se quedaban con "el primer
// activo del cliente" o mezclaban los datos de todos bajo un mismo
// cliente — con esto cada activo es su propia unidad, sin ambigüedad.
function flattenAccounts(clients) {
  const out = [];
  for (const c of clients || []) {
    const accs = c.ad_accounts || [];
    for (const a of accs) {
      out.push({ ...a, displayName: accs.length > 1 ? a.label : c.name, client: c });
    }
  }
  return out;
}

export function ClientProvider({ children }) {
  const { user } = useAuth();
  const [clients, setClients] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [account, setAccountState] = useState(null);
  const [loading, setLoading] = useState(true);

  // Restaura el activo guardado en localStorage si sigue en la lista, o
  // cae al primero (o null si está vacía). Compartido entre el fetch
  // inicial y refresh(), para que ambos manejen igual el caso de un
  // activo que ya no existe (p.ej. fue eliminado).
  const restoreOrFallback = useCallback((list) => {
    const flat = flattenAccounts(list);
    const savedId = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const restored = flat.find((a) => String(a.id) === savedId);
    const next = restored || flat[0] || null;
    setAccounts(flat);
    setAccountState(next);
    return next;
  }, []);

  useEffect(() => {
    if (!user) {
      setClients(null);
      setAccounts([]);
      setAccountState(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api.listClients()
      .then((list) => {
        if (cancelled) return;
        setClients(list);
        restoreOrFallback(list);
      })
      .catch(() => {
        if (!cancelled) { setClients([]); setAccounts([]); setAccountState(null); }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user, restoreOrFallback]);

  const refresh = useCallback(async () => {
    if (!user) return null;
    try {
      const list = await api.listClients();
      setClients(list);
      const flat = flattenAccounts(list);
      const currentId = account ? String(account.id) : null;
      if (currentId && flat.some((a) => String(a.id) === currentId)) {
        // El activo sigue existiendo: mantenlo (con datos frescos).
        setAccounts(flat);
        setAccountState(flat.find((a) => String(a.id) === currentId));
      } else {
        // El activo ya no existe (p.ej. se eliminó): cae al primero de la
        // lista, o null si quedó vacía.
        restoreOrFallback(list);
      }
      return list;
    } catch {
      return null;
    }
  }, [user, account, restoreOrFallback]);

  const setAccount = useCallback((next) => {
    setAccountState(next);
    if (typeof window !== "undefined") {
      if (next) localStorage.setItem(STORAGE_KEY, String(next.id));
      else localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return (
    <ClientCtx.Provider
      value={{
        // `client`: el CLIENTE dueño del activo activo — sigue existiendo
        // para lo poco que de verdad solo necesita datos de cliente (ej.
        // Ajustes mostrando en qué moneda reporta). La navegación real
        // (Resumen, Reportes, Leads) usa `account`/`accounts` de aquí en
        // adelante, nunca `client`.
        client: account?.client || null,
        clients,
        account,
        accounts,
        setAccount,
        loading,
        refresh,
      }}
    >
      {children}
    </ClientCtx.Provider>
  );
}

export const useClient = () => useContext(ClientCtx);
