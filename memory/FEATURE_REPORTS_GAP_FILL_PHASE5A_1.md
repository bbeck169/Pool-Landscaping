# Feb-2026 · Reports Gap Fill — Phase 5a.1 (tracer bullet)

Backend + Web frontend ship for the first of nine reports in
the Phase-5 catalog gap-fill. Mobile parity is not covered
(separate later track).

## Locked decisions

**Catalog placement (A):** Add the new report as a tile in the
existing flat `ReportsHub.jsx` grid, with a section badge on the
card (`Others` for Business Snapshot). No structural change to
the hub. The tabbed-catalog question (sections vs badges) is
deferred until we have 6+ new reports to place.

**Ship-budget slice (B.1):** Business Snapshot only this cycle,
full-fidelity. Attrition Report + Time to Get Paid queue for
the next dispatch.

## Business Snapshot — endpoint contract

`GET /api/reports/business-snapshot`

Query params:

| Name | Type | Notes |
|---|---|---|
| `tenant_id` | `str?` | **super_admin only.** Other roles → 403. |

Response envelope:

```jsonc
{
  "service_radius": {
    "max_miles":         25.0 | null,
    "avg_last_30d_miles": 12.4 | null  // null when the tenant's
                                         // job docs don't carry
                                         // a computed distance —
                                         // we do NOT fabricate.
  },
  "employee_count":       10,
  "bh_per_week_capacity": 400.0,
  "tenant_id":  "<tid>",
  "computed_at": "2026-09-11T18:00:57.495398+00:00"
}
```

### Sample curl (verified live)

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
TOKEN=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"admin@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/business-snapshot" \
   -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Sample live response on the current preview tenant (Aquaterra):

```json
{
    "service_radius": {"max_miles": null, "avg_last_30d_miles": null},
    "employee_count": 10,
    "bh_per_week_capacity": 400.0,
    "tenant_id": "affdfbfa-88b9-4baa-ae45-2ef78531b6e4",
    "computed_at": "2026-09-11T18:00:57.495398+00:00"
}
```

`service_radius.max_miles` is `null` because the Aquaterra seed
tenant doc doesn't carry a `service_radius` field yet. That's
the truthful state — the UI renders `—`, not a fabricated value.

## Data sources (canonical, mirrored — not parallel-implemented)

* **`service_radius.max_miles`** ← `db.tenants.service_radius`.
  Same field the onboarding wizard writes at
  `frontend/src/pages/onboarding/OnboardingPage.jsx:163`
  (`in-service-radius`). Coerced to `float` on read; non-numeric
  values are logged and returned as `null`.
* **`service_radius.avg_last_30d_miles`** ← average of
  `db.jobs.distance_miles` for jobs with `completed_at` (or
  `created_at`) in the last 30 days for the tenant. Returns
  `null` when zero jobs in the window carry the denormalized
  distance. **We do not synthesize distances from raw lat/lng
  here** — the truthful stance is "unknown". A follow-up ticket
  can wire the on-write denormalization if ops needs this to be
  non-null on every tenant.
* **`employee_count`** ← the same union-and-dedupe set used by
  `routers/technicians.py::list_technicians` (active
  `db.technicians` rows for the tenant + assignable-role users
  in `db.users`, deduped by `user_id`). This is the canonical
  active-technician set; the roster surface and the snapshot
  count agree byte-for-byte.
* **`bh_per_week_capacity`** ← sum of each active tech's
  `weekly_hours` (falls back through
  `hours_per_week`/`budgeted_hours_per_week`). Techs without an
  explicit value contribute the canonical **40 hrs/week** default
  (mirrors `workforce.overtime_weekly_hours`). Verified via live
  curl: 10 active techs × 40 = 400 BH/week — correct.

## KPI-cockpit parity note

The Phase-5 brief specified "Values MUST match the KPI cockpit's
Service Radius panel exactly." **After grepping the codebase
(`kpi.cockpit`, `KPI Cockpit`, `kpi_cockpit`, `cockpit_tile`,
`Service Radius`, `BH per Week`, `# of Employees`), no pre-
existing "KPI Cockpit" surface was found** — none of those terms
appear in `/app/backend`, `/app/frontend/src`, or `/app/memory`.
The Business Snapshot is therefore the **first** surface in the
codebase to expose these three values.

