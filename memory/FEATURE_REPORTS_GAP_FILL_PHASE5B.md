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
