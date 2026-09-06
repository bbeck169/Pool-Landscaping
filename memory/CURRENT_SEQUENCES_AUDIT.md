# Current "Sequences" (post-K69: Automations) — Feature-Surface Audit
## Prepared Feb 2026 for GHL-parity scoping

**Purpose:** Give the user a single-page snapshot of what the
existing marketing "sequences" surface (renamed to **Automations**
in the UI under K69) actually does today, so the future
GoHighLevel-parity Workflows rebuild can be scoped against a
concrete gap list.

The audit is written against the code paths as of the K69 rename;
backend collections + route names (`marketing_sequences.py`,
`db.marketing_sequences`) intentionally keep the old terminology
for backwards compat.

---

## 1. Where it lives

| Layer | Path |
|-------|------|
| FE route | `/marketing/automations`, `/marketing/automations/new`, `/marketing/automations/:id` (with 301-equivalent `<Navigate>` redirects from the old `/sequences` paths). |
| FE admin route | `/admin/marketing/automations`. |
| FE components | `pages/marketing/MarketingSequencesPage.jsx` (admin CRUD + editor modal), `pages/marketing/SequencePages.jsx` (public/legacy list + detail), `components/marketing/triggerBuilder/TriggerBuilder.jsx` (Phase-2 condition editor). |
| BE router | `routers/marketing_sequences.py`. Endpoints stay under `/api/marketing/sequences/*`. |
| BE services | `services/marketing/drip_events.py`, `services/marketing/event_registry.py`, `services/marketing/enrolments.py`, `services/marketing/lead_triggers.py`, `services/marketing/scheduler.py`. |
| DB collections | `db.marketing_sequences`, `db.marketing_sequence_enrolments`, `db.marketing_sequence_sends`, `db.marketing_event_ledger`. |

---

## 2. Triggers available today

Sourced from `services/marketing/event_registry.py::EVENT_CATALOG`.
This is the **canonical** catalog rendered by the Phase-2 trigger-
builder UI dropdown.

| Wire key | UI label | Entity | Scheduled? | Negative offset ok? |
|----------|----------|--------|:---:|:---:|
| `new_lead` | New lead created | lead | no | no |
| `lead_status_changed` | Lead status changed | lead | no | no |
| `estimate_sent` | Estimate sent | estimate | no | no |
| `estimate_signed` | Estimate signed | estimate | no | no |
| `job_scheduled` | Job scheduled | job | **yes** | **yes** |
| `job_scheduled_reminder_1d` | 1 day before scheduled job | job | yes | yes |
| `job_completed` | Job completed | job | no | no |
| `job_cancelled` | Job cancelled | job | no | no |
| `invoice_sent` | Invoice sent | invoice | no | no |
| `invoice_paid` | Invoice paid | invoice | no | no |
| `invoice_overdue` | Invoice overdue | invoice | yes | no |
| `payment_failed` | Payment failed | payment | no | no |
| `customer_birthday` | Customer birthday | customer | yes | yes |
| `service_anniversary` | Service anniversary | customer | yes | yes |
| `chemistry_out_of_range` | Chemistry out of range | job | no | no |
| `repair_flagged` | Repair job flagged | job | no | no |

Plus two **non-event enrolment surfaces** (legacy, still supported):

* `manual` — admin manually enrols a specific customer / lead
  from the sequence detail page.
* `segment_join` — nightly sweep enrols any customer that newly
  matches a saved segment definition.

**Legacy aliases** kept for backwards compat (`service_completed`,
`customer_created`, `review_left`, `estimate_accepted`,
`invoice_past_due_{3,7,14,N}_days`, `birthday`) map onto the
canonical keys above at read time.

---

## 3. Trigger conditions (Phase-2 Trigger Builder)

The Phase-2 upgrade added a **filter layer** on top of the event
trigger — a nested `trigger.conditions` doc evaluated when the
event fires. The editor renders as a per-condition-group form
(NOT a canvas). Supported condition atoms:

