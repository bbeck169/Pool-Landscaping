# Phase 1 — Custom Trigger Builder · Backend (Feb 2026)

## Deliverables Checklist

**1. Central event registry** — `services/marketing/event_registry.py`  ✅ (pre-existing, extended with `invoice_past_due_N_days` alias)
- 15+ canonical events cataloged with `entity` / `scheduled` / `allow_negative_offset` metadata.
- Legacy → canonical alias map handles `service_completed → job_completed`, `birthday → customer_birthday`, `estimate_accepted → estimate_signed`, and the `invoice_past_due_{3,7,14,N}_days → invoice_overdue` collapse.

**2. Schema-v2 trigger evaluator** — `services/marketing/trigger_evaluator.py`  ✅ (pre-existing)
- 4 delay modes: `immediate`, `after {value,unit}`, `before {value}` (anchors on `event_payload.scheduled_at`), `on_weekday {weekday, time_local}`.
- 9 filter dimensions: customer_segment, work_class, tags, technician_id, crew_id, job_value_gte, zip, last_visit_gte_days, custom_fields (eq/neq/gte/lte/contains/in).
- AND / OR combining across N conditions.
- Fail-closed semantics on missing ctx keys.

**3. Event dispatcher + ledger dedupe** — `services/marketing/event_dispatcher.py`  ✅ (pre-existing)
- `emit_event(event, tenant_id, entity_id, customer_id, scheduled_at, payload_extras, correlation_id)`
- Deduplicates on `marketing_event_ledger` unique index `(tenant_id, customer_id, event_key)`.
- Runs BOTH the legacy `on_event` fanout AND the schema-v2 evaluator in one call — additive during migration window.

**4. Emission hooks (additive-only)** ✅
| File | Event(s) | Site |
|---|---|---|
| `routers/leads.py` | `new_lead` | `POST /leads` (background task) |
| `routers/leads.py` | `lead_status_changed` | `_apply_lead_update` when status flips |
| `routers/estimates.py` | `estimate_sent` | `POST /estimates` |
| `routers/estimate_viewer.py` | `estimate_signed` | `_mark_accepted` |
| `routers/jobs.py` | `job_scheduled` | `POST /jobs` (if scheduled_date present) + `PUT /jobs/{jid}` (when scheduled_date changes) |
| `routers/jobs.py` | `job_completed` | `PUT /jobs/{jid}` when status flips to `completed` |
| `routers/jobs.py` | `job_cancelled` | `PUT /jobs/{jid}` when status flips to `cancelled` |
| `routers/jobs.py` | `repair_flagged` | `POST /jobs` + `PUT /jobs/{jid}` when work_class → `repair` |
| `routers/quotes.py` | `invoice_sent` | `POST /quotes` (doc_type=invoice) |
| `routers/quotes.py` | `invoice_paid` | `record-payment` (fully_paid) + `pay_quote` |
| `services/payments/stripe_charge.py` | `invoice_paid` | `handle_webhook_event` on `payment_intent.succeeded` |
| `services/payments/stripe_charge.py` | `payment_failed` | `handle_webhook_event` on `payment_intent.payment_failed` |
| `routers/service_reports.py` | `chemistry_out_of_range` | `submit` when any banded core reading outside "Average" |

All 5 existing legacy `_drip_on_event` fanouts remain UNTOUCHED — the new emissions are additive and dedupe against the same ledger.

**5. Daily cron sweeps** — `services/marketing/phase1_sweeps.py` ✅
Registered in `server.py` at **09:05 UTC** (5 min after M5c sweep):
- `_sweep_invoice_overdue(tenant_id)` — walks `db.quotes` for unpaid past-due invoices.
- `_sweep_customer_birthday(tenant_id)` — MM-DD match on `customers.birthday`. Correlation includes year → 1× per year.
- `_sweep_service_anniversary(tenant_id)` — MM-DD match on `first_service_at || created_at`, skips year 0. Correlation includes anniversary year.
- `_sweep_job_scheduled_reminder_1d(tenant_id)` — re-arms the reminder for schema-v2 sequences.

**Per-tenant isolation**: `daily_phase1_trigger_sweep` wraps EACH sub-sweep for EACH tenant in its own try/except — one slow/broken tenant never blocks another.

