# FEATURE — Add Card on File (magic-link email flow, truthful outcomes)

> ## ⚠️ PROD-STALE CALLOUT (Feb 10, 2026 · post-Save-to-GitHub)
>
> The user has been reproducing the "sending email…" silent-fail
> on **`app.plofv.com` (production)** — the URL screenshot
> confirms it. Every fix in this memo is on **preview only**.
>
> **Fix path**: user must run **Save-to-GitHub → redeploy prod**
> for these fixes to take effect. Until that happens, the prod
> button will keep lying about success. Ledger honesty and SMS
> parity fixes (below) also require the same deploy.
>
> All main-agent access is preview-only. Do NOT touch prod code
> directly.

**Date shipped**: Feb 10, 2026 · Preview
**Scope**: Fix the silent-fail "sending email…" bug on the admin "Add card on file" button. Preserve the existing email + magic-link flow (customer clicks link → lands DIRECTLY on Stripe SetupIntent page, no portal login). Rename button label. Bump magic-link TTL to 7 days. Follow-ups: SMS parity, ledger honesty split (accepted-by-provider vs terminal-status), Resend `delivery_delayed` mapping.
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


---

## Feb-2026 · Follow-up P1 — SMS parity, ledger honesty, delivery-delayed

### SMS parity fix (silent-fail parity with the email path)

**Root cause**: the route called the legacy sync wrapper `utils.send_sms`, which returns bool only. The route wrapped it in `try/except` and set `sent_sms=True` unconditionally on any non-exception path. Two vectors returned False silently and still marked "sent":

1. **RC BYO unconfigured** — `services.sms.rc_adapter.send` returns `{provider: "mock", provider_status: "not_configured"}`. Legacy wrapper → False. Old route → `sent_sms=True` anyway.
2. **Comms env-guard downgraded** — returns `{provider: "ringcentral", provider_status: "dry_run"}`. Same shape.

**Fix**: `routers/customers.py :: send_card_add_link` now calls `services.sms.rc_adapter.send` **directly** and inspects the full response envelope. Truthful mapping:

| RC response | New route behavior |
|---|---|
| `provider=ringcentral, status ∈ {queued, sent, delivered, accepted}` | `sent_sms=True`, `sms_status=<live status>`, `provider_response_id` persisted |
| `provider=mock` | `sent_sms=False`, `sms_status="sms_not_configured"`, `sms_error="RingCentral BYO credentials missing…"` |
| `provider_status="dry_run"` | `sent_sms=False`, `sms_status="gate_dry_run"`, `sms_error="Comms env-guard downgraded…"` |
| Anything else | `sent_sms=False`, `sms_status="provider_rejected"` |

If neither channel actually left the pod, the route returns **HTTP 502 `PROVIDER_FAILURE`** with the per-channel status + error in the structured detail. The FE toast surfaces the exact reason instead of lying about success.

### Ledger-honesty split (accepted-by-provider vs terminal status)

**Before**: `delivered: true` in `marketing_deliveries` meant "Resend returned 200 with a message id". It did **not** mean the recipient's inbox actually accepted it. The word `delivered` was a lie for downstream consumers.

**After**: every add-card delivery row now carries THREE fields:

| Field | Meaning | When it changes |
|---|---|---|
| `accepted_by_provider: bool` | Provider API returned success at send time | Frozen at insert |
| `provider_status: str` | Live-cursor status (moves through the lifecycle) | Updated by webhook on every event |
| `provider_terminal_status: str \| null` | **Terminal outcome only** — one of `delivered` / `bounced` / `complained` / null | Updated by webhook **only on terminal events** — retryable states (`delivery_delayed`) and engagement (`opened`, `clicked`) leave it untouched |
| `terminal_delivered: bool \| null` | Convenience tri-state derived from `provider_terminal_status` — null = unknown, true = delivered, false = bounced/complained | Same |

`delivered` remains as a back-compat alias for `accepted_by_provider` — do NOT trust it for downstream logic; use `terminal_delivered` or `provider_terminal_status` when the question is "did the mailbox receive it?".

**Correlation fix**: the add-card route now persists `provider_response_id` (the Resend message id) on the delivery row. Was previously dropped, which meant every terminal webhook `email.delivered`/`bounced`/etc. was orphaned from its row (`update_one({"provider_response_id": <id>})` matched nothing). Verified on preview — a fresh send after the fix persisted `provider_response_id: "86534ff5-…"`. All backfill is forward-looking; historical rows are orphaned by design.

