/**
 * Offline cache — web fallback (in-memory shim).
 *
 * expo-sqlite is native-only; on web we provide an in-memory
 * Map-backed store with the same public API so upstream consumers
 * compile and degrade silently. Data does not persist across
 * page reloads — this is intentional; the web preview is not the
 * primary offline target.
 */

type AnyRow = { id: string; [k: string]: any };

/* ── In-memory stores ──────────────────────────────────────────────── */

let _jobs = new Map<string, { techUserId: string; scheduledDate: string; payload: AnyRow }>();
let _customers = new Map<string, AnyRow>();
let _properties = new Map<string, AnyRow>();
let _user: AnyRow | null = null;

/* ── Public API (mirrors cache.native.ts) ──────────────────────────── */

export async function initCache(): Promise<void> {
  // No-op on web — no schema to create.
}

export async function cacheWeekJobs(
  techUserId: string,
  jobs: AnyRow[],
): Promise<void> {
  if (!techUserId) return;
  // Wipe existing entries for this tech, then insert new ones.
  for (const [key, val] of _jobs) {
    if (val.techUserId === techUserId) _jobs.delete(key);
  }
  for (const j of jobs) {
    if (!j?.id) continue;
    _jobs.set(j.id, {
      techUserId,
      scheduledDate: String(j.scheduled_date || "").slice(0, 10),
      payload: j,
    });
  }
}

export async function getCachedWeekJobs(
  techUserId: string,
  weekStart?: string | null,
): Promise<AnyRow[]> {
  if (!techUserId) return [];
  const results: AnyRow[] = [];
  for (const val of _jobs.values()) {
    if (val.techUserId !== techUserId) continue;
    if (weekStart) {
      const end = _addDays(weekStart, 7);
      if (val.scheduledDate < weekStart || val.scheduledDate >= end) continue;
    }
    results.push(val.payload);
  }
  return results;
}

export async function getCachedJob(id: string): Promise<AnyRow | null> {
  if (!id) return null;
  return _jobs.get(id)?.payload ?? null;
}

export const cacheCustomer = async (c: AnyRow): Promise<void> => {
  if (c?.id) _customers.set(c.id, c);
};
export const getCachedCustomer = async (id: string): Promise<AnyRow | null> => {
  return _customers.get(id) ?? null;
};

export const cacheProperty = async (p: AnyRow): Promise<void> => {
  if (p?.id) _properties.set(p.id, p);
};
export const getCachedProperty = async (id: string): Promise<AnyRow | null> => {
  return _properties.get(id) ?? null;
};

export const cacheMe = async (u: AnyRow): Promise<void> => {
  _user = u?.id ? u : null;
};
export const getCachedMe = async (): Promise<AnyRow | null> => {
  return _user;
};

export async function wipeCache(): Promise<void> {
  _jobs.clear();
  _customers.clear();
  _properties.clear();
  _user = null;
}

export function __resetForTests(): void {
  _jobs = new Map();
  _customers = new Map();
  _properties = new Map();
  _user = null;
}

/* ── Internal helper ───────────────────────────────────────────────── */

function _addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
