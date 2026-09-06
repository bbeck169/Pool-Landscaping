# Reporting Suite · Legacy Exports Audit

Compiled: Feb 2026 · Phase R0 kickoff · Read-only inventory of every
CSV / PDF / XLSX export currently shipping from the backend or the
web frontend. R1–R7 phases will pick these up individually for
parity — this document is the tracking sheet. **Nothing here is
modified by R0.**

## Convention

Each row lists:

* **Endpoint / file** — the wire path + backend router file, or the
  frontend page/component if the export is client-side.
* **Entity** — high-level noun the export represents.
* **Columns / payload** — what the file contains at write time
  (best-effort snapshot; the exhaustive column list lives in the
  router source).
* **R-phase owner** — which future phase will inherit parity
  responsibility. R0 does NOT change any of these.

## Backend exports

| # | Endpoint | Router file | Entity | Payload | R-phase owner |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET /api/export/jobs?from=&to=` | `routers/reports.py` L607 | Jobs | JSON `{filename, content, count}` — CSV of jobs in a date window (id, customer, tech, service, scheduled_at, status, total, etc.) | R2 (Operations) |
| 2 | `GET /api/export/invoices?from=&to=` | `routers/reports.py` L627 | Invoices | JSON `{filename, content, count}` — CSV of invoices (id, customer, issued_date, paid_date, amount, amount_paid, status, method) | R1 (Financial) |
| 3 | `GET /api/reports/profit.csv?from=&to=` | `routers/profit_report.py` L311 | Profit | Streaming CSV — per-job revenue, cost, margin, margin% | R1 (Financial) |
| 4 | `GET /api/admin/gps/scorecard/export.csv?window=` | `routers/driver_scorecard.py` L68 | Driver scorecard | CSV — driver_id, name, ping count, idle minutes, average speed, safety score | R2 (Operations) |
| 5 | `GET /api/admin/gps/export/activity.csv?from=&to=` | `routers/gps_user_controls.py` L263 | GPS activity | Streaming CSV — timestamp, tech_id, action, lat, lon, source | R2 (Operations) |
| 6 | `GET /api/admin/gps/export/pings.csv?from=&to=` | `routers/gps_user_controls.py` L355 | GPS pings | Streaming CSV — timestamp, tech_id, lat, lon, speed, heading, battery | R2 (Operations) |
| 7 | `GET /api/workforce/export/timesheets.csv?from=&to=` | `routers/workforce.py` L620 | Timesheets | Streaming CSV — tech_id, name, week, hours, overtime, pay | R2 (Operations) |
| 8 | `GET /api/customers/export` | `routers/impexp.py` L62 | Customers | JSON `{filename: customers.csv, content, count}` — full customer roster | R3 (Customers) |
| 9 | `GET /api/customers/import-template` | `routers/impexp.py` L79 | Customers | CSV template — reference for the import route below | R3 (Customers) |
| 10 | `POST /api/customers/import-csv` | `routers/customers.py` L3298 | Customers | READ-side (upload only) — no export payload | Not a parity target (write side) |
| 11 | `GET /api/pricebook/export` | `routers/impexp.py` L68 | Pricebook | JSON `{filename: pricebook.csv, content, count}` | R1 (Financial) |
| 12 | `GET /api/submissions/export/csv?directory_slug=` | `routers/directories.py` L456 | Directory submissions | Streaming CSV — submission metadata + form field values | R6 (Custom) |
| 13 | `GET /api/checks/payroll/template.csv` | `routers/checks.py` L1543 | Checks / payroll | Streaming CSV template | R1 (Financial) |
| 14 | `POST /api/checks/payroll/import-csv` | `routers/checks.py` L1556 | Checks / payroll | WRITE side — no export | Not a parity target (write side) |
| 15 | `GET /api/checks/{id}/pdf` | `routers/checks.py` L1146 | Checks | PDF — individual physical check | R1 (Financial) |
| 16 | `GET /api/checks/batches/{bid}/pdf` (2 endpoints, inline + attach) | `routers/checks.py` L1497 + L1518 | Checks | PDF — batch of physical checks | R1 (Financial) |
| 17 | `GET /api/estimates/{id}/pdf` | `routers/estimator.py` L970 | Estimates | PDF — customer-facing estimate | R4 (Sales) |
| 18 | `GET /api/seo/reports/{rid}/pdf` | `routers/seo_phase17c.py` L1091 | SEO report | PDF — client SEO audit deliverable | R2 (Operations) — or defer as marketing-suite parity |
| 19 | `GET /api/reports/chemical-costs` | `routers/chemical_cost_report.py` (Feb-2026) | Chemistry | JSON aggregation (not a file export, but a report surface) | R2 (Operations) |

