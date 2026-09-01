/**
 * Phase 20 · Feb-2026 · Sub-item C — session-memoized fetch for the
 * Stripe publishable key + mode.
 *
 * Frontend components that need the publishable key at page-load time
 * (Elements init) call ``getStripeConfig()``. First call hits the
 * backend once; subsequent calls in the same page-session return the
 * cached value.
 *
 * Phase K1 · Feb-2026 — extended to surface ``stripe_configured``
 * (derived from a non-empty publishable_key) so payment surfaces can
 * render a neutral customer-facing fallback instead of exposing
 * env-var names.  A single ``console.warn`` per page-session fires
 * when the backend reports the endpoint is unconfigured so ops sees
 * the pattern in DevTools without flooding.
 *
 * Reason for existing: prior implementation read
 * ``REACT_APP_STRIPE_PUBLISHABLE_KEY(_TEST|_LIVE)`` from the frontend
 * build-time env. That variable is now removed — the key ships from
 * the backend at request time so live/test cutover is one env flip on
 * the server, no rebuild.
 *
 * Falls back gracefully to an empty string + ``stripe_configured:
 * false`` when the backend hasn't been configured; callers should
 * check the flag and render the K1 fallback.
 */
import { api } from "@/api";

let _cached = null;
let _inflight = null;
let _unconfiguredWarned = false;

function _emitUnconfiguredWarnOnce(reason) {
  if (_unconfiguredWarned) return;
  _unconfiguredWarned = true;
  // eslint-disable-next-line no-console
  console.warn(
    "[stripe] publishable key not configured on the server " +
    `(reason: ${reason}). Set STRIPE_PUBLISHABLE_KEY_TEST or ` +
    "STRIPE_PUBLISHABLE_KEY_LIVE in the backend environment. " +
    "Customer-facing surfaces will render the neutral fallback.",
  );
}

/**
 * Resolve `{publishable_key, stripe_configured, mode}` from the
 * backend, cached for the lifetime of the page. Multiple concurrent
 * callers share a single inflight request via the promise cache.
 */
export async function getStripeConfig() {
  if (_cached) return _cached;
  if (_inflight) return _inflight;
  _inflight = api
    .get("/payments/stripe/config")
    .then((r) => {
      const pubKey = r?.publishable_key || "";
      // Backend explicitly signals the state; when older backends
      // don't return the field we derive it from the key so a
      // stale server doesn't break the frontend.
      const stripeConfigured = typeof r?.stripe_configured === "boolean"
        ? r.stripe_configured
        : Boolean(pubKey);
      _cached = {
        publishable_key: pubKey,
        stripe_configured: stripeConfigured,
        mode: r?.mode || "test",
      };
      if (!stripeConfigured) _emitUnconfiguredWarnOnce("empty_pub_key");
      return _cached;
    })
    .catch((err) => {
      // Never let a config-fetch failure crash the calling component —
      // return a null-object so callers render the neutral fallback.
      _cached = {
        publishable_key: "",
        stripe_configured: false,
        mode: "test",
      };
      _emitUnconfiguredWarnOnce(
        `fetch_failed: ${err?.message || String(err)}`);
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
  _unconfiguredWarned = false;
}
