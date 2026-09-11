# Feb-2026 · Reports Gap Fill — Phase 5a.2 (cockpit-mirror trio)

Second sub-phase of the reports gap fill. Ships three reports that
had been flagged as **required to mirror canonical helpers
verbatim**: Revenue by Service, Recurring vs. Project Revenue,
Client Lifetime Value.

Same shell pattern as Phase 5a.1: flat-grid `ReportsHub.jsx` tile
with a section badge, a dedicated `/reports/*` page
(`AdminOnly`-gated), a `/api/reports/*` endpoint, CSV export,
`DateRangePicker`-driven refetch, tenant scope. Each router
**imports** the existing canonical helper — never re-derives.

---

## LTV helper decision — option **b** (new wrapper)

Chose **option (b)**: add a new `analytics._client_lifetime_summary`
that wraps `_lifetime_revenue_by_customer` and returns the richer
per-customer shape needed by the CLV report. Left
`_lifetime_revenue_by_customer` untouched — signature-compatible
so the Attrition report's existing call site
(`routers/reports_attrition.py:123`) works with zero code change.

Rationale:
* Smallest-diff. Attrition ships continues to pass its regression
  suite (5/5) without any modification.
* The parity contract is preserved as a **unit-test invariant**:
  `test_reports_client_lifetime_value::test_clv_parity_with_lifetime_revenue_helper`
  asserts `_client_lifetime_summary[cid]["collected"] ==
  _lifetime_revenue_by_customer(...)[cid]` for every cid. A future
  edit to either helper that breaks the invariant will fail CI
  loudly — this is safer than option (a)'s "change signature and
  hope every caller is fixed."

Also added a companion top-level helper
`analytics._is_recurring_invoice` — mirrors the exact predicate at
`dashboard.py:167` (`title` contains `weekly`/`monthly`/`recurring`).
Both the CLV summary and the Recurring vs. Project router call
this helper by name — the two surfaces cannot drift.

---

## Report 1 — Revenue by Service

`GET /api/reports/revenue-by-service?start_date&end_date`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Envelope: `{summary: {total_billed, total_collected, top_service_by_revenue: {name, amount}}, rows: [{service_name, service_id, billed_amount, collected_amount, job_count, avg_ticket}], chart: {top_services: [...top 10]}, tenant_id, start_date, end_date, computed_at}`.

Section badge: `Financial`. Route: `/reports/revenue-by-service`.

Canonical pins:
* **Collection** — `db.quotes` where `doc_type="invoice"` (same as
  `reports.revenue_by_customer`).
* **Pivot** — `invoice.title` (`"Unclassified"` fallback when
  absent). This is the field the invoice grid + admin dashboards
  already display; the invoice schema doesn't carry a stable
  `service_id` on line items today, so `service_id` is a slug of
  `service_name`. If ops needs a stable id, follow-up ticket.
* **`collected_amount`** — `routers.reports._paid_amt` (**direct
  import**). Every existing revenue slice uses this helper; drift
  is impossible.
* **`billed_amount`** — sum of `invoice.total` (all statuses,
  soft-deleted excluded).

### Sample curl
```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api
T=$(curl -s -X POST "$API/auth/login" -H "Content-Type: application/json" \
     -d '{"email":"super@aquaterra.com","password":"password123"}' \
     | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "$API/reports/revenue-by-service?start_date=2025-11-01&end_date=2026-02-28" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live on the Aquaterra preview tenant: `total_billed=1400.00, total_collected=200.00, top="KK ref" ($1000)` — truthful state.

---

## Report 2 — Recurring vs. Project Revenue

`GET /api/reports/recurring-vs-project-revenue?start_date&end_date`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str` | `YYYY-MM-DD` (inclusive) |
| `end_date`   | `str` | `YYYY-MM-DD` (inclusive) |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Envelope: `{summary: {total_revenue, recurring_amount, project_amount, recurring_pct}, rows: [{month, recurring_amount, project_amount, total}], chart: {donut: {recurring, project}, trailing_12mo: [...]}, tenant_id, start_date, end_date, computed_at}`.

Section badge: `Financial`. Route: `/reports/recurring-vs-project-revenue`.

Canonical pins:
* **Predicate** — `analytics._is_recurring_invoice` (title
  contains `weekly`/`monthly`/`recurring`). **Verbatim** mirror of
  `dashboard.py:167`; both surfaces call the same helper.
