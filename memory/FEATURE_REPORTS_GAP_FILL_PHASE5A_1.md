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


---

# Part B — Attrition Report + Time to Get Paid

Second dispatch of Phase 5a.1. Ships the remaining 2 reports from
the original 5a.1 catalog slice. Same shell pattern as Business
Snapshot: flat-grid `ReportsHub.jsx` tile with a section badge, a
dedicated `/reports/*` page (`AdminOnly`-gated), a
`/api/reports/*` endpoint, CSV export, date-range filter (via the
existing `DateRangePicker` component), tenant scope.

## Attrition Report — endpoint contract

`GET /api/reports/attrition`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Response envelope:

```jsonc
{
  "summary": {
    "total_attrited": 0,
    "attrition_rate_pct": 0.0,
    "avg_ltv_of_attrited": 0.0
  },
  "rows": [
    {"customer_id", "customer_name", "became_inactive_at",
     "inactive_reason", "lifetime_value", "last_service_date"}
  ],
  "chart": {"reason_counts": {"<reason>": <int>}},
  "tenant_id":   "<tid>",
  "start_date":  "<iso>",
  "end_date":    "<iso>",
  "computed_at": "<iso>"
}
```

Section badge: `Others`. Route: `/reports/attrition` (`AdminOnly`).

### Sample curl (verified live on preview)

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
TOKEN=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/attrition?start_date=2026-02-01&end_date=2026-02-28" \
   -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Canonical data-source pins (Attrition)

| Field | Source | Notes |
|---|---|---|
| Inactive transition | `db.customers.is_active=false` (union of P27-muted rows and plain-deactivated rows) | Excludes `deleted_at`-set rows so cleanup doesn't drift the numbers. |
| `became_inactive_at` | `muted_at` (mute path) OR `updated_at` (deactivation path) | Rows with neither are excluded — we don't invent a transition date. |
| `inactive_reason` | `muted_reason` (P29 field) OR `"not_specified"` fallback | Matches the P29 semantic. `not_specified` surfaces the population that was deactivated without a reason. |
| `lifetime_value` | `routers.analytics._lifetime_revenue_by_customer` (**direct import**) | Cockpit parity is a compile-time guarantee, not copy-paste. Same helper that powers the analytics dashboard. |
| `last_service_date` | latest `db.jobs.completed_at` per `customer_id` | Mirrors `analytics.churn_risk` picking pattern. |
| `attrition_rate_pct` | `total_attrited / at_risk_denominator * 100`, 1dp | Denominator = customers created **before** the window (the population "at risk" during it). |

## Time to Get Paid — endpoint contract

`GET /api/reports/time-to-get-paid`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Response envelope:

```jsonc
{
  "summary": {
    "avg_days_to_paid": 0.0,
    "p50_days": 0.0,
    "p90_days": 0.0,
    "invoices_counted": 0
  },
  "rows": [
    {"invoice_id", "customer_id", "customer_name",
     "sent_at", "paid_at", "days_to_paid"}
  ],
  "chart": {"monthly_avg_days":
    [{"month": "YYYY-MM", "avg_days": <float>}, ...]},
  "tenant_id":   "<tid>",
  "start_date":  "<iso>",
  "end_date":    "<iso>",
  "computed_at": "<iso>"
}
```

Section badge: `Receivables`. Route: `/reports/time-to-get-paid`
(`AdminOnly`).

### Sample curl (verified live on preview)

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
TOKEN=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/time-to-get-paid?start_date=2025-11-11&end_date=2026-02-11" \
   -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Canonical data-source pins (TTGP)

| Field | Source | Notes |
|---|---|---|
| Collection | `db.quotes` where `doc_type="invoice"` AND `payment_status="paid"` | Phase-11 unified invoice ledger; this is what `analytics.churn_risk` reads at L172-192 and what `finances` writes on invoice send. |
| `sent_at` proxy | invoice `sent_at` if present, else `created_at` | The unified invoice schema does NOT reliably stamp a distinct `sent_at`. `estimator.py:1089` stamps it on estimates, `finances.py:181` bumps status to "sent" without a timestamp on the invoice doc. The helper prefers explicit `sent_at` when it exists, otherwise falls back to `created_at`. Documented deviation from the literal spec wording. |
| Delta validity | both timestamps present AND `paid_at >= sent_at` | Negatives and NULLs dropped from BOTH summary and rows (spec: "do not compute against partials"). |
| Percentiles | linear interpolation (Excel-compatible PERCENTILE.INC) | Deterministic on empty input → `0.0`. |
| Trailing 12-month chart | bucketed by `paid_at.strftime("%Y-%m")` | Independent of the window filter, per spec. |

### Cockpit-parity spot-check (TTGP)

