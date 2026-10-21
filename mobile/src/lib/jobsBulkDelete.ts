/**
 * TD-82-mobile-calendar-bulk · canonical job bulk soft-delete.
 *
 * Migrated from the retired-via-shim `POST /jobs/bulk-soft-delete {job_ids}`
 * (BE `routers/jobs.py:4253`, slated for 410 Gone in TD-82 Phase 2B) to the
 * canonical `POST /jobs/bulk-delete {ids}` (`routers/bulk_crm.py:444`, shared
 * `_generic_bulk_delete` + `_job_locked`). Same role gate (admin/manager) and
 * soft-delete semantics; response `{ok, deleted_count, deleted, failed[{id, reason, status_code}]}`.
 *
 * Count read mirrors web `CalendarSchedule.jsx` (e57734f00):
 * `deleted_count ?? deleted.length`, with a final fallback to the requested
 * id count (the legacy mobile toast value) if the envelope carries neither.
 */
import { api } from "@/src/api";

export async function bulkDeleteJobs(ids: string[]): Promise<{ count: number; failed: any[] }> {
  const r: any = await api.post("/jobs/bulk-delete", { ids });
  const count = r?.deleted_count ?? (Array.isArray(r?.deleted) ? r.deleted.length : ids.length);
  return { count, failed: Array.isArray(r?.failed) ? r.failed : [] };
}
