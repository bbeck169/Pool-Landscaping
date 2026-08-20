/**
 * Feb-2026 · Slice 6 — 24h Post-Completion Edit Window (mobile).
 *
 * Client-side mirror of ``backend/services/edit_window.py``:
 *   * ``EDIT_WINDOW_HOURS`` — kept in lockstep with backend constant.
 *   * ``isWithinEditWindow(job)`` — decides whether to SHOW the edit
 *     affordance; the backend PATCH re-checks server-side so a false
 *     positive here just yields a 403 with a friendly detail.
 *   * ``hoursSinceCompletion(job)`` — returns float hours or null.
 *
 * Chosen strategy for mobile parity: **online-only edits** with an
 * "Online required to edit" static hint when the device is offline.
 * Rationale: (a) the backend PATCH endpoint is a separate code path
 * from the completion side-effect path, so no side-effect suppression
 * mechanism needs to change; (b) queuing edits offline risks pushing
 * them past the 24h window before they replay — cleaner to bounce
 * the user back to the field UX. Future work can promote this to a
 * ``pending_edits`` queue on top of the existing
 * ``queueMutation("job.edit", …)`` primitive if field data show
 * offline edits are the norm.
 */

export const EDIT_WINDOW_HOURS = 24;


/** Returns ``true`` iff ``job.status == "completed"`` AND the
 * ``completed_at`` timestamp is within ``EDIT_WINDOW_HOURS`` of now.
 * Missing / unparseable timestamps return ``false``.
 */
export function isWithinEditWindow(job: any): boolean {
  if (!job || String(job.status || "").toLowerCase() !== "completed") return false;
  const raw = job.completed_at;
  if (!raw) return false;
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return false;
  const hours = (Date.now() - dt.getTime()) / 3_600_000;
  return hours >= 0 && hours <= EDIT_WINDOW_HOURS;
}


export function hoursSinceCompletion(job: any): number | null {
  if (!job?.completed_at) return null;
  const dt = new Date(job.completed_at);
  if (Number.isNaN(dt.getTime())) return null;
  return (Date.now() - dt.getTime()) / 3_600_000;
}
