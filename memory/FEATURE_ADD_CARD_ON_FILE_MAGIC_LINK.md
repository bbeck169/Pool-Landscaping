# FEATURE — Add Card on File (magic-link email flow, truthful outcomes)

**Date shipped**: Feb 10, 2026 · Preview
**Scope**: Fix the silent-fail "sending email…" bug on the admin "Add card on file" button. Preserve the existing email + magic-link flow (customer clicks link → lands DIRECTLY on Stripe SetupIntent page, no portal login). Rename button label. Bump magic-link TTL to 7 days.
**Status**: ✅ SHIPPED to preview. Not yet in production (user redeploys.)

## Pivot recap

Earlier scope proposed an inline SetupIntent modal (rip out email entirely). User clarified: the email flow is the correct behavior — the customer clicks the CTA and lands on Stripe DIRECTLY (no portal login required). The bug was the FE lying about success + the BE silently no-op'ing on config gaps. This ticket fixes that; the inline-modal work was reverted cleanly.

**Reverted in this pass**:
- Deleted `frontend/src/components/customers/AdminAddCardOnFileModal.jsx`.
- Deleted `frontend/src/test/admin-add-card-on-file.test.jsx` (inline-modal test).
- Deleted `backend/tests/test_admin_add_card_on_file.py` (inline-modal test).
- Removed the `POST /api/customers/{cid}/setup-intent` admin alias endpoint.
- Removed the `onCardAdded` prop plumbing from `CustomerDetail.jsx` (banner no longer needs a modal-success refetch — the email flow is out-of-band).

The Feb-2026 top action stack layout tweak (Card-on-file above Portal invite) is preserved.

## Root cause of the silent-fail

The old endpoint returned HTTP 200 in **all** of these cases, and the FE unconditionally toasted "Add-card link sent to <email>":

| Trigger | Old behavior | New behavior |
|---|---|---|
| Customer has no email on file | HTTP 200, `sent_email: false` | HTTP **400** `NO_CONTACT_ON_FILE` (or `partial` if SMS still sent) |
| Customer has no phone on file | HTTP 200, `sent_sms: false` | Continues with email only if it can send; degrades to `partial` outcome |
| `add_card_request_email` template missing on tenant | HTTP 200, `sent_email: false` | HTTP **409** `TEMPLATE_MISSING` |
| Resend key missing on pod | HTTP 200, `sent_email: false` | HTTP **502** `PROVIDER_FAILURE` |
| Recipient opted out / gated / quiet-hours deferred / SDK exception | HTTP 200, `sent_email: false` | HTTP **502** `PROVIDER_FAILURE` with per-channel `status` + `error` in the detail |
| Full success | HTTP 200, `sent_email: true`, `sent_sms: true` | HTTP 200, `outcome: "sent"`, `channels.{email,sms}.status: "sent"` |

The FE now inspects `sent_email || sent_sms` for the success gate and surfaces `res.reason` (or the structured detail from the error path) instead of a generic "sent" toast.

## Magic-link auth model (already correct — verified)

- **URL shape**: `${public_origin}/portal/add-card?token=${JWT}` — built by `services.add_card_links.build_add_card_link`.
- **Auth**: NONE. The JWT is the sole authority (`add_card_links.decode_add_card_token`). The `/portal/add-card` route in `frontend/src/App.js` is public — no portal login required. The route naming lives under `/portal/*` for URL-prefix consistency; the page itself opens Stripe Elements against a fresh SetupIntent bound to the customer via `POST /api/customers/add-card/{token}/setup-intent`.
- **TTL**: 7 days (bumped from 24h in this pass per new spec — env-overridable via `PORTAL_ADD_CARD_LINK_TTL_HOURS`).
- **Post-success**: `POST /api/customers/add-card/{token}/attach` mirrors the PaymentMethod into `payment_methods` — the same **Task-5 primitive** the admin-side attach path uses. On success the customer sees the card in their portal Saved Payment Methods screen; auto-billing picks it up via `_pick_default_pm` (see next section).

## Auto-billing wiring check

Confirmed wired end-to-end:
- **Route**: `POST /api/invoices/bulk-charge-card-on-file` (`invoices_bulk_charge.py`) + `POST /api/payments/stripe/charge` (`stripe_router.py`).
- **PM picker**: `_pick_default_pm(tenant_id, customer_id)` at `invoices_bulk_charge.py:107` — queries `db.payment_methods` filtered by `{tenant_id, customer_id, is_default: true}` first, then any PM as fallback. That's the **exact same collection** the magic-link attach writes to, so a card added via the email flow becomes charge-eligible immediately.
- **Opt-in gate**: `customers.autobilling_enabled` bool controls the customer's participation. Portal endpoint `/customer-portal/autobilling/enable` toggles it.

