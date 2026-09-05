# Phase K58 — Mobile Schedule Map Coord Resolver Ladder

**Ship date:** Feb 2026
**Scope:** Backend `/api/jobs` coord serialisation + mobile shared coord
resolver.  Root fix for the user-reported "No mapped stops today" empty
state on the mobile Schedule → Map view.
**Status:** 🟢 SHIPPED — Slice A (backend) + Slice B (mobile).

---

## Field report (context)

Users reported the mobile Schedule surface's Map sub-view rendering the
empty state ("No mapped stops today") on the exact same day that the
List sub-view showed 5+ jobs.  Diagnosis (K58 6-point report) turned up
a **serialisation gap** in `GET /api/jobs`:

* Backend job docs carried coord data on `job.latitude/longitude` (26
  jobs) and `job.site_lat/site_lng` (30 jobs) but the API serializer
  only surfaced `customer.service_lat` under `location_lat/lng`.  Only
  1 customer in the tenant had `service_lat` populated → only 5 jobs
  emerged from the API with a mappable coord.
* Mobile `ScheduleMap.native.tsx`'s filter was
  `j.location_lat != null && j.location_lng != null` — no fallback
  to the wider coord field set that `DailyRouteMap.native.tsx` on the
  same screen already supported via its inline `resolveJobCoords()`.

User adjudication: ship both fixes as **Option C** — backend
resolver ladder (Slice A) AND mobile shared helper (Slice B) — split
into two commits for revert safety.

## Slice A — Backend `/api/jobs` coord resolver ladder

**File:** `backend/routers/jobs.py::list_jobs` (~lines 620-730 post-K58).

Ladder (highest priority first — first hit wins):

| Rung | Source                                     | Notes |
|------|--------------------------------------------|-------|
| 1    | `job.site_lat` / `job.site_lng`            | Written by `services/google_maps/geocoding.py` (30 jobs in preview tenant). |
| 2    | `job.latitude` / `job.longitude`           | Newer geocoding write path (26 jobs in preview tenant). |
| 3    | `property.latitude` / `property.longitude` | Batched via `properties.find({"_id": {"$in": pids}})`.  Inner fallback to `property.lat` / `property.lng` (flat shape). |
| 4    | `customer.service_lat` / `customer.service_lng` | Pre-K58 baseline.  Seeded in the customer enrichment block above; the ladder OVERRIDES with a higher rung when available. |

Output — every job in the response payload now carries the resolved
coords under **two** keys:

* `location_lat` / `location_lng` — historical alias (mobile web +
  legacy consumers).
* `latitude` / `longitude` — K58 dual-key output for the mobile
  shared-helper's Rung 2 (defence-in-depth against a future consumer
  drifting off the `location_*` alias).

Both keys are stamped in lockstep — same float, same `None`.

### Batched property lookup

The pre-K58 property enrichment already used a single
`properties.find({"_id": {"$in": pids}})` batch — no N+1.  Slice A
extended that projection to include the four coord field variants
(`latitude`, `longitude`, `lat`, `lng`) so the resolver ladder can
consume it without a second query.  `pmap` is hoisted outside the
`try/except` scope so the K58 ladder can reference it after the
enrichment block.  When the property fetch fails, `pmap` remains the
empty dict and rungs 3 falls through to rung 4 (no crash).

### Role scope

The ladder is gated on `user.get("role") != "customer"` — customers
never see coord fields on the job payload (pre-K58 contract preserved).

### Tests

`backend/tests/test_jobs_map_coord_ladder.py` — 6 pytest cases:

1. Rung 1 wins over rungs 2/3/4.
2. Rung 2 wins over rungs 3/4 when rung 1 absent.
3. Rung 3 wins over rung 4 when rungs 1/2 absent.
4. Rung 4 is the fallback when no higher rung fires.
5. All-empty rungs → `None` on both key pairs (never 0.0).
6. Batched property lookup: 3 jobs across 3 distinct `property_id`
   values return correct rung-3 coords (implicit batching assertion).

**Live impact:** in the preview tenant, jobs surfacing with mappable
coords increased from 5 (pre-K58) to 34 (post-K58) — a **6.8×** jump
in map pins with no code change on the mobile side yet.  Slice B
adds another rung of defence.