* **Population** — paid invoices only
  (`payment_status="paid"`, soft-deleted excluded). Unpaid
  invoices are excluded from BOTH buckets so the split matches
  the dashboard's "collected revenue" semantics, not gross.
* **Trailing-12mo chart** — independent of the filter (bucketed by
  `paid_at[:7]`), per spec.

### Sample curl
```bash
curl -s "$API/reports/recurring-vs-project-revenue?start_date=2025-11-01&end_date=2026-02-28" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live: `total_revenue=200.00, recurring=0.00, project=200.00` — the
current seed has no recurring-title paid invoices in the window.

---

## Report 3 — Client Lifetime Value

`GET /api/reports/client-lifetime-value?start_date&end_date`

| Param | Type | Notes |
|---|---|---|
| `start_date` | `str?` | `YYYY-MM-DD`. Both null → all-time (default). |
| `end_date`   | `str?` | `YYYY-MM-DD`. Both null → all-time (default). |
| `tenant_id`  | `str?` | **super_admin only.** Other roles → 403. |

Envelope: `{summary: {avg_ltv_recurring, avg_ltv_project, top_10_pct_revenue_share, active_client_count}, rows: [{customer_id, customer_name, first_service_date, last_service_date, total_billed, total_collected, is_active, client_type}], chart: {ltv_buckets: [{bucket, count}]}, tenant_id, as_of, start_date, end_date, computed_at}`.

Section badge: `Others`. Route: `/reports/client-lifetime-value`.

Canonical pins:
* **`billed` / `collected`** — `analytics._client_lifetime_summary`
  (new wrapper over `_lifetime_revenue_by_customer`). Parity
  invariant asserted by
  `test_clv_parity_with_lifetime_revenue_helper`.
* **`client_type`** — `recurring` if
  `recurring_invoice_count > project_invoice_count`, else
  `project`. Report-layer classifier; documented above.
* **`first_service_date` / `last_service_date`** — min/max of
  `jobs.completed_at` per customer.
* **`is_active`** — `customer.is_active` truthy (or missing →
  Phase 34f default of "active"). Semantically inverse of the
  Attrition report's `is_active=false` cohort.
* **`avg_ltv_recurring` / `avg_ltv_project`** — mean of
  `total_collected` within each cohort.
* **`top_10_pct_revenue_share`** — sum of `total_collected` for
  `ceil(len(rows) * 0.10)` top rows, divided by grand total ×100
  (1dp). `ceil` used so 1 customer with any collected always
  registers as 100%.

Histogram buckets (upper-exclusive except last):
`$0-500` · `$500-1K` · `$1K-2.5K` · `$2.5K-5K` · `$5K+`.

### Sample curl (all-time default)
```bash
curl -s "$API/reports/client-lifetime-value" \
   -H "Authorization: Bearer $T" | python3 -m json.tool
