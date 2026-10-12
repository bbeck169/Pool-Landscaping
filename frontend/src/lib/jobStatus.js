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
  // Phase 3 · Feb-2026 — "Bold red" completed treatment (user
  // request).  The soft-pink #FDECEC was indistinguishable from
  // open jobs at a glance; bumped to a bright coral-red with
  // white text applied via the ``[data-k50-bg="#ff4542"]``
  // cascade in ``index.css``.  Feb-2026 Schedule polish — the
  // exact hex is now ``#ff4542`` (contrast against white text
  // drops from ~5.9:1 at the prior Tailwind red-600 #DC2626 to
  // ~4.1:1, still AA for large text — recorded for future
  // auditability).  Mobile parity ticket is separate
  // (``mobile/src/lib/jobStatus.ts`` keeps the prior hex until
  // that ticket ships).
  completed:   "#ff4542",  // bright coral-red — dramatic completed signal
  cancelled:   "#FECACA",  // light red (Tailwind red-200) — deliberately
                           // redder than ``completed`` so day/week views
                           // separate the two at a glance
  skipped:     "#FED7AA",  // light orange (Tailwind orange-200)
  // Phase P47 · Feb-2026 — ``missed`` is written by the auto-
  // cleanup poller when a job stayed open past
  // ``MISSED_JOB_STALENESS_HOURS`` without a completion.  Slightly
  // deeper red than ``cancelled`` so the two are visually
  // separable on the Schedule surface — cancelled is operator
  // intent, missed is "the system flagged this as unfinished".
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
