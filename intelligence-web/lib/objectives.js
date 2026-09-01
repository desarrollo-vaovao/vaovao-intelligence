// Traducción del objetivo de campaña de Meta — compartida entre
// Reportes y Resumen (antes duplicada solo en Reportes, por eso Resumen
// mostraba el código crudo de la API, ej. "OUTCOME_ENGAGEMENT").
const OBJECTIVE_LABELS = {
  LINK_CLICKS: "Tráfico", TRAFFIC: "Tráfico", MESSAGES: "Mensajes",
  POST_ENGAGEMENT: "Interacción", PAGE_LIKES: "Seguidores", REACH: "Alcance",
  BRAND_AWARENESS: "Reconocimiento", VIDEO_VIEWS: "Vistas de video",
  LEAD_GENERATION: "Leads", CONVERSIONS: "Conversiones",
  // Taxonomía nueva de Meta (ODAX) — reemplazó a los objetivos de arriba,
  // pero varias cuentas siguen devolviendo la vieja según cuándo se creó la
  // campaña. Sin esto, el objetivo salía como el código crudo de la API
  // (ej. "OUTCOME_ENGAGEMENT") en vez de una etiqueta traducida.
  OUTCOME_AWARENESS: "Reconocimiento", OUTCOME_TRAFFIC: "Tráfico",
  OUTCOME_ENGAGEMENT: "Interacción", OUTCOME_LEADS: "Leads",
  OUTCOME_SALES: "Ventas", OUTCOME_APP_PROMOTION: "Promoción de app",
};

export function objectiveLabel(obj) {
  return OBJECTIVE_LABELS[obj] || obj || "—";
}

const STATUS_LABELS = {
  ACTIVE: "Activa",
  PAUSED: "Pausada",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}
