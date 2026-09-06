# Phase K63 · Feb-2026 — Widget Forms → Leads Data Parity + Per-Tenant Notification Recipients

## Scope

Extend the P18 lead-alert plumbing so the tenant admin can manage the
recipient list from the UI, guarantee every field the public widget
forms collect makes it onto the `/leads` detail view, and swap the
old flat-list dispatcher for an idempotent, rich-shape fan-out.

## Deliverables

| Step | Deliverable | Status |
|------|-------------|--------|
| 0 | Widget → Lead data-parity audit table (below) | ✅ |
| 1 | `LeadDetail.jsx` renders every widget field | ✅ |
| 2 | `GET/PUT /api/tenants/{tid}/settings/lead-notifications` + Settings UI | ✅ |
| 3 | Async notification dispatcher (Resend + RingCentral) with idempotency | ✅ |

## Step 0 — Widget → Lead Data-Parity Audit

Cross-references every widget-form field to the persisted lead
document and the `LeadDetail.jsx` renderer. Rows are locked by the
pytests in
`backend/tests/test_lead_widget_persistence_and_raw_submission.py`
and `test_lead_schema_new_fields_persisted.py`.

| Widget field       | Lead document key       | LeadDetail row       | Notes |
|--------------------|-------------------------|----------------------|-------|
| Name               | `name`                  | Contact card         | Falls back to `"Website Visitor"` when empty |
| Phone              | `phone`                 | Contact card         | Rendered as tel: link |
| Email              | `email`                 | Contact card         | Rendered as mailto: link |
| Service address    | `service_address`       | Location card        | K63 · surfaces on detail when set |
| Legacy address     | `address`               | Location card        | Fallback when `service_address` empty |
| Service interest   | `service_interest`      | Interest chip        | Free-text label from widget |
| Notes / message    | `message`               | **Notes card (K63)** | Widget "notes/comments" textarea → previously not rendered on `/leads` — fixed in `LeadDetail.jsx` |
| UTM source         | `utm_source`            | Attribution card     | Existing |
| UTM medium         | `utm_medium`            | Attribution card     | Existing |
| UTM campaign       | `utm_campaign`          | Attribution card     | Existing |
| Referrer           | `referrer`              | Attribution card     | Existing |
| User agent         | `user_agent`            | Attribution card     | Existing |
| Widget id          | `widget_id`             | Attribution card     | Existing |
| Raw submission     | `raw_submission`        | Debug drawer (admin) | Full JSON snapshot; hidden by default |

**Gap closed:** the widget "notes/comments" field persisted to
`lead.message` but the `/leads/{id}` page never rendered it. K63
step 1 added a "Notes" card that renders `lead.message` verbatim
(pre-wrap) whenever the field is non-empty.

## Step 2 — Per-Tenant Notification Recipients

### Data shape (stored on `tenants.lead_notification_recipients`)

```json
[
  {
    "id":            "<uuid>",
    "name":          "Brian",
    "email":         "brian@plofv.com",
    "phone":         "+16028874400",
    "sms_opt_in":    true,
    "email_opt_in":  true
  }
]
```

* Recipients are tenant-scoped.
* Phone stored in E.164 (`+15551234567`); backend normalises common
  US inputs on PUT.
* Email stored lowercase.

### Endpoints

| Method | Path | Role gate | Purpose |
|--------|------|-----------|---------|
| GET    | `/api/tenants/{tid}/settings/lead-notifications` | `admin`, `super_admin`, `owner` (via `require_admin`) | Returns rich recipient list. Lazy-migrates legacy P18 flat lists on first admin open. |
| PUT    | `/api/tenants/{tid}/settings/lead-notifications` | Same | Replaces recipient list. |

### PUT validation

