/**
 * Phase 20 · Feb-2026 · Sub-item C — session-memoized fetch for the
 * Stripe publishable key + mode.
 *
 * Frontend components that need the publishable key at page-load time
 * (Elements init) call ``getStripeConfig()``. First call hits the
 * backend once; subsequent calls in the same page-session return the
 * cached value.
 *
 * Reason for existing: prior implementation read
 * ``REACT_APP_STRIPE_PUBLISHABLE_KEY(_TEST|_LIVE)`` from the frontend
 * build-time env. That variable is now removed — the key ships from
 * the backend at request time so live/test cutover is one env flip on
 * the server, no rebuild.
 *
 * Falls back gracefully to an empty string when the backend hasn't
 * been configured (in which case Elements will surface its own
 * "publishable key required" error).
 */
import { api } from "@/api";

let _cached = null;
let _inflight = null;

/**
 * Resolve `{publishable_key, mode}` from the backend, cached for the
 * lifetime of the page. Multiple concurrent callers share a single
 * inflight request via the promise cache.
 */
export async function getStripeConfig() {
  if (_cached) return _cached;
  if (_inflight) return _inflight;
  _inflight = api
    .get("/payments/stripe/config")
    .then((r) => {
      _cached = {
        publishable_key: r?.publishable_key || "",
        mode: r?.mode || "test",
      };
      return _cached;
    })
    .catch(() => {
      // Never let a config-fetch failure crash the calling component —
      // return a null-object so Elements surfaces its own error.
      _cached = { publishable_key: "", mode: "test" };
      return _cached;
    })
    .finally(() => {
      _inflight = null;
    });
  return _inflight;
}

/** Testing shim — clears the module-level cache so pytest / vitest
 *  can exercise a fresh fetch cycle. Do not call from prod code.
 */
export function _resetStripeConfigCacheForTests() {
  _cached = null;
  _inflight = null;
}
