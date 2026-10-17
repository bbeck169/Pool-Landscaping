/**
 * Phase K50 · Feb-2026 — Schedule job-card status background shading.
 *
 * MOBILE mirror of ``frontend/src/lib/jobStatus.js`` — same status
 * keys, same hex values, same alias table.  Web + mobile Schedule
 * cards MUST render identically per the K50 brief.
 *
 * TODO(I13) — Tenant theme override.
 * ------------------------------------------------------------------
 * Phase I1.5.c.fix · Feb-2026: The web sibling reskins the
 * ``open``/``scheduled`` mint tile background under a tenant preset
 * via the ``--tenant-schedule-tile-bg`` CSS custom property (see
 * ``frontend/src/index.css`` `[data-k50-bg="#EAF7F0"]` rule +
 * ``frontend/src/theme/tenantVars.js`` derived-var wiring).
 *
 * React Native has no CSS-var substrate, so the mobile Schedule
 * card cannot participate in that overlay from *this* module — the
 * ``K50_JOB_STATUS_BG`` map deliberately keeps its static hex so
 * web + mobile parity is preserved when no tenant override is set.
 *
 * When Phase I13 (mobile tenant theme parity) lands, wire the
 * consumer to read the persisted ``tenant.theme.accents.badge_bg``
 * (fallback ``#EAF7F0``) via a hook instead of ``jobStatusColor()``
 * for the ``open``/``scheduled`` bucket only. Do NOT mutate this
 * frozen map — the K50/K74.1 contract locks it for every non-tenant
 * path (e.g. tests, cached data, offline mode).
 */

export const K50_JOB_STATUS_BG: Readonly<Record<string, string>> =
  Object.freeze({
    // Phase K74.1 · Feb-2026 — mint-green lightening; parity with
    // ``frontend/src/lib/jobStatus.js``. ``open``/``scheduled`` moved
    // from ``#D6F5EE`` → ``#EAF7F0``.  Web + mobile MUST match.
    open: "#EAF7F0",
    scheduled: "#EAF7F0",
    in_progress: "#FEF3C7",
    // Feb-2026 · Schedule finished-state card styling — parity with web
    // e62babc5f (frontend/src/lib/jobStatus.js). All finished states
    // (completed / closed / cancelled / skipped) → Tailwind gray-100 so
    // finished cards recede; body text #374151 via jobStatusTextColor
    // (9.37:1 on #F3F4F6, AAA; web comment's 10.4:1 is vs white). Replaces the Oct-2026 mobile-only soft
    // green #ECFDF5 + red/orange cancelled/skipped.
    completed: "#F3F4F6",
    cancelled: "#F3F4F6",
    skipped: "#F3F4F6",
    // NOT finished — actionable, stays prominent (web parity).
    missed: "#FCA5A5",
  });

/** Completed-card accents (✓ icon). BG derived from the map so the
 *  card + helpers can't drift apart. On #F3F4F6: body #374151 ≈ 9.37:1,
 *  ✓ accent #065F46 ≈ 6.98:1. `K50_COMPLETED_MUTED_FG` is kept for
 *  existing importers; finished cards now use `K50_FINISHED_FG`. */
export const K50_COMPLETED_BG = K50_JOB_STATUS_BG.completed;
export const K50_COMPLETED_MUTED_FG = "#52525B";
export const K50_COMPLETED_ACCENT = "#065F46";
export const K50_FINISHED_FG = "#374151";

/** True for completed / closed / done only (drives the ✓ icon). Alias-based —
 *  cancelled/skipped share the finished bg but are NOT "completed". */
export function isCompletedCardStatus(status?: string | null): boolean {
  const s = String(status ?? "").toLowerCase().trim();
  return (_ALIAS[s] || s) === "completed";
}

/**
 * Web parity (e62babc5f `isFinishedJobStatus`): true for the terminal /
 * archive bucket rendered in the recessive grey style — completed
 * (+ closed / done), cancelled (+ canceled), skipped. Case- and
 * whitespace-insensitive. Excludes `missed`, `could_not_service`, and
 * every open / in-progress / on_hold / requested / reopened / pending.
 */
export function isFinishedJobStatus(status?: string | null): boolean {
  const s = String(status ?? "").toLowerCase().trim();
  if (!s) return false;
  const alias: Record<string, string> = { closed: "completed", done: "completed", canceled: "cancelled" };
  const key = alias[s] || s;
  return key === "completed" || key === "cancelled" || key === "skipped";
}

/** Web parity (`jobStatusTextColor`): #374151 for finished states, else
 *  null so the renderer keeps its existing default text color. */
export function jobStatusTextColor(status?: string | null): string | null {
  return isFinishedJobStatus(status) ? K50_FINISHED_FG : null;
}

const _ALIAS: Readonly<Record<string, string>> = Object.freeze({
  active: "in_progress",
  in_progress: "in_progress",
  inprogress: "in_progress",
  closed: "completed",
  done: "completed",
  canceled: "cancelled",
  pending: "open", // K57 · Feb-2026 — parity with web helper.
});

/**
 * Resolve the K50 background hex for a given job status.
 *
 * Case-insensitive; trims whitespace; returns ``null`` for any
 * unknown / empty status so the caller can fall back to its
 * previous default (typically ``colors.surface``).
 */
export function jobStatusColor(status?: string | null): string | null {
  const s = String(status ?? "").toLowerCase().trim();
  if (!s) return null;
  const key = _ALIAS[s] || s;
  return K50_JOB_STATUS_BG[key] || null;
}
