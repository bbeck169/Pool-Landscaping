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
    if (e?.name === "AbortError") throw new Error("Request timed out — check your connection and try again.");
    throw new Error("Network error — check your connection and try again.");
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
    let msg: any = data?.detail;
    if (Array.isArray(msg)) {
      msg = msg.map((e: any) => (e?.msg || "").replace(/^Value error,\s*/i, "")).filter(Boolean).join(" ");
    }
    if (typeof msg !== "string" || !msg) msg = `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p: string) => request(p),
  post: (p: string, body?: any, timeoutMs?: number) =>
    request(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }, timeoutMs ?? 30000),
  put: (p: string, body?: any) => request(p, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: (p: string, body?: any) =>
    request(p, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: (p: string) => request(p, { method: "DELETE" }),
};
