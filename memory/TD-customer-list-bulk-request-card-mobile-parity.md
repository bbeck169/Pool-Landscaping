# TD-customer-list-bulk-request-card-mobile-parity — P3

**Opened:** Feb-2026 (as part of `TD-customer-list-bulk-request-card-on-file` sprint; updated with `TD-customer-list-bulk-request-card-stripe-setupintent` ship).
**Status:** NOT STARTED.
**Owner:** unassigned.
**Priority:** P3 — field techs rarely drive card requests; admins on the web app do this day-to-day.

## Context (updated for Ticket J Stripe pivot)

The admin bulk "Request card on file" action is now backed by a real
Stripe SetupIntent flow (`TD-customer-list-bulk-request-card-stripe-setupintent`),
superseding the Ticket I generic template send:

- `POST /api/customers/bulk-request-card-setup-intent` fires a
  single-use capture token per customer (7-day TTL), persisted in
  `customer_card_capture_tokens`.
- Each customer receives email + SMS with a per-customer link to
  `/customer-portal/add-card/{token}` on the web.
- That public page uses Stripe Elements with Link + wallets
  disabled (card-only). Token resolves via
  `GET /api/card-capture/{token}` + `POST /api/card-capture/{token}/confirm`.

The Expo mobile tech app does NOT currently expose this bulk admin
action. Grep against `/app/mobile/src/**/*` for
`bulk-request-card-setup-intent`, `customer-card-capture`, "Request
card on file" returns zero matches.

## Proposed fix shape

If an admin on mobile wants to kick off the same bulk action:

- Reuse the shipped endpoints (BE already scopes by tenant + role;
  no new endpoint required).
- Add a `RequestCardOnFileSheet.tsx` in `mobile/src/components/customers/`
  that mirrors the simplified web modal (recipient count + hardcoded
  previews + confirm; no template picker).
- Add a native card capture surface (or a WebView wrapper over the
  web `/customer-portal/add-card/{token}` route) if the mobile user
  ever needs to open their own link. Realistically the capture link
  is targeted at the customer, not the field tech — so the mobile
  parity is admin-side only: the field tech kicks off a bulk send,
  the customer still receives the link in email/SMS and opens it in
  their own browser.
- Wire into the existing mobile customers list bulk-select toolkit
  (`mobile/src/components/bulk-select/BulkSelectToolkit.tsx`).

## Not blocking

Field techs don't drive card requests in the current product flow;
admin usage is almost entirely on the web app. Deferred until an
admin asks for it or a telemetry signal justifies the lift.
