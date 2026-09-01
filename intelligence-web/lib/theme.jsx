"use client";
import { createContext, useContext, useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "vv_theme";
const ThemeCtx = createContext(null);

// Debe coincidir EXACTO con el script inline de layout.jsx (ver
// THEME_BOOT_SCRIPT): ese script resuelve y pinta el tema correcto antes
// de que React hidrate, para no mostrar un flash del tema equivocado. Si
// la lógica de acá y la del script divergen, ese flash vuelve.
function resolveTheme(preference) {
  if (preference === "light" || preference === "dark") return preference;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Inyectado como <script> síncrono ANTES de que se pinte la página (ver
// app/layout.jsx): sin esto, el <html> nace sin data-theme, el navegador
// pinta con la paleta oscura por defecto de globals.css, y recién cuando
// React hidrata y corre el efecto de abajo se corrige — ese parpadeo es
// visible sobre todo con preference="light" o sistema-en-modo-claro.
export const THEME_BOOT_SCRIPT = `(function(){try{
  var p = localStorage.getItem("${STORAGE_KEY}") || "system";
  var t = (p === "light" || p === "dark") ? p : (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", t);
}catch(e){}})();`;

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState("system");
  const [resolved, setResolved] = useState("dark");

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) || "system";
    setPreference(stored);
    setResolved(resolveTheme(stored));
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
  }, [resolved]);

  // Con preference="system", si la persona cambia el tema del SISTEMA
  // operativo mientras la pestaña sigue abierta, la app se actualiza sola
  // en vez de quedarse pegada al valor que tenía al cargar.
  useEffect(() => {
    if (preference !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(resolveTheme("system"));
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [preference]);

  const setTheme = useCallback((next) => {
    localStorage.setItem(STORAGE_KEY, next);
    setPreference(next);
    setResolved(resolveTheme(next));
  }, []);

  return (
    <ThemeCtx.Provider value={{ preference, resolved, setTheme }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export const useTheme = () => useContext(ThemeCtx);
