// Thin fetch wrapper around the FastAPI backend.
// Reads REACT_APP_BACKEND_URL (CRA convention) and attaches the JWT bearer token
// from localStorage on every request.
const BASE = process.env.REACT_APP_BACKEND_URL;
export const api_base = () => `${BASE}/api`;
export const TOKEN_KEY = "token";

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY) || "";
  const tenantSlug = localStorage.getItem("tenant_slug") || "";
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (tenantSlug) headers["X-Tenant-Slug"] = tenantSlug;
  return headers;
}

async function request(path, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${BASE}/api${path}`, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (e?.name === "AbortError") {
      throw new Error("Request timed out — check your connection and try again.");
    }
    throw new Error("Network error — check your connection and try again.");
  }
  clearTimeout(timer);
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    let msg = data?.detail;
    if (Array.isArray(msg)) {
      msg = msg
        .map((e) => (e?.msg || "").replace(/^Value error,\s*/i, ""))
        .filter(Boolean)
        .join(" ");
    }
    if (typeof msg !== "string" || !msg) msg = `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p) => request(p),
  post: (p, body, timeoutMs) =>
    request(
      p,
      { method: "POST", body: body ? JSON.stringify(body) : undefined },
      timeoutMs
    ),
  put: (p, body) =>
    request(p, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: (p, body) =>
    request(p, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),
  request: (p, opts) => request(p, opts),
  del: (p) => request(p, { method: "DELETE" }),
};
