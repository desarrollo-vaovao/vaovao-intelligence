// Cliente del API de VaoVao Intelligence.
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("vv_token");
}

async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let payload;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload });

  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.detail || "Algo salió mal. Intenta de nuevo.";
    throw new Error(typeof msg === "string" ? msg : "Error de validación");
  }
  return data;
}

export const api = {
  login: (email, password) =>
    request("/auth/login", { method: "POST", form: { username: email, password } }),
  me: () => request("/auth/me"),

  listClients: () => request("/clients"),
  createClient: (body) => request("/clients", { method: "POST", body }),
  updateClient: (clientId, body) => request(`/clients/${clientId}`, { method: "PATCH", body }),
  deleteClient: (clientId) => request(`/clients/${clientId}`, { method: "DELETE" }),
  addAdAccount: (clientId, body) =>
    request(`/clients/${clientId}/ad-accounts`, { method: "POST", body }),
  updateAdAccount: (clientId, accountId, body) =>
    request(`/clients/${clientId}/ad-accounts/${accountId}`, { method: "PATCH", body }),
  deleteAdAccount: (clientId, accountId) =>
    request(`/clients/${clientId}/ad-accounts/${accountId}`, { method: "DELETE" }),
  refreshAdAccountName: (clientId, accountId) =>
    request(`/clients/${clientId}/ad-accounts/${accountId}/refresh-name`, { method: "POST" }),

  listUsers: () => request("/users"),
  createUser: (body) => request("/users", { method: "POST", body }),
  updateUser: (id, body) => request(`/users/${id}`, { method: "PATCH", body }),

  getMeta: () => request("/organization/meta-credentials"),
  addMetaToken: (body) => request("/organization/meta-credentials", { method: "POST", body }),
  deleteMetaToken: (id) => request(`/organization/meta-credentials/${id}`, { method: "DELETE" }),
  getMetaTokenAdAccounts: (id) => request(`/organization/meta-credentials/${id}/adaccounts`),

  getOrgSettings: () => request("/organization/settings"),
  updateOrgSettings: (body) => request("/organization/settings", { method: "PATCH", body }),

  reportStatus: () => request("/reports/status"),
  // La generación corre en segundo plano en el backend: esto arranca el job,
  // hace polling del estado y descarga el PDF cuando queda listo.
  // onProgress(status) es opcional, se llama en cada vuelta del polling.
  //
  // El intervalo ARRANCA CORTO Y CRECE en vez de ser fijo. Con el 1500 ms fijo
  // que había antes, un reporte que el backend terminaba en 800 ms igual se
  // sentía de 3 segundos: se esperaba el tic completo ANTES de preguntar
  // siquiera, y otro medio tic de promedio después de que ya estaba listo.
  // Ese tiempo no era ni Meta ni el PDF, era la app esperándose a sí misma.
  //
  // El techo es 1000 ms —MENOR que el intervalo fijo anterior— a propósito: si
  // se dejara crecer más (2 s, por ejemplo) se abrirían huecos más grandes que
  // los de antes y un reporte que termina a los ~5 s se detectaría MÁS TARDE
  // que con el esquema viejo. Así, los reportes rápidos se detectan casi al
  // instante y ninguno queda peor. Sondear cada segundo no cuesta nada: el
  // endpoint de estado solo lee un dict en memoria.
  generateReport: async (body, { onProgress } = {}) => {
    const { job_id } = await request("/reports/generate", { method: "POST", body });

    let job;
    let wait = 300;
    for (;;) {
      await new Promise((r) => setTimeout(r, wait));
      wait = Math.min(wait * 1.4, 1000);
      job = await request(`/reports/jobs/${job_id}`);
      if (onProgress) onProgress(job.status);
      if (job.status === "done" || job.status === "error") break;
    }
    if (job.status === "error") {
      throw new Error(job.error || "No se pudo generar el reporte.");
    }

    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${BASE}/reports/jobs/${job_id}/pdf`, { headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo descargar el PDF.");
    }

    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "reporte.pdf";

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    return filename;
  },
  checkAccess: (account_id) => request("/reports/check-access", { method: "POST", body: { account_id } }),
  reportSummary: (body) => request("/reports/summary", { method: "POST", body }),

  fbStatus: () => request("/auth/facebook/status"),
  fbLogin: () => request("/auth/facebook/login"),
  fbAccounts: () => request("/auth/facebook/adaccounts"),
  fbDisconnect: () => request("/auth/facebook/", { method: "DELETE" }),

  // Leads
  listLeads: (params = {}) => {
    const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ""));
    return request(`/leads?${new URLSearchParams(clean)}`);
  },
  getLead: (id) => request(`/leads/${id}`),
  updateLead: (id, body) => request(`/leads/${id}`, { method: "PATCH", body }),
  leadsStatus: () => request("/leads/status"),
  exportLeadsCsv: async (params = {}) => {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ""));
    const qs = new URLSearchParams(clean).toString();
    const res = await fetch(`${BASE}/leads/export/csv${qs ? `?${qs}` : ""}`, { headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo exportar.");
    }
    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "leads.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    return filename;
  },
  reconcileOrphans: (pageId) =>
    request(`/leads/orphans/${pageId}/reconcile`, { method: "POST" }),
};

export { getToken, request };