### Resend `email.delivery_delayed` handling

The Resend dashboard shows many real customer emails stuck at **Delivery Delayed** — this is Resend's label for retryable states like greylisting, temporary provider hold, or upstream deferral. It is NOT a terminal state; Resend retries the send and transitions to either `delivered` or `bounced` when the retry resolves.

**Fix**: added `email.delivery_delayed` to the webhook mapper (`routers/resend_webhooks.py`). On receipt:
- Stamps `provider_status = "delivery_delayed"` + `delivery_delayed_at = <now>`.
- **Does NOT** touch `terminal_delivered` or `provider_terminal_status` — those wait for the eventual retry outcome.
- Ops UI can now filter by `provider_status = "delivery_delayed"` to see stuck sends and manually action them (bounce, follow up via SMS, etc.).

### Resend webhook wiring status

Infrastructure was already in place at `POST /api/webhooks/resend` (svix-signed, mapping delivered/bounced/complained/opened/clicked). This pass added `delivery_delayed` + the `provider_terminal_status` split.

**Preview `resend_webhook_events` collection count = 0** — no webhook events have been received on this pod. Two possibilities:
1. The preview environment's webhook endpoint URL is not registered in the Resend dashboard for this project. Ops needs to add `https://<preview-host>/api/webhooks/resend` (with a matching `RESEND_WEBHOOK_SECRET`) in the Resend project settings.
2. Resend fires webhooks only for the environment that the API key belongs to — if preview + prod share a single Resend project, all webhooks land on the URL registered there (likely prod's).

**Action item for the user** (out-of-scope for this ticket): confirm Resend webhook registration for the preview environment. Without webhooks, `provider_terminal_status` will stay null forever on preview, and the deliveries ledger cannot answer "did the customer actually get the email?".

### Why "delivered:true" but no mail in the tester's inbox (preview)

Preview seed data uses `@aquaterra.com` recipients (e.g. `k9verify@aquaterra.com`, `k14tester@aquaterra.com`). **`aquaterra.com` is a placeholder domain — there are no receiving mail servers, no MX records that route to a real mailbox.** Resend accepts the send (issues a message id, `provider_status="sent"`) and then silently bounces because there's nowhere to deliver. The ledger's old `delivered:true` flag reflected acceptance-time success, not terminal delivery.

**Preview-testing note for future ops**: to verify terminal delivery on preview, seed one customer with a real email address (e.g. your own inbox). Sends to `@aquaterra.com` will always land at "Delivery Delayed" or "Bounced" on the Resend dashboard even though the ledger shows `accepted_by_provider: true`.

## Files touched (this follow-up pass)

- `backend/routers/customers.py` — SMS branch rewritten to call RC adapter directly + persist `provider_response_id` + `provider_terminal_status` on both channels. `~90 line` diff.
- `backend/routers/resend_webhooks.py` — added `email.delivery_delayed` mapping + split `provider_terminal_status` from live `provider_status`. `~25 line` diff.
- `backend/tests/test_add_card_on_file_email_flow.py` — 3 new SMS tests (unconfigured / gate dry-run / happy path).
- `backend/tests/test_resend_webhook_terminal_status.py` — 6 new webhook tests (delivered / bounced / complained / delivery_delayed / engagement / unknown-id).
- `memory/FEATURE_ADD_CARD_ON_FILE_MAGIC_LINK.md` — this update.

## Test tally (running total)

| Suite | Cases | Result |
|---|---|---|
| `backend/tests/test_add_card_on_file_email_flow.py` | 11 (was 7) | ✅ |
| `backend/tests/test_resend_webhook_terminal_status.py` | 6 (new) | ✅ |
| `frontend/src/test/card-on-file-btn-layout.test.jsx` | 7 | ✅ |
| `frontend/src/test/admin-add-card-on-file-email.test.jsx` | 5 | ✅ |
| `frontend/src/test/customer-detail-top-action-stack.test.jsx` | 6 | ✅ |
| `frontend/src/test/p44-no-payment-filter.test.jsx` | 9 | ✅ |
| `frontend/src/test/phase12-require-card.test.jsx` | 3 | ✅ |

Total across P1 diagnostics: **47/47 green** on preview. Nothing shipped to prod yet.

