/**
 * Phase 53 · Stripe Elements bootstrap.
 *
 * Exports a memoized `stripePromise` that lazy-loads the Stripe.js
 * bundle once we know the publishable key. Uses our own
 * `/api/stripe/publishable-key` endpoint so we never bake the key
 * into the frontend build.
 */
import { loadStripe } from "@stripe/stripe-js";
import { api } from "@/api";

let _promise = null;

export function getStripePromise() {
  if (_promise) return _promise;
  _promise = (async () => {
    try {
      const r = await api.get("/stripe/publishable-key");
      const pk = r?.publishable_key || r?.key;
      if (!pk) return null;
      return await loadStripe(pk);
    } catch {
      return null;
    }
  })();
  return _promise;
}
