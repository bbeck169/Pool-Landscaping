# Fix — Preview Pool Checklist Fixture Seed (bundled-tester unblock)

**Phase**: Feb-2026 · P0 test-fixture unblock
**Scope**: backend seed only (web / mobile unchanged)

## Problem

Bundled tester dispatched to verify P0 #2 (legacy Chemical Readings
removed) was blocked by a data-setup issue in preview: the only
`status == "in_progress"` Pool-ish job (`c40ea98d-…`) carried
`service_report.template == "generic"`, so the checklist rendered the
empty-state "reclassify" picker instead of the 5 core-reading inputs
required by Tests 3–5.

## Fix

Added an idempotent seed helper `seed_preview_pool_checklist_job` in
`backend/seed.py` and wired it into `backend/server.py` right after
`seed_demo_second_customer` so it runs on every backend boot. The
helper mirrors the pattern established by `seed_demo_second_customer`.

Behaviour:

1. Look up the fixed target job `c40ea98d-d42b-4f91-890e-04fe398b0ee9`.
2. If already in the desired shape (`service_type == "Pool Cleaning"`
   AND `service_report.template == "pool"` AND
   `water_bodies[0].type == "pool"`), fast-path
   `{"created": False, "already_ok": True}` — no writes.
3. Otherwise `$set`:
   - `jobs.service_type = "Pool Cleaning"`.
   - `jobs.status = "in_progress"` (only when the job is not already
     there — leaves scheduled/completed rows alone in the freak case
     the fixture drifts).
   - `service_reports.template = "pool"`.
   - `service_reports.water_bodies[0]` → pool body carrying the five
     canonical CORE readings from `services/chemistry_gate.CORE_READINGS`
     (`free_chlorine`, `total_chlorine`, `alkalinity`, `ph`,
     `cyanuric_acid`), each with `value: None` so the tech has empty
     inputs to fill.
   - `service_reports.chemical_readings` mirrors the same 5 rows
     (matches the flatten-helper contract the close-gate reads).
4. Preserves any existing `id` / `label` / `chemicals_used` / `media`
   / `notes` from the current `water_bodies[0]` if present — no
   history stomp.
5. Emits an INFO log line on write, silent on the idempotent path.

## Files touched

| File | Change | LOC |
|---|---|---|
| `backend/seed.py` | new `seed_preview_pool_checklist_job` helper + constants | +52 |
| `backend/server.py` | one `await step(...)` line after `seed_demo_second_customer` | +7 |

Total: 59 LOC (helper is 52; the rest is the call-site + comment).

## Tester target

```
Job ID       : c40ea98d-d42b-4f91-890e-04fe398b0ee9
Customer     : Jennifer Carson · customer@aquaterra.com
Customer ID  : 8910bfde-3ba0-4b18-b54f-6ac5657af13d
Technician   : Carlos Rivera (id cc683510-b8f9-4762-b571-d1b389be8080)
Service type : Pool Cleaning
Status       : in_progress
Template     : pool
Water bodies : [{type: "pool", label: "Main Pool", readings: [5 empty core]}]
```

Log confirmation (from live boot):

```
[seed_preview_pool_checklist_job] reclassified
    job=c40ea98d-d42b-4f91-890e-04fe398b0ee9
    → service_type=Pool Cleaning, template=pool
```

Idempotent re-run:

```
>>> asyncio.run(seed_preview_pool_checklist_job())
{'created': False, 'already_ok': True,
 'job_id': 'c40ea98d-d42b-4f91-890e-04fe398b0ee9'}
```

## Test coverage

- Backend boot log confirms the seed ran and reclassified the job.
- Manual verification via direct Mongo read shows the target state
  landed correctly (see `[seed_preview_pool_checklist_job]` INFO
  above and DB snapshot inspected in the same session).
- Idempotency confirmed via a second in-process invocation returning
  `{"already_ok": True}` with zero writes.

## Out of scope

- Bulk reclassification of other `generic`-templated Pool-ish jobs.
  The helper targets one specific record used by the bundled tester;
  wider migration is deferred.
- Cleaning up the empty-state `pool-service-type-picker-block` path
  in `PoolChecklistForm.jsx` — separate follow-up.
- Mobile parity — mobile team handles its own fixtures.
