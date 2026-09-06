# Phase K63.polish · Feb-2026 — Notification Dispatch Log API + Last-Notified-At Chip

## Scope

Read-only observability on top of the K63 lead-alert dispatcher.
Two deliverables:

1. Backend endpoint exposing the ``audit_logs`` rows the K63
   dispatcher writes.
2. Frontend chip on each recipient row in the Lead Alerts settings
   page, driven by the endpoint, with a drill-down modal.

## Backend

**File:** ``backend/routers/admin_notification_dispatch_log.py``
**Route:** ``GET /api/admin/notification-dispatch-log``

### Query params

| Param        | Type     | Notes |
|--------------|----------|-------|
| ``lead_id``  | str      | Exact match |
| ``recipient``| str      | Email lower-cased before match; phone matched exact |
| ``channel``  | ``email`` \| ``sms`` | Invalid value → 400 |
| ``status``   | ``sent`` \| ``failed`` | Invalid value → 400 |
| ``since``    | ISO-8601 | Rows where ``created_at >= since`` are returned. Accepts trailing ``Z``. Invalid → 400 |
| ``limit``    | 1..200   | Defaults to 50; anything > 200 is clamped |

### Response shape

```json
{
  "items": [
    {
      "id": "<audit_logs.id>",
      "lead_id": "<uuid>",
      "recipient": "brian@plofv.com",
      "channel": "email",
      "status": "sent",
      "provider_message_id": "resend-abc123",
      "error": null,
      "created_at": "2026-02-15T11:57:00Z"
    }
  ],
  "total": 1,
  "limit": 50
}
```

### Guarantees

* Newest-first order (``created_at`` desc).
* Tenant-scoped — ``tenant_id`` is resolved from the acting user's
  auth token via ``get_current_tenant``; callers cannot read other
  tenants' rows.
* Role gate: ``require_admin`` (admin, super_admin, owner). Manager
  and technician callers get 403.
* Read-only. No mutation endpoints exist.
* Response is derived from ``audit_logs`` rows written by
  ``services.lead_notifications``. The dispatcher was NOT modified.
* Fields that would leak provider secrets (Resend API keys,
  RingCentral tokens, etc.) are NOT present in the source rows,
  so nothing to redact — audit rows are already PII-safe by
  construction (no raw message body).

## Frontend

### Chip on each Lead Alerts row

**File:** ``frontend/src/pages/settings/LeadAlertsSettings.jsx``

* New table column "Last activity". The chip is driven by a single
  ``pickChip(latestRow, nowMs)`` pure function (exported for
  vitest) that maps the recipient's most-recent dispatch row into
  one of five states:

  | State  | Label sample              | Tone / palette |
  |--------|---------------------------|----------------|
  | none   | "No sends yet"            | muted (grey) |
  | success| "Last: 3 min ago"         | success (green) |
  | neutral| "Last: 2 days ago"        | neutral (sky) |
  | warning| "Silent 14+ days"         | warning (amber) |
  | danger | "Last attempt failed 5 min ago" | danger (red) |

* Chip is clickable when a dispatch row exists — opens a drill-
  down modal showing the last 20 rows for that recipient.
* Log is fetched once on mount (``GET /admin/notification-dispatch-
  log?limit=200``) and again after every successful Save.

### Modal (drill-down)

Component: ``DispatchLogModal`` inside the same file.

* Fetches ``GET /admin/notification-dispatch-log?recipient=…&limit=20``.
* Columns: When · Channel · Status · Lead (first 8 chars of id) ·
  Details.
* Failure rows render the ``error`` field; success rows render the
  ``provider_message_id``.
* Overlay + click-outside-to-close; ``X`` close button; own
  ``data-testid`` set on every row for playwright / QA drives.

## Test coverage

| File | Cases | Green |
|------|-------|-------|
| ``backend/tests/test_k63_polish_dispatch_log.py`` | 17 | ✅ |
| ``frontend/src/test/k63-polish-dispatch-log.test.jsx`` | 10 | ✅ |
| Existing K63 + P18 suites | 21 (backend) + 10 (FE) | ✅ (no regression) |

## Canary verification note

The tester submitted ``K63-TESTER-CANARY-1788660890`` (lead_id
``cf2e0a99-4ba3-4044-949c-2f6ca737e191``) into tenant AquaTerra.

Query result on preview backend at K63.polish ship time:

```
audit_logs where tenant_id=affdfbfa-… and event ∈ {lead_notification_sent, lead_notification_failed}
   → 0 rows
lead_notification_dispatches where tenant_id=affdfbfa-… and lead_id=cf2e0a99-…
   → 0 rows
```

**⚠️ The canary lead's dispatch fan-out never fired.** The lead
document exists in ``db.leads`` but neither the audit trail nor
the idempotency table shows an SMS or email attempt for it. That's
NOT ``status=sent`` and NOT ``status=failed`` — it's "the dispatcher
was never invoked" for this particular lead. Possible causes to
investigate in a follow-up phase (K63.canary-diagnosis?):

1. The widget-form → lead insert path for whichever endpoint the
   tester hit doesn't call ``send_lead_alert_notifications``. The
   dispatcher is wired at ``lead_requests.py:406``,
   ``marketing.py:182 & 246``, ``marketing_forms.py:522``, and
   ``widget_chat.py:355`` — a sixth ingress path (or a raw insert
   in a router the tester exercised) may be missing the fan-out
   call.
2. The lead insert happened BEFORE the K63 dispatcher-migration
   deployment landed on preview.
3. ``_is_contact_muted_in_tenant`` returned a match — but the
   canary's ``k63+1788660890@x.com`` / ``+16025551234`` don't match
   any AquaTerra customer, so this is unlikely.

Recommended next step: ask the tester which endpoint they hit
(``POST /api/lead-requests``? ``POST /api/marketing/forms/…``?)
and grep that router for a ``send_lead_alert_notifications``
call. This is out of scope for K63.polish.

## Follow-ups

* K63.canary-diagnosis — trace which widget-form ingress path
  the tester's canary used and confirm the dispatcher wiring.
* Index migration ``quotes(tenant_id, customer_id, paid_at/created_at)``
  — folded into R1 kickoff.
