/**
 * Phase P20 — Sequential Route Lock REMOVED.
 *
 * The feature (jobs must be completed in dispatched order) has been
 * retired.  `isJobLockedByRoute` is stubbed to always return false
 * so any lingering imports resolve cleanly.  This module is a
 * deletion candidate once all consumer imports are confirmed removed.
 */

export type JobLike = {
  id: string;
  status?: string | null;
  route_index?: number | null;
  route_order?: number | null;
};

/** @deprecated Phase P20 — always returns false; lock feature removed. */
export function isJobLockedByRoute(
  _jobs: JobLike[],
  _targetJob: JobLike,
): boolean {
  return false; // Mobile-P20: sequential route lock removed.
}

export default isJobLockedByRoute;
