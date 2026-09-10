/**
 * Phase 1 Offline Read · Route Hydrator
 *
 * On app foreground + connectivity, silently pre-fetches today's route
 * for the logged-in tech: job details + service reports (checklist
 * bootstraps). All data stored via the SQLite read_cache layer so the
 * tech can open any job from today's route offline.
 *
 * Fix 1 — Replaces N+1 per-job GET calls with a single call to
 *          GET /api/mobile/offline-bundle.
 * Fix 3 — Honest sync status: only stamps lastSyncedAt when
 *          cachedJobs === totalJobs; otherwise sets "partial"/"failed".
 */
import { api } from "@/src/api";
import { writeCache, readCache } from "@/src/services/readCache";
import { isOnlineNow } from "@/src/services/sync/netBus";
import { stripBase64FromReport } from "@/src/services/photoUrlCache";

// ── Cache key helpers ────────────────────────────────────────────────
export const CK = {
  todayJobs: (userId: string) => `route:jobs:today:${userId}`,
  jobDetail: (jobId: string) => `job:detail:${jobId}`,
  jobBootstrap: (jobId: string) => `job:bootstrap:${jobId}`,
  hydrationMeta: (userId: string) => `hydration:meta:${userId}`,
} as const;

export type SyncStatus = "synced" | "partial" | "failed" | "idle";

export type HydrationMeta = {
  lastSyncedAt: string;        // ISO — only stamped when cached === total (clean sync)
  lastPartialSyncAt: string;   // ISO — stamped on partial or failed sync
  lastError: string;           // Error message on failure
  syncStatus: SyncStatus;
  totalJobs: number;
  cachedJobs: number;
  inProgress: boolean;
};

// ── Module-level state (subscribers get notified) ────────────────────
type Listener = (meta: HydrationMeta) => void;
const _listeners = new Set<Listener>();
let _meta: HydrationMeta = {
  lastSyncedAt: "",
  lastPartialSyncAt: "",
  lastError: "",
  syncStatus: "idle",
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
 * Fix 1: Single GET /mobile/offline-bundle replaces N+1 per-job fetches.
 * Fix 3: Honest sync status with partial/failed tracking.
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

  _meta = { ..._meta, inProgress: true, lastError: "" };
  _notify();

  try {
    // ─── Fix 1: Single bundle call replaces N+1 ─────────────────────
    const bundle = await _safeFetch("/mobile/offline-bundle", ac.signal);
    if (ac.signal.aborted) return _meta;

    if (!bundle) {
      // Network error or endpoint failure — mark as failed.
      _meta = {
        ..._meta,
        syncStatus: "failed",
        lastError: "Could not reach the server.",
        lastPartialSyncAt: new Date().toISOString(),
        inProgress: false,
      };
      await writeCache(CK.hydrationMeta(userId), _meta).catch(() => {});
      _notify();
      return _meta;
    }

    const jobList: any[] = bundle.jobs || [];
    const reports: any[] = bundle.service_reports_in_progress || [];
    const totalFromServer: number = bundle.job_count ?? jobList.length;

    // Cache the job list.
    await writeCache(CK.todayJobs(userId), jobList).catch(() => {});

    _meta = { ..._meta, totalJobs: totalFromServer, cachedJobs: 0 };
    _notify();

    if (totalFromServer === 0 && jobList.length === 0) {
      _meta = {
        lastSyncedAt: new Date().toISOString(),
        lastPartialSyncAt: _meta.lastPartialSyncAt,
        lastError: "",
        syncStatus: "synced",
        totalJobs: 0,
        cachedJobs: 0,
        inProgress: false,
      };
      await writeCache(CK.hydrationMeta(userId), _meta).catch(() => {});
      _notify();
      return _meta;
    }

    // Build report lookup by job_id for O(1) matching.
    const reportByJobId = new Map<string, any>();
    for (const r of reports) {
      const jid = r.job_id || r.jobId;
      if (jid) reportByJobId.set(jid, r);
    }

    // Cache each job + its matching service report.
    let cached = 0;
    let errors = 0;
    for (const job of jobList) {
      if (ac.signal.aborted) break;
      const jid = job.id;
      if (!jid) { errors++; continue; }

      try {
        const report = reportByJobId.get(jid) || null;
        // Fix 2: Strip base64 blobs from report photos (backward compat).
        const cleanReport = stripBase64FromReport(report);
        await writeCache(CK.jobDetail(jid), job);
        await writeCache(CK.jobBootstrap(jid), { job, report: cleanReport });
        cached++;
      } catch {
        errors++;
      }

      // Update progress every 5 jobs.
      if (cached % 5 === 0 || cached === jobList.length) {
        _meta = { ..._meta, cachedJobs: cached };
        _notify();
      }
    }

    // ─── Fix 3: Honest sync status ──────────────────────────────────
    const now = new Date().toISOString();
    const allCached = cached >= totalFromServer;
    let syncStatus: SyncStatus;
    if (cached === 0 && totalFromServer > 0) {
      syncStatus = "failed";
    } else if (allCached) {
      syncStatus = "synced";
    } else {
      syncStatus = "partial";
    }

    _meta = {
      lastSyncedAt: allCached ? now : _meta.lastSyncedAt,
      lastPartialSyncAt: !allCached ? now : (_meta.lastPartialSyncAt || ""),
      lastError: errors > 0 ? `${errors} job(s) failed to cache.` : "",
      syncStatus,
      totalJobs: totalFromServer,
      cachedJobs: cached,
      inProgress: false,
    };
    await writeCache(CK.hydrationMeta(userId), _meta).catch(() => {});
    _notify();
    return _meta;
  } catch (e: any) {
    _meta = {
      ..._meta,
      inProgress: false,
      syncStatus: "failed",
      lastError: e?.message || "Hydration failed.",
      lastPartialSyncAt: new Date().toISOString(),
    };
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
