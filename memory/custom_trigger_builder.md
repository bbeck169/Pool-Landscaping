# Custom Trigger Builder — Internal Reference (Feb 2026)

**Scope**: Marketing Sequences · schema-v2 triggers · Phases 1-3.
**Owner surfaces**: `backend/services/marketing/`, `frontend/src/components/marketing/triggerBuilder/`.

This doc is the internal developer reference for the Custom Trigger Builder feature. For the Phase-1 deliverables checklist see `PHASE1_CUSTOM_TRIGGER_BUILDER.md`; this file focuses on the *how* — catalog, evaluator contract, and the day-to-day recipes.

---

## 1. Event catalog (16 canonical events)

Source of truth: `backend/services/marketing/event_registry.py::EVENT_CATALOG`.
The frontend consumes `GET /api/marketing/sequences/event-catalog` for the picker.

Every entry carries 4 metadata fields:

| Field | Purpose |
|---|---|
| `label` | Human-readable string for the UI dropdown. |
| `entity` | `lead` / `estimate` / `job` / `invoice` / `payment` / `customer`. Drives which document the evaluator hydrates. |
| `scheduled` | Whether the event has a native `scheduled_at`. Gates the `delay:{mode:"before"}` UI. |
| `allow_negative_offset` | Explicit gate for negative-offset (`"before"`) delays — some `scheduled` events (`invoice_overdue`) still forbid negatives. |

Current catalog:

| Event | Entity | Scheduled | Neg. offset |
|---|---|---|---|
| `new_lead` | lead | no | no |
| `lead_status_changed` | lead | no | no |
| `estimate_sent` | estimate | no | no |
| `estimate_signed` | estimate | no | no |
| `job_scheduled` | job | yes | yes |
| `job_scheduled_reminder_1d` | job | yes | yes |
| `job_completed` | job | no | no |
| `job_cancelled` | job | no | no |
| `chemistry_out_of_range` | job | no | no |
| `repair_flagged` | job | no | no |
| `invoice_sent` | invoice | no | no |
| `invoice_paid` | invoice | no | no |
| `invoice_overdue` | invoice | yes | no |
| `payment_failed` | payment | no | no |
| `customer_birthday` | customer | yes | yes |
| `service_anniversary` | customer | yes | yes |

Legacy `trigger_type` scalars (`service_completed`, `birthday`, `estimate_accepted`, `invoice_past_due_{3,7,14,N}_days`, `customer_created`, `review_left`) are aliased at read time via `LEGACY_TRIGGER_ALIASES`. Non-event surfaces (`manual`, `segment_join`) remain empty in v2 and never fire from `emit_event`.

---

## 2. Trigger schema v2

Persisted at `marketing_sequences.trigger` alongside `schema_version: 2`. Legacy `trigger_type`/`trigger_config` are preserved for zero-regression on the M5c editor path.

```json
{
  "logic": "AND",
  "conditions": [
    {
      "event": "job_completed",
      "delay": {"mode": "after", "value": 3, "unit": "day"},
      "filters": {
        "customer_segment": ["pool"],
        "work_class": ["service"],
        "tags": ["vip"],
        "technician_id": ["<uuid>"],
        "crew_id": ["<uuid>"],
        "job_value_gte": 500,
        "zip": ["85387"],
        "last_visit_gte_days": 30,
        "custom_fields": [
          {"key": "pool_type", "op": "eq", "value": "salt"}
        ]
      }
    }
  ]
}
```

Constraints:
- `logic ∈ {"AND", "OR"}` (case-insensitive on write; stored upper).
- `conditions` may be empty — evaluator returns `False`, so the sequence never fires. Used for `manual` / `segment_join` migration remnants.
- Every `condition.event` must resolve via `canonicalize_event_key` to a key in `EVENT_CATALOG`.
- Every `condition.delay` must pass `_validate_delay` (see §3).
- `filters` keys not listed in §4 are treated as unknown and silently ignored (fail-open at the filter dim level — an unknown key does not fail the filter closed). Consumers should therefore keep the filter shape stable.

Wire-shape validation lives in `routers/marketing_sequences.py::patch_sequence`. It re-runs on every PATCH, so a hand-crafted mutation over Compass still passes through the same guardrails.

---

## 3. Delay modes (4)

