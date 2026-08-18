/**
 * Feb-2026 · Preview/dev environment detection (mobile parity).
 *
 * Mirrors ``frontend/src/utils/env.js`` — the SAME hostname gate
 * shipped as a defense-in-depth measure after the demo-tiles prod
 * leak on ``app.plofv.com``. Native mobile has no ``window.location``
 * so we lean on ``EXPO_PUBLIC_BACKEND_URL`` (baked in at build time
 * from the Expo ``.env`` — same host the client is actually talking
 * to) plus the ``__DEV__`` runtime flag.
 *
 * Rules:
 *  - ``__DEV__`` true (Metro / dev-client) → preview.
 *  - ``EXPO_PUBLIC_BACKEND_URL`` host ends with
 *    ``preview.emergentagent.com`` → preview.
 *  - ``EXPO_PUBLIC_BACKEND_URL`` host is a localhost variant → preview.
 *  - Anything else → production (fail-closed).
 */

function _backendHost(): string {
  try {
    const url = process.env.EXPO_PUBLIC_BACKEND_URL || "";
    if (!url) return "";
    // ``new URL`` is available in Hermes 0.72+; we still guard.
    const u = new URL(url);
    return (u.hostname || "").toLowerCase();
  } catch (_) {
    return "";
  }
}

export function isPreviewOrDev(): boolean {
  // ``__DEV__`` is a global injected by the React Native runtime.
  // Wrap in a try in case a lint/typecheck env strips it.
  try {
    // @ts-ignore — RN global
    if (typeof __DEV__ !== "undefined" && __DEV__) return true;
  } catch (_) { /* noop */ }
  const h = _backendHost();
  if (!h) return false;
  if (h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0") return true;
  if (h.endsWith(".preview.emergentagent.com")) return true;
  if (h === "preview.emergentagent.com") return true;
  return false;
}

export function isProductionHost(): boolean {
  return !isPreviewOrDev();
}
