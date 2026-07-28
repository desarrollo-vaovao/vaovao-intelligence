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

  listUsers: () => request("/users"),
  createUser: (body) => request("/users", { method: "POST", body }),
  updateUser: (id, body) => request(`/users/${id}`, { method: "PATCH", body }),

  getMeta: () => request("/organization/meta-credentials"),
  setMeta: (body) => request("/organization/meta-credentials", { method: "PUT", body }),
  clearMeta: () => request("/organization/meta-credentials", { method: "DELETE" }),

  reportStatus: () => request("/reports/status"),
  generateReport: async (body) => {
    // El reporte vuelve como PDF (binario), no como JSON: se descarga directo.
    const headers = { "Content-Type": "application/json" };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${BASE}/reports/generate`, {
      method: "POST", headers, body: JSON.stringify(body),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo generar el reporte.");
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

  fbStatus: () => request("/auth/facebook/status"),
  fbLogin: () => request("/auth/facebook/login"),
  fbAccounts: () => request("/auth/facebook/adaccounts"),
  fbDisconnect: () => request("/auth/facebook/", { method: "DELETE" }),
};

export { getToken };