# FIX — `POST /api/schedule/optimize-route` day filter + technician targeting

**Phase:** Web · Preview only  
**Scope:** `backend/routers/route_optimization.py` (optimize-route endpoint + `OptimizeIn` schema) · Test coverage.  
**Out of scope:** Any frontend change (CalendarSchedule already sends `technician_id`) · Any refactor of the routing service beyond these two edits · Any recurring-jobs backend changes.

## Two defects, one file — both fixed

### 1. Day filter now matches `scheduled_date` too

Before: the Mongo filter matched `scheduled_start` only (`{"$gte": day_start, "$lte": day_end}`). Any job seeded with the flat `scheduled_date` ISO string (legacy seeds + the recurring-generator writes) was silently dropped — which is most of them.

After: mirrored **verbatim** from `get_route_stops` (same file, `~line 508`):

```python
"$and": [{
    "$or": [
        {"scheduled_start": {"$gte": day_start, "$lte": day_end}},
        {"scheduled_date": date_str},
    ],
}],
```

Both endpoints stay in sync. If the day-filter contract shifts in one, the other should follow in the same PR.

### 2. Technician targeting bug — body `technician_id` now honored

Before: the endpoint only accepted `user_id` as a **query param**. `CalendarSchedule.optimizeRoute` sends `technician_id` in the **body** payload — the body was ignored and the endpoint always ran against the caller.

After:
- `OptimizeIn` now declares `technician_id: Optional[str] = None` on the body model.
- Resolution order (unchanged auth):
  1. `body.technician_id` when present.
  2. `user_id` query param (backwards compat with legacy callers).
  3. Caller's own `user["id"]` as the default.
- Admin / super_admin gate on the override path is preserved.
- Non-admin caller passing another user's id → **403 `Cannot optimize another user's route`** (unchanged).
- Technicians are blocked at `role == "technician"` upstream (pre-existing Feb-2026 hotfix, line 113-118) — untouched.
- Cross-tenant guard now falls back to `technicians.id` when the direct `users.id` lookup misses (mirrors the resolution cascade in `get_route_stops`) so the frontend can send either shape without a 404.

## Tests added

`backend/tests/test_route_optimization.py`:

- **`test_optimize_route_honors_body_technician_id_for_admin`** — admin caller passes `technician_id=<mike>` in the body payload; endpoint plans for Mike (not admin). Seeded job's id appears in `ordered_job_ids`.
- **`test_optimize_route_day_filter_matches_scheduled_date`** — seeds two co-located jobs with `scheduled_date` only (no `scheduled_start`); both appear in the optimizer output for that day.

Both tests live-run against the preview backend and clean up after themselves.

## Test-suite status

- `pytest tests/test_route_optimization.py`: **4 passed, 1 skipped** (sunbelt tenant missing — pre-existing).
- Pre-existing baseline failures in `test_route_optimization_google_directions.py` + `test_route_optimizer_response_contract.py` + `test_route_optimization_approval.py` remain and are **unrelated** to this fix (they seed a `role: "technician"` user and hit the pre-existing dispatcher-only 403 gate). Verified against a `git stash` snapshot of the pre-fix source.

## OpenAPI

Still **1736** paths — no new routes.

## Files touched

- `backend/routers/route_optimization.py`
- `backend/tests/test_route_optimization.py`
- `memory/FIX_OPTIMIZE_ROUTE_DAY_FILTER_AND_TECH_TARGETING.md` (this doc)
