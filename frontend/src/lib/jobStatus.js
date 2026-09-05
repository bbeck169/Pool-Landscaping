/**
 * Phase K50 · Feb-2026 — Schedule job-card status background shading.
 *
 * SINGLE source of truth for the ``status → card background hex``
 * map on the WEB Schedule pages (CalendarSchedule.jsx +
 * TodaySchedule.jsx).  The mobile mirror lives at
 * ``mobile/src/lib/jobStatus.ts`` and MUST keep the same status keys
 * and hexes so the two surfaces render identically per the K50
 * spec.
 *
 * Scope note (from the K50 brief):
 *   * These colors are for the SCHEDULE JOB CARD BACKGROUND ONLY.
 *   * Status pills, badges, calendar-event dots, and dashboard
 *     status tokens continue to use their existing palettes
 *     (``STATUS_PILL``, ``STATUS_COLORS``, ``colors.status.*``).
 *   * The K50 map is deliberately narrower — only the five status
 *     buckets the user called out are covered; anything else falls
 *     through to ``null`` so the caller keeps its previous default
 *     (typically ``colors.surface`` / white).
 */

/** Frozen so downstream consumers can't mutate the shared map. */
export const K50_JOB_STATUS_BG = Object.freeze({
  open:        "#D6F5EE",  // light teal green — "active, not yet started"
  scheduled:   "#D6F5EE",  // alias for ``open`` on the Schedule surface
  in_progress: "#FEF3C7",  // light yellow (Tailwind yellow-100)
  completed:   "#FDECEC",  // soft pink
  cancelled:   "#FECACA",  // light red (Tailwind red-200) — deliberately
                           // redder than ``completed`` so day/week views
                           // separate the two at a glance
  skipped:     "#FED7AA",  // light orange (Tailwind orange-200)
});

/**
 * Resolve the K50 background hex for a given job status.
 *
 * Case-insensitive; trims whitespace; returns ``null`` for any
 * unknown / empty status so the caller falls back to its previous
 * default (do NOT paint every non-K50 status the same generic
 * shade — that would strip semantics from statuses like ``on_hold``
 * / ``requested`` that already have their own pill treatment).
 *
 * @param {string | null | undefined} status
 * @returns {string | null}
 */
export function jobStatusColor(status) {
  const s = String(status || "").toLowerCase().trim();
  if (!s) return null;
  // Common legacy aliases surfaced across the codebase.  Keep the
  // map above canonical; the alias table below is the only place
  // we translate — no scattered ``|| ""`` string comparisons.
  const alias = {
    active: "in_progress",
    in_progress: "in_progress",
    inprogress: "in_progress",
    closed: "completed",
    done: "completed",
    canceled: "cancelled",   // US spelling → canonical UK spelling.
  };
  const key = alias[s] || s;
  return K50_JOB_STATUS_BG[key] || null;
}
