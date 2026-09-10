# FEATURE — Admin Add-Card-on-File (inline SetupIntent)

**Date shipped**: Feb 10, 2026 · Preview
**Scope**: Rewired the top-of-page "Add card on file" button on the admin Customer detail page. No more email round-trip — the admin now inputs the customer's card directly into Stripe's PaymentElement.
**Status**: ✅ SHIPPED to preview. Not yet in production (user redeploys.)

## What & Why

Admins holding a physical card at the pool / dispatch bench asked to skip the customer-portal round-trip. The old "Send add-card link" button emailed the customer, who then had to click through and enter the card themselves. Now the button opens a modal, Stripe Elements mounts inline against a fresh SetupIntent, and the card is saved on file in-place. No email. No portal.

## API surface

### New — `POST /api/customers/{cid}/setup-intent` (admin alias)
Thin admin-scoped alias that **delegates to the existing Task-5 primitive** `services.payments.stripe_charge.create_setup_intent`. Same envelope as the sibling `POST /api/payments/stripe/setup-intent`:

```json
{
  "client_secret": "seti_..._secret_...",
  "setup_intent_id": "seti_...",
  "stripe_customer_id": "cus_...",
  "mode": "test" | "live",
  "publishable_key": "pk_test_..." | "pk_live_..."
}
```

- **Auth**: admin / manager / super_admin. Customer / technician → 403. Unauthenticated → 401. Unknown customer → 404. Stripe upstream error → 502.
- Delegates 100% to the Task-5 primitive — **no new payment logic**. The customer-scoped URL exists so the admin call site owns a clean URL shape without diverging from the sibling self-serve endpoint.

### Unchanged (reused verbatim)
- `POST /api/payments/stripe/attach` — the child `StripeAddCardForm` posts the PaymentMethod id here to mirror into `payment_methods`. Task-5 code path.
- `payment_method.attached` webhook in `stripe_charge.handle_webhook_event` — mirrors PMs into `payment_methods` for any attach that Stripe fires (belt-and-braces if the FE-driven attach fails).
- `setup_intent.succeeded` webhook — verifies the SetupIntent lifecycle.

## Frontend

### New component — `AdminAddCardOnFileModal.jsx`
Dialog wrapper around the pre-existing `StripeAddCardForm` (Phase 14a). Fetches `GET /api/payments/stripe/config` for the publishable key, passes `customerId` for admin-on-behalf, closes on success and fires an `onSuccess(row)` callback for the parent to refetch. Test-ids:
- `add-card-on-file-modal`
- `add-card-on-file-modal-title`
- `add-card-on-file-modal-cancel`
- (child) `stripe-add-card-form`, `stripe-add-card-submit`, `stripe-add-card-cancel`, `stripe-add-card-error`, `stripe-payment-element`

### Rewired — `CardOnFileWarningBanner.jsx`
Same testid contract (`card-on-file-send-link-btn`), same visibility gate (`effective_require_card_on_file && !has_card_on_file`). Button label changed from "Send add-card link" → **"Add card on file"** with a `<CreditCard>` icon. onClick opens `AdminAddCardOnFileModal` instead of POSTing the old email endpoint. On modal success:
- `onCardAdded(row)` — parent (`CustomerDetail`) triggers `load()` to refetch the customer.
- `onSent(msg)` — legacy toast wire preserved but now only fires on a **real** Stripe success (never a silent no-op — this closes the "toast lies" bug from the P1 diagnostic).

### `CustomerDetail.jsx`
Added `onCardAdded={() => load()}` to the banner instance inside the top action stack. One-line change.

## Files touched

**Backend (1)**
- `backend/routers/customers.py` — new `POST /customers/{cid}/setup-intent` admin alias (~45 lines including RBAC + docstring).

**Frontend (3)**
- `frontend/src/components/customers/AdminAddCardOnFileModal.jsx` — new (~120 lines). Reuses `StripeAddCardForm` verbatim.
- `frontend/src/components/customers/CardOnFileWarningBanner.jsx` — rewritten from scratch (email send → modal open). Same size; smaller call surface.
- `frontend/src/pages/customers/CustomerDetail.jsx` — 1 prop plumbed (`onCardAdded`).

**Tests (2)**
- `backend/tests/test_admin_add_card_on_file.py` — 7 pytest cases (envelope, admin/manager/super_admin allowed, customer role 403, tech 403, unknown customer 404, Stripe error 502, `payment_method.attached` webhook mirror regression guard). All green.
- `frontend/src/test/admin-add-card-on-file.test.jsx` — 4 vitest cases (button opens modal + no email fetch, confirm success → close + refetch, error surfaces inline + modal stays open, cancel is a no-op). All green.

**Docs (1)**
- `memory/FEATURE_ADMIN_ADD_CARD_ON_FILE_INLINE.md` — this file.

## Test tally

