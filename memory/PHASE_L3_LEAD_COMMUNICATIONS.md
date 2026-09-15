# Phase L3 · Text + Email from Leads · Feb-2026

## Summary
Free-form SMS + email compose rooted at a lead, with row-level actions
on the leads list and header buttons + a merged Communication Timeline
on the Lead Detail page.  Reuses the exact customer-side providers so
no new provider integration was introduced.

## Providers reused
* SMS  →  `services/sms/rc_adapter.py::send` (RingCentral) — same
  adapter `POST /customers/{cid}/send-sms` uses.  Honors K31 consent,
  marketing suppression, BYO cap, testmode mock.
* Email →  `services/comms_email_adapter.py::send_email` (Resend) —
  same adapter `POST /customers/{cid}/send-email` uses.

## Endpoints added (`api_router` → `/api` prefix)
1. `POST /api/leads/{lead_id}/send-sms`
2. `POST /api/leads/{lead_id}/send-email`
3. `GET  /api/leads/{lead_id}/communications`

All three are gated by `admin | super_admin | manager | owner`.

## Data
* New collection: `lead_communications`
  * Indexes:
    - `lead_comms_by_lead`         → `(tenant_id, lead_id, created_at DESC)`
    - `lead_comms_by_provider_id`  → `(tenant_id, provider_message_id)` sparse
* Row created BEFORE provider dispatch (crash-mid-call still leaves a
  discoverable `queued` row on the timeline).
* Leads soft fields: `sms_ok` / `email_ok` (default `True` via
  `.get(..., True)` — no migration needed for historical rows).

## Inbound reply capture
* SMS → the existing RingCentral webhook (`routers/ringcentral.py`)
  already stashes `matched_lead_id` on `db.sms_inbound`.  The timeline
  aggregator UNIONs those rows in read-time as `direction=inbound`.
  No new webhook path was invented.
* Email → **DEFERRED** — Resend has no inbound webhook in this repo.
  A `TODO(inbound-email):` marker sits at the aggregator site so the
  extension point is discoverable via grep.

## Status normalization
RC / Resend provider strings are coerced into a uniform enum on the
row so the timeline can pill-color deterministically:

```
sent | queued | delivered | mocked | dry_run                → "sent"
failed | invalid_phone | suppressed* | cap_exceeded |
skipped_opted_out | not_sent_missing_key | no_consent       → "failed"
(unknown)                                                    → "sent"
```

Unknown values fall through to `"sent"` best-effort with the raw
provider string stashed on `provider_status_raw` for observability
so a mystery state never crashes the endpoint.

## Files changed / added
Backend:
* `backend/routers/lead_communications.py` (new)
* `backend/server.py` (register router on `api_router`)

Frontend:
* `frontend/src/pages/leads/LeadComposeModal.jsx` (new)
* `frontend/src/pages/leads/LeadsDashboardPage.jsx` (row-level icons)
* `frontend/src/pages/leads/LeadDetail.jsx` (header buttons + timeline)

Tests:
* `backend/tests/test_lead_communications_send_sms.py` (8 cases)
* `backend/tests/test_lead_communications_send_email.py` (8 cases)
* `backend/tests/test_lead_communications_timeline.py` (3 cases)
* `frontend/src/test/lead-compose-modal.test.jsx` (4 cases)
* `frontend/src/test/lead-row-compose-buttons.test.jsx` (3 cases)
* `frontend/src/test/lead-detail-communication-timeline.test.jsx` (2 cases)

## Test counts
* pytest (L3 files only) — 19 passed.
* pytest (L3 + neighbouring lead files) — 45 passed.
* vitest (full suite) — 4475 passed, 34 skipped, 0 failed.

## Live smoke
Real POST via `admin@aquaterra.com` to a phone-bearing lead returned:
```
status=sent · provider_message_id=3069848732019 (RC)
```
and the row appears on `GET /leads/{id}/communications` immediately.

## Deviations from spec
* None functional. Two observability nudges beyond the brief:
  * Unknown provider statuses are coerced to `sent` with the raw value
    stashed on `provider_status_raw` (per nudge #2).
  * Pagination cursor is `<created_at>|<id>` so ties on `created_at`
    are broken deterministically (per nudge #4).
