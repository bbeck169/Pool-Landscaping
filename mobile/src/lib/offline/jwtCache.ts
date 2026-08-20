/**
 * Feb-2026 · Phase 1 offline foundation — 24-hour JWT expiry cache.
 *
 * Persists the ISO expiry alongside the token itself (which the
 * existing ``storage.secureSet(TOKEN_KEY, …)`` helper already
 * handles).  On boot the app calls ``getFreshCachedJwt()``; if that
 * returns non-null the auth store can hydrate offline — the tech
 * skips the login screen.
 *
 * We deliberately store the expiry as a separate SecureStore entry
 * rather than decoding the JWT.  Decoding requires a
 * base64url-decoder + JSON parse for every boot; the sidecar entry
 * is O(1) and avoids drift when we later rotate to short-lived
 * tokens.
 */
import { storage } from "@/src/utils/storage";
import { TOKEN_KEY } from "@/src/api";

const EXP_KEY = "pool_crm_token_exp";
const _TTL_MS = 24 * 60 * 60 * 1000; // 24 h


export async function persistJwtExpiry(now: number = Date.now()): Promise<void> {
  const iso = new Date(now + _TTL_MS).toISOString();
  await storage.secureSet(EXP_KEY, iso);
}


export async function readJwtExpiry(): Promise<Date | null> {
  const raw = await storage.secureGet<string>(EXP_KEY, "");
  if (!raw) return null;
  const dt = new Date(String(raw));
  return Number.isNaN(dt.getTime()) ? null : dt;
}


export async function isJwtCacheFresh(): Promise<boolean> {
  const exp = await readJwtExpiry();
  if (!exp) return false;
  return exp.getTime() > Date.now();
}


/**
 * Returns the raw bearer token IF a fresh (unexpired) expiry
 * sidecar exists.  Otherwise ``null`` — caller must send the tech
 * to the login screen.  Used on boot to decide whether to hydrate
 * the auth store offline.
 */
export async function getFreshCachedJwt(): Promise<string | null> {
  const fresh = await isJwtCacheFresh();
  if (!fresh) return null;
  const token = await storage.secureGet<string>(TOKEN_KEY, "");
  return token ? String(token) : null;
}


export async function clearJwtExpiry(): Promise<void> {
  await storage.secureRemove(EXP_KEY);
}
