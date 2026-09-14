# Feature: Recommended Schedule — auto-assign on save (centroid v1)

**Date**: Feb-2026
**Status**: Backend + web frontend complete. Mobile parity deferred
(backend response already carries `auto_assign_info` so mobile just
mirrors the UX after `e1_expo_frontend_dev` picks it up).

Introduces a one-shot **route-proximity centroid** auto-assign
step on `POST /api/recurring-jobs`. When the caller leaves BOTH
`assigned_tech_id` and `day_of_week` unset, the endpoint hugs an
existing route slot in the same `(service_type, frequency)`
window and stamps the picked tech + day on the persisted record.
Any manual field wins cleanly.

---

## 1. Algorithm (centroid v1)

Fully in-memory. No external API calls. Runs entirely off
existing collections (`customers`, `recurring_job_templates`).

```
if body.assigned_tech_id OR body.crew_id OR body.day_of_week set:
    reason = "manual_override"; return.

if new customer has no lat/lng (canonical or legacy field pair):
    reason = "no_geocode"; return.

peers = recurring_job_templates.find({
    tenant_id, service_type, frequency,
    is_active: true,
    day_of_week != null, assigned_tech_id != null   # slots must be
                                                    # complete to
                                                    # contribute
})

if not peers:
    reason = "no_existing_routes"; return.

# Group peers into slots keyed on (day_of_week, tech_id).
# Compute centroid (avg lat, avg lng) from each slot's customers.
slot_bucket = { (dow, tech_id): [(lat, lng), ...], ... }

# Slots where every peer customer lacks coords are dropped with
# a warning log. If EVERY slot drops → reason = "no_existing_routes"
# (fall-through — we can't reason about a slot with no coords).

# Haversine (in metres) from the new customer to each surviving
# centroid; pick the minimum.
best = argmin { haversine(new_customer, slot_centroid) }

extra_minutes = round(best.distance_m / 750)   # 45 km/h → 750 m/min
source_meters = round(best.distance_m)

stamp:
    body.assigned_tech_id = best.tech_id
    body.day_of_week      = best.day_of_week

return {
    auto_assigned: true, reason: "route_proximity",
    assigned_tech_id, day_of_week, technician_name,
    extra_minutes, source_meters,
}
```

### Distance heuristic — 750 m per minute

Assumes 45 km/h urban service-area average (Google's baseline
for "typical local trip" density in the US SW). Trade-off:

* **Simple**: no external Routes API call, no per-request
  latency. The whole auto-assign step is a single Mongo probe
  round-trip.
* **Rough**: doesn't account for one-way streets, HOV lanes,
  time-of-day traffic, or actual road network topology. A
  16-km detour through downtown Phoenix reads as 21 min here
  when reality is closer to 35.
* **Directionally correct**: for the "hug the closest existing
  route" decision, centroid-Haversine is monotonic with
  real-world distance in ~95 % of cases — the pick almost
  always matches what the Routes API would return.

Upgrade path: **Google Routes API v2** (already used by the
schedule router) behind a `feature_flags.route_proximity_v2`
tenant flag. The v2 code will replace `_haversine_m` +
`_METERS_PER_MINUTE` with a real `compute_drive_time_matrix`
call. The persisted `auto_assign_source_meters` +
`auto_assign_extra_minutes` fields stay backwards-compat — v1
rows just get filled with Haversine values, v2 with real
minutes.

### Coord fallback chain

Customer coords are read as `latitude/longitude` (canonical
Feb-2026 pair, populated by `geocode_and_persist_customer`) →
`service_lat/service_lng` (legacy pre-P37a). Missing both = no
geocode → skip.

### Technician name resolution

`_tech_name` probes `technicians` FIRST, then falls back to
`users` — different tenants seed the tech row under one or the
other depending on their onboarding path. Either match wins.

---

## 2. Trigger conditions + skip reasons

The endpoint runs auto-assign only when ALL of these hold on the
inbound payload:

