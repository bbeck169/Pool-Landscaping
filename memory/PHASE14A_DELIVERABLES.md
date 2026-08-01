# Phase 14a · Feb-2026 — Stripe Re-Integration · Deliverables Report

## Investigation micro-report
1. `requirements.txt`: no `stripe` — clean.
2. Backend: no `import stripe` / `from stripe` — clean.
3. Frontend: no `@stripe/*` / `stripe-js` — clean.
4. Dangling env: `frontend/.env` line 7 (`REACT_APP_STRIPE_PUBLISHABLE_KEY=pk_live_...`) preserved per env rules; superseded by `_TEST`/`_LIVE` split.
5. UI mount points located: `pages/portal/*`, `pages/customers/CustomerDetail.jsx`.

## Files shipped
### Backend
- `services/payments/stripe_charge.py` (5 async helpers + webhook helpers)
- `routers/stripe_router.py` (6 endpoints)
- `tests/test_stripe_phase14a.py` (18 cases · 15 pass, 3 skip on missing prereqs)
- `server.py` — router include (parallel to `payments_summary` block)
- `requirements.txt` — `stripe>=13.0.0,<15.0.0` (`stripe==14.4.1` installed)
- `.env` — `STRIPE_MODE`, `STRIPE_SECRET_KEY_TEST/LIVE`, `STRIPE_WEBHOOK_SECRET_TEST/LIVE`, `STRIPE_PUBLISHABLE_KEY_TEST/LIVE`

### Frontend
- `components/payments/StripeAddCardForm.jsx` (reusable Elements form)
- `components/customers/AdminCardCapturePanel.jsx` (admin on-behalf capture)
- `pages/portal/PortalPaymentMethods.jsx` (customer self-serve)
- `pages/customers/CustomerDetail.jsx` — Payments tab mount + import
- `App.js` — `/portal/payment-methods` route + import
- `.env` — `REACT_APP_STRIPE_MODE`, `REACT_APP_STRIPE_PUBLISHABLE_KEY_TEST/LIVE`
- `package.json` — `@stripe/stripe-js@9.12.1`, `@stripe/react-stripe-js@6.8.0`

## Endpoints (all under `/api/payments/stripe/*`)
- `POST /setup-intent`               — customer self OR admin+ (admin must pass `customer_id`)
- `POST /attach`                     — customer self OR admin+
- `GET  /payment-methods/{cid}`      — customer self OR admin+; tech 403
- `DELETE /payment-methods/{pm_id}`  — customer own OR admin+; tech 403
- `POST /charge`                     — admin/manager/super_admin ONLY (tech + customer 403)
- `POST /webhook`                    — public; signature verified inline

## Collections
- `db.stripe_charges` (fresh) — every charge attempt logged. Legacy `db.stripe_payments_live` NOT resurrected.
- `db.payment_methods` — reused with `provider="stripe"` field so Lumino rows (if any) stay isolated.

## Mode split
`STRIPE_MODE` (test|live) drives:
- Backend: `STRIPE_SECRET_KEY_TEST` / `_LIVE`, `STRIPE_WEBHOOK_SECRET_TEST` / `_LIVE`
- Frontend: `REACT_APP_STRIPE_PUBLISHABLE_KEY_TEST` / `_LIVE`

Fallback chain: mode-specific → `STRIPE_API_KEY` (platform-injected `sk_test_emergent`) → hardcoded `sk_test_emergent`. Preview works without extra config.

## Test summary
```
15 passed, 3 skipped in 9.12s
```
Skips: 2 router happy-paths need a real `STRIPE_SECRET_KEY_TEST=sk_test_...` (cross-process stub not possible); 1 needs a technician demo login that isn't seeded in this preview.

## Smoke tests (external)
- `POST /api/payments/stripe/setup-intent` (no auth) → 403 ✓
- `GET  /api/payments/stripe/payment-methods/{cid}` (no auth) → 403 ✓
- `POST /api/payments/stripe/webhook` (no sig, empty secret) → 400 ✓

## Deferred (per user brief)
- Phase 14b: Invoice Filters + Bulk Charge-Card-on-File (uses `charge_card_on_file` primitive shipped here).
