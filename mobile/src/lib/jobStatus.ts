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
    // Phase 3 · Feb-2026 — "Bold red" completed (web parity, 5f89f2588).
    // Was soft-pink #FDECEC → Tailwind red-600 #DC2626. Bumped to bright
    // coral-red #ff4542 (web parity, 85fd76f17). Cards on this bg flip
    // text/icons to white (white-on-#ff4542 ≈ 4.1:1 — AA large text).
    completed: "#ff4542",
    cancelled: "#FECACA",
    skipped: "#FED7AA",
  });

/** Bold-red completed bg + the white foreground used on it.
 *  Derived from the map (not a literal) so a future completed-hex bump
 *  can't silently drop the white-text flip in ``isBoldRedStatus``. */
export const K50_BOLD_RED_BG = K50_JOB_STATUS_BG.completed;
export const K50_ON_BOLD_RED_FG = "#FFFFFF";

/** True when the card bg is the bold-red completed treatment. */
export function isBoldRedStatus(status?: string | null): boolean {
  return jobStatusColor(status) === K50_BOLD_RED_BG;
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
