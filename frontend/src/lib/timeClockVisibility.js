/**
 * TD-64 · Feb-2026 — Time Clock surface visibility helper (web).
 *
 * Shared helper used by every web Time Clock render site to answer
 * one question: should this user see the Time Clock UI at all?
 *
 * Mirrors the BE truth set in ``backend/routers/timeclock_landscaping.py``
 * (``_LANDSCAPE_DEPTS`` at line 359). Keep this list in sync with the
 * backend; adding a new department to the BE requires a matching
 * addition here.
 *
 * ─── Visibility contract (operator-locked) ──────────────────────
 * Landscape technicians  → Time Clock gate + screens + buttons visible.
 * Pool technicians       → NO Time Clock surface anywhere. Not even
 *                           the nav entry, the dashboard widget, the
 *                           ToolsHub tile, the route handler, or the
 *                           full-screen gate.
 * Admin / super_admin    → see admin-only Time Clock surfaces (team
 *                           aggregation, punch edits). Those are
 *                           gated by role elsewhere and NOT the
 *                           concern of this helper.
 *
 * ─── Input sources (priority order) ──────────────────────────────
 * 1. ``user.show_time_clock`` (BE-authoritative boolean on
 *    ``GET /api/auth/me``). Always wins when present.
 * 2. ``user.effective_department`` (BE-computed designation,
 *    resolves ``users.department`` → ``technicians.department``
 *    fallback — mirrors the clock-in regression fix helper).
 * 3. ``user.department`` (legacy fallback).
 *
 * All string inputs are case-insensitive + whitespace-trimmed before
 * membership check.
 */
export const LANDSCAPE_DEPTS = new Set([
  "landscaping",
  "landscape_tech",
  "landscaper",
  "both",
]);


export function shouldShowTimeClock(user) {
  if (!user) return false;
  // BE-authoritative boolean wins when present.
  if (typeof user.show_time_clock === "boolean") return user.show_time_clock;
  const raw = user.effective_department ?? user.department ?? "";
  const d = String(raw).trim().toLowerCase();
  return LANDSCAPE_DEPTS.has(d);
}


export default shouldShowTimeClock;
