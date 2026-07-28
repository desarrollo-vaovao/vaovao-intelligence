"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/clientes" : "/login");
  }, [user, loading, router]);
  return <div style={{ display: "grid", placeItems: "center", height: "100vh", color: "var(--muted)" }}>Cargando…</div>;
}
