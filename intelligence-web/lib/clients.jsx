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
        const savedId = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
        const restored = list.find((c) => String(c.id) === savedId);
        setClientState(restored || list[0] || null);
      })
      .catch(() => {
        if (!cancelled) { setClients([]); setClientState(null); }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user]);

  const setClient = useCallback((next) => {
    setClientState(next);
    if (typeof window !== "undefined") {
      if (next) localStorage.setItem(STORAGE_KEY, String(next.id));
      else localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return (
    <ClientCtx.Provider value={{ client, clients, setClient, loading }}>
      {children}
    </ClientCtx.Provider>
  );
}

export const useClient = () => useContext(ClientCtx);
