## Iteration 61 — Phase K23: Mobile parity for K1 Stripe-not-configured fallback
- **Commit**: 99b1e82a9d222de3aea91e1215dbe5972fc5f6a0
- **Date**: 2026-09-02
- **Changes**:
  - Created `src/lib/stripeConfig.tsx`:
    - `StripeUnconfiguredNotice` — full-card amber placeholder (alert icon + "Stripe payments not configured" + custom message)
    - `StripeUnconfiguredBanner` — compact inline variant for embedding in tiles/cards
    - Both with testIDs, customizable messages
  - Updated `src/config/stripe.tsx`:
    - Added `stripeConfigured: boolean` to StripeConfig context type
    - Derived fail-closed: `pk.length > 0` → true, else false
    - Default context value: `stripeConfigured: false`
  - Guarded 6 payment surfaces:
    1. `customer/[id]/payment-methods.tsx` — `StripeUnconfiguredNotice` + disabled Add card/ACH buttons when `!stripeConfigured`
    2. `invoice/[id].tsx` — `StripeUnconfiguredNotice` replaces Pay Now button when `!stripe.stripeConfigured`
    3. `payments/methods.tsx` — `StripeUnconfiguredNotice` + disabled Add card button when `!stripeConfigured`
    4. `portal/payment-method.tsx` — `StripeUnconfiguredNotice` replaces Add button (was inline text-only notice); button hidden entirely when unconfigured
    5. `quote/[id].tsx` — `StripeUnconfiguredNotice` replaces customer Pay Now when `!stripeConfigured`
    6. `PaymentMethodTiles.tsx` — `StripeUnconfiguredBanner` inline banner above tiles when `!stripeConfigured`
  - Tests: 6 new in `__tests__/stripeConfig.test.tsx`, all passing
  - Metro bundles clean, all 8 modified files lint clean
  - `portal/payment-method.tsx` also reads `stripe_configured` from API response (server-side flag) — preserved existing behavior, enhanced with shared notice component
- **Files created**: `src/lib/stripeConfig.tsx`, `__tests__/stripeConfig.test.tsx`
- **Files modified**: `src/config/stripe.tsx`, `app/customer/[id]/payment-methods.tsx`, `app/invoice/[id].tsx`, `app/payments/methods.tsx`, `app/portal/payment-method.tsx`, `app/quote/[id].tsx`, `src/components/customers/PaymentMethodTiles.tsx`
- **Web files referenced**: K1 web pattern (frontend StripeUnconfigured fallback)
- **Key decisions**:
  - `stripeConfigured` derived from pk presence (fail-closed), not a separate API call
  - `portal/payment-method.tsx` preserves server-side `stripe_configured` flag from `/customer-portal/payment-methods` response as additional guard
  - Both Notice (full card) and Banner (compact inline) variants for different contexts
