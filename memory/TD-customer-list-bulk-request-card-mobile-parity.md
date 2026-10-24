# TD-customer-list-bulk-request-card-mobile-parity — P3

**Opened:** Feb-2026 (as part of `TD-customer-list-bulk-request-card-on-file` sprint).
**Status:** NOT STARTED.
**Owner:** unassigned.
**Priority:** P3 — field techs rarely drive card requests; admins on
the web app do this day-to-day.

## Context

`TD-customer-list-bulk-request-card-on-file` shipped the "Request
card on file" bulk action in the web Customers list toolbar
(`frontend/src/pages/customers/CustomersList.jsx` + new
`RequestCardOnFileModal.jsx`). The action is admin-only and
dispatches both email + SMS via tenant-scoped marketing templates
through the new `POST /api/customers/bulk-request-card` endpoint.

The Expo mobile tech app does NOT currently expose this action.
Grep against `/app/mobile/src/**/*` for `bulk-request-card`,
`add_card_request`, "Request card on file" returns zero matches.

## Proposed fix shape

If a tenant admin on mobile wants to kick off the same bulk action:
- Reuse the shipped `POST /api/customers/bulk-request-card` endpoint
  (BE already scopes by tenant + role; no new endpoint required).
- Add a `RequestCardOnFileSheet.tsx` in
  `mobile/src/components/customers/` that mirrors the web modal:
  * Template pickers (one per channel) backed by
    `GET /marketing/templates?channel=email|sms&active=true`.
  * Auto-preselect `add_card_request_email` / `add_card_request_sms`
    by `code`.
  * Live preview via `POST /marketing/templates/{tid}/preview`.
  * Confirmation sheet with the per-row result list + tallies.
- Wire into the existing mobile customers list bulk-select toolkit
  (`mobile/src/components/bulk-select/BulkSelectToolkit.tsx`) as a
  5th action.

## Not blocking

Field techs don't drive card requests in the current product flow;
this is strictly admin-on-mobile parity. Deferred until an admin
asks for it or a telemetry signal (web action usage ÷ mobile
sessions) justifies the lift.
