## Iteration 65 — Phase K27: Soshie API shape + Set-default payment method
- **Commit**: 7d68485e8b713bc31dca244dbd40334d4c25d4f3
- **Date**: 2026-09-02
- **Changes**:
  ### Part E — Soshie moderation API normalization
  - `src/api/soshieModeration.ts`: Response type changed from `{ posts: ModerationPost[] }` to `{ items: ModerationPost[] }` (aligns with backend response)
  - `app/(app)/soshie-moderation.tsx` line 296: `res?.posts` → `res?.items` (was reading empty array because backend returns `items` key)
  
  ### Part F — Set-default payment method
  - `src/components/stripe/PaymentMethodRow.tsx`:
    - Added `onSetDefault` + `settingDefault` props
    - Non-default cards: star icon + "Set default" pill button (blue on light blue background)
    - Default cards: only "Default" chip shown, no button
    - Loading state: "Setting…" text while POST in flight
    - Wrapped in `actions` row alongside existing remove button
  - `app/customer/[id]/payment-methods.tsx`:
    - Added `settingDefaultId` state
    - Added `onSetDefault` handler: `POST /payments/stripe/payment-methods/{pm_id}/set-default`
    - Refetches list on success, Alert on error
    - Guarded by `stripeConfigured` (K23 interlock) — passes `undefined` for `onSetDefault` when Stripe unconfigured
  - Portal side (`portal/payment-method.tsx`): **No changes needed** — displays single method only (no multi-card list)
  
  ### Tests: 7 new in `__tests__/k27_setDefault.test.tsx`
  - 5 PaymentMethodRow tests (default/non-default rendering, press handler, missing prop, loading state)
  - 2 Soshie API shape tests (items vs posts normalization)
  - All passing, all files lint clean, Metro clean
- **Files modified**: `soshieModeration.ts`, `soshie-moderation.tsx`, `PaymentMethodRow.tsx`, `customer/[id]/payment-methods.tsx`
- **Files created**: `__tests__/k27_setDefault.test.tsx`
