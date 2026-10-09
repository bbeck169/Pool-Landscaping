/**
 * Phase 9-M · Customer-profile lazy-section TTL cache.
 *
 * Fresh port of web ``frontend/src/hooks/useCustomerTabCache.js``
 * (Phase 9d · b5c09c9dc).  Same idiom as mobile
 * ``useFormTemplateRuntime``: module-scoped ``Map`` + hook wrapper.
 *
 *   key   = `${customerId}::${tabKey}`
 *   entry = { data, fetchedAt }   (ms since epoch)
 *
 * Within TTL (5 min) ``getOrFetch`` returns the warm entry without
 * calling the fetcher; on a miss or after expiry the fetcher runs and
 * its result is cached.  ``invalidate`` / ``clearCustomer`` exist for
 * mutate-and-refresh flows.
 */
import { useCallback, useRef } from "react";

export const DEFAULT_TAB_CACHE_TTL_MS = 5 * 60 * 1000;
let _ttlMs = DEFAULT_TAB_CACHE_TTL_MS;

type Entry = { data: unknown; fetchedAt: number };
const _cache = new Map<string, Entry>();

const _key = (customerId: string, tabKey: string) => `${customerId}::${tabKey}`;

export function _resetCacheForTest() {
  _cache.clear();
  _ttlMs = DEFAULT_TAB_CACHE_TTL_MS;
}

export function _setTtlForTest(ms: number) {
  _ttlMs = Math.max(0, Number(ms) || 0);
}

export function _getCacheSizeForTest() {
  return _cache.size;
}

export function useCustomerTabCache(customerId: string | undefined | null) {
  const idRef = useRef(customerId);
  idRef.current = customerId;

  const getOrFetch = useCallback(async <T,>(tabKey: string, fetcher: () => Promise<T>): Promise<T> => {
    const cid = idRef.current;
    if (!cid) return fetcher();
    const k = _key(cid, tabKey);
    const hit = _cache.get(k);
    if (hit && Date.now() - hit.fetchedAt < _ttlMs) return hit.data as T;
    const data = await fetcher();
    _cache.set(k, { data, fetchedAt: Date.now() });
    return data;
  }, []);

  const invalidate = useCallback((tabKey: string) => {
    const cid = idRef.current;
    if (cid) _cache.delete(_key(cid, tabKey));
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
