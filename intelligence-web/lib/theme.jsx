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

// Compartido con app/ajustes/page.jsx, que es el único lugar donde la
// persona elige el tema (ver decisión de mover el control del header a
// Ajustes > Cuenta).
export const THEME_OPTIONS = [
  {
    value: "light", label: "Claro",
    icon: (
      <>
        <circle cx="12" cy="12" r="4.2"></circle>
        <path d="M12 2.5v2.4M12 19.1v2.4M4.6 4.6l1.7 1.7M17.7 17.7l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.6 19.4l1.7-1.7M17.7 6.3l1.7-1.7"></path>
      </>
    ),
  },
  {
    value: "dark", label: "Oscuro",
    icon: <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.8 6.8 0 0 0 10.5 10.5Z"></path>,
  },
  {
    value: "system", label: "Sistema",
    icon: (
      <>
        <rect x="3" y="4.5" width="18" height="12" rx="1.8"></rect>
        <path d="M8.5 20h7M12 16.5V20"></path>
      </>
    ),
  },
];
