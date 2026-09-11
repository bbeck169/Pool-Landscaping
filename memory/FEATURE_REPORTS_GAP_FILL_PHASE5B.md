# Feb-2026 · Reports Gap Fill — Phase 5b.1 (Close Ratio + Time to Close)

Third and final major sub-phase of the reports gap-fill workstream.
Ships the first two of the four Phase 5b reports; Labor Efficiency
and Booked Out / Capacity are queued for **Phase 5b.2** and are
not touched in this dispatch.

## Split decision

Split as **5b.1 (Close Ratio + Time to Close) now** / **5b.2
(Labor Efficiency + Booked Out / Capacity) next**. Rationale:

* Both 5b.1 reports read from `db.leads` — a shared source that
  makes it cheap to bundle their recon, tests, and shell wiring.
* Time to Close mirrors the Time to Get Paid pattern verbatim
  (same `_iso_day_bounds`, `_parse_dt`, `_percentile`, trailing-
  12-month chart) — the diff is small and lints clean.
* 5b.2's two reports share the scheduling data source AND both
  reuse the Business Snapshot `bh_per_week_capacity` helper —
  they belong together and stay in isolation from the pipeline
  data model.
* Matches the user's stated preferred split.

Announced at the top of the dispatch before writing code, per
spec.

---

## Report 1 — Close Ratio

`GET /api/reports/close-ratio?start_date&end_date`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Envelope: `{summary: {close_ratio_pct, leads_created, leads_closed_won, leads_closed_lost}, rows: [{month, leads_created, closed_won, closed_lost, close_ratio_pct}], chart: {monthly_close_ratio: [{month, close_ratio_pct}]}, tenant_id, start_date, end_date, computed_at}`.

Section badge: `Others`. Route: `/reports/close-ratio` (`AdminOnly`).