## Slice B — Mobile shared coord helper

**New file:** `mobile/src/utils/jobCoords.ts`

Extracted the pre-K58 inline `resolveJobCoords()` from
`DailyRouteMap.native.tsx`, generalised it, and re-exported it as the
shared helper both map components consume.

Ladder (highest priority first):

| Rung | Source                                     |
|------|--------------------------------------------|
| 1    | `job.location_lat` / `job.location_lng`    |
| 2    | `job.latitude` / `job.longitude`           |
| 3    | `job.site_lat` / `job.site_lng`            |
| 4    | `job.property?.location?.{lat,lng}`        |

Plus ancillary defensive tolerances carried over from the pre-K58
helper:

* Non-finite / NaN values treated as absent.
* `(0, 0)` "null island" coord pair treated as absent (upstream
  geocoders occasionally emit it as a "no result" marker).
* String-typed coord values that `Number()` can parse are accepted
  (legacy DB rows that stored coords as strings).
* Legacy `job.location` + `job.service_address.coordinates` shapes
  preserved as sub-rungs for cross-tenant safety.

### Consumer wiring

* **`mobile/src/components/schedule/ScheduleMap.native.tsx`** —
  strict-flat `j.location_lat != null && j.location_lng != null` gate
  replaced with the shared helper.  The `geocoded` array now carries a
  `__coords` annotation on each entry so the render loop reads the
  resolved value once (no per-marker ladder recompute).
* **`mobile/src/components/schedule/DailyRouteMap.native.tsx`** — the
  pre-K58 inline `resolveJobCoords` is now a thin re-export of the
  shared helper.  Preserves the public API for any test / consumer
  that imports `resolveJobCoords` from this file.

### Tests

`mobile/__tests__/k58-jobCoords.test.ts` — 13 Jest cases:

* Rungs 1-4 priority assertions.
* Null / undefined / all-empty inputs → `null`.
* `(0, 0)` null-island guard (falls through to next rung).
* NaN / Infinity rejection.
* String coord acceptance.
* `property.location.lon` (spelling variant) tolerated.
* `jobHasCoords` boolean equivalence.
* **Parity gate**: grep-based assertion that both
  `ScheduleMap.native.tsx` AND `DailyRouteMap.native.tsx` import
  `resolveJobCoords` from `@/src/utils/jobCoords`.  Also asserts the
  pre-K58 strict-flat predicate no longer exists in
  `ScheduleMap.native.tsx` (regression guard).

## Guardrail respected

If EVERY job in the day window still has zero coords after the ladder,
`ScheduleMap.native.tsx` still renders the "No mapped stops today"
empty state.  That's correct behaviour — the fix is to give the
resolver something to resolve, not to render a fake pin at (0, 0).

## Revert safety

* **Slice A** — the K58 ladder block (single block in `jobs.py`) can be
  deleted and the projection reverted; the pre-K58 baseline (customer
  `service_lat/lng` seeded into `location_lat/lng`) still fires
  unchanged.  Pmap hoisting is compatible with pre-K58 code paths.
* **Slice B** — restore the pre-K58 inline `resolveJobCoords` in
  `DailyRouteMap.native.tsx` and revert `ScheduleMap.native.tsx`'s
  filter.  The shared helper module can remain in place (unused).

## Follow-ups

* **K58.1 (P2, backlog)** — customer geocoding backfill: only 1 of 154
  customers had `service_lat` populated.  Migration to run
  `services/google_maps/geocoding.py` over all customers with an
  address but no `service_lat` — would light up rung 4 for the ~30 %
  of jobs that fall through rungs 1-3.  Not a blocker for K58.
* **K58.2 (P2, backlog)** — property geocoding backfill: 124 of 327
  properties have `latitude` / `longitude`, 5 have flat `lat` / `lng`
  only.  Reconciliation ticket to normalise to a single shape and
  backfill the rest.
* **K7 mobile parity** (unrelated, in queue) — apply today-default
  filters to mobile workstream so the coord ladder's benefit surfaces
  even when the tech opens Schedule mid-day.
