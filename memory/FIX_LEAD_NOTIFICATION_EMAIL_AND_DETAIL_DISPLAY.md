# Fix — Lead notification email + Lead detail display

**Phase**: Feb-2026 · Urgent bugfix (2 defects)  
**Reported**: business owner saw a public lead submission (Marilyn
Guhr) produce **no admin email** at all, and the lead-detail modal
was **missing the street address + Requested Service** rows.

## Root-cause analysis

### Defect A — Missing admin email on public leads

Three notification hooks fire on `POST /api/public/leads`:

| Hook | File | Recipient logic |
|---|---|---|
| `apply_lead_post_create` | `services/leads_side_effects.py` | Single-recipient. Email to `tenant.internal_lead_notifications.email` (default `brian@plofv.com`). |
| K63 dispatcher `send_lead_alert_notifications` | `services/lead_notifications.py` | Rich list in `tenant.lead_notification_recipients` with per-channel opt-in toggles. Legacy fallback: `tenant.lead_alert_email_recipients`. |
| Marketing sequences `fire_new_lead_sequence_trigger` | `services/marketing/lead_triggers.py` | Only active sequences enrol. |

Audit trail on the aquaterra tenant showed the K63 email HAS been
sending — but only to `brian@plofv.com` because that's the sole
opt-in row in the tenant's rich list. Additional admins
(`admin@aquaterra.com`, `super@aquaterra.com`, `manager@aquaterra.com`)
plus any `business_settings.notification_email` **were never
included**. If Brian's mailbox filters / spam-folders the message,
the business owner has zero backup path.

**Fix — new safety net fan-out** (`services/lead_admin_notifications.py`):

1. Resolves recipients from THREE sources:
   - Every `users` row on the tenant with
     `role ∈ {admin, super_admin, manager, owner}`,
     `deactivated_at` unset, and `notify_new_leads !== false`.
   - `tenant.business_settings.notification_email` if set.
   - (K63 rich list is INTENTIONALLY not queried here — it fires
     on its own path.)
2. Case-insensitive dedupe preserves first-seen casing.
3. Fire-and-forget via `BackgroundTasks` — never blocks the POST.
4. Shares the K63 `lead_notification_dispatches` idempotency
   table with a distinct `:admin-fanout` target suffix so a
   K63-listed recipient doesn't get two copies.
5. Every attempt writes to `audit_logs`
   (`lead_admin_notification_sent` / `…_failed`) so a mailbox
   miss can be traced.
6. Zero admin recipients → logs a `WARNING` and returns
   `{"queued": 0, "reason": "no_admin_recipients"}` rather than
   silent no-op.

**Email template shape** (`_compose_email_html`) — rendered inside
the tenant's brand shell (`wrap_html_in_shell`):

```
Subject: New Lead: {name} — {service_interest or "Get a Free Quote"}

Body (HTML table):
  Name (in heading)
  Email
  Phone
  Address          → multi-line block:  street\ncity, state zip
  Requested Service
  Notes            → preserves newlines
  Submitted        → Phoenix-local timestamp
  Source           → website_form / referral / …

CTA: View lead in admin → {app_url}/leads/{id}
```

**Hooks added**:

- `POST /api/public/leads` — `routers/leads.py` (right after the
  K63 dispatcher call).