Grep for `time_to_get_paid`, `days_to_paid`, `DSO` across
`routers/`, `services/`, `frontend/src/`. No cockpit tile with
the name "Time to Get Paid" currently renders on the preview
seed data. The closest live surface is `routers/dunning.py:700`
which computes a **weighted DSO** for AR aging — semantically
distinct from "days from sent to paid" (DSO is about
*outstanding* balance, this report is about *cycle time* on
already-paid invoices). No live parity spot-check possible today;
when a Time to Get Paid cockpit tile lands, its query should call
this endpoint (or reuse `_percentile` / `_parse_dt`) rather than
re-derive the numbers.

Live curl on the current preview tenant (Aquaterra) with a
90-day filter returned `invoices_counted=2` with all-zero
percentiles — the paid invoices in the seed data are same-day
pays. That's the truthful state.

## Files touched (Part B)

**Backend**

* `routers/reports_attrition.py` — new.
* `routers/reports_time_to_get_paid.py` — new.
* `server.py` — 2 router imports + registrations (10-line block
  next to the Business Snapshot registration).
* `tests/_f7_loop_fixture.py` — 2 module names appended to
  `_REBOUND_MODULES` for the Motor loop rebind.
* `tests/test_reports_attrition.py` — new; **5 tests**.
* `tests/test_reports_time_to_get_paid.py` — new; **5 tests**.

**Frontend**

* `src/pages/reports/AttritionReport.jsx` — new page: 3 summary
  tiles + horizontal-bar reason chart + row table + CSV export +
  `DateRangePicker`-driven refetch.
* `src/pages/reports/TimeToGetPaidReport.jsx` — new page: 4
  summary tiles + SVG line chart (trailing-12mo monthly avg) +
  row table (desc by `days_to_paid`) + CSV export +
  `DateRangePicker`-driven refetch.
* `src/pages/reports/ReportsHub.jsx` — 2 icon imports
  (`UserMinus`, `Clock`) + 2 new tiles in `builtTiles` with
  section badges `Others` / `Receivables`.
* `src/App.js` — 2 imports + 2 routes (both `AdminOnly`).
* `src/test/attrition-report.test.jsx` — new; **3 tests**.
* `src/test/time-to-get-paid-report.test.jsx` — new; **3 tests**.

## Test results (Part B)

Backend:

| Suite | Result |
|---|---|
| `test_reports_attrition.py` | **5/5 ✅** |
| `test_reports_time_to_get_paid.py` | **5/5 ✅** |

Backend regression sweep (7 suites re-run in one shot including
Business Snapshot, forced-password-reset, temp-password,
S3 Phase-1, multi-contact Phase-2): **53/53 ✅**.

Frontend:

| Suite | Result |
|---|---|
| `attrition-report.test.jsx` | **3/3 ✅** |
| `time-to-get-paid-report.test.jsx` | **3/3 ✅** |

Frontend regression sweep (7 suites re-run in one shot including
Business Snapshot, forced-password-reset, chooser, bootstrap,
portal login): **27/27 ✅**.

OpenAPI: `GET /api/openapi.json` returns 200 with **1715 paths**
(+3 since the pre-5a.1 baseline of 1712). Both new endpoints
appear:

* `/api/reports/attrition`
* `/api/reports/time-to-get-paid`

## Guardrails respected (Part B)

* Preview-only. No prod deploy. No Save-to-GitHub.
* No `/app/mobile/` files touched.
* No external repo cloned.
* English only. Small-diff per report.
* Phase 5a.2 / 5b NOT started in this dispatch.

## Deviations (Part B)

* **`sent_at` fallback to `created_at`.** The Phase-11 unified
  invoice ledger doesn't reliably stamp a distinct `sent_at` on
  the invoice doc — `finances.py:181` sets `status="sent"`
  without a timestamp, and `estimator.py:1089` stamps `sent_at`
  on *estimate* docs. The report prefers explicit `sent_at` when
  present and falls back to `created_at`. If ops wants a precise
  send-time going forward, a follow-up ticket can wire a
  `services/invoice_send/sent_at_stamp.py` write on the send
  path — outside the small-diff scope for this dispatch.
* **No live cockpit parity for Time to Get Paid.** No cockpit
  tile with that name renders today; the closest cousin is the
  weighted DSO tile in `dunning.py` which measures a semantically
  different thing (outstanding balance vs cycle time).
* **LTV pinned to `analytics._lifetime_revenue_by_customer`
  (paid-invoice sum).** The Phase-5a.2 "Client Lifetime Value"
  report will introduce a richer LTV model. This router imports
  the current canonical helper by name so a future upgrade
  auto-propagates without touching this file — Phase-5a.2
  alignment target per the dispatch brief.

## Queue update

**5a.1 (COMPLETE):**

* ~~Business Snapshot~~ ✅ shipped
* ~~Attrition Report~~ ✅ shipped (this dispatch)
* ~~Time to Get Paid~~ ✅ shipped (this dispatch)

**5a.2 (next):**

* Revenue by Service
* Recurring vs. Project Revenue
* Client Lifetime Value

**Phase 5b:**

* Close Ratio
* Time to Close
* Labor Efficiency
* Booked Out / Capacity
