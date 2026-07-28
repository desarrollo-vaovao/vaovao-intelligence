"use client";
import { useState, useEffect, useRef } from "react";

const MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const MESES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun",
                     "jul", "ago", "sep", "oct", "nov", "dic"];
const DIAS = ["L", "M", "X", "J", "V", "S", "D"];

const META_BLUE = "#1877F2";

// ── Utilidades de fecha ──
export const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const parseISO = (s) => {
  if (!s) return null;
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

const sameDay = (a, b) =>
  a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

const lastDay = (y, m) => new Date(y, m + 1, 0).getDate();

// ── Períodos automáticos ──
export function periodoMensual(offset = 0) {
  const hoy = new Date();
  const d = new Date(hoy.getFullYear(), hoy.getMonth() + offset, 1);
  return { from: iso(d), to: iso(new Date(d.getFullYear(), d.getMonth(), lastDay(d.getFullYear(), d.getMonth()))) };
}

export function periodoQuincenal(offset = 0) {
  const hoy = new Date();
  let y = hoy.getFullYear(), m = hoy.getMonth();
  // 0 = quincena actual, -1 = la anterior
  let primera = hoy.getDate() <= 15;
  for (let i = 0; i < Math.abs(offset); i++) {
    if (primera) { m -= 1; if (m < 0) { m = 11; y -= 1; } primera = false; }
    else { primera = true; }
  }
  return primera
    ? { from: iso(new Date(y, m, 1)), to: iso(new Date(y, m, 15)) }
    : { from: iso(new Date(y, m, 16)), to: iso(new Date(y, m, lastDay(y, m))) };
}

export function formatoCorto(from, to) {
  const a = parseISO(from), b = parseISO(to);
  if (!a || !b) return "Selecciona el período";
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear())
    return `${a.getDate()} – ${b.getDate()} ${MESES_CORTO[b.getMonth()]} ${b.getFullYear()}`;
  return `${a.getDate()} ${MESES_CORTO[a.getMonth()]} – ${b.getDate()} ${MESES_CORTO[b.getMonth()]} ${b.getFullYear()}`;
}

// ── Componente ──
export default function DateRangePicker({ from, to, onChange }) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(() => parseISO(from) || new Date());
  const [pendingStart, setPendingStart] = useState(null);
  const [hover, setHover] = useState(null);
  const boxRef = useRef(null);

  useEffect(() => {
    function onDoc(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) {
        setOpen(false); setPendingStart(null);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => { if (from) setCursor(parseISO(from)); }, [from]);

  const start = parseISO(from), end = parseISO(to);

  function pick(d) {
    if (!pendingStart) { setPendingStart(d); setHover(null); return; }
    const a = pendingStart < d ? pendingStart : d;
    const b = pendingStart < d ? d : pendingStart;
    onChange(iso(a), iso(b));
    setPendingStart(null);
    setOpen(false);
  }

  function preset(range) { onChange(range.from, range.to); setOpen(false); setPendingStart(null); }

  // Rango a pintar: el confirmado, o el que se está armando con el mouse
  const rangeA = pendingStart || start;
  const rangeB = pendingStart ? hover : end;
  const lo = rangeA && rangeB ? (rangeA < rangeB ? rangeA : rangeB) : null;
  const hi = rangeA && rangeB ? (rangeA < rangeB ? rangeB : rangeA) : null;

  // Grilla del mes (semana empieza lunes)
  const y = cursor.getFullYear(), m = cursor.getMonth();
  const primerDia = (new Date(y, m, 1).getDay() + 6) % 7;
  const total = lastDay(y, m);
  const celdas = [...Array(primerDia).fill(null), ...Array.from({ length: total }, (_, i) => new Date(y, m, i + 1))];

  const PRESETS = [
    ["Quincena actual", periodoQuincenal(0)],
    ["Quincena anterior", periodoQuincenal(-1)],
    ["Este mes", periodoMensual(0)],
    ["Mes pasado", periodoMensual(-1)],
  ];

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="input"
        onClick={() => setOpen((o) => !o)}
        style={{ textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}
      >
        <span style={{ color: from ? "var(--text)" : "var(--muted2)" }}>{formatoCorto(from, to)}</span>
        <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 10 }}>▾</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 40,
            background: "var(--surface)", border: "1px solid var(--border2)",
            borderRadius: "var(--radius)", padding: 14, display: "flex", gap: 14,
            boxShadow: "0 16px 40px rgba(0,0,0,.55)",
          }}
        >
          {/* Atajos */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 130,
                        borderRight: "1px solid var(--border)", paddingRight: 12 }}>
            {PRESETS.map(([label, range]) => {
              const activo = from === range.from && to === range.to;
              return (
                <button
                  key={label}
                  type="button"
                  onClick={() => preset(range)}
                  style={{
                    textAlign: "left", padding: "7px 9px", borderRadius: "var(--radius-sm)",
                    fontFamily: "inherit", fontSize: 11, cursor: "pointer", border: "none",
                    background: activo ? "rgba(24,119,242,.14)" : "transparent",
                    color: activo ? META_BLUE : "var(--muted)",
                    fontWeight: activo ? 500 : 400,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Calendario */}
          <div>
            <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
              <button type="button" onClick={() => setCursor(new Date(y, m - 1, 1))}
                style={navBtn}>‹</button>
              <div style={{ flex: 1, textAlign: "center", fontSize: 12, fontWeight: 500 }}>
                {MESES[m]} {y}
              </div>
              <button type="button" onClick={() => setCursor(new Date(y, m + 1, 1))}
                style={navBtn}>›</button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 30px)", gap: 2 }}>
              {DIAS.map((d, i) => (
                <div key={i} style={{ fontSize: 9, color: "var(--muted2)", textAlign: "center",
                                      textTransform: "uppercase", letterSpacing: .5, paddingBottom: 4 }}>{d}</div>
              ))}

              {celdas.map((d, i) => {
                if (!d) return <div key={i} />;
                const esInicio = sameDay(d, start) || sameDay(d, pendingStart);
                const esFin = sameDay(d, end);
                const dentro = lo && hi && d > lo && d < hi;
                const extremo = esInicio || esFin;

                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => pick(d)}
                    onMouseEnter={() => pendingStart && setHover(d)}
                    style={{
                      width: 30, height: 28, border: "none", cursor: "pointer",
                      fontFamily: "inherit", fontSize: 11, borderRadius: 4,
                      background: extremo ? META_BLUE : dentro ? "rgba(24,119,242,.16)" : "transparent",
                      color: extremo ? "#fff" : dentro ? META_BLUE : "var(--text)",
                      fontWeight: extremo ? 600 : 400,
                      transition: "background .1s",
                    }}
                  >
                    {d.getDate()}
                  </button>
                );
              })}
            </div>

            <div style={{ fontSize: 10, color: "var(--muted2)", marginTop: 10, textAlign: "center" }}>
              {pendingStart ? "Ahora elige la fecha final" : "Haz clic en la fecha inicial"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const navBtn = {
  background: "transparent", border: "1px solid var(--border)", color: "var(--muted)",
  width: 24, height: 24, borderRadius: 4, cursor: "pointer", fontSize: 14, lineHeight: 1,
};
