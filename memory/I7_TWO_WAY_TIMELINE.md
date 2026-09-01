# Phase I7 · Two-Way Timeline Design Note (deferred)

Audit performed Feb 2026 · Phase J1.

## Inbound collections status

Grepped preview MongoDB for the following expected collections:
`sms_inbox`, `email_inbox`, `inbound_sms`, `inbound_email`,
`sms_messages`, `email_messages`, `messages`. **All zero rows or
non-existent.** No inbound-side collection exists in this
deployment.

The current portal chat thread (`/portal/messages`) writes to a
separate `portal_thread_messages` collection (bidirectional in-app
chat), not an SMS/email inbox — those are chat-only, not
webhook-received comms.

## Deferred merge path (for future implementation)

If/when RingCentral SMS inbound webhooks + IMAP/Postmark email
inbound land, the merge path in
`backend/routers/communication_timeline.py` becomes:

1. Query a new `notification_inbox_log` collection with the same
   ``recipient_id`` + ``resolved_address`` linkage as
   `notification_dispatch_log`.
2. Flip `direction: "inbound"` on each row.
3. Merge into the same items array pre-sort; sort key unchanged
   (`occurred_at DESC`).
4. Frontend: add a small left-facing arrow icon on inbound rows
   and left-align them (mirror of the current outbound-right
   convention if we want a two-column stream, or keep the single
   column with the direction pill).

## Design decisions to lock before shipping

- Do inbound SMS auto-open the portal chat thread, or stay
  passive-log-only? (Product call.)
- Which webhook adapter writes to `notification_inbox_log`? A
  new module vs. extending `services/sms/rc_adapter.py` +
  `services/email/receiver.py`.
- RBAC: portal role should still receive server-stripped items;
  only `body_preview` needs sanitization for inbound (already
  handled by the shared `_preview` function).

## Non-goals for this note
- No schema commitment.
- No frontend changes.
- No new endpoints.
