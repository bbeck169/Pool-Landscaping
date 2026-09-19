/**
 * Belt-and-suspenders resolver for ``user.technician_id``.
 *
 * On tenants where the ``technicians_user_id_backfill`` migration hasn't
 * been run in production, ``user.technician_id`` comes back ``null`` from
 * the auth payload.  This helper resolves it via ``GET /api/technicians/me``
 * (backend parallel task).
 *
 * - Fast-path: ``user.technician_id`` is truthy → return immediately (zero
 *   network cost).
 * - Slow-path: fetch ``/api/technicians/me`` once, return ``data.id``.
 *   Cached in a module-level Map keyed by ``user.id`` so subsequent mounts
 *   skip the roundtrip.
 * - 404: the tech genuinely isn't in the roster → return ``null``.
 * - Other errors: return ``null`` and log a warning.
 */
import { api } from "@/src/api";

/** Module-level cache: user.id → resolved technician_id. */
const _cache = new Map<string, string | null>();

export interface MinimalUser {
  id?: string | null;
  technician_id?: string | null;
  role?: string | null;
}

/**
 * Resolve the authoritative ``technician_id`` for this user.
 *
 * Returns ``string`` (the resolved id) or ``null`` (no linked profile).
 */
export async function resolveTechnicianId(
  user: MinimalUser | null | undefined,
): Promise<string | null> {
  if (!user?.id) return null;

  // Fast-path: already populated on the auth payload.
  if (user.technician_id) return user.technician_id;

  // Cache hit — avoid repeated network calls.
  const cached = _cache.get(user.id);
  if (cached !== undefined) return cached;

  // Slow-path: ask the backend.
  try {
    const res: any = await api.get("/technicians/me");
    const tid: string | null = res?.id ?? res?.technician_id ?? null;
    _cache.set(user.id, tid);
    return tid;
  } catch (e: any) {
    const status = e?.status ?? e?.response?.status;
    if (status === 404) {
      // Tech genuinely not in the roster.
      _cache.set(user.id, null);
      return null;
    }
    // eslint-disable-next-line no-console
    console.warn("[resolveTechnicianId] lookup failed:", e?.message || e);
    // Don't cache errors — let the next mount retry.
    return null;
  }
}

/** Clear the module cache (useful for logout / impersonation). */
export function clearTechnicianIdCache(): void {
  _cache.clear();
}

/** @internal — exposed for tests only. */
export const _testCache = _cache;