| Suite | Cases | Result |
|---|---|---|
| `backend/tests/test_admin_add_card_on_file.py` | 7 | ✅ (new) |
| `frontend/src/test/admin-add-card-on-file.test.jsx` | 4 | ✅ (new) |
| `frontend/src/test/customer-detail-top-action-stack.test.jsx` | 6 | ✅ (from last tweak) |
| `frontend/src/test/customer-portal-invite-relocation.test.jsx` | 6 | ✅ |
| `frontend/src/test/portal-invite-dual-mount.test.jsx` | 5 | ✅ |
| `frontend/src/test/phase12-require-card.test.jsx` | 3 | ✅ |
| `frontend/src/test/p44-no-payment-filter.test.jsx` | 9 | ✅ (still uses the old email endpoint — CustomersList row action) |
| `frontend/src/test/customer-detail-action-row.test.jsx` | 5 | ✅ |
| `frontend/src/test/customer-detail-tabs-dropdown.test.jsx` | 9 | ✅ |

## E2E smoke on preview

```
$ curl -X POST /api/customers/926cee64.../setup-intent (admin)
  → HTTP 200
  → { client_secret: "seti_...", publishable_key: "pk_live_...",
      setup_intent_id: "seti_...", stripe_customer_id: "cus_...",
      mode: "live" }

$ curl -X POST /api/customers/x/setup-intent (no token)   → HTTP 401
```

Live Stripe SetupIntent minted successfully against the aquaterra preview tenant's Stripe account (live mode key present on the pod).

## Callers of the old `POST /customers/{cid}/send-card-add-link` endpoint

The old email endpoint is **kept alive** — one legitimate self-service caller remains:

| Caller | File | Purpose |
|---|---|---|
| `CardOnFileWarningBanner` | Removed — rewired to inline modal | (retired) |
| Row action on Customers list | `frontend/src/pages/customers/CustomersList.jsx` L336 `handleSendPaymentLink` | Bulk-friendly quick send from the list view. Admin may still want to email a link if the customer isn't in front of them. Kept. |
| P44 no-payment-filter test | `frontend/src/test/p44-no-payment-filter.test.jsx` | Test asserts the row action still POSTs to the email endpoint. Unchanged. |
| `test_phase12_require_card.py`, `test_batch12c_get_tenant_settings.py` | Backend tests | Legacy contract tests. Kept. |

**Decision**: do NOT deprecate the email endpoint. Both flows (email round-trip + inline capture) have legitimate operator use cases. The button on the top of the Customer detail page is the "operator holds the card" flow; the list row action is the "email a customer who isn't in front of me" flow.

## Old email flow root cause (§ per user request)

**Symptom** (from the P1 diagnostic): admin clicked the top-of-page "Send add-card link" button, UI toasted "Card add link sent to <email>", but Resend received nothing.

**Root cause (confirmed on preview)**: the frontend banner unconditionally toasted success as long as the endpoint returned HTTP 200, without inspecting the `sent_email` / `sent_sms` booleans in the response body. The endpoint returned HTTP 200 in **all** of the following silent-no-op cases:
1. Customer has `email = null` on file (guard `if email_tpl and customer.get("email")` skips the send). Reproduced on preview with `drift-dt-fd70e7` → `{"ok":true,"sent_email":false,"sent_sms":false,"email_recipient":null,"sms_recipient":null}` and the FE still toasted success.
2. `marketing_templates` collection missing the `add_card_request_email` / `add_card_request_sms` row for the tenant (25 tenants had it seeded; some legacy `TEST-*` / `csv-*` tenants did not).
3. `services.comms_email_adapter.send_email` returned any status other than `sent` / `sent_no_provider_id` (opted_out, deferred quiet-hours, testmode mock, `not_sent_missing_key`, `suppressed_not_demo`, or any exception from the Resend SDK) — all yield `sent_email=False` while the route still returns HTTP 200.

**Impact of this feature on the RCA**: the *button that surfaced the symptom* now bypasses email entirely and invokes Stripe SetupIntent directly. Success now means "Stripe accepted the card" — no template, no send-status, no room for the toast to lie. The old endpoint remains for the row-action caller but the FE toast bug there is a separate deferred fix (see the P1 memo). If the user wants that fix rolled in, it's ~15 LOC in `CustomersList.handleSendPaymentLink` to gate the success toast on `res.sent_email || res.sent_sms` and surface a distinct warning otherwise.

## Follow-ups (out-of-scope handoff)

- **Mobile parity** → `e1_expo_frontend_dev`: if the Expo admin shell has a matching Card-on-File CTA, mirror the SetupIntent modal. The web endpoint is admin-only; mobile can reuse the same URL.
- **Chase Stalled Invites** — remains PAUSED. Resume after this ships.
- **Legacy FE toast bug** in `CustomersList.handleSendPaymentLink` — same "success toast on 200 ignoring sent booleans" shape. Small fix if ops asks; deferred here to keep the diff reviewable.
