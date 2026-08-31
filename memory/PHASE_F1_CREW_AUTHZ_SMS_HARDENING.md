# Phase F1 · Feb-2026 — Crew Tech Authz Helper + SMS Identity Hardening

## Ship summary
Fixed two P0 bugs identified in the Feb-2026 data-integrity audit:

- **P0-B (crew tech "Not your job")**: Every job-touching gate that
  compared `job.technician_id != user.technician_id` inline now
  routes through the shared helper
  `services.authz.is_tech_authorized_on_job(user, job, db, tenant_id)`.
  The helper accepts either a **direct assignment** (user_id or
  technician_id) OR **crew membership** (job.crew_id resolves to a
  crew whose `tech_ids` array contains the caller). This is the same
  semantics `scope_jobs_query` (schedule scoping) has been using — F1
  makes the JobDetail + write endpoints agree.
- **P0-A (portal service-request SMS crosswire)**:
  `routers/customer_portal.py::create_service_request` now derives
  `customer_name` / `customer_phone` / `customer_email` **strictly from
  the customers row** (`cust`). Prior code fell back to
  `user.name` / `user.phone` first — a stale session paired with a
  fresh customer row shipped the SMS with mismatched identity.
  Added a hard invariant assertion: if the session's
  `user.customer_id` != the resolved `cust.id`, the endpoint raises
  **HTTP 500** and logs `service_request identity_drift ...`. No SMS/
  email fires when the invariant fails.

## Files touched
| File | Change |
|---|---|
| `backend/services/authz.py` | **NEW** — shared helper. |
| `backend/routers/jobs.py` | Added import; refactored 11 tech gates. |
| `backend/routers/workstream_job_detail.py` | Refactored `GET /jobs/{jid}/detail` tech gate — the direct repro path for the P0-B bug. |
| `backend/routers/job_media_line_items.py` | Refactored `_tech_can_touch` (now async) — 4 gates. |
| `backend/routers/maintenance.py` | Refactored `POST /jobs/{jid}/maintenance-log` gate. |
| `backend/routers/service_reports.py` | Refactored `_authorize_report` — 4 downstream endpoints. |
| `backend/routers/customer_portal.py` | SMS identity hardening + drift assertion. |

## Scope notes (deltas from the greenlit plan)
- The plan said *"jobs.py + mirrors in dispatch.py + mobile_sync.py"*.
  Actual audit: `dispatch.py` and `mobile_sync.py` have **zero**
  `"Not your job"` gates — nothing to refactor there. The real
  mirrors are `workstream_job_detail.py`, `job_media_line_items.py`,
  `maintenance.py`, and `service_reports.py`. All refactored to keep
  the user's "don't leave half-fixed" rationale intact — the reported
  bug repro path lives in `workstream_job_detail.py` (the JobDetail
  aggregator).
- The handoff note said `db.crews.member_ids` — the actual field is
  `crews.tech_ids`. Helper uses `tech_ids`, matching
  `scope_jobs_query` on `routers/jobs.py:248`.

## Regression tests (all passing — 49/49)
- `backend/tests/test_jobs_crew_membership_authorization.py` — 9 tests
- `backend/tests/test_schedule_visibility_matches_job_detail.py` — 5 tests
- `backend/tests/test_portal_service_request_ignores_body_customer_id.py` — 2 tests
- `backend/tests/test_portal_service_request_sms_template_single_source.py` — 3 tests
- `backend/tests/test_f1_crew_authz_integration.py` — 30 live-HTTP integration tests (added by testing agent, seeds a crew-only job in Mongo, drives the real preview URL as `carlos@aquaterra.com` — Blue Crew member)

## Follow-up fix from first test pass
- **`routers/jobs.py::list_job_edits` (~line 1836)** — the `find_one`
  projection was narrowed to `{id, technician_id, deleted_at}`, so
  `crew_id` was absent from the job dict passed to
  `is_tech_authorized_on_job`. The helper's crew-branch short-circuited
  and every crew-only job returned 403. **Fixed by widening the projection
  to include `crew_id` and `tenant_id`.** All 30 integration tests now
  pass.
- Contract to keep: any `db.jobs.find_one` whose result feeds into
  `is_tech_authorized_on_job` MUST include `crew_id` (and `tenant_id`).
  Prefer `{"_id": 0}` (full doc) unless the projection is deliberately
  narrow for performance.

Run with:
```
cd /app/backend && python3 -m pytest \
  tests/test_jobs_crew_membership_authorization.py \
  tests/test_schedule_visibility_matches_job_detail.py \
  tests/test_portal_service_request_ignores_body_customer_id.py \
  tests/test_portal_service_request_sms_template_single_source.py -v
```

## Follow-ups (Phase F2 / F3 · pending your greenlight)
- **F2 · Data repair** — dry-run first, target 10 dangling customer
  refs and 2 dangling tech refs surfaced in the audit.
- **F3 · Guardrails** — startup boot-check for dangling refs +
  contract tests.
- **Tech Debt** — log 6 unassigned-scheduled jobs (Dashboard hint UX).