No follow-up work required — the email flow feeds directly into the existing auto-billing pipeline.

## Files touched

**Backend (2)**
- `backend/routers/customers.py` — rewrote `send_card_add_link` inner body: per-channel `status` + `error` tracking, structured HTTP 400/409/502 error codes on hard-fail conditions, truthful response envelope (`outcome`, `channels.{email,sms}`), truthful `provider_status` + `error` on the deliveries ledger rows. Removed the earlier admin `setup-intent` alias.
- `backend/services/add_card_links.py` — magic-link default TTL 24h → 7 days (env override unchanged).

**Frontend (2)**
- `frontend/src/components/customers/CardOnFileWarningBanner.jsx` — email-flow banner restored; toast now gates success on `sent_email || sent_sms` and surfaces structured server error codes verbatim (`NO_CONTACT_ON_FILE`, `TEMPLATE_MISSING`, `PROVIDER_FAILURE`, `RATE_LIMITED`). Button label renamed to **"Add card on file"** (`<CreditCard>` icon). Test-id `card-on-file-send-link-btn` preserved.
- `frontend/src/pages/customers/CustomerDetail.jsx` — reverted the modal-success plumbing (unused now).

**Tests (2)**
- `backend/tests/test_add_card_on_file_email_flow.py` — 7 pytest cases (happy path invokes Resend + returns truthful envelope, no-contact 400, template-missing 409, missing Resend key 502, magic-link Stripe target + 7-day TTL, customer 403, admin/manager/super_admin allowed). All green.
- `frontend/src/test/admin-add-card-on-file-email.test.jsx` — 5 vitest cases (label copy, success toast names recipients, silent no-op → error toast NOT success, structured 4xx surfaces server message, 429 friendly retry). All green.

**Docs (1)**
- `memory/FEATURE_ADD_CARD_ON_FILE_MAGIC_LINK.md` — this file.

## Test tally

| Suite | Cases | Result |
|---|---|---|
| `backend/tests/test_add_card_on_file_email_flow.py` | 7 | ✅ (new) |
| `frontend/src/test/admin-add-card-on-file-email.test.jsx` | 5 | ✅ (new) |
| `frontend/src/test/customer-detail-top-action-stack.test.jsx` | 6 | ✅ (from last tweak) |
| `frontend/src/test/customer-portal-invite-relocation.test.jsx` | 6 | ✅ |
| `frontend/src/test/portal-invite-dual-mount.test.jsx` | 5 | ✅ |
| `frontend/src/test/phase12-require-card.test.jsx` | 3 | ✅ |
| `frontend/src/test/p44-no-payment-filter.test.jsx` | 9 | ✅ |

Total: 41/41 green.

## E2E smoke on preview

```
$ curl POST /api/customers/aa44e856.../send-card-add-link (admin)
  → HTTP 200
  → {"ok":true,"sent_email":true,"sent_sms":true,
     "email_recipient":"k9verify@aquaterra.com",
     "sms_recipient":"+15555550199",
     "outcome":"sent",
     "channels":{"email":{"sent":true,"status":"sent","error":null},
                 "sms":{"sent":true,"status":"sent","error":null}}}

$ curl POST /api/customers/drift-dt-fd70e7/send-card-add-link (null email + phone)
  → HTTP 400
  → {"detail":{"code":"NO_CONTACT_ON_FILE",
      "message":"Customer has no email or phone on file. Add contact info and try again.",
      "reasons":{"email":"no_recipient_on_file","sms":"no_recipient_on_file"}}}
```

## Follow-ups (out-of-scope handoff)

- **CustomersList row action** (`handleSendPaymentLink` at `CustomersList.jsx:336`) still uses the old toast shape (200 without checking `sent_email`). Same fix pattern as the banner — ~15 LOC. Not touched here to keep the diff reviewable; call out for a follow-up ticket.
- **Mobile parity** → `e1_expo_frontend_dev`: if the Expo admin shell has a matching Card-on-File CTA, mirror the truthful-toast fix. Endpoint contract is unchanged from the FE consumer perspective.
- **Chase Stalled Invites** — remains PAUSED. Resume after this ships.