## Frontend-driven exports

The web app also builds CSVs client-side in a handful of places
using page-level "Download CSV" buttons. These are the current
first-class ones (grep target: `Download CSV`, `toCsv`, `Blob.*csv`):

| # | Page / component | Entity | Payload | R-phase owner |
| --- | --- | --- | --- | --- |
| 20 | `pages/reports/BusinessSummary.jsx` | Business summary | Client-side CSV of the tiles + trend rows | R5 (Overview) |
| 21 | `pages/reports/Forecast.jsx` | Revenue forecast | Client-side CSV of 90-day forecast rows | R1 (Financial) |
| 22 | `pages/reports/CustomerRetentionReport.jsx` | Customer retention | Client-side CSV | R3 (Customers) |
| 23 | `pages/reports/RevenueSlices.jsx` (city / crew / customer / gross-sales / invoiced-items) | Revenue slices | Client-side CSVs (5 tabs) | R1 (Financial) |
| 24 | `pages/reports/ChemicalCostReportPage.jsx` | Chemistry cost | Client-side CSV | R2 (Operations) |
| 25 | `pages/reports/UncategorizedItemsReport.jsx` | Income category audit | Client-side CSV | R1 (Financial) |
| 26 | `pages/reports/PricebookCostComparison.jsx` | Pricebook cost delta | Client-side CSV | R1 (Financial) |
| 27 | `pages/reports/SupplierSpendReport.jsx` | Supplier spend | Client-side CSV | R1 (Financial) |
| 28 | `pages/reports/GpsAutoStartAudit.jsx` | GPS auto-start audit | Client-side CSV | R2 (Operations) |
| 29 | `pages/reports/PoolServiceReport.jsx` | Pool service report | Client-side CSV | R2 (Operations) |
| 30 | `pages/reports/JobMarginLeaderboard.jsx` | Job margins | Client-side CSV | R1 (Financial) |
| 31 | `pages/reports/WeeklyDigestPage.jsx` | Weekly digest | Email + downloadable summary | R7 (Scheduled) |
| 32 | `pages/reports/DriverActivityPage.jsx` | Driver activity | Client-side CSV | R2 (Operations) |
| 33 | `pages/reports/IncomeByCategoryPage.jsx` | Income by category | Client-side CSV | R1 (Financial) |
| 34 | `pages/reports/PricingInsights.jsx` | Pricing insights | Client-side CSV | R4 (Sales) |
| 35 | `pages/reports/SupplierSyncAnalytics.jsx` | Supplier sync metrics | Client-side CSV | R2 (Operations) |

## Roll-up

* **Discovered exports**: **35** total (19 backend + 16 frontend-driven).
* **R1 (Financial)**: 12 exports.
* **R2 (Operations)**: 12 exports.
* **R3 (Customers)**: 3 exports.
* **R4 (Sales)**: 2 exports.
* **R5 (Overview)**: 1 export.
* **R6 (Custom)**: 1 export.
* **R7 (Scheduled)**: 1 export.
* **Write-side (not parity targets)**: 3 endpoints (payroll import, customer import, template).

## Parity contract (for R1+ shipping teams)

When an R-phase inherits an export, it MUST:

1. Preserve the wire path + response media type of the legacy
   endpoint (breaks bookmarks + email deep-links otherwise).
2. Re-render the client-side CSV using the new metric registry
   (so a KPI value in the tabbed Reports Suite matches the CSV
   the user downloads on the same page).
3. Add an "Export" affordance on the equivalent KPI card in the
   Reports Suite so the two surfaces feel like the same product,
   not parallel worlds.
4. NOT delete the legacy endpoint until the R-phase's dashboard
   is fully shipped and the migration note is called out in the
   phase's ship report.

## Non-goals for R0

R0 does not:

* Touch any of the 35 exports.
* Change the CSV/PDF media types or column ordering.
* Move any file paths.