### Sample curl (verified live on preview)
```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
T=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/close-ratio?start_date=2025-11-13&end_date=2026-02-11" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live on Aquaterra: `close_ratio_pct=66.7, leads_created=22, leads_closed_won=8, leads_closed_lost=4`.

### Canonical data-source pins
| Field | Source | Notes |
|---|---|---|
| Collection | `db.leads` | Same as `routers/leads.py` and `dashboard.py` lead counters. |
| Status enum | `closed_won` / `closed_lost` (canonical) | Same enum at `routers/leads.py:44`. |
| Legacy write compatibility | `Closed Won` / `Closed Lost` (title-case) | Legacy writes at `routers/leads.py:485,602` used title-case. The report normalizes on read (`_norm_status`) so old and new writes match up identically — no dependency on `migrate_lead_statuses` having run. |
| Denominator for ratio | `won + lost` only | Open leads excluded per spec. |
| Cohort semantics | `created_at` in window | "Of the leads born in the window, how many did we close?" — matches the standard sales interpretation of close ratio. |

---

## Report 2 — Time to Close

`GET /api/reports/time-to-close?start_date&end_date`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Envelope: `{summary: {avg_days_to_close, p50_days, p90_days, leads_counted}, rows: [{lead_id, customer_id, customer_name, created_at, closed_at, days_to_close, outcome}], chart: {monthly_avg_days: [{month, avg_days}]}, tenant_id, start_date, end_date, computed_at}`.

Section badge: `Others`. Route: `/reports/time-to-close` (`AdminOnly`). Uses `Hourglass` icon to visually distinguish from Time to Get Paid (`Clock`) in the hub grid.

### Sample curl (verified live on preview)
```bash
curl -s "$API/reports/time-to-close?start_date=2025-11-13&end_date=2026-02-11" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live on Aquaterra: `leads_counted=0` (seed data doesn't have any leads with `closed_at` set in that window — truthful `—` state; the seed writes closed-won without stamping `closed_at`, an existing data pattern this report does not paper over).

### Canonical data-source pins
| Field | Source | Notes |
|---|---|---|
| Collection | `db.leads` | Same as Close Ratio. |
| `created_at` / `closed_at` | Both required + `closed_at >= created_at` | Partial rows and negative deltas are silently dropped from BOTH summary and rows (spec: "do not compute against partials"). |
| Outcome filter | `status ∈ {closed_won, closed_lost}` after normalization | A stray `closed_at` on a still-open row is treated as data drift and excluded to avoid inflating counts — verified by `test_ttc_skips_open_leads_and_partials_and_negatives`. |
| Percentiles | `_percentile` — linear interpolation (Excel-compatible PERCENTILE.INC) | Verbatim mirror of the Time to Get Paid helper. |
| Trailing 12-month chart | bucketed by `closed_at.strftime("%Y-%m")` | Independent of the window filter, per spec (matches TTGP). |

---

## Files touched

**Backend (new)**
* `routers/reports_close_ratio.py`
* `routers/reports_time_to_close.py`
* `tests/test_reports_close_ratio.py` — 5 tests
* `tests/test_reports_time_to_close.py` — 5 tests

**Backend (edited)**
* `server.py` — 2 imports + 2 router registrations next to the
  Phase 5a.2 block.
* `tests/_f7_loop_fixture.py` — 2 module names added to
  `_REBOUND_MODULES`.

**Frontend (new)**
* `src/pages/reports/CloseRatioReport.jsx`
* `src/pages/reports/TimeToCloseReport.jsx`
* `src/test/close-ratio-report.test.jsx` — 3 tests
* `src/test/time-to-close-report.test.jsx` — 3 tests

**Frontend (edited)**
* `src/App.js` — 2 imports + 2 `AdminOnly` routes.
* `src/pages/reports/ReportsHub.jsx` — 1 icon import
  (`Hourglass`) + 2 new tiles in `builtTiles` with section
  badge `Others`.

**Memory** — this file, `/app/memory/FEATURE_REPORTS_GAP_FILL_PHASE5B.md`.

---

## Test results

Backend — **10/10 across the 2 new suites**:

| Suite | Result |
|---|---|
| `test_reports_close_ratio.py` | 5/5 ✅ |
| `test_reports_time_to_close.py` | 5/5 ✅ |

Backend regression sweep — **78/78 across 12 suites** (the 2 new
+ 5a.2 trio + 5a.1 Part B pair + 5a.1 Business Snapshot + Forced
Password Reset + Temp Password Flow + S3 Phase 1 + Multi-Contact
Phase 2).

Frontend — **6/6 across the 2 new suites**:

| Suite | Result |
|---|---|
| `close-ratio-report.test.jsx` | 3/3 ✅ |
| `time-to-close-report.test.jsx` | 3/3 ✅ |

Frontend regression sweep — **29/29 across 9 suites**.

OpenAPI: `GET /api/openapi.json` returns 200 with **1720 paths**
(+2 since Phase 5a.2, +8 since the pre-5a.1 baseline of 1712).
Both new endpoints appear:

* `/api/reports/close-ratio`
* `/api/reports/time-to-close`

---

## Guardrails respected

* Preview-only. No prod deploy. No Save-to-GitHub.
* No `/app/mobile/` files touched.
* No external repo cloned (recurring
  `bbeck169/Pool-Landscaping.git` injection remains ignored).
* Small-diff per report. Reused Time to Get Paid's percentile /
  parse-datetime helpers verbatim (implementation, not import —
  see deviations below).
* English only.
* Phase 5b.2 NOT started.

---

## Deviations

* **`_iso_day_bounds`, `_parse_dt`, `_percentile` are duplicated
  across `reports_time_to_get_paid.py` and `reports_time_to_close.py`
  rather than promoted to a shared helper module.** Small-diff
  bias: promoting these helpers now would require touching TTGP
  (a shipped, tested surface) which the spec explicitly forbids
  ("No opportunistic refactors of adjacent surfaces"). The two
  copies are byte-identical; a follow-up "Reports shared helpers"
  ticket can DRY this up once 5b.2 lands.
* **Status normalization is per-file inline, not a shared helper.**
  Both close ratio and time-to-close define `_norm_status`
  locally. Same reasoning as above — a shared module can be
  extracted once the Phase 5b workstream lands in full.
* **Time to Close uses `closed_at` (not `updated_at`) as the
  outcome timestamp.** `routers/leads.py:485` and `:602`
  explicitly stamp `closed_at` on the write path; using
  `updated_at` would drift on any post-close note edit. The
  report accepts this at the cost of dropping any lead whose
  historical write predates the `closed_at` addition — those rows
  are pre-close-metadata anyway and would have polluted the
  numbers with stale deltas.

---

## Queue update

**Phase 5b.1 (COMPLETE):**

* ~~Close Ratio~~ ✅ shipped (this dispatch)
* ~~Time to Close~~ ✅ shipped (this dispatch)

**Phase 5b.2 (next dispatch):**

* Labor Efficiency
* Booked Out / Capacity

Once 5b.2 lands, the KPI Cockpit → Reports gap-fill workstream is
complete (9 of 9 reports shipped across 5a.1 / 5a.1 Part B / 5a.2
/ 5b.1 / 5b.2).

---

# Phase 5b.2 — Labor Efficiency + Booked Out / Capacity

Final pair. Closes out the KPI Cockpit → Reports gap-fill
workstream (**9 of 9 reports shipped**).

## Business Snapshot capacity-helper reuse (parity requirement)

`routers/reports_booked_out_capacity.py` reuses Business
Snapshot's capacity helpers **by direct import at the module
top** — no parallel implementation, no copy-paste:

```python
# routers/reports_booked_out_capacity.py, module-level imports
from routers.reports_business_snapshot import (
    _active_technicians_for_tenant,
    _weekly_hours_for,
)
```

`weekly_capacity_hours` is then computed with the exact same
sum-comprehension the Business Snapshot endpoint uses:

```python
active_techs = await _active_technicians_for_tenant(tid)
weekly_capacity_hours = round(
    sum(_weekly_hours_for(t) for t in active_techs), 2,
)
```

**Parity is enforced at two levels by
`test_booked_out_reuses_business_snapshot_capacity_helpers`:**

1. **Function-identity check** — `boc._active_technicians_for_tenant
   is bs._active_technicians_for_tenant` and same for
   `_weekly_hours_for`. If anyone later moves the helpers or
   creates a local shadow, the identity assertion fails loudly.
2. **Number-level check** — calls both endpoints against the same
   seeded tenant and asserts `boc.weekly_capacity_hours ==
   bs.bh_per_week_capacity`.

Live-verified on preview: Business Snapshot reports
`bh_per_week_capacity=400.0`; Booked Out reports
`weekly_capacity_hours=400.0`. Same number, no drift possible.

## Report 3 — Labor Efficiency

`GET /api/reports/labor-efficiency?start_date&end_date`

Envelope: `{summary: {labor_efficiency_pct, budgeted_hours, actual_hours, jobs_counted}, rows: [{job_id, customer_id, customer_name, service_date, budgeted_hours, actual_hours, efficiency_pct, technician_id, technician_name}], chart: {monthly_efficiency: [{month, efficiency_pct}]}, tenant_id, start_date, end_date, computed_at}`.

Section badge: `Others`. Route: `/reports/labor-efficiency` (`AdminOnly`).

### Canonical pins (Labor Efficiency)

| Field | Source | Notes |
|---|---|---|
| Collection | `db.jobs` with `scheduled_date` in window | Same predicate as the schedule/dispatch surfaces (regex prefix on the day portion to handle both bare-date and full-ISO stamps per `routers/jobs.py:544-570`). |
| `budgeted_hours` | `job.budgeted_hours` → `job.estimated_hours` → `job.duration_hours` (fallback chain) | Excluded when none of the three is set (truthful "insufficient data"). |
| `actual_hours` | `job.actual_hours` → `job.time_entry_hours_total` | Excluded when zero or missing (no divide-by-zero, no fabricated 100%). |
| Row sort | ascending by `efficiency_pct` (worst-first) | Per spec — top of the table is where ops attention pays off. |
| Summary efficiency | weighted: `sum(budgeted) / sum(actual) * 100` | Job-size-weighted (not mean of ratios), so a 20h job carries more weight than a 1h job. |

### Sample curl (verified live)

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
T=$(curl -s -X POST "$API/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@aquaterra.com","password":"password123"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/labor-efficiency?start_date=2025-11-01&end_date=2026-02-28" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live on Aquaterra: `jobs_counted=0` — the seed jobs don't carry
`budgeted_hours` + `actual_hours`, so the FE renders the truthful
"Insufficient data" state.

## Report 4 — Booked Out / Capacity

`GET /api/reports/booked-out-capacity?weeks_ahead=N`

Envelope: `{summary: {weekly_capacity_hours, total_booked_hours, avg_weekly_utilization_pct, first_available_week}, rows: [{week_start, week_end, booked_hours, capacity_hours, utilization_pct, jobs_count}], chart: {weekly_bookings: [{week_label, week_start, booked_hours, capacity_hours}]}, tenant_id, computed_at}`.

Section badge: `Others`. Route: `/reports/booked-out-capacity` (`AdminOnly`). **NO date range filter** — forward-looking rolling view per spec. `weeks_ahead` quick-picks: 4 / 8 / 12 / 24 (backend `ge=1, le=24`).

### Canonical pins (Booked Out / Capacity)

| Field | Source | Notes |
|---|---|---|
| `weekly_capacity_hours` | `_active_technicians_for_tenant` + `_weekly_hours_for` (from `reports_business_snapshot`) | See Business Snapshot capacity-helper reuse section above. |
| Booked-hours per week | sum of `_first_float(job, "budgeted_hours", "estimated_hours", "duration_hours")` bucketed by ISO week of `scheduled_date` | Reuses the Labor Efficiency picker verbatim (imported by name) so the two reports bucket the same job the same way. |
| Week alignment | Monday-anchored, ISO 8601 (`isocalendar()`) | Bare-date and full-ISO `scheduled_date` shapes both handled. |
| `first_available_week` | First week under 80% utilization (`_FULL_UTIL_THRESHOLD`) | Returns `None` when fully-booked throughout the `weeks_ahead` window — truthful null. |

### Sample curl (verified live)

```bash
curl -s "$API/reports/booked-out-capacity?weeks_ahead=8" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live on Aquaterra: `weekly_capacity_hours=400.0` (matches Business Snapshot), `total_booked_hours=0.0`, `avg_weekly_utilization_pct=0.0`, `first_available_week="2026-W37"` (the current ISO week).

## Files touched (Phase 5b.2)

**Backend (new)**
* `routers/reports_labor_efficiency.py`
* `routers/reports_booked_out_capacity.py`
* `tests/test_reports_labor_efficiency.py` — 5 tests
* `tests/test_reports_booked_out_capacity.py` — 5 tests (incl.
  the Business Snapshot capacity-helper parity assertion)

**Backend (edited)**
* `server.py` — 2 imports + 2 router registrations next to the
  Phase 5b.1 block.
* `tests/_f7_loop_fixture.py` — 2 module names added to
  `_REBOUND_MODULES`.

**Frontend (new)**
* `src/pages/reports/LaborEfficiencyReport.jsx`
* `src/pages/reports/BookedOutCapacityReport.jsx`
* `src/test/labor-efficiency-report.test.jsx` — 3 tests
* `src/test/booked-out-capacity-report.test.jsx` — 3 tests
  (incl. weeks-ahead quick-pick refetch)

**Frontend (edited)**
* `src/App.js` — 2 imports + 2 `AdminOnly` routes.
* `src/pages/reports/ReportsHub.jsx` — 2 new tiles (icons
  `Gauge` and `CalendarClock` were already imported in prior
  phases, no new lucide imports needed).

**Memory** — this Phase 5b.2 section appended to
`/app/memory/FEATURE_REPORTS_GAP_FILL_PHASE5B.md`.

## Test results (Phase 5b.2)

Backend — **10/10 across the 2 new suites**:

| Suite | Result |
|---|---|
| `test_reports_labor_efficiency.py` | 5/5 ✅ |
| `test_reports_booked_out_capacity.py` | 5/5 ✅ |

Backend regression sweep — **88/88 across 14 suites** (the 2 new
+ 5b.1 pair + 5a.2 trio + 5a.1 Part B pair + 5a.1 Business
Snapshot + Forced Password Reset + Temp Password Flow + S3
Phase 1 + Multi-Contact Phase 2).

Frontend — **6/6 across the 2 new suites**:

| Suite | Result |
|---|---|
| `labor-efficiency-report.test.jsx` | 3/3 ✅ |
| `booked-out-capacity-report.test.jsx` | 3/3 ✅ |

Frontend regression sweep — **35/35 across 11 suites**.

OpenAPI: `GET /api/openapi.json` returns 200 with **1722 paths**
(+2 since Phase 5b.1, +10 since the pre-5a.1 baseline of 1712).
Both new endpoints appear:

* `/api/reports/labor-efficiency`
* `/api/reports/booked-out-capacity`

## Deviations (Phase 5b.2)

* **`_iso_day_bounds` copied a fourth time in `reports_labor_efficiency.py`.**
  Same small-diff bias as Phase 5b.1 deviations 1 & 2. The
  "Reports shared helpers" follow-up ticket now has four copies
  to consolidate (TTGP + TTC + Attrition + Labor Efficiency).
  `reports_booked_out_capacity.py` intentionally does NOT
  duplicate this helper (no date-range param on this endpoint).
* **`_first_float` is imported cross-router from Labor Efficiency
  into Booked Out / Capacity** rather than duplicated. Chose the
  import over the copy because both routers ship in the same
  dispatch — the parity contract is created and used in the
  same PR. If a future edit needs to change the fallback chain,
  the change is localized to one file.
* **Booked Out schedule query uses date-string range on
  `scheduled_date`** (`{"$gte": window_start, "$lt": window_end}`)
  rather than a regex prefix. The schedule window is always
  Monday-aligned so the string bounds are safe (no day-boundary
  ambiguity). This differs from the Labor Efficiency router
  which does use a regex prefix — because that report accepts a
  user-supplied `YYYY-MM-DD` and needs to match both bare-date
  and full-ISO scheduled_date shapes on the same day.

---

## Workstream status — COMPLETE

**All 9 Phase 5 reports shipped:**

| Phase | Report | Status |
|---|---|---|
| 5a.1 | Business Snapshot | ✅ |
| 5a.1 Part B | Attrition Report | ✅ |
| 5a.1 Part B | Time to Get Paid | ✅ |
| 5a.2 | Revenue by Service | ✅ |
| 5a.2 | Recurring vs. Project Revenue | ✅ |
| 5a.2 | Client Lifetime Value | ✅ |
| 5b.1 | Close Ratio | ✅ |
| 5b.1 | Time to Close | ✅ |
| 5b.2 | Labor Efficiency | ✅ |
| 5b.2 | Booked Out / Capacity | ✅ |

(That's 10 rows because Phase 5a.1 shipped Business Snapshot
first and then the Part B pair — total 9 reports as originally
scoped, plus Business Snapshot which was the tracer bullet.)

**Total openapi surface change:** **+10 endpoints** since the
pre-5a.1 baseline (1712 → 1722 paths).

**Follow-up ticket queued for next dispatch:** "Reports shared
helpers" — DRY up `_iso_day_bounds`, `_parse_dt`, `_percentile`,
`_norm_status`, `_first_float` into a
`routers/reports_shared/` module. Now that all 9 reports have
shipped, the refactor can safely touch all sibling routers in
one atomic PR without triggering "small-diff per report"
violations.

