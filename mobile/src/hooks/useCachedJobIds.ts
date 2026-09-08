/**
 * Phase 1 Offline Read · useCachedJobIds hook
 *
 * Given a list of job IDs, checks which ones have cached bootstrap
 * data in SQLite. Returns a Set<string> of cached IDs.
 *
 * Used by the schedule grid to show a "Cached ✓" pill per job row.
 */
import { useEffect, useState, useRef } from "react";
import { isJobCached } from "@/src/services/routeHydrator";

/**
 * Returns a Set of job IDs that have cached offline data.
 * Re-checks whenever `jobIds` changes.
 */
export function useCachedJobIds(jobIds: string[]): Set<string> {
  const [cached, setCached] = useState<Set<string>>(new Set());
  const prevIdsRef = useRef("");

  useEffect(() => {
    const key = jobIds.join(",");
    if (key === prevIdsRef.current) return;
    prevIdsRef.current = key;

    if (!jobIds.length) {
      setCached(new Set());
      return;
    }

    let cancelled = false;
    (async () => {
      const results = await Promise.all(
        jobIds.map(async (id) => {
          const ok = await isJobCached(id);
          return ok ? id : null;
        }),
      );
      if (!cancelled) {
        setCached(new Set(results.filter(Boolean) as string[]));
      }
    })();

    return () => { cancelled = true; };
  }, [jobIds]);

  return cached;
}
