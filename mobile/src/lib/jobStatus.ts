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
    // Oct-2026 mobile hotfix — completed/closed cards RECEDE: soft green
    // emerald-50 #ECFDF5 (was bold coral-red #ff4542, web 85fd76f17).
    // Deliberate MOBILE-ONLY divergence from web (operator request: red
    // was hard to read + visually dominant). Standard dark text stays.
    completed: "#ECFDF5",
    cancelled: "#FECACA",
    skipped: "#FED7AA",
  });

/** Receded completed-card treatment (Oct-2026 mobile hotfix).
 *  BG derived from the map so the card + helpers can't drift apart.
 *  On #ECFDF5: primary text #09090B ≈ 19:1, secondary #52525B ≈ 7.3:1
 *  (replaces the old white flip; service-tag hues like #059669 would
 *  sit < 4.5:1 on green), ✓ accent dark green #065F46 ≈ 7.3:1. */
export const K50_COMPLETED_BG = K50_JOB_STATUS_BG.completed;
export const K50_COMPLETED_MUTED_FG = "#52525B";
export const K50_COMPLETED_ACCENT = "#065F46";

/** True for completed / closed / done (anything resolving to the completed bg). */
export function isCompletedCardStatus(status?: string | null): boolean {
  return jobStatusColor(status) === K50_COMPLETED_BG;
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