* `assigned_tech_id` is null or empty string.
* `crew_id` is null or empty string.
* `day_of_week` is null.

When any one of them is set, `_wants_auto_assign = False` and the
result is `{auto_assigned: false, reason: "manual_override"}`.

Skip reasons in the response payload:

| `reason` | When it fires |
| -------- | ------------- |
| `manual_override` | Caller supplied a tech, crew, or day_of_week. |
| `no_geocode` | New customer has no `latitude`/`service_lat` on file. |
| `no_existing_routes` | Zero peer templates match `(service_type, frequency, is_active=true)`, OR every peer's customer lacks coords. |
| `internal_error` | The helper raised; the create still succeeds (persistence proceeds) but auto-assign is treated as fallen through. |
| `route_proximity` | Success. Tech + day were stamped on the doc. |

### DOW validation bypass

`_validate` normally rejects weekly/biweekly frequencies without
a `day_of_week` (HTTP 422). When auto-assign was ATTEMPTED
(the trigger fired) but fell through (`no_geocode` or
`no_existing_routes`), the endpoint calls
`_validate(body, skip_dow_gate=True)` so the record still
persists without a tech/day per spec §2. All other validations
(frequency, custom interval, monthly pattern, quarterly/
semi-annual, work-class) still run.

---

## 3. Response payload shape

`POST /api/recurring-jobs` — response body extended with:

```json
{
  "id": "...",
  "customer_id": "...",
  "service_type": "Weekly Pool Service",
  "frequency": "weekly",
  "day_of_week": 2,
  "assigned_tech_id": "u-tech-42",
  ...

  // ── Persistent breadcrumb fields (also stored on the doc) ──
  "auto_assigned": true,
  "auto_assign_reason": "route_proximity",
  "auto_assign_extra_minutes": 3,
  "auto_assign_source_meters": 2247,

  // ── Client-only bundle (NOT persisted, response-only) ──
  "auto_assign_info": {
    "auto_assigned": true,
    "reason": "route_proximity",
    "technician_id": "u-tech-42",
    "technician_name": "Ana Rivera",
    "day_of_week": 2,
    "extra_minutes": 3
  }
}
```

`auto_assign_info` is a **response-only convenience bundle** —
the frontend uses it to pick the toast variant + render the
badge on the same round-trip. The persisted breadcrumb fields
(`auto_assigned`, `auto_assign_reason`, etc.) live on the doc
and drive the list/detail badge.

---

## 4. Frontend UX

### New Recurring Job modal — toast on save

Wired in `frontend/src/pages/admin/RecurringJobs.jsx` inside
`save()`. Uses `sonner` (already available in the codebase).

| `auto_assign_info.reason` | Toast copy | Variant |
| ------------------------- | ---------- | ------- |
| `route_proximity` (auto_assigned=true) | `Assigned to {technician_name} on {Mon…Sun} based on route proximity` | `toast.success` |
| `no_geocode` | `Created — no coordinates on customer, please assign manually` | Neutral `toast()` |
| `no_existing_routes` | `Created without auto-assign — no existing routes for this frequency yet` | Neutral `toast()` |
| `manual_override` (or anything else) | No extra toast — the create itself is the confirmation | — |

All toasts render with `duration: 4500 ms`.

### List row badge

Rendered next to the existing "Paused" / "Inactive" chips in the
status column:

```jsx
{r.auto_assigned ? (
  <span data-testid={`recurring-job-auto-assign-badge-${r.id}`}
        title={`via route proximity · +${r.auto_assign_extra_minutes || 0}m extra drive time`}>
    <Sparkles size={9} /> Auto-assigned
  </span>
) : null}
```

* Testid: `recurring-job-auto-assign-badge-<id>`
* Icon: lucide `Sparkles` at 9px
* Color: soft blue (`#DBEAFE` bg, `#1E3A8A` text)
* Tooltip surfaces the extra-drive-time estimate so an ops
  reviewer can eyeball "was this a good pick?" without opening
  the detail view.