| Field family | Ops | Example |
|--------------|-----|---------|
| Lead fields (`source`, `status`, `service_interest`, `est_value`) | eq, neq, gt, gte, lt, lte, in | `lead.source in ["Widget", "Website"]` |
| Customer fields (`tags`, `channel_opt_in.email`, `channel_opt_in.sms`, `lifetime_value`) | contains, eq, gte | `customer.tags contains "vip"` |
| Job fields (`services[]`, `technician_id`, `est_value`) | contains, eq, gt | `job.services contains "chlorine_wash"` |
| Invoice fields (`total`, `days_past_due`) | gt, gte | `invoice.days_past_due gte 7` |
| Time-of-day / day-of-week | in | window guard against 2am sends |

Groups compose with AND / OR to arbitrary depth. Evaluator lives
at `services/marketing/conditions.py::evaluate_conditions`.

---

## 4. Actions available today

Two step types, both configured per-step in the editor:

| Step type | Fields | Notes |
|-----------|--------|-------|
| `email` | `template_id`, `delay {mode, value, unit}`, `subject_override?` | Uses `marketing_templates` doc; Resend adapter delivery. Suppressions checked pre-send. |
| `sms` | `template_id`, `delay {mode, value, unit}` | RingCentral adapter delivery. Character-limit warning at editor time. |

Step delays: `{mode: "after", value: 3, unit: "days"}` or
`{mode: "before", value: 1, unit: "days"}` (only valid when the
trigger event has `allow_negative_offset: true` — see catalog
above).

Sequence-level toggles:
* `active` — pause / resume the automation without deleting it.
* `stop_on_reply` — abort remaining steps if the customer replies
  by SMS or email.
* `stop_on_unsubscribe` — abort if the customer unsubscribes at
  any point.

**Actions we do NOT have today** (blockers vs GHL):
- Wait-for-condition step (branching wait).
- If/else split (path fork based on a condition).
- Assign-task step (create a `db.tasks` row for a technician).
- Update-contact-field step.
- Add/remove tag step.
- HTTP webhook step.
- Loop / go-to-step primitive.
- AI-conversation step (GHT calls this "AI Employee action").

---

## 5. Configuration surface — form, not canvas

The editor is a **linear form**:

* Left panel — trigger picker (dropdown) + condition builder
  (grouped rows).
* Right panel — ordered list of steps, add/remove, drag-to-
  reorder inside the same channel.
* Preview modal — renders the templated email/SMS body against a
  chosen sample recipient (a real customer of the tenant).

**No canvas**, no visual flow-chart. Every step executes in strict
`order` sequence. No parallel branches, no wait-for-condition
gates, no conditional splits.

---

## 6. Templates + snippets

`db.marketing_templates` has **789 docs** across all tenants right
now, of which **644 are system-provided** (industry-canned drips
Emergent ships out-of-the-box: welcome, review request, past-due,
green-pool follow-up, chemistry alert). The remaining ~145 are
tenant-customised.

Templates carry:
* `subject` (email only).
* `body` — MJML-ish for email, plain-text w/ Liquid interpolation
  for SMS.
* Merge variables: `{{customer.name}}`, `{{invoice.total}}`,
  `{{job.date}}`, `{{tenant.brand.primary_color}}`, etc.
* `is_system` flag — system templates are read-only per tenant
  but can be "cloned" into a custom copy for editing.

---

## 7. Actual usage snapshot (production data at audit time)

Live counts against `db.marketing_sequences`:

| Metric | Value |
|--------|------:|
| Total docs | 42 |
| **Active** | **0** ⚠️ |
| Distinct tenants with at least one doc | 10 |
| System-shipped drips available | 644 templates (not yet fanned out as sequences) |

