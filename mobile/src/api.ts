import { storage } from "@/src/utils/storage";
import { logApi } from "@/src/utils/diagnostics";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
export const TOKEN_KEY = "pool_crm_token";

/** Full public base for the FastAPI backend, without `/api`. */
export const api_base = () => `${BASE}/api`;

/** Read the raw bearer token (async — SecureStore on iOS, AsyncStorage on Android). */
export async function getAuthToken(): Promise<string> {
  return (await storage.secureGet<string>(TOKEN_KEY, "")) || "";
}

async function authHeaders() {
  const token = await storage.secureGet<string>(TOKEN_KEY, "");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/**
 * Custom error class used so callers (e.g. write-queue) can distinguish a
 * "no network" failure from an HTTP-status failure. Anything thrown here
 * with `kind === "network"` is safe to retry from the offline queue with
 * the same X-Idempotency-Key. HTTP 4xx/5xx are NOT retried automatically.
 */
export class ApiNetworkError extends Error {
  kind = "network" as const;
  constructor(msg: string) { super(msg); this.name = "ApiNetworkError"; }
}

/**
 * K61.a.2 · Feb-2026 — Structured HTTP-error type.
 *
 * ``request()`` used to throw a plain ``Error`` with only the humanised
 * message, forcing every catch site to do fragile substring matching
 * on ``e.message`` (or the pre-K61 dead-code branch that reached for
 * ``e.response.data.detail`` on the assumption the client was axios).
 *
 * ``ApiError`` attaches the HTTP ``status`` code (number) and the RAW
 * parsed backend ``detail`` field (string / array / dict — whatever
 * FastAPI + Pydantic emitted, unmodified) so callers can inspect the
 * shape structurally:
 *
 *     try { await api.post(...); }
 *     catch (e) {
 *       if (e instanceof ApiError && e.status === 422 &&
 *           typeof e.detail === "object" && e.detail !== null &&
 *           (e.detail as any).detail === "chemistry_core_readings_missing") {
 *         // structured branch — read e.detail.missing_labels etc.
 *       }
 *     }
 *
 * ``e.message`` retains the pre-K61 humanised string so every existing
 * catch site that only reads the message keeps working unchanged.
 */
export class ApiError extends Error {
  kind = "http" as const;
  status: number;
  /**
   * Raw parsed backend ``detail`` field.  ``string`` for
   * ``HTTPException(400, "…")`` sites, ``Array<{loc,msg,...}>`` for
   * Pydantic 422 validation errors, or a plain object for structured
   * business-rule raises (chemistry gate, customer merge, etc).
   * ``null`` when the response body was empty / non-JSON.
   */
  detail: unknown;
  constructor(msg: string, status: number, detail: unknown) {
    super(msg);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * JWT soft-delete enforcement — register a callback that fires on 401.
 * The AuthProvider calls this on mount so the API layer can trigger logout
 * when the backend rejects a soft-deleted user's token.
 *
 * K36 amendment · "kicked out all day" repro fix. A burst of parallel
 * requests firing on Schedule mount (jobs + crews + users) could each
 * see a transient 401 (clock skew, in-flight token rotation, or the
 * legit expiry) and every one would independently call `_logoutOn401`,
 * yanking the user out mid-load. We now debounce logout so only the
 * first 401 in a `LOGOUT_COOLDOWN_MS` window actually triggers logout,
 * and we breadcrumb each 401 so the diagnostic buffer captures the
 * exact request that started it.
 */
let _logoutOn401: (() => void) | null = null;
export function registerLogoutOn401(fn: () => void) { _logoutOn401 = fn; }

const LOGOUT_COOLDOWN_MS = 5_000;
let _lastLogoutAt = 0;
function _handle401(path: string) {
  const now = Date.now();
  if (now - _lastLogoutAt < LOGOUT_COOLDOWN_MS) {
    // Suppressed — a sibling request already tripped the logout.
    logApi({ method: "AUTH", path, status: 401, errorKind: "http", errorMsg: "401 suppressed (cooldown)" });
    return;
  }
  _lastLogoutAt = now;
  logApi({ method: "AUTH", path, status: 401, errorKind: "http", errorMsg: "401 → logout" });
  storage.secureRemove(TOKEN_KEY).catch(() => {});
  _logoutOn401?.();
}

async function request(path: string, options: RequestInit = {}, timeoutMs = 30000, externalSignal?: AbortSignal) {
  const headers = await authHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const _method = String(options.method || "GET").toUpperCase();
  const _t0 = Date.now();
  // K15 · external AbortSignal — abort internal controller when external fires.
  let _extCleanup: (() => void) | undefined;
  if (externalSignal) {
    if (externalSignal.aborted) { clearTimeout(timer); throw new ApiNetworkError("Request aborted"); }
    const _onAbort = () => controller.abort();
    externalSignal.addEventListener("abort", _onAbort, { once: true });
    _extCleanup = () => externalSignal.removeEventListener("abort", _onAbort);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}/api${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(timer);
    _extCleanup?.();
    const isTimeout = e?.name === "AbortError";
    logApi({
      method: _method, path,
      ms: Date.now() - _t0,
      errorKind: isTimeout ? "timeout" : "network",
      errorMsg: e?.message || String(e),
    });
    if (isTimeout) throw new ApiNetworkError("Request timed out — check your connection and try again.");
    throw new ApiNetworkError("Network error — check your connection and try again.");
  }
  clearTimeout(timer);
  _extCleanup?.();
  const text = await res.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null; // non-JSON body (e.g. proxy HTML error page)
    }
  }
  if (!res.ok) {
    // JWT soft-delete enforcement: 401 → clear token + logout callback
    // (K36 · debounced so a burst of parallel 401s from the same
    // Schedule mount doesn't compound-logout the tech).
    if (res.status === 401) {
      _handle401(path);
    } else {
      logApi({ method: _method, path, status: res.status, ms: Date.now() - _t0, errorKind: "http" });
    }
    let msg: any = data?.detail;
    // K61.a.2 · Feb-2026 — preserve the RAW parsed ``detail`` alongside
    // the humanised message so downstream callers can inspect the
    // structured shape (e.g. Close-job's chemistry gate reads
    // ``detail.detail === "chemistry_core_readings_missing"`` and
    // ``detail.missing_labels``).  ``rawDetail`` is stringified /
    // truncated safely below only for the human message; the raw
    // parsed value is attached to the thrown ``ApiError`` unchanged.
    const rawDetail: any = data?.detail;
    // FastAPI ``HTTPException(detail=[{"msg": ..., "loc": ...}, ...])``
    // shape — Pydantic validation errors + explicit list raises.
    if (Array.isArray(msg)) {
      msg = msg.map((e: any) => (e?.msg || "").replace(/^Value error,\s*/i, "")).filter(Boolean).join(" ");
    }
    // Feb 2026 · P0 iOS close-job fix — FastAPI
    // ``HTTPException(detail={...})`` shape used by structured
    // business-rule raises (chemistry gate, customer merge,
    // marketing validators, etc). Prefer explicit ``message`` /
    // ``msg`` keys and append missing-field labels when present so
    // the tech sees "Cannot close job — required chemistry
    // readings missing: Free Cl, Total Cl, Alkalinity, pH, CYA"
    // instead of a generic "Request failed (422)".
    else if (msg && typeof msg === "object") {
      const _obj: any = msg;
      const _base: string = String(
        _obj.message || _obj.msg || _obj.error || _obj.detail || "",
      );
      const _labels: any = _obj.missing_labels || _obj.missing_fields;
      if (_base && Array.isArray(_labels) && _labels.length) {
        msg = `${_base}: ${_labels.join(", ")}`;
      } else if (_base) {
        msg = _base;
      } else {
        // Last-resort — stringify enough to be diagnosable rather
        // than swallowing the response.
        try { msg = JSON.stringify(_obj).slice(0, 300); }
        catch { msg = ""; }
      }
    }
    if (typeof msg !== "string" || !msg) msg = `Request failed (${res.status})`;
    // K61.a.2 · Feb-2026 — throw an ``ApiError`` so callers can inspect
    // ``err.status`` (HTTP status code) and ``err.detail`` (raw parsed
    // backend ``detail`` field) structurally, without relying on
    // fragile message substring matching.  ``err.message`` retains the
    // pre-K61 humanised string so every existing catch site keeps
    // working unchanged.
    throw new ApiError(msg, res.status, rawDetail);
  }
  logApi({ method: _method, path, status: res.status, ms: Date.now() - _t0 });
  return data;
}

export const api = {
  get: (p: string, opts?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request(p, opts?.headers ? { headers: opts.headers } : {}, 30000, opts?.signal),
  post: (p: string, body?: any, timeoutMs?: number, headers?: Record<string, string>) =>
    request(p, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      ...(headers ? { headers } : {}),
    }, timeoutMs ?? 30000),
  put: (p: string, body?: any, headers?: Record<string, string>) =>
    request(p, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
      ...(headers ? { headers } : {}),
    }),
  patch: (p: string, body?: any, headers?: Record<string, string>) =>
    request(p, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
      ...(headers ? { headers } : {}),
    }),
  del: (p: string, headers?: Record<string, string>) =>
    request(p, { method: "DELETE", ...(headers ? { headers } : {}) }),
};