Contract: `resolve_enrollment_time(condition, event_payload, tenant_now?)` returns the UTC `datetime` at which the enrolment's first send should fire.

| Mode | Shape | Semantics |
|---|---|---|
| `immediate` | `{"mode":"immediate"}` | `next_send_at = now`. |
| `after` | `{"mode":"after","value":N,"unit":"minute\|hour\|day\|week"}` | `next_send_at = now + N units`. |
| `before` | `{"mode":"before","value":N}` (days only) | `next_send_at = event_payload.scheduled_at - N days`. Requires the event to carry `scheduled_at` — otherwise falls back to `now`. |
| `on_weekday` | `{"mode":"on_weekday","weekday":0-6,"time_local":"HH:MM"}` | Next matching weekday at `HH:MM` **UTC**. If today matches but time has passed → +7 days. |

Failure modes:
- Unknown mode / bad units / negative values → `ValueError` at validation time (surfaces as HTTP 422 on the PATCH).
- Bad `on_weekday` weekday (out of 0-6) or malformed `time_local` → `ValueError`.

The `on_weekday.time_local` is **UTC**, not tenant-local. Timezone-aware scheduling is a Phase 4 pickup — see §9 pitfalls.

---

## 4. Filter dimensions (9)

Every filter dim is optional. Missing → "don't care" (pass). Present but no ctx value for it → **fail closed** (do not enrol). This asymmetry is deliberate: an operator who explicitly opted for `tags:["vip"]` doesn't want a customer with no tags to slip through.

| Dim | Type | Ctx key | Match semantics |
|---|---|---|---|
| `customer_segment` | list<str> | `customer_segment` (from `customer.service_line` or `customer.segment`) | list intersection |
| `work_class` | list<str> | `work_class` (from `job.work_class`) | list intersection |
| `tags` | list<str> | `tags` (from `customer.tags`) | list intersection |
| `technician_id` | list<uuid> | `technician_id` (from `job.technician_id`) | list intersection |
| `crew_id` | list<uuid> | `crew_id` (from `job.crew_id`) | list intersection |
| `job_value_gte` | number | `job_value` (from `job.job_value` → `job.total`) | `float(ctx.job_value) >= filter` |
| `zip` | list<str> | `zip` (from `customer.service_zip` / `zip` / `billing_zip`) | list intersection |
| `last_visit_gte_days` | number | `last_visit_days_ago` (computed from `last_service_at`/`last_visit_at`) | `days_since >= filter` |
| `custom_fields` | list<spec> | `custom_fields` (from `customer.custom_fields`) | per-spec: see below |

`custom_fields` spec: `{"key": "<field>", "op": "eq"\|"neq"\|"contains"\|"gte"\|"lte"\|"in", "value": <any>}`. Every spec in the list must match (implicit AND across specs). `op:"in"` accepts an array value.

Hydration source: `event_dispatcher.hydrate_event_ctx(tenant_id, event, entity_id, customer_id, payload_extras)`. Preview endpoint uses the parallel `_build_preview_ctx` in `routers/marketing_sequences.py` (synchronous, no Motor round-trip).

---

## 5. AND / OR logic

Top-level combinator on the trigger doc. Behaviour:

- `logic: "AND"` — every condition in the list must match. Empty list → `False`.
- `logic: "OR"` — any condition matches. Empty list → `False`.
- `find_matching_condition(...)` returns the **first** hit — used by the enrolment writer to pick which condition's `delay` drives `next_send_at` when multiple OR branches match.

Cross-event OR is supported: `{logic:"OR", conditions:[{event:"invoice_paid"}, {event:"estimate_signed"}]}`. The evaluator only matches a condition whose `event` equals the payload's `event`, so an `invoice_paid` firing evaluates only the first branch; an `estimate_signed` firing evaluates only the second. Both enrol the same sequence via the same ledger entry.

---

## 6. Preview-matches endpoint

Contract: `POST /api/marketing/sequences/{sid}/preview-matches`.

Request body (optional):

```json
{
  "trigger_override": { "logic": "AND", "conditions": [...] },
  "limit": 25
}
```

- `trigger_override` — schema-v2 shape. When present, replaces the sequence's stored trigger for the preview run. This is what the Phase-2 `LiveMatchPreview` panel sends on every keystroke (with a 500ms debounce).
- `limit` — sample rows returned (1..25, server hard-caps at 25). The count is always the full scan; only the sample list is capped.

