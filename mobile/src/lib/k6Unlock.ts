/**
 * K6 · CLOSED-JOB-EDIT-UNLOCK — single canonical mobile copy of the
 * completed-job edit-unlock role set.
 *
 * Mirrors BE `services/edit_window.py::K6_UNLOCK_ROLES` (which makes
 * these roles bypass the 24 h post-completion edit window) and web
 * `pages/jobs/JobDetail.jsx::K6_UNLOCK_ROLES`. Change this set ONCE and
 * every mobile gate (checklist editor, job detail) moves together.
 */
export const K6_UNLOCK_ROLES: ReadonlySet<string> = new Set([
  "super_admin", "admin", "manager", "tech", "technician", "owner",
  // Forward-compat — no seeded user carries "employee" today.
  "employee",
  // TD-78c (web/BE 1f3a1d5e1) — dispatchers can edit closed jobs.
  "dispatcher",
]);

/** Web `canEditCompleted`: K6 role AND job status === "completed".
 *  Customers are never in the set, so they stay read-only. */
export function canEditCompletedJob(role: string | null | undefined, job: any): boolean {
  return K6_UNLOCK_ROLES.has(String(role || "")) && job?.status === "completed";
}
