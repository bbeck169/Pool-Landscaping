/**
 * N4' · Feb-2026 — Global-search API client for the PageHeader
 * dropdown.
 *
 * Calls ``GET /api/search/global`` and returns the parsed JSON body.
 * Distinct from the app-wide ``src/api.js`` wrapper because that
 * wrapper does not accept an external ``AbortController`` signal —
 * it manages its own 30 s timeout signal internally. The N4' UX
 * requires that a fast typist's earlier request be *actually
 * cancelled* mid-flight (not just have its result discarded)
 * when a newer keystroke supersedes it, so we go direct-fetch here
 * and duplicate the 5-line auth-header composition.
 *
 * Public API
 * ──────────
 *   searchGlobal(query, { signal, limit = 5 }) → Promise<{customers, documents}>
 *
 * Errors
 * ──────
 * * ``AbortError`` — silently rethrown so the caller can filter it
 *   out. Callers should NOT set state on abort.
 * * Any other fetch/HTTP error — thrown as ``Error`` with a
 *   ``.status`` field mirroring ``src/api.js``.
 * * Server-side ``q < 2`` handling ships in the backend
 *   (returns 200 with empty groups) — the client never needs to
 *   short-circuit here.
 */

const BASE = process.env.REACT_APP_BACKEND_URL || "";
const TOKEN_KEY = "token";


function _authHeaders() {
  const headers = { "Content-Type": "application/json" };
  try {
    const token = (typeof localStorage !== "undefined")
      ? localStorage.getItem(TOKEN_KEY) : "";
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const slug = (typeof localStorage !== "undefined")
      ? localStorage.getItem("tenant_slug") : "";
    if (slug) headers["X-Tenant-Slug"] = slug;
  } catch { /* localStorage unavailable (SSR / test) */ }
  return headers;
}


export async function searchGlobal(query, { signal, limit = 5 } = {}) {
  const q = (query || "").trim();
  const params = new URLSearchParams({ q, limit: String(limit) });
  const url = `${BASE}/api/search/global?${params.toString()}`;
  const res = await fetch(url, {
    method: "GET",
    headers: _authHeaders(),
    signal,
  });
  if (!res.ok) {
    const err = new Error(`search_global_request_failed_${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}
