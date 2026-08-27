import { storage } from "@/src/utils/storage";

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
 * JWT soft-delete enforcement — register a callback that fires on 401.
 * The AuthProvider calls this on mount so the API layer can trigger logout
 * when the backend rejects a soft-deleted user's token.
 */
let _logoutOn401: (() => void) | null = null;
export function registerLogoutOn401(fn: () => void) { _logoutOn401 = fn; }

async function request(path: string, options: RequestInit = {}, timeoutMs = 30000) {
  const headers = await authHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${BASE}/api${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(timer);
    if (e?.name === "AbortError") throw new ApiNetworkError("Request timed out — check your connection and try again.");
    throw new ApiNetworkError("Network error — check your connection and try again.");
  }
  clearTimeout(timer);
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
    // JWT soft-delete enforcement: 401 → clear token + logout callback.
    if (res.status === 401) {
      storage.secureRemove(TOKEN_KEY).catch(() => {});
      _logoutOn401?.();
    }
    let msg: any = data?.detail;
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
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p: string, headers?: Record<string, string>) =>
    request(p, headers ? { headers } : {}),
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
