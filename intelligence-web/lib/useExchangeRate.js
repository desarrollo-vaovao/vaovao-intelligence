"use client";
import { useEffect, useState } from "react";
import { api } from "./api";

// Mismo respaldo que usa el backend (report_builder.DEFAULT_EXCHANGE_RATE_USD_GTQ)
// para cuando la organización todavía no configuró el suyo en Ajustes.
const DEFAULT_RATE = 7.75;

// Tipo de cambio USD<->GTQ de la organización (Ajustes > General). Se usa
// para convertir el presupuesto que la persona ya escribió al cambiar de
// moneda en el formulario — sin esto, escribir "50" en USD y luego tocar
// GTQ deja el mismo número con otro símbolo, como si $50 se hubieran
// vuelto Q50 solos.
export function useExchangeRate() {
  const [rate, setRate] = useState(DEFAULT_RATE);

  useEffect(() => {
    api.getOrgSettings()
      .then((s) => { if (s.exchange_rate_usd_gtq) setRate(s.exchange_rate_usd_gtq); })
      .catch(() => {});
  }, []);

  return rate;
}

// factor por el que multiplicar un monto en `from` para obtenerlo en `to`.
export function exchangeFactor(from, to, rate) {
  if (from === to) return 1;
  if (from === "USD" && to === "GTQ") return rate;
  if (from === "GTQ" && to === "USD") return 1 / rate;
  return 1;
}