```
Live: `active_client_count=35, avg_ltv_project=$15.28, top_10_pct_revenue_share=100.0%` on the Aquaterra preview tenant.

---

## Files touched

**Backend (new):**
* `routers/reports_revenue_by_service.py`
* `routers/reports_recurring_vs_project.py`
* `routers/reports_client_lifetime_value.py`
* `tests/test_reports_revenue_by_service.py` — 5 tests
* `tests/test_reports_recurring_vs_project.py` — 5 tests
* `tests/test_reports_client_lifetime_value.py` — 5 tests

**Backend (edited):**
* `routers/analytics.py` — added `_is_recurring_invoice` and
  `_client_lifetime_summary` helpers next to
  `_lifetime_revenue_by_customer`. Existing helper unchanged.
  `typing` import extended to include `Any, Dict`.
* `server.py` — 3 imports + 3 router registrations next to the
  Phase 5a.1 block.
* `tests/_f7_loop_fixture.py` — 3 module names added to
  `_REBOUND_MODULES`.

**Frontend (new):**
* `src/pages/reports/RevenueByServiceReport.jsx`
* `src/pages/reports/RecurringVsProjectReport.jsx`
* `src/pages/reports/ClientLifetimeValueReport.jsx`
* `src/test/revenue-by-service-report.test.jsx` — 3 tests
* `src/test/recurring-vs-project-report.test.jsx` — 3 tests
* `src/test/client-lifetime-value-report.test.jsx` — 3 tests

**Frontend (edited):**
* `src/App.js` — 3 imports + 3 `AdminOnly` routes.
* `src/pages/reports/ReportsHub.jsx` — 3 icon imports (`Wrench`,
  `RefreshCw`, `TrendingUp`) + 3 new tiles in `builtTiles`.

**Memory:** `/app/memory/FEATURE_REPORTS_GAP_FILL_PHASE5A_2.md`
(this file).

---

## Test results

Backend — **15/15 across the 3 new suites**:

| Suite | Result |
|---|---|
| `test_reports_revenue_by_service.py` | 5/5 ✅ |
| `test_reports_recurring_vs_project.py` | 5/5 ✅ |
| `test_reports_client_lifetime_value.py` | 5/5 ✅ |

Backend regression sweep — **68/68 across 10 suites** (the 3 new
+ 5a.1 Business Snapshot + 5a.1 Part B Attrition + 5a.1 Part B
TTGP + Forced Password Reset + Temp Password Flow + S3 Phase 1 +
Multi-Contact Phase 2).

Frontend — **9/9 across the 3 new suites**:

| Suite | Result |
|---|---|
| `revenue-by-service-report.test.jsx` | 3/3 ✅ |
| `recurring-vs-project-report.test.jsx` | 3/3 ✅ |
| `client-lifetime-value-report.test.jsx` | 3/3 ✅ |

Frontend regression sweep — **28/28 across 8 suites** (the 3 new
+ Attrition + TTGP + Business Snapshot + Forced Password Reset +
Login Account Chooser).

OpenAPI: `GET /api/openapi.json` returns 200 with **1718 paths**
(+3 since 5a.1 Part B, +6 since the pre-5a.1 baseline of 1712).
All 3 new endpoints appear:
* `/api/reports/revenue-by-service`
* `/api/reports/recurring-vs-project-revenue`
* `/api/reports/client-lifetime-value`

---

## Guardrails respected

* Preview-only. No prod deploy. No Save-to-GitHub.
* No `/app/mobile/` touches.
* No external repo cloned (recurring
  `bbeck169/Pool-Landscaping.git` injection remains ignored).
* Small-diff per report. Existing helpers reused, never
  re-derived.
* English only.
* Phase 5b NOT started.

---

## Deviations

* **Revenue by Service pivot is invoice `title`, not a per-line-item
  `service_id`.** The Phase-11 unified invoice ledger doesn't
  carry a stable `service_id` on line items; the invoice grid
  itself categorizes by `title`. `service_id` in the row envelope
  is a slug of `service_name` — good enough for CSV joins and
  chart keys, not a stable link to a service catalog. If ops
  needs a first-class service catalog link, a follow-up ticket
  can wire `db.services.id` onto invoice line items.
* **CLV `client_type` classifier is invoice-mix majority.** A more
  sophisticated classifier (spend share instead of count share,
  or a customer-level `client_type` field) is possible but was
  out of scope for this small-diff dispatch. The current
  classifier matches the dashboard's title-keyword split so the
  two surfaces cannot classify a customer differently within the
  same window.
* **Recurring vs. Project excludes unpaid invoices** even though
  the report title just says "revenue." This mirrors the
  dashboard split at `dashboard.py:167` which operates on
  `paid` only (via the `paid` variable). Documented as a pin
  above so ops sees the same numbers on both surfaces.
* **LTV helper choice — option (b), new wrapper.** Attrition's
  existing call to `_lifetime_revenue_by_customer` is preserved
  as-is; the CLV report uses the richer `_client_lifetime_summary`
  wrapper. Parity is asserted by unit test. See "LTV helper
  decision" above.

---

## Queue update

**5a.1 + 5a.2 (COMPLETE):**

* ~~Business Snapshot~~ ✅ (Phase 5a.1)
* ~~Attrition Report~~ ✅ (Phase 5a.1 Part B)
* ~~Time to Get Paid~~ ✅ (Phase 5a.1 Part B)
* ~~Revenue by Service~~ ✅ (Phase 5a.2)
* ~~Recurring vs. Project Revenue~~ ✅ (Phase 5a.2)
* ~~Client Lifetime Value~~ ✅ (Phase 5a.2)

**Phase 5b (queued for next dispatch):**

* Close Ratio
* Time to Close
* Labor Efficiency
* Booked Out / Capacity