Response:

```json
{
  "sequence_id": "<sid>",
  "evaluated_at": "2026-02-15T09:00:00+00:00",
  "match_count": 122,
  "sample": [
    {"customer_id": "...", "name": "...", "reason": "job_completed · segment=pool · zip=85387"}
  ],
  "truncated": true
}
```

Walk selection heuristic: if every condition names a job-scoped event (`job_scheduled`, `job_scheduled_reminder_1d`, `job_completed`, `job_cancelled`, `chemistry_out_of_range`, `repair_flagged`) → walk jobs (limit 2000). Otherwise walk customers (limit 5000). Zero writes.

---

## 7. Recipe — add a new event to the catalog

1. **Add to catalog** — `backend/services/marketing/event_registry.py::EVENT_CATALOG` with `label`, `entity`, `scheduled`, `allow_negative_offset`.
2. **Add hydration** (if the event ships new ctx fields) — extend `event_dispatcher.hydrate_event_ctx` to load the entity from `payload_extras` first, then fall back to `db.<collection>.find_one`.
3. **Wire the emission** — add a single `emit_event(event=..., tenant_id=..., entity_id=..., customer_id=..., correlation_id=...)` call at the domain-event site (router / service / webhook handler). Use a stable `correlation_id` that's unique per (tenant, entity, meaningful state change) — this is what the ledger dedupes against.
4. **Legacy alias (if renaming)** — add the old key → new key mapping to `LEGACY_TRIGGER_ALIASES`. Do not rename a canonical key already shipped.
5. **Test coverage** — add a phase-1 unit test for evaluator behaviour and an e2e flow in `tests/test_custom_trigger_builder_e2e.py`.

No frontend changes required — the UI reads the catalog dynamically.

---

## 8. Recipe — add a new cron-driven event

Cron-driven events don't fire from a synchronous router touchpoint; they're swept from `backend/services/marketing/phase1_sweeps.py` at **09:05 UTC** daily.

1. Do §7 steps 1-3 for the event's catalog entry + hydration.
2. Add a `_sweep_<eventname>(tenant_id)` helper to `phase1_sweeps.py`:
   - Query only the current tenant (never cross-tenant).
   - For each match, call `emit_event(..., correlation_id=<stable-per-year-or-day-per-entity>)`.
   - Return the count of NEW fires (deduped ones are counted as 0 by construction).
3. Register the sweep in `daily_phase1_trigger_sweep()`. Wrap the call in its own `try/except` so a slow query on one tenant doesn't block the others.
4. Add a `_sweep_<eventname>` test in `tests/test_marketing_phase1_trigger_builder.py`.
5. Optional — expose the sweep via `POST /api/test-hooks/marketing/run-sweep?sweep=<name>` (routers/marketing_test_hooks.py) if you need e2e coverage that fires the sweep on demand.

**Timezone note**: sweeps run at 09:00 UTC (M5c legacy) + 09:05 UTC (Phase 1). All date comparisons are done in UTC. Tenant-local time is a Phase 4 pickup.

---

## 9. Common pitfalls

**Idempotency ledger — always pass a stable `correlation_id`.**
- `marketing_event_ledger` has a unique index on `(tenant_id, customer_id, event_key)` where `event_key = "<event>:<correlation_id>"`.
- If you omit `correlation_id`, the dispatcher falls back to `_correlation_from_meta` — fine for events that fire from a single site, but replay-fragile for anything that fires from multiple call sites.
- Reserve `correlation_id` shape per event family and document it inline. Examples:
  - `invoice_overdue` → `<invoice_id>`.
  - `customer_birthday` → `<customer_id>:birthday:<year>`.
  - `service_anniversary` → `<customer_id>:anniversary:<years>`.
  - `job_scheduled_reminder_1d` → `<job_id>:reminder1d:<yyyy-mm-dd>`.

**Tenant scoping — every query needs it.**
- The evaluator is pure and doesn't reach into the DB. But the dispatcher and preview endpoint DO. Every `find` / `find_one` must include `"tenant_id": tenant_id`. Missing it leaks across tenants.
- The `daily_phase1_trigger_sweep` per-tenant loop enforces this via its `try/except` wrapper — a slow query on tenant A can't block tenant B's sweep.

