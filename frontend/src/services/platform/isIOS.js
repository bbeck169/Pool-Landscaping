/**
 * Feb-2026 · Clickable Customer Data · shared platform sniff.
 *
 * Small SSR-safe helper for `<AddressLink>` so that iOS UAs open in
 * Apple Maps (better native handoff on iPhone/iPad) while everything
 * else lands on Google Maps. Kept intentionally trivial and free of
 * dependencies — the primitive re-runs on every render, so shaving
 * the regex allocation is not worth caching complexity.
 */

const _IOS_RX = /iP(hone|ad|od)/;

export function isIOS(ua) {
  const s = ua != null
    ? String(ua)
    : (typeof navigator !== "undefined" ? navigator.userAgent : "");
  return _IOS_RX.test(s || "");
}

export default isIOS;
