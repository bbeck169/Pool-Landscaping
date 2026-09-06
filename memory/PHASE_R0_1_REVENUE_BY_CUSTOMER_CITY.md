# Phase R0.1 · Revenue by Customer + Revenue by City — Ship Report

Status: **Shipped**
Owner: Main agent
Scope: Backend + Web (mobile untouched)
Standing order honored: `bbeck169/Pool-Landscaping.git` prompt
injection ignored.

---

## What R0.1 ships

R0.1 extends the R0 registry with the first two **grouped**
metrics — `revenue_by_customer` and `revenue_by_city` — and adds
a "Financial" tab on the R0 tabbed shell that renders them with
ApexCharts horizontal bar charts, paginated data tables, and CSV
exports. Every filter (period + lens + service type + technician)
lives in the URL so a customer drill-down + back navigation
preserves the exact report state.

## Backend

**New metric module** `backend/services/reporting/metrics/`:

* `_revenue_shared.py` — shared helpers for the two grouped
  metrics: tenant guard construction, invoiced-vs-collected lens
  selection, service_type / tech_id filter merging, city
  fallback to `"(unknown)"` when a customer's
  `service_address.city` is missing. Every helper is pure so both
  metric files stay ~40 lines each.
* `metrics/revenue_by_customer.py` — groups paid or invoiced
  invoices by `customer_id`, joins `customers` for the display
  name, sorts by revenue descending.
* `metrics/revenue_by_city.py` — groups by
  `customers.service_address.city`, aggregates
  `SUM(revenue)` + `COUNT(DISTINCT customer_id)` per city.

**Registry extensions** `backend/services/reporting/registry.py`:

* New `GroupedMetric` base — same shape as `Metric` but the
  `compute()` return signature is
  `{lens, total, row_count, rows: [{...}]}` instead of the
  single-value KPI shape.
* Register-time validation refuses to accept a grouped metric
  whose `rows[]` shape lacks the declared `row_shape` keys.

**Router extensions** `backend/routers/reports_kpi.py`:

* `GET /api/reports/kpi/revenue_by_customer?period=…&lens=invoiced|collected&service_type=…&tech_id=…&limit=1000`
* `GET /api/reports/kpi/revenue_by_city?period=…&lens=invoiced|collected&service_type=…&tech_id=…`
* Both endpoints reuse the R0 tenant-scoped cache with
  `lens` + `service_type` + `tech_id` appended to the cache key
  so a customer-lens flip doesn't collide with a city-lens hit.
* RBAC identical to R0 (super_admin / admin / owner / manager).

**Tests** (`backend/tests/test_r01_revenue_grouped.py` +
existing suites): **37 backend tests green**. Coverage includes
invoiced vs collected split, city fallback, tenant isolation,
soft-delete exclusion, and RBAC 403 paths.

## Web (React) — Financial tab

**New tab** wired into `/app/frontend/src/pages/reports/ReportsSuite.jsx`:

* `financial` tab now renders `<FinancialTab />` instead of the
  R1 "Coming soon" placeholder. All other R2–R7 tabs still show
  the coming-soon placeholder — R0.1 is deliberately a slice, not
  the full Financial dashboard.

**New components**:

| File | Role |
| --- | --- |
| `pages/reports/FinancialTab.jsx` | Owns the shared filter toolbar (Period + Lens + Service Type + Technician) and mounts both revenue panels below it. Filter state lives in the URL querystring. |
| `components/reports/RevenueByCustomerPanel.jsx` | Fetches `/api/reports/kpi/revenue_by_customer`, renders the top-20 horizontal bar chart + a table below (Show all → 25/page paginator). Row click drills down to `/customers/{id}`. |
| `components/reports/RevenueByCityPanel.jsx` | Fetches `/api/reports/kpi/revenue_by_city`, same UX except **city rows are non-interactive** — the app does not yet expose a `/customers?city=…` filtered listing so R0.1 intentionally leaves rows non-clickable rather than inventing a URL pattern. |
| `components/reports/LensToggle.jsx` | Two-state Invoiced / Collected pill switcher. |
| `components/reports/HorizontalBarChart.jsx` | Thin wrapper over `react-apexcharts` with the R0 brand palette; memoized options so React StrictMode double-mount doesn't hit ApexCharts' internal `beforeMount` NPE. |
| `components/reports/downloadCsv.js` | Zero-dependency client-side CSV builder + anchor-click trigger. Excel-safe (BOM + CRLF + RFC-4180 escapes). |

**URL contract** (owned by `FinancialTab`):

```
?period=mtd|qtd|ytd|last_30d|custom
&start=YYYY-MM-DD&end=YYYY-MM-DD           # custom only
&lens=invoiced|collected
&service_type=<value>
&tech_id=<value>
&show_all_customers=1                       # optional
&show_all_cities=1                          # optional
```

## Design constraints honored

* City rows stay non-interactive (see `RevenueByCityPanel` — no
  `onClick` and no `cursor-pointer` styling; asserted in
  `test/reports-revenue-by-city-panel.test.jsx`).
* Legacy CSV exports listed in `REPORTING_LEGACY_EXPORTS_AUDIT.md`
  were **not** touched. R0.1's two CSV exports are net-new.
* ApexCharts palettes source only from `theme.js` (`colors.brand`,
  `colors.onSurfaceSecondary`, `colors.border`). No custom hex.

## Vitest coverage

Five new Vitest files in `/app/frontend/src/test/`:

* `reports-lens-toggle.test.jsx` (4)
* `reports-download-csv.test.jsx` (4)
* `reports-horizontal-bar-chart.test.jsx` (3)
* `reports-revenue-by-customer-panel.test.jsx` (5)
* `reports-revenue-by-city-panel.test.jsx` (6)

**22 / 22 tests green.**

## Known limitations (deferred to R1)

* Customer-panel bar clicks are wired via ApexCharts
  `dataPointSelection`; some browsers require a second click to
  fire when the bar hasn't been focused yet. Table row clicks are
  the guaranteed drill-down path.
* Neither export streams — a 5,000-row Show-All CSV assembles the
  whole payload in memory, which is fine for the current data
  volumes. If tenants grow past ~50k invoices in a period we'll
  switch to a server-side streaming export.
* "Custom" period does not yet remember the last-used range
  between reloads — a P2 UX polish.