**Fail-closed on missing ctx keys.**
- If a filter dim is present in the trigger but its ctx key is missing on the hydrated payload, the evaluator returns `False`. This is intentional (see §4). If you're debugging "why doesn't this trigger fire on my seeded test data?" — check that `hydrate_event_ctx` actually populates the ctx key for your event.

**Timezone-aware weekday scheduling — currently UTC-only.**
- `delay:{mode:"on_weekday", weekday:0-6, time_local:"09:00"}` is anchored on the UTC clock, not the tenant's local timezone. Tenants in Phoenix hit "9am local" at 16:00 UTC — the sweep currently doesn't account for this. Phase 4 pickup: read `tenant.timezone` and compute local offsets.

**Boot migration is idempotent — do not re-run manually.**
- `services/migrations/migrate_sequences_to_v2.py` runs on every server start via the `services/migrations/` sentinel. It skips docs with `schema_version >= 2`. If you need to re-migrate a doc (e.g. after a manual DB fix that broke the trigger shape), unset `schema_version` in Mongo and restart the backend.

**Test hooks env gate.**
- The `routers/marketing_test_hooks.py` router is only mounted when `ALLOW_TEST_HOOKS=1`. The `APP_ENV=production` guard force-clears the flag before request handling but **after** the router is imported at boot — so in prod-mode preview environments, the endpoints are still reachable but require a `super_admin` JWT.

---

## 10. Frontend surfaces

**`TriggerBuilder.jsx`** — top-level state owner. Persists an unsaved draft to `localStorage.sequence.<id>.draftTrigger` so a page refresh doesn't lose work. Computes an `isDirty` flag from a canonical JSON diff against `initialTrigger` and:

1. Fires a sonner toast on the first dirty transition ("Unsaved changes — draft auto-saved locally").
2. Registers a `beforeunload` browser handler while dirty so a tab close prompts.

Emits `onChange`, `onValidityChange`, `onDirtyChange` callbacks so the parent `SequenceEditor` can gate its Save button.

**`ConditionRow.jsx`** — renders one row. Includes an HTML5 native drag handle (`GripVertical` from `lucide-react`) when the parent passes an `onReorder(from, to)` prop. The row itself is the drop target; the drag payload is the source row's index as a string.

**`FilterBuilder.jsx`** — 9 collapsible rows, one per filter dim. Empty rows are stripped by `helpers.stripEmptyFilters` before PATCH, so an operator who opens a filter row and then leaves it empty doesn't accidentally match nothing.

**`LiveMatchPreview.jsx`** — right-hand debug panel. 500ms debounced POST to `preview-matches` with the current draft as `trigger_override`. Zero-condition idle state shows "Add a condition to see match count".

**`helpers.js`** — pure utilities. `stripEmptyFilters`, `validateTrigger` (client-side gate), `buildTriggerPayload` (PATCH shape), `normaliseDelay`, `loadDraft`/`saveDraft`/`clearDraft`.

---

## 11. Tests

**Backend**
- `tests/test_marketing_phase1_trigger_builder.py` — 41 unit tests: catalog, evaluator, dispatcher, migration, sweeps, preview endpoint shape.
- `tests/test_custom_trigger_builder_e2e.py` — 9 e2e flows over HTTP: immediate, delayed, AND, OR, sweep idempotency, birthday sweep, ledger dedupe, filter negation, preview accuracy.

**Frontend**
- `src/test/trigger-builder.test.jsx` — 48 vitest cases covering helpers, EventPicker/DelayComposer/FilterBuilder/ConditionRow/TriggerBuilder/LiveMatchPreview components, integration payload shape, and Phase 3 polish (drag-reorder + unsaved-toast + zero-cond text).

---

## 12. Known deferred / Phase 4 pickups

- **Timezone-aware `on_weekday` scheduling** — read `tenant.timezone`, compute local send window.
- **Nullable numeric write path for chemical optional readings** — orthogonal to triggers but blocks `chemistry_out_of_range` filter richness.
- **Enrolment-side branching** (per-step condition beyond the trigger match) — schema exists (`steps[].condition`) but no UI or evaluator wiring yet.
- **Audit trail for sequence edits** — no `sequence_edits` collection today; a Compass-side mutation to `trigger` isn't observable in the UI.