Every one of the 42 rows is currently a **test / M5c CRUD
scratch row** (names like `M5 crud renamed`, `M5 enrol …`,
`M5 casc …`). No tenant has a production automation running
right now — this is a **feature that shipped but has never been
turned on by a real user**, which makes it a clean canvas for
the GHL-parity rebuild.

---

## 8. Gaps vs GoHighLevel Workflows (rebuild scoping list)

Ranked roughly by user impact:

1. **No visual canvas.** GHL's workflow builder is a drag-and-drop
   flowchart with connectors between steps. Our editor is a linear
   ordered list. Users mentally map to GHL and expect the canvas
   — this is likely the #1 reason for zero adoption.
2. **No if/else branching.** GHL lets you split on any condition
   (e.g. lead source, tag, custom field). We can only filter at
   the trigger, then run one linear path.
3. **No wait-for-condition step.** GHL can pause a workflow until
   an event happens (`Wait until estimate signed OR 7 days`). We
   only support fixed delays.
4. **No task / assign-user step.** GHL can drop a task on a
   specific team member (or round-robin the team). We only have
   email + SMS steps.
5. **No tag / field manipulation.** GHL workflows routinely
   add/remove tags and update custom fields as side effects. Ours
   are pure send-message pipelines.
6. **No webhook step.** GHL can call external HTTP endpoints as
   part of a workflow. We have zero integration hooks.
7. **No AI-conversation step ("AI Employee").** GHL's headline
   feature; would map onto our Emergent LLM Key stack cleanly but
   we have nothing today.
8. **No goal / conversion tracker.** GHL lets you set a "goal
   event" so the workflow automatically drops a contact when they
   convert (e.g. lead → customer). We rely on `stop_on_reply` +
   `stop_on_unsubscribe` only.
9. **No workflow-level analytics.** We have `MarketingAnalyticsPage`
   with per-sequence open/click/reply counters but no funnel
   drop-off visualisation.
10. **No versioning / edit-in-place safety.** GHL keeps history so
    admins can roll back a bad edit. We overwrite in place.
11. **No global template library UI.** System templates exist in
    the DB but there's no browsable library the user can pull
    from — you can only pick a template from the step-edit form.
12. **No A/B testing.** Nice-to-have.
13. **Trigger catalog is smaller.** GHL has ~40 native triggers
    (birthday, appointment reminder, form submit, calendar
    booking, opportunity moved, contact tag added…). We have 16
    canonical events + 2 non-event surfaces. Roughly 60% overlap.

---

## 9. What we DO have that GHL doesn't (retain in rebuild)

* Native suppression list check on every send (Phase 27), keyed
  to a specific `send_type` (`marketing`, `review_request`,
  `automation`) so a contact that's opted-out of marketing can
  still receive an invoice reminder.
* Native muted-contact + muted-customer honoring — the same
  contact record that muted a technician also mutes the drip.
* Segment-based enrolment via nightly sweep (`segment_join`).
* System-canned drips out-of-the-box (644 templates).
* Every automation writes an `audit_logs` row for the K63 lead-
  alert dispatcher and a dedicated `marketing_event_ledger` row
  for the send — full delivery observability.
* Per-tenant brand-token injection (`{{tenant.brand.primary_color}}`)
  so a single template renders correctly across every tenant.

---

## 10. Migration considerations for a GHL-parity rebuild

* **Data:** existing 42 docs are all test / scratch data. Safe to
  wipe. Zero prod data to migrate.
* **Templates:** the 789 `marketing_templates` docs (644 system +
  ~145 tenant custom) DO have production value — the rebuild
  should keep this collection intact and consume it from the new
  workflow schema.
* **Backend routes:** `/api/marketing/sequences/*` should stay
  live for the transition and shadow-write the new schema, then
  redirect once the new UI ships. Or, cleanly deprecate — 0
  active sequences means the risk is very low.
* **UI:** `/marketing/automations` (K69 name) becomes the new
  workflow builder. The K69 rename already prepared the URL
  slug + label for it, so users won't see a second rename.