**6. Boot migration** — `services/migrations/migrate_sequences_to_v2.py` ✅
Registered in `server.py` startup after tech-backfill.
- Reads every `marketing_sequences` doc; skips any already at `schema_version >= 2` (idempotent).
- Rewrites legacy `trigger_type + trigger_config` into `trigger:{logic:AND, conditions:[{event, delay:{mode:"immediate"|"after"}, filters:{}}]}` + stamps `schema_version=2`.
- Legacy fields PRESERVED — zero regression on M5c path.
- Special case: `invoice_past_due_N_days` with `days_past_due=N` becomes `delay:{mode:"after", value:N, unit:"day"}` on `invoice_overdue`.
- Emits summary log: `migrated=N skipped=M preserved=N tenants=T`.

**7. `POST /api/marketing/sequences/{sid}/preview-matches`** ✅
Response shape:
```json
{
  "sequence_id": "...",
  "evaluated_at": "2026-02-15T09:00:00+00:00",
  "match_count": 122,
  "sample": [{"customer_id":"...", "name":"...", "reason":"..."}],
  "truncated": true
}
```
- Body: `{trigger_override?: {...}, limit?: 1..25}`. Server hard-caps `limit` at 25.
- No writes. Walks customers OR jobs depending on whether every condition names a job-scoped event.
- 404 for unknown sequence.

**8. Pytest suite** — `tests/test_marketing_phase1_trigger_builder.py` ✅
**41 tests, all passing.** Covers:
- 5 event_registry tests (catalog completeness, alias resolution, gates)
- 8 delay-mode tests (all 4 modes + roll-forward + invalid raise)
- 10 filter-dimension tests (all 9 dims + missing-ctx fail-closed + empty pass-through)
- 5 AND/OR/empty-conditions/event-mismatch/first-hit tests
- 2 dispatcher idempotency tests
- 3 migration tests (v1→v2, v2 re-run no-op, past-due offset preservation)
- 4 sweep tests (birthday dedupe, invoice_overdue selective hit, anniversary year-0 skip, tenant isolation via monkey-patch)
- 4 preview-matches tests (shape, 25-sample cap + truncated flag, 404, trigger_override)

## Files Created
- `/app/backend/services/marketing/phase1_sweeps.py`
- `/app/backend/services/migrations/migrate_sequences_to_v2.py`
- `/app/backend/tests/test_marketing_phase1_trigger_builder.py`

## Files Modified (additive-only)
- `/app/backend/services/marketing/event_registry.py` (add `invoice_past_due_N_days` alias)
- `/app/backend/routers/marketing_sequences.py` (`preview-matches` endpoint)
- `/app/backend/routers/leads.py` (`new_lead`, `lead_status_changed`)
- `/app/backend/routers/estimates.py` (`estimate_sent`)
- `/app/backend/routers/estimate_viewer.py` (`estimate_signed`)
- `/app/backend/routers/jobs.py` (`job_scheduled`, `job_completed`, `job_cancelled`, `repair_flagged`)
- `/app/backend/routers/quotes.py` (`invoice_sent`, `invoice_paid`)
- `/app/backend/services/payments/stripe_charge.py` (`invoice_paid`, `payment_failed` webhook path)
- `/app/backend/routers/service_reports.py` (`chemistry_out_of_range`)
- `/app/backend/server.py` (scheduler + boot migration registration)

## Verification
- 41/41 Phase 1 tests pass.
- Pre-existing test failures unrelated to Phase 1 (documented in PRD) — verified via git stash comparison.
- Live smoke test: `preview-matches` returns 122 matches on the seeded aquaterra tenant, `sample_len=25`, `truncated=true`.
- Boot migration executed on live server — all 16 sequences now report `schema_version=2 · has_trigger=True`.

## Next Action Items
- **P1**: Phase 2 — Custom Trigger Builder Frontend (react builder UI that consumes `preview-matches`).
- **P2**: Add auto-suggest tech from crew on the New Job form.
- **P2**: Surface crew-only jobs on individual tech schedules (`scope_jobs_query`).
- **P2**: Add auxiliary hint text back to `<CustomerCombobox>` dropdown options.
- **P2**: Nullable numeric write path for chemical optional readings.
- **P2**: Workstream tech-isolation, reschedule tech_name drift, workstream Manager RBAC — deferred backlog.
- **P3**: Refactor `service_reports.py:1626` door-hanger send path to use `resolve_technician_names` cascade.