| Rule | HTTP | Message |
|------|------|---------|
| Tenant mismatch (`tid ≠ acting tenant.id`) | 403 | `Tenant mismatch` |
| More than 10 recipients | 400 | `Maximum 10 recipients per tenant` |
| Invalid email (non-`x@y.z`) | 400 | `Recipient N: invalid email address` |
| Invalid phone (not E.164 after normalisation) | 400 | `Recipient N: invalid phone (use E.164 like +16025551234)` |
| `sms_opt_in=true` with empty phone | 400 | `Recipient N: SMS opt-in requires a phone number` |
| `email_opt_in=true` with empty email | 400 | `Recipient N: Email opt-in requires an email address` |

### UI (`/settings/notifications/lead-alerts`)

* File: `frontend/src/pages/settings/LeadAlertsSettings.jsx`
* Mount: `frontend/src/App.js` → wrapped in `<AdminOnly>`.
* Entry: `NotificationPrefs` renders a link card ("Manage recipients")
  under the existing per-user preferences matrix.
* Row-level validation surfaces a red error under each malformed
  row; Save is disabled until every row passes.
* Recipient counter (`X/10 recipients`); Add button disabled at 10.
* Testids:
  * `lead-alerts-settings-page`
  * `lead-alerts-table`
  * `lead-alerts-row-{idx}` + `lead-alerts-{name,email,phone,email-optin,sms-optin,remove}-{idx}`
  * `lead-alerts-add`, `lead-alerts-count`, `lead-alerts-save`, `lead-alerts-toast`, `lead-alerts-error`

## Step 3 — Async Notification Dispatcher

File: `backend/services/lead_notifications.py`

* Rich list wins over the legacy flat lists when both are set —
  legacy addresses are NOT fanned out to when the tenant has
  migrated to the K63 shape (prevents accidental double-send).
* Per-recipient opt-in gates the channel independently:
  * `sms_opt_in && phone`   → BackgroundTask → RingCentral adapter.
  * `email_opt_in && email` → BackgroundTask → Resend adapter.
* Idempotency: every dispatch pins a row in
  `lead_notification_dispatches` (`{tenant_id, lead_id, target, channel}`).
  A second call for the same triple is a no-op — widget
  double-submits, retry storms, and manual re-fires cannot spam
  recipients.
* Audit: success → `audit_logs { event: "lead_notification_sent" }`.
  Failure → `lead_notification_failed` with truncated error. Audit
  rows never carry the raw message body (PII-safe).
* Fire-and-forget: every adapter call lives inside a BackgroundTask
  wrapped in a broad try/except — a broken RC/Resend outage cannot
  bound the lead-create request latency or fail the lead insert.
* Cross-tenant safe: helper takes the tenant doc as an arg, does
  zero DB tenant lookup, so tenant A's lead can never fan out to
  tenant B's recipients.
* P27 muted-customer suppression preserved: a lead whose
  phone/email matches a muted customer in the same tenant returns
  `{muted_suppressed_customer_id: <cid>}` and skips fan-out.

## Test coverage

| File | Coverage |
|------|----------|
| `backend/tests/test_k63_tenant_lead_notifications.py` | Role gate (admin, super_admin ok; manager, tech 403), cross-tenant PUT 403, recipient cap 10, email + phone validation, opt-in-requires-target, PUT/GET round-trip, phone normalisation. |
| `backend/tests/test_k63_dispatcher_idempotency.py` | Rich list gates channels by opt-in, legacy list is IGNORED when rich list present, second call for same (lead, target, channel) triple is a no-op. |
| `backend/tests/test_lead_alert_notifications.py` (P18) | Retained — empty list no-op, cross-tenant isolation, adapter-failure swallowed, SMS + email body templates. |
| `frontend/src/test/k63-lead-alerts-settings.test.jsx` | Endpoint pair contract, 10-cap + Add gating, counter render, E.164 hint, row validation regex, Save gating, per-row testids, NotificationPrefs link card, AdminOnly route wiring. |

## Follow-ups (queued)

* **Index migration** `quotes(tenant_id, customer_id, paid_at/created_at)` — folded into R1 kickoff (Option B).
* **R0.1+ prod redeploy** — safe to redeploy once this phase clears QA.
