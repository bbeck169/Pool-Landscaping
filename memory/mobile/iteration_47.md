# Iteration 47 — B2 Stripe Card + ACH Native Capture

## Date: 2026-08-30

## What was implemented

### 1. SDK Installation
- `@stripe/stripe-react-native@0.50.3` installed via `npx expo install`
- Config plugin added to `app.json` with `merchantIdentifier: "merchant.com.poolscape.crm"`, `enableGooglePay: false`
- Platform-safe SDK wrapper created (`src/lib/stripeSdk.tsx` + `.web.tsx`) to handle web preview gracefully

### 2. API Layer
- `src/api/stripe.ts` (65 LOC) — typed wrappers for:
  - `getStripeConfig()` → `GET /api/payments/stripe/config`
  - `createSetupIntent(customerId, paymentMethodTypes?)` → `POST /api/payments/stripe/setup-intent`
  - `attachPaymentMethod(customerId, pmId, setDefault?)` → `POST /api/payments/stripe/attach`
  - `listPaymentMethods(customerId)` → `GET /api/payments/stripe/payment-methods/{id}`
  - `removePaymentMethod(pmId)` → `DELETE /api/payments/stripe/payment-methods/{id}`

### 3. Payment Methods Screen
- `app/customer/[id]/payment-methods.tsx` (369 LOC) — full-featured admin screen:
  - A. **Saved methods list** — card + ACH rows with brand/bank, last4, expiry/verification status, default badge
  - B. **Add card** — creates SetupIntent (card default) → initPaymentSheet → presentPaymentSheet → refresh list
  - C. **Add ACH** — creates SetupIntent with `["us_bank_account"]` → PaymentSheet with `allowsDelayedPaymentMethods: true` → shows micro-deposits ACH note
  - D. **Remove** — confirm modal (single-click, no typed-input) → DELETE endpoint → refresh list
  - Wrapped in `<StripeProvider>` with runtime publishable key from `useStripeConfig()`
  - Pull-to-refresh, loading skeletons, empty state, offline banner + disabled buttons

### 4. Customer Detail Update
- Replaced `pmCard` "Send Link" primary button with navigable "Manage" link to `/customer/{id}/payment-methods`
- "Send add-card link to customer" kept as secondary action (email link still useful for remote scenarios)

### 5. Component Library
- `src/components/stripe/PaymentMethodRow.tsx` (165 LOC) — reusable row component:
  - Card: brand icon + last4 + expiry + default chip
  - ACH: bank icon + last4 + verification status chip (verified/unverified/pending/failed)
  - Remove button with destructive styling

### 6. Web Bundling Fix
- Created `src/services/sync/db.web.ts` — no-op shim for expo-sqlite on web
- Fixes pre-existing Metro web bundling failure (wasm resolution) that was masked by cached bundle

### Portal status
- `portal/payment-method.tsx` — existing hosted-web WebBrowser flow retained (functional)
- `portal/add-card.tsx` — existing hosted add-card page retained
- Native capture on portal deferred (customer portal has simpler hosted-web flow that works)

## Test results
| Suite | Tests | Status |
|-------|-------|--------|
| stripe-payment-sheet-init.test.tsx | 3/3 | ✅ |
| stripe-payment-methods-list.test.tsx | 5/5 | ✅ |
| stripe-offline-banner.test.tsx | 1/1 | ✅ |
| stripe-attach-round-trip.test.tsx | 1/1 | ✅ |
| **Full regression** | **726/747** | 8 pre-existing, 0 new |

## Platform Notes
- **Expo prebuild required**: The `@stripe/stripe-react-native` SDK's `PaymentSheet` needs native modules (EAS Build / `expo run:ios` / `expo run:android`). On web preview, the add card/ACH buttons show a graceful "native build required" alert.
- The `.web.tsx` / `.tsx` platform file pattern is the correct way to handle this — Metro auto-selects the right file.
- Existing StripeConfigProvider (fetching pk from API at boot) is reused.
- The hosted-web email-link flow is preserved as a secondary action.

## Dependencies installed
- `@stripe/stripe-react-native@0.50.3`