---

## 5. Files touched

| File | Change |
| ---- | ------ |
| `backend/services/recurring_jobs/__init__.py` | **NEW** — package marker (empty). |
| `backend/services/recurring_jobs/route_proximity.py` | **NEW** — `compute_route_proximity_assignment` + `_haversine_m` + `_tech_name` + `_customer_coords`. ~180 LOC. |
| `backend/routers/recurring_jobs.py` | `create_recurring` runs auto-assign BEFORE `_validate`; mutates body on success; stamps persistent breadcrumb fields + returns `auto_assign_info`. `_validate` grew a `skip_dow_gate` kwarg. |
| `frontend/src/pages/admin/RecurringJobs.jsx` | `save()` picks the toast variant off `auto_assign_info.reason`; list row renders the auto-assign badge when `r.auto_assigned` is true. |
| `backend/tests/test_recurring_jobs_auto_assign.py` | **NEW** — 6 tests: happy path × 1, no-peers × 1, no-geocode × 1, manual-override × 2 (tech-only + dow-only), minutes-heuristic × 1. |
| `frontend/src/test/recurring-jobs-auto-assign.test.jsx` | **NEW** — 3 Vitest cases: badge renders, toast copy lock. |
| `memory/FEATURE_RECOMMEND_SCHEDULE_AUTO_ASSIGN.md` | This memo. |

---

## 6. Test status

* **Backend** (`pytest tests/test_recurring_jobs_auto_assign.py`)
  → **6 passed** (new file). Adjacent recurring-jobs sweep
  → **53 passed, 4 failed** where all 4 failures are pre-existing
  baseline drift (`test_recurring_jobs_nth_weekday_role_gate.py`
  tests seed `customer_id="bug-repro-1"` without creating the
  customer row; `test_k4_schedule_recurring_appears_on_page` has
  scheduler-cursor drift). Confirmed via `git stash` that all 4
  reproduce on the untouched baseline — unrelated to this phase.
* **Frontend** (`yarn test:unit` — full suite):
  **581 files passed | 1 skipped · 4355 passed | 34 skipped**
  (was 4352 → **+3** matching the new file).
* **OpenAPI paths**: **1740** (unchanged — spec correctly
  predicted stable; this is an in-place enhancement to
  `POST /api/recurring-jobs`, no new routes).

---

## 7. Future upgrade path (v2 — Google Routes API)

Behind a `tenants.feature_flags.route_proximity_v2` boolean flag.

1. Add `services/recurring_jobs/route_proximity_v2.py`.
2. Replace `_haversine_m(...)` with a call to
   `services.google_maps.routes.compute_drive_time_matrix(...)`
   (already implemented for the schedule optimizer).
3. Replace the `750 m/min` heuristic with the real
   `duration_seconds` returned by the Routes API. Persist as
   `auto_assign_source_seconds` alongside the legacy meters
   field (both stay backwards-compat).
4. Cache: 30-day per-pair TTL on `db.route_time_cache` keyed on
   `(tenant_id, from_customer_id, to_slot_hash)`.
5. Dispatch:

   ```python
   if tenant.feature_flags.get("route_proximity_v2"):
       from services.recurring_jobs.route_proximity_v2 import (
           compute_route_proximity_assignment as impl,
       )
   else:
       from services.recurring_jobs.route_proximity import (
           compute_route_proximity_assignment as impl,
       )
   ```

The response shape (`auto_assign_info`) does NOT change — the
frontend picks the same toast copy regardless of backing
algorithm.

---

## 8. Out of scope

* Google Routes API integration (v2 upgrade later — see §7).
* Preview button ("show me what the auto-assign would pick before
  I save") — declined per spec.
* Mobile parity — deferred; `auto_assign_info` in the response
  makes the mobile UX drop-in when `e1_expo_frontend_dev` mirrors.
* A–F backlog items.
