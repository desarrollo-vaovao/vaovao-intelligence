"use client";
import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

const ClientCtx = createContext(null);
const STORAGE_KEY = "vv_active_client";

export function ClientProvider({ children }) {
  const { user } = useAuth();
  const [clients, setClients] = useState(null);
  const [client, setClientState] = useState(null);
  const [loading, setLoading] = useState(true);

  // Restaura el cliente guardado en localStorage si sigue en la lista,
  // o cae al primero de la lista (o null si está vacía). Compartido entre
  // el fetch inicial y refresh(), para que ambos manejen igual el caso de
  // un cliente activo que ya no existe (p.ej. fue eliminado).
  const restoreOrFallback = useCallback((list) => {
    const savedId = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const restored = list.find((c) => String(c.id) === savedId);
    const next = restored || list[0] || null;
    setClientState(next);
    return next;
  }, []);

  useEffect(() => {
    if (!user) {
      setClients(null);
      setClientState(null);
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
        if (!cancelled) { setClients([]); setClientState(null); }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user, restoreOrFallback]);

  const refresh = useCallback(async () => {
    if (!user) return null;
    try {
      const list = await api.listClients();
      setClients(list);
      const currentId = client ? String(client.id) : null;
      if (currentId && list.some((c) => String(c.id) === currentId)) {
        // El cliente activo sigue existiendo: mantenlo (con datos frescos).
        const fresh = list.find((c) => String(c.id) === currentId);
        setClientState(fresh);
      } else {
        // El cliente activo ya no existe (p.ej. fue eliminado): cae al
        // primero de la lista, o null si quedó vacía.
        restoreOrFallback(list);
      }
      return list;
    } catch {
      return null;
    }
  }, [user, client, restoreOrFallback]);

  const setClient = useCallback((next) => {
    setClientState(next);
    if (typeof window !== "undefined") {
      if (next) localStorage.setItem(STORAGE_KEY, String(next.id));
      else localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return (
    <ClientCtx.Provider value={{ client, clients, setClient, loading, refresh }}>
      {children}
    </ClientCtx.Provider>
  );
}

export const useClient = () => useContext(ClientCtx);
