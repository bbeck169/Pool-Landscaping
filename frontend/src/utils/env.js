/**
 * Feb-2026 · Preview/dev environment detection.
 *
 * Fail-closed hostname + build-mode gate used by anything that must
 * NEVER render on customer-facing production (e.g. the demo-logins
 * block on the login page).
 *
 * Rules:
 *  - Preview hosts: any subdomain of ``preview.emergentagent.com``.
 *  - Dev builds: Vite ``import.meta.env.MODE === "development"`` or
 *    CRA/webpack ``process.env.NODE_ENV === "development"``.
 *  - ``localhost`` / ``127.0.0.1`` / ``0.0.0.0`` are treated as dev.
 *  - Every other hostname (production custom domains like
 *    ``app.plofv.com``) → ``false``.
 *
 * WHY belt-and-suspenders (Feb-2026 P0 incident):
 * The prior gate read the backend's ``/api/config/public.app_env``
 * value. The prod backend on ``app.plofv.com`` had been deployed with
 * ``APP_ENV=preview`` + ``SHOW_DEMO_LOGINS=true`` in its ``.env`` — a
 * seeded env-var drift — so the endpoint reported "preview" and the
 * demo tiles leaked to a live customer domain. A hostname check
 * that ships in the client bundle can never be talked out of hiding
 * the block on a wrong-env production deploy.
 */

function _hostname() {
  try {
    if (typeof window !== "undefined" && window.location && window.location.hostname) {
      return String(window.location.hostname).toLowerCase();
    }
  } catch (_) { /* jsdom / SSR */ }
  return "";
}

function _isDevMode() {
  try {
    // Vite build → import.meta.env.MODE. CRA/webpack fall-through
    // via ``process.env.NODE_ENV``. We probe both so this file
    // stays universal across the vite migration and any legacy
    // CRA leftovers in the tree.
    // eslint-disable-next-line no-undef
    if (typeof import.meta !== "undefined" && import.meta.env
        && import.meta.env.MODE === "development") return true;
  } catch (_) { /* older bundlers strip ``import.meta`` */ }
  try {
    if (typeof process !== "undefined" && process.env
        && process.env.NODE_ENV === "development") return true;
  } catch (_) { /* strict CSP / no process */ }
  return false;
}

/** True when the current browser context is preview or dev. */
export function isPreviewOrDev() {
  if (_isDevMode()) return true;
  const h = _hostname();
  if (!h) return false;
  if (h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0") return true;
  // Any *.preview.emergentagent.com subdomain (Emergent's preview
  // ingress). We match on suffix so both the top-level
  // "poolscape-audit.preview.emergentagent.com" and future preview
  // clone hosts are covered.
  if (h.endsWith(".preview.emergentagent.com")) return true;
  return false;
}

/** Explicit inverse — semantic sugar for hide-in-prod call sites. */
export function isProductionHost() {
  return !isPreviewOrDev();
}
