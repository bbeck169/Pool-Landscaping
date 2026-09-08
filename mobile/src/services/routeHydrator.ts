/**
 * Phase 1 Offline Read · Route Hydrator
 *
 * On app foreground + connectivity, silently pre-fetches today's route
 * for the logged-in tech: job details + service reports (checklist
 * bootstraps). All data stored via the SQLite read_cache layer so the
 * tech can open any job from today's route offline.
 *
 * Does NOT touch write flows — those are Phase 2.
 */
import { api } from "@/src/api";
import { writeCache, readCache } from "@/src/services/readCache";
import { isOnlineNow } from "@/src/services/sync/netBus";

// ── Cache key helpers ────────────────────────────────────────────────
export const CK = {
  todayJobs: (userId: string) => `route:jobs:today:${userId}`,
  jobDetail: (jobId: string) => `job:detail:${jobId}`,
  jobBootstrap: (jobId: string) => `job:bootstrap:${jobId}`,
  hydrationMeta: (userId: string) => `hydration:meta:${userId}`,
} as const;

export type HydrationMeta = {
  lastSyncedAt: string; // ISO
  totalJobs: number;
  cachedJobs: number;
  inProgress: boolean;
};

// ── Module-level state (subscribers get notified) ────────────────────
type Listener = (meta: HydrationMeta) => void;
const _listeners = new Set<Listener>();
let _meta: HydrationMeta = {
  lastSyncedAt: "",
  totalJobs: 0,
  cachedJobs: 0,
  inProgress: false,
};
let _abortController: AbortController | null = null;

function _notify() {
  _listeners.forEach((fn) => { try { fn({ ..._meta }); } catch {} });
}

export function subscribeHydration(fn: Listener): () => void {
  _listeners.add(fn);
  // Immediately send current state.
  fn({ ..._meta });
  return () => { _listeners.delete(fn); };
}

export function getHydrationMeta(): HydrationMeta {
  return { ..._meta };
}

// ── Helpers ──────────────────────────────────────────────────────────
function _todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Fetch a single endpoint, returning null on failure (never throws). */
async function _safeFetch(url: string, signal?: AbortSignal): Promise<any | null> {
  try {
    return await api.get(url, signal ? { signal } : undefined);
  } catch {
    return null;
  }
}

// ── Main hydration ───────────────────────────────────────────────────
/**
 * Pre-fetch today's route for `userId`. Runs silently; callers can
 * subscribe to progress via `subscribeHydration`.
 *
 * Returns the final HydrationMeta.
 */
export async function hydrateToday(userId: string): Promise<HydrationMeta> {
  if (!userId || !isOnlineNow()) return _meta;
  if (_meta.inProgress) return _meta; // debounce

  // Cancel any stale hydration.
  _abortController?.abort();
  const ac = new AbortController();
  _abortController = ac;

  _meta = { ..._meta, inProgress: true };
  _notify();

  try {
    const today = _todayISO();
    const tomorrow = (() => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    })();

    // Step 1: Fetch today's jobs.
    const jobs = await _safeFetch(
      `/jobs?start=${today}&end=${tomorrow}&technician_id=${userId}`,
      ac.signal,
    );
    if (ac.signal.aborted) return _meta;

    const jobList: any[] = Array.isArray(jobs)
      ? jobs
      : jobs?.items || jobs?.jobs || [];

    // Cache the job list.
    await writeCache(CK.todayJobs(userId), jobList).catch(() => {});

    _meta = { ..._meta, totalJobs: jobList.length, cachedJobs: 0 };
    _notify();

    if (!jobList.length) {
      _meta = {
        lastSyncedAt: new Date().toISOString(),
        totalJobs: 0,
        cachedJobs: 0,
        inProgress: false,
      };
      await writeCache(CK.hydrationMeta(userId), _meta).catch(() => {});
      _notify();
      return _meta;
    }

    // Step 2: For each job, fetch detail + service report in parallel.
    // Batch in groups of 4 to avoid flooding.
    const BATCH = 4;
    let cached = 0;

    for (let i = 0; i < jobList.length; i += BATCH) {
      if (ac.signal.aborted) break;
      const batch = jobList.slice(i, i + BATCH);

      await Promise.allSettled(
        batch.map(async (job) => {
          if (ac.signal.aborted) return;
          const jid = job.id;
          if (!jid) return;

          // Fetch detail + service report in parallel.
          const [detail, report] = await Promise.all([
            _safeFetch(`/jobs/${jid}`, ac.signal),
            _safeFetch(`/jobs/${jid}/service-report`, ac.signal),
          ]);

          if (ac.signal.aborted) return;

          // Cache whatever succeeded.
          if (detail) {
            await writeCache(CK.jobDetail(jid), detail).catch(() => {});
          }
          if (detail && report) {
            await writeCache(CK.jobBootstrap(jid), { job: detail, report }).catch(() => {});
            cached++;
          } else if (detail) {
            // Cache partial (detail only) — checklist won't work but job detail will.
            await writeCache(CK.jobBootstrap(jid), { job: detail, report: null }).catch(() => {});
            cached++;
          }
        }),
      );

      // Update progress after each batch.
      _meta = { ..._meta, cachedJobs: cached };
      _notify();
    }

    // Finalize.
    _meta = {
      lastSyncedAt: new Date().toISOString(),
      totalJobs: jobList.length,
      cachedJobs: cached,
      inProgress: false,
    };
    await writeCache(CK.hydrationMeta(userId), _meta).catch(() => {});
    _notify();
    return _meta;
  } catch {
    _meta = { ..._meta, inProgress: false };
    _notify();
    return _meta;
  }
}

/** Cancel any in-flight hydration. */
export function cancelHydration(): void {
  _abortController?.abort();
  _abortController = null;
  _meta = { ..._meta, inProgress: false };
  _notify();
}

/** Restore saved meta from SQLite on cold start. */
export async function restoreHydrationMeta(userId: string): Promise<HydrationMeta> {
  const saved = await readCache<HydrationMeta>(CK.hydrationMeta(userId)).catch(() => null);
  if (saved) {
    _meta = { ...saved, inProgress: false };
    _notify();
  }
  return _meta;
}

/**
 * Check whether a specific job ID has a cached bootstrap.
 * Returns true if we have *at least* a job detail in the read_cache.
 */
export async function isJobCached(jobId: string): Promise<boolean> {
  const data = await readCache(CK.jobBootstrap(jobId)).catch(() => null);
  return data?.job != null;
}

/**
 * Read cached bootstrap for a job (for offline checklist).
 */
export async function getCachedJobBootstrap(jobId: string): Promise<{ job: any; report: any } | null> {
  return readCache<{ job: any; report: any }>(CK.jobBootstrap(jobId)).catch(() => null);
}

/**
 * Read cached job detail.
 */
export async function getCachedJobDetail(jobId: string): Promise<any | null> {
  return readCache(CK.jobDetail(jobId)).catch(() => null);
}
