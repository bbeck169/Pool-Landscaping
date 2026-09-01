// Thin fetch wrapper around the FastAPI backend.
// Reads REACT_APP_BACKEND_URL (CRA convention) and attaches the JWT bearer token
// from localStorage on every request.
const BASE = process.env.REACT_APP_BACKEND_URL;
export const api_base = () => `${BASE}/api`;
export const TOKEN_KEY = "token";

// Feb-2026 · Zombie-session hotfix — the auth-token error details raised
// by ``backend/utils.get_current_user``. When the backend returns 401 with
// one of these details, the client's cached JWT is truly dead; we must
// clear the session and bounce the user to /login. Any OTHER 401 detail
// (rate-limit sentinel, custom endpoint reason, etc.) still throws a
// plain Error and does NOT touch the session — preserves current shape.
const AUTH_401_DETAILS = new Set([
  "token expired",
  "invalid token",
  "account_deleted",
  "account is deactivated",
]);

// Paths where a 401 must NEVER clear the user's JWT session:
//   • /login, /portal/login   — user is unauthenticated by design
//   • /portal/*, /public/*    — magic-link contexts using their OWN
//                                 token in a query string. A 401 there
//                                 means the MAGIC link is dead, not the
//                                 signed-in staff session.
function _isSessionSafePath(pathname) {
  if (!pathname) return false;
  return (
    pathname.startsWith("/login") ||
    pathname.startsWith("/portal") ||
    pathname.startsWith("/public") ||
    pathname.startsWith("/signup") ||
    pathname.startsWith("/forgot-password") ||
    pathname.startsWith("/reset-password")
  );
}

function _clearSessionAndRedirect() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem("user");
    localStorage.removeItem("tenant_slug");
    localStorage.removeItem("tenant_name");
  } catch { /* localStorage unavailable — best-effort */ }
  if (typeof window !== "undefined" && window.location) {
    // Preserve where the user was so a future phase can bounce them
    // back post-login. Path is captured, not full URL, to avoid
    // leaking any query-string tokens.
    const from = encodeURIComponent(
      (window.location.pathname || "/") + (window.location.search || ""),
    );
    window.location.assign(`/login?reason=expired&from=${from}`);
  }
}

function authHeaders() {
  // Phase K13 · Feb-2026 — when this tab is running an admin
  // impersonation session (opened via ``window.open("/portal/home?
  // impersonation_token=…")``), prefer the per-tab sessionStorage
  // token over the admin's localStorage token so the admin's own
  // session (in another tab) is not touched.  Only applies while the
  // active route is a portal route.
  let token = "";
  try {
    const path = (typeof window !== "undefined" && window.location)
      ? window.location.pathname || "" : "";
    const portalToken = (typeof sessionStorage !== "undefined")
      ? (sessionStorage.getItem("portal_token") || "") : "";
    if (portalToken && path.startsWith("/portal")) {
      token = portalToken;
    }
  } catch { /* sessionStorage may be unavailable (SSR / test env) */ }
  if (!token) token = localStorage.getItem(TOKEN_KEY) || "";
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
    } else if (msg && typeof msg === "object") {
      // FastAPI custom-shape details like `{code, msg}` (e.g. 403 not_landscaping).
      msg = msg.msg || msg.message || msg.code || msg.error || null;
    }
    if (typeof msg !== "string" || !msg) msg = `Request failed (${res.status})`;
    // Feb-2026 · Zombie-session hotfix — global 401 interceptor.
    // Only fires when:
    //   1. Status is 401.
    //   2. Detail matches the known auth-token error set (NOT any 401).
    //   3. We're not already on an auth/portal/public page (loop guard).
    // Any other 401 (custom endpoint sentinel, portal magic-link 401,
    // etc.) falls through and throws exactly as before.
    if (res.status === 401 && typeof msg === "string") {
      const lower = msg.toLowerCase();
      const isAuthTokenFailure = AUTH_401_DETAILS.has(lower);
      const pathname =
        typeof window !== "undefined" && window.location
          ? window.location.pathname
          : "";
      if (isAuthTokenFailure && !_isSessionSafePath(pathname)) {
        _clearSessionAndRedirect();
        // Still throw so any in-flight caller sees a rejection and
        // stops rendering; the redirect will unmount them anyway.
      }
    }
    const err = new Error(msg);
    err.status = res.status;
    // Feb-2026 · Customer Delete UX overhaul — attach the parsed
    // response body so callers can surface rich failure payloads
    // (e.g. the 409 ``customer_has_unpaid_invoices`` shape carries
    // ``invoice_ids`` + ``invoice_count`` in ``data.detail``).
    // ``err.data`` mirrors axios' ``err.response?.data`` shape so
    // consumers can migrate later without churn.
    err.data = data;
    throw err;
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
  // Feb-2026 · P7 hotfix — expose ``delete`` for API-verb parity with
  // ``get / post / put / patch``.  Historical callers used ``del`` (a
  // legacy alias to sidestep the ``delete`` reserved word in older JS);
  // both names now point at the same request. New call sites should
  // prefer ``.delete()``.
  delete: (p) => request(p, { method: "DELETE" }),
  del: (p) => request(p, { method: "DELETE" }),
};