- `POST /api/marketing/forms/{fid}/submit` — `routers/marketing_forms.py`
  (right after the K63 dispatcher call, guarded on the "new lead
  actually created" flag).

Admin-manual `POST /api/leads` is intentionally NOT hooked — an
admin creating a lead by hand doesn't need to receive an email
about it.

### Defect B — Lead detail modal missing street + service_interest

`pages/leads/LeadsDashboardPage.jsx :: LeadDetailDrawer` rendered
the Address row only from `lead.address`, but widget-form
submissions persist under `lead.service_address`. When a lead
came in via the widget, the row was silently hidden.
`service_interest` was surfaced but under the harder-to-notice
"Interested in:" label with no dedicated testid.

**Fix**:

- Address row now falls back through
  `lead.address || lead.service_address` and always renders when
  either is set, under a clean **Address:** label. Testid:
  `lead-detail-address`.
- Kept the separate "Service address:" row for the corner case
  where both fields diverge (kept its existing testid
  `lead-service-address`).
- `service_interest` row renamed **Interested in:** →
  **Requested Service:** with testid `lead-detail-service-interest`.

Neither field label leaks when the source value is empty — the
row is elided entirely.

## Testid map

| Testid | Element |
|---|---|
| `lead-detail-address` | Address row (street, with fallback) |
| `lead-detail-service-interest` | Requested Service row |
| `lead-service-address` | Divergent service_address row (legacy) |
| `lead-city-state-zip` | City / State / Zip line (unchanged) |
| `lead-contact-block` | Wrapper (unchanged) |

## Admin recipient resolution rules

Union of:
1. `users` where `tenant_id == caller_tenant`, `role ∈ admin_set`,
   `email != ""`, `deactivated_at IS NULL`, and
   `notify_new_leads` is not explicitly `False`.
2. `tenant.business_settings.notification_email` (string) if set.

Deduped case-insensitively, first-seen casing wins.

The K63 rich list is deduped at SEND time via the
`lead_notification_dispatches` idempotency table so a K63
recipient never receives two copies of the same lead email.

## Test coverage added

Backend — `tests/test_lead_admin_notification_fanout.py`:

- `test_resolves_admin_users_and_business_email` — union +
  filter logic (excludes tech role, deactivated users, opt-outs).
- `test_dedupes_business_email_against_user_row` — case-insensitive
  dedupe.
- `test_empty_when_no_admins_and_no_business_email` — returns `[]`.
- `test_html_contains_all_lead_fields` — every field lands in the
  template (name, email, phone, street, city/state/zip,
  service_interest, notes, timestamp, CTA link).
- `test_subject_line_matches_spec` — subject format + interest
  fallback.
- `test_admin_fanout_audit_row_created` — POST `/api/public/leads`
  end-to-end; asserts `lead_admin_notification_sent` audit rows
  and an idempotency row appear.
- `test_no_admins_returns_reason` — helper reports
  `no_admin_recipients` cleanly.

**All 7 pass** + adjacent regression suites
(`test_phase16_lead_side_effects.py`,
`test_k63_dispatcher_idempotency.py`,
`test_public_lead_intake_bugfix.py`,
`test_widget_lead_intake_field_capture.py`,
`test_lead_form_address_capture.py`) also green.

Frontend — `test/lead-detail-address-and-service-interest.test.jsx`:

- Renders Address row from `lead.address`.
- Falls back to `service_address` when `address` is empty.
- Hides Address row when both empty (city/state/zip still renders).
- Renders Requested Service row when `service_interest` is set.
- Hides Requested Service row when unset.
- Both rows together for a fully-populated lead.

**All 6 pass** + legacy `phase17-lead-drawer-field-rendering.test.jsx`
still green (the pre-fix testid `lead-service-interest` is
tested against its own inline replica, unaffected by the rename).

## Guardrails

- Send is fire-and-forget via `BackgroundTasks`; a Resend outage
  cannot bound the POST response tail latency.
- Zero admin recipients → structured `WARNING` log (not silent).
- Idempotency: same `(tenant, lead, target)` triple with
  `:admin-fanout` suffix cannot double-send even under widget
  double-submit / retry storms.
- Per-recipient `try/except` — one recipient's SMTP failure never
  starves the rest.

## API surface

**No new endpoints**. OpenAPI paths stable at 1749 (unchanged
from the previous Polish Bundle).

## Out of scope

- Mobile parity (admin desktop only).
- Auto-conversion to customer (existing button flow untouched).
- K63 rich-list migration to auto-include admin users (would
  change tenant config semantics — deferred).
- SMS variant of the admin fan-out (existing K63 SMS path
  already covers this need; broadening it can happen later).
