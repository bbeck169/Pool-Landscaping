/**
 * Phase O5 · useOfflineQuery — shared hook for offline-first reads.
 *
 * Pattern:
 *   1. Read SQLite cache immediately → render with cached data.
 *   2. If cache is fresh enough (staleTime) → skip network, return cached.
 *   3. If online → fire network fetch in background.
 *   4. On success → update SQLite cache + re-render with fresh data.
 *   5. On offline → return cached data with isStale=true.
 *   6. No infinite loops — fetcher is ref-latched, errors don't trigger re-fetch.
 */
import { useEffect, useState, useRef, useCallback } from "react";
import { readCacheWithAge, writeCache } from "@/src/services/readCache";
import { isOnlineNow } from "@/src/services/sync/netBus";

export type OfflineQueryResult<T> = {
  data: T | null;
  isLoading: boolean;
  isStale: boolean;
  isOffline: boolean;
  error: Error | null;
  refetch: () => void;
};

type UseOfflineQueryOptions = {
  /** Skip the network fetch even if online. */
  enabled?: boolean;
  /** Stale time in ms — don't refetch if cache is newer than this. Default 0 (always refetch). */
  staleTime?: number;
};

export function useOfflineQuery<T = any>(
  key: string,
  fetcher: () => Promise<T>,
  options: UseOfflineQueryOptions = {},
): OfflineQueryResult<T> {
  const { enabled = true, staleTime = 0 } = options;

  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isStale, setIsStale] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Guard: prevent state updates after unmount.
  const mountedRef = useRef(true);
  // Guard: prevent duplicate fetches.
  const fetchIdRef = useRef(0);

  // Strategy A — ref-latch the fetcher so `execute` is stable regardless
  // of whether callers wrap their fetcher in useCallback. This prevents
  // infinite re-render loops when an inline fetcher is passed.
  const fetcherRef = useRef(fetcher);
  useEffect(() => { fetcherRef.current = fetcher; });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const execute = useCallback(async (force = false) => {
    const fetchId = ++fetchIdRef.current;
    if (!mountedRef.current) return;

    setIsLoading(true);
    setError(null);

    // Step 1: Read from cache (with write-timestamp).
    try {
      const { data: cached, cachedAt } = await readCacheWithAge<T>(key);
      if (cached !== null && mountedRef.current && fetchId === fetchIdRef.current) {
        setData(cached);

        // staleTime guard: if the cache entry is younger than staleTime
        // AND this isn't a forced refetch (pull-to-refresh / explicit
        // refetch()), return the cached value without hitting the network.
        if (
          !force &&
          staleTime > 0 &&
          cachedAt != null &&
          Date.now() - cachedAt < staleTime
        ) {
          setIsStale(false);
          setIsLoading(false);
          return; // ← fresh cache; skip network.
        }

        setIsStale(true); // Will be flipped to false if fresh fetch succeeds.
      }
    } catch {
      // Cache read failure is non-fatal.
    }

    // Step 2: Fetch from network if online and enabled.
    const online = isOnlineNow();
    if (!mountedRef.current || fetchId !== fetchIdRef.current) return;
    setIsOffline(!online);

    if (!online || !enabled) {
      if (mountedRef.current && fetchId === fetchIdRef.current) setIsLoading(false);
      return;
    }

    try {
      const fresh = await fetcherRef.current();
      if (!mountedRef.current || fetchId !== fetchIdRef.current) return;

      setData(fresh);
      setIsStale(false);
      setError(null);

      // Write through to cache (fire-and-forget).
      writeCache(key, fresh).catch(() => {});
    } catch (e: any) {
      if (!mountedRef.current || fetchId !== fetchIdRef.current) return;
      setError(e);
      // If we have cached data, keep it displayed.
      // isStale remains true since the fetch failed.
    } finally {
      if (mountedRef.current && fetchId === fetchIdRef.current) setIsLoading(false);
    }
    // `fetcher` intentionally excluded — ref-latched above to prevent loops.
  }, [key, enabled, staleTime]);

  useEffect(() => {
    execute();
  }, [execute]);

  // refetch() always bypasses staleTime (force = true).
  const refetch = useCallback(() => {
    execute(true);
  }, [execute]);

  return { data, isLoading, isStale, isOffline, error, refetch };
}
