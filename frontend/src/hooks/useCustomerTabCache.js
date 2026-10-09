/**
 * Phase 9d · Feb-2026 — Customer-profile lazy-tab TTL cache.
 *
 * Session-scoped in-memory cache for the customer profile's lazy
 * tabs (jobs / invoices / quotes / notes / service reports /
 * photos). A tab's data stays warm for ``TAB_CACHE_TTL_MS`` after
 * fetch so hopping between tabs feels instant inside the TTL window
 * while still eventually re-fetching for freshness.
 *
 * API shape mirrors ``useFormTemplateRuntime`` (same codebase
 * idiom): module-scoped ``Map`` + hook wrapper. Keyed by
 * ``${customerId}::${tabKey}`` so two profiles never cross-pollute
 * each other's cache. Entry shape:
 *
 *   { data: any, fetchedAt: number }  // fetchedAt in ms since epoch
 *
 * The hook returns a stable ``getOrFetch`` function the caller
 * invokes with a tab key + an async fetcher. Within TTL the
 * fetcher is NOT called; outside TTL (or on a miss) the fetcher
 * runs and its result is cached.
 *
 * Explicit cache controls (``invalidate`` / ``clearCustomer``) are
 * exposed for mutate-and-refresh flows (e.g. "Create job" from the
 * jobs tab should bust ``jobs`` + ``summary``).
 *
 * TTL is a module-level constant (5 minutes per the Phase 9d
 * brief). Tests override it via the exported setter — the hook
 * reads TTL on every call so a test can shrink + expand without
 * remounting the component.
 */
import { useCallback, useRef } from "react";


// Default TTL = 5 minutes. Exported for tests that want to assert
// the shipping value without hard-coding the magic number.
export const DEFAULT_TAB_CACHE_TTL_MS = 5 * 60 * 1000;
let _ttlMs = DEFAULT_TAB_CACHE_TTL_MS;

// Module-scoped cache. Shared across all component instances so
// tab-hopping between re-mounts (e.g. React Strict Mode double-
// invoke, parent re-render) still hits the warm entry.
const _cache = new Map();   // key = `${customerId}::${tabKey}` → entry


function _key(customerId, tabKey) {
  return `${customerId}::${tabKey}`;
}


// ───────────────────────────────────────────────────────────────
// Test / caller utilities. All module-level so they can be imported
// from suites without having to render the hook first.
// ───────────────────────────────────────────────────────────────
export function _resetCacheForTest() {
  _cache.clear();
  _ttlMs = DEFAULT_TAB_CACHE_TTL_MS;
}

export function _setTtlForTest(ms) {
  _ttlMs = Math.max(0, Number(ms) || 0);
}

export function _getCacheSizeForTest() {
  return _cache.size;
}


/**
 * Hook returning the cache controls bound to a single customer id.
 *
 *   const { getOrFetch, invalidate, clearCustomer } =
 *     useCustomerTabCache(customerId);
 *
 *   const jobs = await getOrFetch("jobs", () =>
 *     api.get(`/jobs?customer_id=${customerId}&limit=50`));
 */
export function useCustomerTabCache(customerId) {
  // Pin the customerId through a ref so the stable callbacks don't
  // recapture every render — matches the hook pattern already in
  // use across the codebase (``useGpsRoute``, ``useFormTemplate``).
  const idRef = useRef(customerId);
  idRef.current = customerId;

  const getOrFetch = useCallback(async (tabKey, fetcher) => {
    const cid = idRef.current;
    if (!cid) return fetcher();
    const k = _key(cid, tabKey);
    const now = Date.now();
    const hit = _cache.get(k);
    if (hit && (now - hit.fetchedAt) < _ttlMs) {
      return hit.data;
    }
    const data = await fetcher();
    _cache.set(k, { data, fetchedAt: Date.now() });
    return data;
  }, []);

  const invalidate = useCallback((tabKey) => {
    const cid = idRef.current;
    if (!cid) return;
    _cache.delete(_key(cid, tabKey));
  }, []);

  const clearCustomer = useCallback(() => {
    const cid = idRef.current;
    if (!cid) return;
    const prefix = `${cid}::`;
    for (const k of Array.from(_cache.keys())) {
      if (k.startsWith(prefix)) _cache.delete(k);
    }
  }, []);

  return { getOrFetch, invalidate, clearCustomer };
}
