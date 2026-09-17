/**
 * Phase SRL — Sequential route lock helper (mobile-only).
 *
 * Determines whether a job is "locked" because an earlier stop in
 * the tech's daily route hasn't been completed or skipped yet.
 *
 * The caller is responsible for sorting `jobs` in route order
 * (by `route_index ?? route_order`) before passing them in.
 */

export type JobLike = {
  id: string;
  status?: string | null;
  route_index?: number | null;
  route_order?: number | null;
};

/** Statuses that "unlock" the next stop in the route. */
export const TERMINAL_STATUSES = new Set([
  "completed", "canceled", "cancelled", "skipped", "could_not_service",
]);

/**
 * Returns `true` if `targetJob` should be locked because at least one
 * earlier job in `jobs` (array index = route position) is NOT terminal.
 *
 * Edge cases:
 *  - Empty array → false (permissive).
 *  - targetJob not found in array → false + console.warn.
 *  - First job (index 0) → always false.
 */
export function isJobLockedByRoute(
  jobs: JobLike[],
  targetJob: JobLike,
): boolean {
  if (!jobs.length || !targetJob) return false;
  const idx = jobs.findIndex((j) => j.id === targetJob.id);
  if (idx === -1) {
    console.warn("[sequentialRouteLock] target job not in list:", targetJob?.id);
    return false;
  }
  if (idx === 0) return false; // first stop always unlocked
  for (let i = 0; i < idx; i++) {
    const s = (jobs[i].status || "").toLowerCase();
    if (!TERMINAL_STATUSES.has(s)) return true;
  }
  return false;
}

export default isJobLockedByRoute;
