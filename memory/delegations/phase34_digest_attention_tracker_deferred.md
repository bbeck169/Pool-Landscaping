# Phase 34 · Task LL follow-up — Digest attention tracker (DEFERRED)

**Status: DEFERRED to next batch. Rationale below.**

## Ask
Wire `opened_at` + `clicked_at` webhook tracking on the weekly digest
send path so the *following* Monday's digest can include a small
"Digest engagement: N owners opened last week's digest" line at the
top.

## Investigation summary
* The Resend send adapter (`services/email/resend_adapter.py`) is
  fully guarded (Task L) and returns a `provider_status` field on
  every send — but there is **no webhook endpoint** in the codebase
  for Resend delivery/open/click events. Grep across
  `/app/backend/routers/` confirms zero `POST /webhooks/resend`
  routes today.
* `communication_sends` collection stores every outbound event but
  has no `opened_at` / `clicked_at` fields populated — the app has
  been running in send-only mode.
* To ship the ask end-to-end we'd need:
  1. A new webhook router `POST /api/webhooks/resend` that
     verifies the Resend signature header, parses the event body,
     upserts `communication_sends.{id}` with the correct timestamp.
  2. Resend account webhook configuration (URL + signing secret
     in `RESEND_WEBHOOK_SECRET` env var) — **the user needs to add
     this to the tenant's Resend dashboard**.
  3. A `digest_sends` collection (or reuse `communication_sends`
     with a `kind="weekly_digest"` tag) so we can query the previous
     week's digest sends when building the current week's digest.
  4. `weekly_bulk_actions_digest.py` extension to query the prior
     week's digest sends + emit the "N opened last week" preamble.

## Why deferred
* Ships against Resend webhook config that only the tenant owner
  can turn on — no way to fully test end-to-end in preview until
  the user configures the Resend webhook URL against
  `https://app.plofv.com/api/webhooks/resend`.
* Signing-secret verification requires the `svix` library (Resend's
  webhook signing lib) — one more dep + env var + integration test
  scaffold.
* Every other item in the current in-flight batch (Live-drip lock,
  Jest expansion to 11 surfaces, shared BulkSelectToolkit, Customers
  UI wire-up) is fully closable in this window; punching in a
  partial webhook layer risks a half-shipped feature.

## Follow-up plan
When the user is ready:
1. Provide Resend webhook signing secret (`RESEND_WEBHOOK_SECRET`).
2. Confirm the webhook URL to configure on Resend (either
   `https://app.plofv.com/api/webhooks/resend` for prod or a preview
   URL for testing).
3. Approve installing `svix` for signature verification.

Estimated shipping window once the above lands: 2–3 hours (webhook
router + `digest_sends` tagging + digest preamble + pytest).
