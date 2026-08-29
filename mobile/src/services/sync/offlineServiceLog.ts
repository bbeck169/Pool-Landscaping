/**
 * Phase O3 · Offline service-log plumbing.
 *
 * Provides:
 *   - `cacheServiceReport(jobId, report)` — writes the full report JSON
 *     into the SQLite `service_reports` table (survives force-quit).
 *   - `getCachedServiceReport(jobId)` — returns the last cached payload.
 *   - `markDirty(jobId)` — flags the cached report as locally-modified.
 *   - `submitOffline(jobId, report)` — enqueues a `service_report.upsert`
 *     op onto the O2 sync_queue and returns the client UUID.
 */
import { getSyncDb } from "./db";
import { enqueue } from "./queue";
import { clientUuid } from "../ids/clientUuid";

// ─── SQLite read/write ─────────────────────────────────────────────

export async function cacheServiceReport(
  jobId: string,
  report: Record<string, any>,
): Promise<void> {
  const db = await getSyncDb();
  const id = report?.id || `local_${jobId}`;
  const payload = JSON.stringify(report);
  const now = Date.now();
  await db.runAsync(
    `INSERT OR REPLACE INTO service_reports (id, job_id, payload, dirty, cached_at)
     VALUES (?, ?, ?, 0, ?)`,
    [id, jobId, payload, now],
  );
}

export async function getCachedServiceReport(
  jobId: string,
): Promise<Record<string, any> | null> {
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ payload: string }>(
    `SELECT payload FROM service_reports WHERE job_id = ? ORDER BY cached_at DESC`,
    [jobId],
  );
  if (!row?.payload) return null;
  try { return JSON.parse(row.payload); }
  catch { return null; }
}

export async function markDirty(jobId: string): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE service_reports SET dirty = 1 WHERE job_id = ?`,
    [jobId],
  );
}

export async function clearDirty(jobId: string): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE service_reports SET dirty = 0 WHERE job_id = ?`,
    [jobId],
  );
}

// ─── Offline submit ────────────────────────────────────────────────

/**
 * Enqueues a `service_report.upsert` into the sync_queue.
 * Returns the client UUID used as the idempotency key.
 */
export async function submitOffline(
  jobId: string,
  report: Record<string, any>,
): Promise<string> {
  const reportId = report?.id || clientUuid();

  const id = await enqueue({
    op_type: "service_report.upsert",
    entity_id: reportId,
    endpoint: "/mobile/sync",
    method: "BATCH",
    payload: {
      job_id: jobId,
      chemical_readings: report.chemical_readings ?? [],
      chemicals_added: report.chemicals_added ?? [],
      checklist_items: report.checklist_items ?? [],
      notes: report.notes ?? "",
      water_bodies: report.water_bodies ?? [],
      submitted: true,
    },
  });

  // Mark the cached copy as dirty so future reads know the server
  // hasn't confirmed yet.
  await markDirty(jobId);

  return id;
}
