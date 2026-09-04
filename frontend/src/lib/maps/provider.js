/**
 * Phase K39a · Feb-2026 — Runtime provider resolver.
 *
 * Resolves ``REACT_APP_MAPS_PROVIDER`` (default "google") down to
 * the actual provider we should render. If the flag asks for HERE
 * but ``REACT_APP_HERE_API_KEY`` is empty, we emit a **single** boot-
 * time console.warn and silently fall back to Google.
 *
 * Kept as a pure function so vitest can call it with an injected env.
 */

let _warned = false;

export function _resetWarnedForTests() {
  _warned = true; // start at "already warned" so tests can flip below
  _warned = false;
}

export function _computeProvider(env = process.env) {
  const raw = (env.REACT_APP_MAPS_PROVIDER || "google").toLowerCase();
  const wanted = raw === "here" ? "here" : "google";
  const hereKey = env.REACT_APP_HERE_API_KEY || "";
  if (wanted === "here" && !hereKey) {
    if (!_warned && typeof console !== "undefined") {
      // eslint-disable-next-line no-console
      console.warn(
        "[maps] REACT_APP_MAPS_PROVIDER=here but REACT_APP_HERE_API_KEY " +
          "is empty — falling back to Google Maps.",
      );
      _warned = true;
    }
    return "google";
  }
  return wanted;
}

/**
 * React hook. Stable across the lifecycle of a session — env vars
 * don't change at runtime — so we compute once on module import.
 * (A hook shape is still exposed to keep the API idiomatic and to
 * leave room for a future runtime override without breaking
 * consumers.)
 */
const _CACHED = _computeProvider();

export function useMapsProvider() {
  return _CACHED;
}
