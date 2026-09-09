// Feb-2026 · Live-Tech-Map · Phase 4.core — ETag-aware board poll.
//
// Standalone helper because the shared ``api`` client discards
// response headers and treats 304 as an error. We use ``fetch``
// directly so we can:
//   1. Send ``If-None-Match`` with the last ETag we saw.
//   2. Detect 304 → return ``{ status: 304 }`` (no data) so the
//      caller skips the re-render.
//   3. Detect 200 → return ``{ status: 200, data, etag }`` so the
//      caller updates state + caches the new ETag for the next
//      poll.
//
// Backend contract: ``GET /api/dispatch/board`` (Phase 1 Q8).
// ETag is ``"<sha256_prefix>"`` — always a quoted string.
import { TOKEN_KEY } from "@/api";

function _authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY) || "";
  const tenantSlug = localStorage.getItem("tenant_slug") || "";
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (tenantSlug) headers["X-Tenant-Slug"] = tenantSlug;
  return headers;
}

function _q(params) {
  const parts = Object.entries(params || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export async function fetchBoardWithEtag(
  { day, tech_user_id, route_type, global_view, date } = {},
  ifNoneMatch = null,
  signal = undefined,
) {
  const BASE = process.env.REACT_APP_BACKEND_URL || "";
  const url = `${BASE}/api/dispatch/board${_q({
    day: day || "all",
    tech_user_id: tech_user_id || undefined,
    route_type: route_type || "all",
    global: global_view ? "true" : undefined,
    date: date || undefined,
  })}`;
  const headers = _authHeaders();
  if (ifNoneMatch) headers["If-None-Match"] = ifNoneMatch;

  const res = await fetch(url, { headers, signal });
  const etag = res.headers.get("ETag") || res.headers.get("etag") || null;

  if (res.status === 304) {
    return { status: 304, data: null, etag: ifNoneMatch };
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const err = new Error(text || `Board fetch failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  const data = await res.json();
  return { status: 200, data, etag };
}