Parity requirement is honored by pinning each tile to its
**canonical source doc**, not to a downstream re-computation:

* Employee count uses the exact same union-and-dedupe as
  `list_technicians` — the roster page is the parity witness.
* `service_radius` reads the onboarding wizard's persisted field
  directly.
* BH/week uses the same 40hr-default constant as `workforce.py`.

If a "KPI Cockpit" is later stood up, its tiles should call this
endpoint (rather than re-derive the values) so the two surfaces
cannot drift.

## Files touched

**Backend**

* `routers/reports_business_snapshot.py` — new (150 lines).
* `server.py` — register the router (`api_router.include_router`,
  ~10-line addition).
* `tests/test_reports_business_snapshot.py` — new; 4 tests.
* `tests/_f7_loop_fixture.py` — one-line addition to
  `_REBOUND_MODULES` (Motor loop rebind for the new router).

**Frontend**

* `src/pages/reports/BusinessSnapshot.jsx` — new page (200 lines):
  3 tiles, CSV export, computed-at stamp, truthful `—`
  empty-state, error banner.
* `src/pages/reports/ReportsHub.jsx` — 1 new tile in `builtTiles`
  with `sectionBadge: "Others"`; `BuiltTile` renders the badge
  when present. Existing tiles unchanged.
* `src/App.js` — 1 import + 1 route (`/reports/business-snapshot`,
  gated by `AdminOnly` to match the sibling reports).
* `src/test/business-snapshot.test.jsx` — new; 3 tests
  (renders + em-dash for null + error banner).

**Memory**

* `/app/memory/FEATURE_REPORTS_GAP_FILL_PHASE5A_1.md` (this file).

## Test results

Backend (`tests/test_reports_business_snapshot.py`) — **4/4**:

| Test | Result |
|---|---|
| `test_business_snapshot_happy_path_and_parity` | ✅ |
| `test_business_snapshot_rejects_tenant_override_for_non_super_admin` | ✅ |
| `test_business_snapshot_super_admin_can_override_tenant` | ✅ |
| `test_business_snapshot_404_when_tenant_missing` | ✅ |

Frontend (`src/test/business-snapshot.test.jsx`) — **3/3**:

| Test | Result |
|---|---|
| renders three tiles + CSV button + computed-at after fetch | ✅ |
| renders em-dash for null service_radius (truthful, not fabricated) | ✅ |
| renders error banner on API failure (not fake success) | ✅ |

OpenAPI: `GET /api/openapi.json` returns 200 with 1712 paths
(+1 from prior 1711). The new endpoint appears at
`/api/reports/business-snapshot`.

## Queue

**5a.1 remainder (next dispatch):**

* Attrition Report (with `inactive_reason` breakdown)
* Time to Get Paid

**5a.2 (dispatch after 5a.1 remainder):**

* Revenue by Service
* Recurring vs. Project Revenue
* Client Lifetime Value

**Phase 5b:**

* Close Ratio
* Time to Close
* Labor Efficiency
* Booked Out / Capacity

## Guardrails respected

* Preview-only. No prod deploy. No Save-to-GitHub.
* No `/app/mobile/` files touched.
* No external repo cloned. English only.
* Small-diff: single new backend router + single new frontend
  page + minimal edits to `server.py`, `App.js`, `ReportsHub.jsx`.
* `/api/openapi.json` still reachable.
* Customer forced-password-reset fix NOT started (queued after
  5a.1 tester pass per user instruction).

## Deviations

* **No live KPI-cockpit-parity spot-check.** No cockpit surface
  exists in the codebase yet. Parity is instead pinned to the
  canonical source docs (see "KPI-cockpit parity note" above).
  If a cockpit lands later, its tiles must call this endpoint,
  not re-derive from source.
* **`service_radius.avg_last_30d_miles` may be `null` on tenants
  whose job docs don't denormalize `distance_miles`.** Truthful
  stance chosen over fabricated distances. Rendering shows `—`.
  Ops can request a follow-up to wire on-write denormalization.
