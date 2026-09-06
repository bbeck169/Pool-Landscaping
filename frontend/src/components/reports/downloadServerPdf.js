/**
 * Phase R1.c · Feb-2026 — helper for downloading a server-generated
 * PDF export while preserving the authenticated session.
 *
 * The default ``api`` client parses every response as JSON, which
 * corrupts binary PDF bytes. We can't hand a signed URL to a
 * bare ``<a href>`` either because the JWT lives in
 * ``localStorage`` — a link would drop it. So we ``fetch`` with
 * the same auth headers, coerce the response into a ``Blob``,
 * generate an object URL, and trigger a same-tab download via
 * a synthetic anchor.
 *
 * Falls back cleanly:
 *   * server 401/403/404 → throws an ``Error`` with the parsed
 *     ``detail`` (matches the ``api.js`` shape so callers can
 *     surface it via ``toast.error``).
 *   * network error → throws ``"Network error — check your
 *     connection and try again."`` (same copy as ``api.request``).
 *
 * ``api_base`` and ``TOKEN_KEY`` are already exported by
 * ``@/api``. In tests, ``@/api`` is mocked so this helper stays
 * import-safe.
 */
import { api_base, TOKEN_KEY } from "@/api";

async function _authFetch(path) {
  const url = `${api_base()}${path}`;
  let token = null;
  try { token = localStorage.getItem(TOKEN_KEY); }
  catch { /* localStorage unavailable */ }
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  let res;
  try {
    res = await fetch(url, { headers });
  } catch {
    throw new Error("Network error — check your connection and try again.");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const text = await res.text();
      const parsed = JSON.parse(text);
      msg = parsed?.detail || msg;
    } catch { /* body was not JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res;
}

/**
 * Fetch ``/api${path}`` with the current auth token and trigger a
 * download of the response body as ``filename``.
 *
 * Idempotent-ish: if the browser environment doesn't support
 * ``URL.createObjectURL`` (JSDOM in tests), we resolve to the
 * blob so tests can assert content-type + size without needing
 * a full DOM download stub.
 */
export async function downloadServerPdf(path, filename) {
  const res = await _authFetch(path);
  const blob = await res.blob();
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return blob;
  }
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename || "report.pdf";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Release the object URL on the next tick so Safari doesn't
  // cancel the download.
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  return blob;
}

export default downloadServerPdf;
