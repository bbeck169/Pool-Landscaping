/**
 * Feb-2026 · Phase 1 offline foundation — write-through cache for
 * the shared api client.
 *
 * The existing ``mobile/src/api.ts`` throws ``ApiNetworkError`` on
 * connection failure; higher-level callers can catch that and fall
 * back to the cache via the ``readOr...`` helpers below.
 *
 *   Success path (2xx):
 *      const jobs = await api.get(`/jobs?tech_user_id=…`);
 *      await writeThroughJobs(techUserId, jobs);
 *      markApiSuccess();
 *
 *   Offline path:
 *      try {
 *        return await api.get(`/jobs?…`);
 *      } catch (e) {
 *        if (e instanceof ApiNetworkError) return readCachedWeekJobs(techUserId);
 *        throw e;
 *      }
 *
 * ``cachedGet(...)`` composes the above two paths into a single
 * call so screen code stays a one-liner.
 *
 * POST / PUT / DELETE are NOT cached — those are Phase 2 (write
 * queue) territory.
 */
import { api, ApiNetworkError } from "@/src/api";
import { markApiSuccess } from "./netStatus";
import {
  cacheWeekJobs, getCachedWeekJobs,
  cacheCustomer, getCachedCustomer,
  cacheProperty, getCachedProperty,
  cacheMe, getCachedMe,
} from "./cache";


/** Normalises the shape ``api.get('/jobs?...')`` returns (either an
 *  array or ``{jobs, items}`` envelope) into a plain array. */
function _unwrapJobs(payload: any): any[] {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.jobs)) return payload.jobs;
  if (payload && Array.isArray(payload.items)) return payload.items;
  return [];
}


export async function writeThroughJobs(
  techUserId: string,
  payload: any,
): Promise<void> {
  const jobs = _unwrapJobs(payload);
  if (!techUserId || !jobs.length) return;
  await cacheWeekJobs(techUserId, jobs);
  markApiSuccess();
}


export async function writeThroughCustomer(payload: any): Promise<void> {
  if (!payload?.id) return;
  await cacheCustomer(payload);
  markApiSuccess();
}


export async function writeThroughProperty(payload: any): Promise<void> {
  if (!payload?.id) return;
  await cacheProperty(payload);
  markApiSuccess();
}


export async function writeThroughMe(payload: any): Promise<void> {
  if (!payload?.id) return;
  await cacheMe(payload);
  markApiSuccess();
}


// Read helpers — thin re-exports so screen code has ONE import.
export {
  getCachedWeekJobs as readCachedWeekJobs,
  getCachedCustomer as readCachedCustomer,
  getCachedProperty as readCachedProperty,
  getCachedMe       as readCachedMe,
};


/**
 * Compose write-through + read-fallback in a single call so screens
 * stay a one-liner:
 *
 *     const data = await cachedGet('/jobs?start=…&end=…', {
 *       writeThrough: (d) => writeThroughJobs(user.id, d),
 *       readCache:    ()  => readCachedWeekJobs(user.id),
 *     });
 *
 * On network failure the returned payload is what the cache had — the
 * caller can't tell it came from disk (that's the point).  If the
 * cache is empty the ``ApiNetworkError`` propagates and the caller
 * shows its normal offline UI.
 */
export async function cachedGet<T = any>(
  path: string,
  opts: {
    writeThrough?: (data: T) => Promise<void>;
    readCache?: () => Promise<T | null | undefined>;
  } = {},
): Promise<T> {
  try {
    const data = (await api.get(path)) as T;
    if (opts.writeThrough) {
      // Fire-and-forget — a cache write failure shouldn't corrupt
      // the online path.
      opts.writeThrough(data).catch(() => {});
    }
    markApiSuccess();
    return data;
  } catch (e: any) {
    if (e instanceof ApiNetworkError && opts.readCache) {
      const cached = await opts.readCache().catch(() => null);
      if (cached != null) return cached as T;
    }
    throw e;
  }
}
