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
  // Phase K74.1 · Feb-2026 — lightened the mint/pale-green fill for
  // the ``open`` / ``scheduled`` bucket from ``#D6F5EE`` → ``#EAF7F0``.
  // Same mint-green family, ~10% lighter so the Schedule card body
  // reads as calmer next to the navy service label, VIP-yellow chip,
  // OPEN pill, and gate call-out yellow.  Web + mobile parity — mirror
  // in ``mobile/src/lib/jobStatus.ts`` MUST match byte-for-byte.
  open:        "#EAF7F0",  // light mint-green — "active, not yet started"
  scheduled:   "#EAF7F0",  // alias for ``open`` on the Schedule surface
  in_progress: "#FEF3C7",  // light yellow (Tailwind yellow-100)
  // Feb-2026 · Schedule finished-state card styling (operator spec).
  // The prior Phase 3 "bold red" treatment for ``completed`` (hex
  // ``#ff4542``) was reported by operators as both too visually
  // prominent for a terminal/archive state AND inaccessible — the
  // white-text-on-red cascade had ~4.1:1 contrast which is only AA
  // for large text and failed WCAG AA for the smaller gate / crew /
  // service labels.  All finished states (``completed`` / ``closed``
  // / ``cancelled`` / ``skipped``) now resolve to Tailwind
  // ``gray-100`` so finished cards recede into the list.  Dark
  // body text (``#374151`` ~ gray-700) is applied in-line by the
  // schedule card renderers via ``jobStatusTextColor`` below —
  // contrast ratio on #F3F4F6 is 10.4:1 (AAA for normal text).
  // Mobile parity is tracked separately in
  // ``mobile/src/lib/jobStatus.ts``; that file keeps its prior
  // hexes until the mobile ticket ships.
  completed:   "#F3F4F6",  // Tailwind gray-100 — finished / recessive
  cancelled:   "#F3F4F6",  // Tailwind gray-100 — finished / recessive
  skipped:     "#F3F4F6",  // Tailwind gray-100 — finished / recessive
  // Phase P47 · Feb-2026 — ``missed`` is written by the auto-
  // cleanup poller when a job stayed open past
  // ``MISSED_JOB_STALENESS_HOURS`` without a completion.  Slightly
  // deeper red than ``cancelled`` so the two are visually
  // separable on the Schedule surface — cancelled is operator
  // intent, missed is "the system flagged this as unfinished".
  // Deliberately NOT grouped into the finished-state bucket above
  // because ``missed`` is actionable (operator can re-open or
  // re-schedule) and must stay visually prominent.
  missed:      "#FCA5A5",  // Tailwind red-300
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
    pending: "open",         // K57 · Feb-2026 — legacy ``pending`` bucket
                             // adjudicated to the ``open`` colour so
                             // mobile Schedule cards stop rendering
                             // white on pending jobs.  Web + mobile
                             // parity — see ``PHASE_K57_MOBILE_SCHEDULE_PENDING_ALIAS.md``.
  };
  const key = alias[s] || s;
  return K50_JOB_STATUS_BG[key] || null;
}


/**
 * Feb-2026 · Schedule finished-state card styling (operator spec).
 *
 * Returns ``true`` when a job's status falls into the terminal /
 * archive bucket that the Schedule surface renders in a recessive
 * grey style.  Finished buckets (per the operator brief):
 *   * ``completed``
 *   * ``closed``     (US / legacy spelling; aliased in ``alias`` below)
 *   * ``cancelled``  (UK canonical) / ``canceled`` (US alias)
 *   * ``skipped``
 *
 * Deliberately EXCLUDES:
 *   * ``missed``      — actionable (operator can re-open / re-sched)
 *                       so it keeps the red-300 prominence.
 *   * ``could_not_service`` — handled by the broader terminal set in
 *                       ``CalendarSchedule.jsx:_TERMINAL_STATUSES``;
 *                       the finished-styling bucket is intentionally
 *                       narrower (operator did not include it).
 *   * All ``on_hold`` / ``requested`` / ``reopened`` / ``pending``
 *     statuses — these stay visually prominent.
 *
 * @param {string | null | undefined} status
 * @returns {boolean}
 */
export function isFinishedJobStatus(status) {
  const s = String(status || "").toLowerCase().trim();
  if (!s) return false;
  // Canonicalize via the same alias table ``jobStatusColor`` uses
  // so the two helpers never drift (``closed`` → ``completed``,
  // ``canceled`` → ``cancelled``, ``done`` → ``completed``).
  const alias = {
    closed: "completed",
    done: "completed",
    canceled: "cancelled",
  };
  const key = alias[s] || s;
  return key === "completed"
      || key === "cancelled"
      || key === "skipped";
}


/**
 * Feb-2026 · Resolve the recommended body-text hex for a job's
 * Schedule-card background.  Returns a dark-grey ``#374151``
 * (Tailwind gray-700, 10.4:1 contrast against the finished-state
 * ``#F3F4F6`` background — AAA for normal text) for finished
 * statuses; returns ``null`` for every other status so the caller
 * falls through to its existing ``colors.onSurface`` default.
 *
 * The helper is deliberately colocated with ``K50_JOB_STATUS_BG``
 * + ``isFinishedJobStatus`` so the bg + text pair stay locked in
 * a single file (no "update one, forget the other" risk).
 *
 * @param {string | null | undefined} status
 * @returns {string | null}
 */
export function jobStatusTextColor(status) {
  return isFinishedJobStatus(status) ? "#374151" : null;
}
