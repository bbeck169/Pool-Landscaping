# Task QQ · Stripe → Lumino migration audit — Feb 2026

## Priority buckets (backend)

### P0 — blocks Add-a-Card (SetupIntent + Vaulted PMs)
| File | Function | Stripe call | Lumino equivalent |
|------|----------|-------------|-------------------|
| `routers/customer_portal.py` | Add-a-card magic link | `stripe.SetupIntent.create` + Elements | `POST /v1/vaulting/sessions` (hosted vault URL) |
| `routers/payments_stripe_live.py` | Portal add-card endpoint | `SetupIntent`, `PaymentMethod.attach` | Vaulting sessions + `POST /v1/customers/{id}/methods` |
| `services/stripe_client.py` | Shared SDK bootstrap | `stripe.api_key = env` | `LuminoClient(api_url, token)` |
| `frontend/src/pages/portal/AddCardPage.jsx` | Elements mount | Stripe.js publishable key | Lumino hosted URL redirect |
| `frontend/src/components/PaymentForm.jsx` | Card element | Stripe Elements | (Phase 2 · replaced by redirect) |

### P1 — blocks Autobilling + one-shot Pay Now
| File | Function | Stripe call | Lumino equivalent |
|------|----------|-------------|-------------------|
| `routers/stripe_payments.py` | Charge saved card | `PaymentIntent.create` (`confirm=true`, `off_session=true`) | `POST /v1/payments` with `method_id` |
| `routers/dunning.py` | Retry failed autopay | Same as above | Same |
| `routers/customer_portal.py::pay_invoice_now` | Portal Pay Now button | `PaymentIntent.create` (interactive) | `POST /v1/payment-sessions` (hosted checkout URL) |
| `routers/finances.py` | Autobilling subscription CRUD | `Subscription.create/update/cancel` | `POST /v1/subscriptions` |

### P2 — webhooks, refunds, admin sync
| File | Function | Stripe call | Lumino equivalent |
|------|----------|-------------|-------------------|
| `routers/stripe_webhooks_live.py` | Event receiver | `stripe.Webhook.construct_event` | HMAC-SHA256 on `x-lumino-signature` |
| `routers/stripe_customer_sync_admin.py` | Admin sync/reconcile | `Customer.retrieve/list` | `GET /v1/customers` |
| `services/stripe_customer_sync.py` | Nightly cron | `Customer.list` | Same |
| `routers/finances.py::refund_*` | Manual refund | `Refund.create` | `POST /v1/refunds` |
| `routers/stripe_admin.py` | Admin tools | Various | Various |
| `services/stripe_key_health.py` | Key-alive health-check | `Balance.retrieve` | `GET /v1/health` |
| `routers/reports.py` | Stripe fees / reconciliation | `BalanceTransaction.list` | `GET /v1/settlements` |

### P3 — removed at cutover (Phase 3)
- All `stripe_customer_id` + `payment_intent_id` fields on documents remain during Phase 1/2. **Do not drop.** After Phase 3 cutover we can null them out (retain for audit).

## Data-migration touchpoints (per collection)

| Collection | Stripe field(s) | Lumino field(s) added by migration |
|------------|-----------------|------------------------------------|
| `customers` | `stripe_customer_id` | `lumino_customer_id` |
| `payment_methods` | `stripe_payment_method_id`, `stripe_customer_id` | `lumino_payment_method_id` |
| `invoices` / `payments` | `payment_intent_id`, `stripe_charge_id` | `lumino_transaction_id`, `lumino_payment_session_id` |
| `subscriptions` (autobilling) | `stripe_subscription_id` | `lumino_subscription_id` |
| `payment_events` (webhooks) | `stripe_event_id` | `lumino_event_id` |

## Counts (grep-derived, `/app/backend/routers` only)
- Router files importing `stripe`: **13**
- Router files with `stripe_customer_id` reference: **7**
- Router files with `payment_intent_id` reference: **5**
- Router files with `stripe_subscription_id` reference: **3**

## Frontend touchpoints
- `frontend/src/lib/stripe.js` — publishable-key loader (Phase 2)
- `frontend/src/components/stripe/StripePayments.jsx` — Elements mount (Phase 2, replace with redirect)
- `frontend/src/components/PaymentForm.jsx` — card form (Phase 2 delete)
- `frontend/src/pages/portal/AddCardPage.jsx` — swap Elements for hosted-URL redirect (Phase 2)
- 15+ admin pages reference `stripe_customer_id` for display only — will still show it during dual-run window; Phase 3 renames to `lumino_customer_id`.

## Phase 1 scope (this batch)
Only the abstraction layer + webhook receiver + env scaffolding + Task-BB extension. No existing Stripe code path modified. No frontend UI changes. No live Lumino calls (env placeholders only).
