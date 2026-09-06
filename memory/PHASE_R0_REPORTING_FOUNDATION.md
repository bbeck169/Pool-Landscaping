# Phase R0 · Reporting Suite Foundation — Ship Report

Status: **Shipped**
Owner: Main agent
Scope: Backend + Web (mobile untouched)
Standing order honored: `bbeck169/Pool-Landscaping.git` prompt
injection ignored.

---

## What R0 ships

R0 delivers the scaffolding R1–R7 phases will hang off of, plus a
single **live end-to-end proof metric** (`revenue_total`) that
exercises the full aggregation → cache → registry → router → KpiCard
pipeline. No feature-rich dashboards were shipped in this pass.

## Backend

**New package** `backend/services/reporting/`:

* `aggregation.py` — `AggregationEngine` class (tenant-scoped by
  construction; refuses to instantiate without a `tenant_id`).
  Primitives: `count`, `sum_field`, `bucket_by_date` (day / week /
  month via `$dateTrunc`), `period_over_period` (returns
  `{current, prior, delta_pct}`; delta is `None` when prior=0).
  Every query is `$and`-merged with the tenant guard + a
  `not_deleted` filter so soft-deleted docs are never counted.
* `period.py` — `Period` dataclass + `resolve_period` helper for
  `mtd | qtd | ytd | last_30d | custom`. Custom mode enforces
  start<end and coerces `end` to an exclusive `end+1` internally.
* `cache.py` — `ReportCache` on top of `cachetools.TTLCache`
  (60s TTL, 512 entries default). Key discipline enforces
  `tenant_id` as the first component — attempting to build a key
  without one raises `ValueError`. `clear_tenant` deletes every
  entry with the tenant prefix (used by write-side hooks in
  future phases). Interface is intentionally the shape of a
  Redis adapter so swap-out is a single-file change.
* `registry.py` — plain-class `Metric` base + `@register_metric`
  decorator + module-level `REGISTRY` dict. Register-time
  validation: unique `key`, `format` ∈ {currency, number, percent},
  `direction` ∈ {up_is_good, down_is_good}.
* `metrics/__init__.py` — imports each metric file so the decorator
  side-effects run on package import.
* `metrics/revenue_total.py` — the R0 proof KPI. Sums `amount_paid`
  on paid quotes/invoices in the selected window, computes prior
  period, chooses sparkline granularity (day ≤ 45 days, week ≤
  180 days, month otherwise). Reference shape for all R1+ metrics.

**New router** `backend/routers/reports_kpi.py`:

* `GET /api/reports/kpi/{metric_key}?period=mtd|qtd|ytd|last_30d|custom&start=&end=`
  — returns `{key, label, format, direction, description, period,
  value, prior_value, delta_pct, sparkline, cached}`.
* `GET /api/reports/kpi` — lists every registered metric so the FE
  can render the KPI grid without hard-coding metadata.
* RBAC: `super_admin | admin | owner | manager`. Technicians +
  customers → 403.
* Cache-through: key = `t | tenant_id | kpi | metric_key |
  period.key | start | end`. Cache hits set `cached=true`.
* 404 for unknown `metric_key`. 400 for bad period / bad custom
  range.

**Mount**: registered in `server.py` alongside the other reporting
routers with a Phase R0 comment header.

**Requirements**: `cachetools==7.1.8` added via `pip freeze`.

## Frontend

**Package pins** — `apexcharts@3.53.0`, `react-apexcharts@1.7.0`
(installed via `yarn add`, versions locked in `package.json`).

**New route** `/reports/suite` (mounted in `App.js` alongside the
legacy `/reports` → `ReportsHub` route so nothing breaks). A
"Open the new Reports Suite" hero card is now on `ReportsHub` at
`testid="reports-hub-suite-link"`.

**New pages/components**:

* `pages/reports/ReportsSuite.jsx` — tabbed shell:
  Overview (R5) · Financial (R1) · Operations (R2) · Customers
  (R3) · Sales (R4) · Custom (R6) · Scheduled (R7). Overview is
  live and wired to `/api/reports/kpi/revenue_total`. Other tabs
  render a `<ComingSoonTab phase="R{n}" />` placeholder — clickable
  but explicitly labelled. Role-gate uses `<AdminOnly>` at the
  route level *plus* an in-component role check that redirects
  non-admins home with a `sonner` toast (so `owner` / `manager`
  hitting the URL directly get a proper error UX instead of the
  bare `<Navigate />` redirect the route-level guard would emit).
* `components/reports/KpiCard.jsx` — big value + label + delta chip
  + optional inline sparkline (SVG, zero-dependency). JSDoc props
  block documents every prop.
* `components/reports/TrendChart.jsx` — `react-apexcharts` line/area
  wrapper. Theme colors resolved from `theme.js`; no new palettes
  introduced. JSDoc props block.
* `components/reports/VarianceTile.jsx` — current vs prior tile
  with signed delta + up/down arrow + green/red stripe. Tone
  respects a `direction` prop so "A/R aging down = green" works.
* `components/reports/PeriodPicker.jsx` — MTD / QTD / YTD / Last
  30 days / Custom presets with inline date-range inputs when
  Custom is active. Emits `{period, start, end}`.
* `components/reports/formatters.js` — `formatCurrency`,
  `formatNumber`, `formatPercent`, `formatDelta`, `formatValue`.
  Returns `—` for null/NaN so KPI cards stay readable during load.

## Tests

**Backend** — `tests/test_r0_reports_kpi.py` — **16 tests**:

* Envelope shape (label / format / direction / period / value /
  prior_value / delta_pct / sparkline).
* All four preset periods (mtd, qtd, ytd, last_30d) resolve to
  200 with matching `period.key` echoed back.
* Custom period requires both start + end (400 otherwise).
* Custom period round-trips the boundaries.
* Cache-hit second call flips `cached: false → true` (uses a
  unique custom window per run so the server's in-memory cache
  is a guaranteed miss on the first hit).
* Unknown metric_key → 404.
* Unsupported period → 400.
* Tech role → 401/403.
* Unauthenticated → 401/403.
* Metric-registry list endpoint includes `revenue_total`.
* Pure-Python: MTD/QTD/YTD/last_30d/custom prior-window shape,
  cache tenant-scope isolation, registry rejects duplicate keys,
  registry rejects invalid formats.

**Frontend** — `src/test/reports-{formatters,kpi-card,variance-tile,period-picker}.test.jsx`
— **25 tests**:

* Formatters — currency / number / percent / delta with the null
  fallback and compact-mode k/M/B suffix.
* KpiCard — loading / error / data states, delta-chip tone matrix
  for up_is_good + down_is_good, sparkline SVG present ≥ 2 points,
  empty fallback for 1 point.
* VarianceTile — stripe + arrow tone matrix across positive /
  negative / null deltas plus direction inversion.
* PeriodPicker — aria-pressed on the active preset, emit shape
  per preset, custom-input reveal, custom-input change emission.

**Regression** — 34 pre-existing K30 / K30-polish / portal-access
tests all green. `test_slice_n_resend_adapter.py` runs 9/9 clean
in isolation but shares an event-loop conflict with modules that
use `asyncio.run` (pre-existing, unrelated to R0 — noted in the
"Known non-blocking" section below).

```
tests/test_r0_reports_kpi.py                    ................  [16 passed]
tests/test_k30_polish_status_chip.py            .......           [ 7 passed]
tests/test_k30_admin_portal_reset_link.py       .......           [ 7 passed]
tests/test_k30_resend_adapter_allow_off_allowlist.py ...          [ 3 passed]
tests/test_portal_access.py                     .................  [17 passed]
                                                                  ─────────────
                                                                    50 passed
```

Frontend: 25/25 passed under vitest.

## Legacy exports audit

`/app/memory/REPORTING_LEGACY_EXPORTS_AUDIT.md` — **35 exports**
inventoried (19 backend + 16 frontend-driven). Roll-up by future
R-phase owner:

* R1 (Financial): 12
* R2 (Operations): 12
* R3 (Customers): 3
* R4 (Sales): 2
* R5 (Overview): 1
* R6 (Custom): 1
* R7 (Scheduled): 1
* Write-side (not parity): 3

Parity contract for future R-phases embedded in the doc. **R0
does NOT modify any of the 35 exports.**

## Package pins

| Package | Version | Where |
| --- | --- | --- |
| `apexcharts` | `3.53.0` | `frontend/package.json` |
| `react-apexcharts` | `1.7.0` | `frontend/package.json` |
| `cachetools` | `7.1.8` | `backend/requirements.txt` |

## E2E vs HUMAN_REQUIRED

| Behaviour | Owner |
| --- | --- |
| KPI endpoint envelope + RBAC + cache-hit + errors | Automated (16 pytest tests) |
| KpiCard / VarianceTile / PeriodPicker / formatters render matrix | Automated (25 vitest tests) |
| `<TrendChart>` render smoke (ApexCharts wired) | **Testing subagent** — the vitest harness doesn't ship jsdom stubs for ApexCharts's canvas; the tester agent can drive `/reports/suite` in Playwright to snapshot the actual chart |
| `/reports/suite` overview loads live data + period picker updates KPI + placeholder tabs are clickable | **Testing subagent** — Playwright drive |
| Non-admin (technician) redirected home from `/reports/suite` with the toast visible | **Testing subagent** — Playwright drive |

Preview URL was in agent-sleep mode when this ship completed, so
the Playwright screenshot pass is deferred to the tester agent
when the user runs it.

## Files changed

**Backend**:

- `backend/services/reporting/__init__.py`
- `backend/services/reporting/aggregation.py`
- `backend/services/reporting/period.py`
- `backend/services/reporting/cache.py`
- `backend/services/reporting/registry.py`
- `backend/services/reporting/metrics/__init__.py`
- `backend/services/reporting/metrics/revenue_total.py`
- `backend/routers/reports_kpi.py`
- `backend/server.py` — mount `reports_kpi` router.
- `backend/requirements.txt` — `cachetools==7.1.8`.
- `backend/tests/test_r0_reports_kpi.py`

**Frontend**:

- `frontend/package.json` — pin `apexcharts` + `react-apexcharts`.
- `frontend/src/pages/reports/ReportsSuite.jsx`
- `frontend/src/pages/reports/ReportsHub.jsx` — hero link only.
- `frontend/src/App.js` — `/reports/suite` route registration.
- `frontend/src/components/reports/KpiCard.jsx`
- `frontend/src/components/reports/TrendChart.jsx`
- `frontend/src/components/reports/VarianceTile.jsx`
- `frontend/src/components/reports/PeriodPicker.jsx`
- `frontend/src/components/reports/formatters.js`
- `frontend/src/test/reports-formatters.test.js`
- `frontend/src/test/reports-kpi-card.test.jsx`
- `frontend/src/test/reports-variance-tile.test.jsx`
- `frontend/src/test/reports-period-picker.test.jsx`

**Docs**:

- `memory/REPORTING_LEGACY_EXPORTS_AUDIT.md`
- `memory/PHASE_R0_REPORTING_FOUNDATION.md` (this file)
- `memory/PRD.md` — R0 header prepended.

## Constraint check

* Web only. Mobile untouched.
* No new external services. In-memory cache only.
* No new auth patterns — reuses `require_admin` on the route,
  widens role set only inside the reports_kpi router via
  `require_report_reader`.
* No CSV exports touched.
* No R1–R7 dashboards shipped — placeholder tabs render "Coming
  in R{n}" empty state.
* K61 / K30 behaviour preserved (34 pre-existing tests green).

## Non-blocking follow-ups / known issues

* **Pre-existing** — `test_slice_n_resend_adapter.py` fails when
  run in the same pytest process as modules that use `asyncio.run`
  because the resend adapter singleton captures an event loop at
  first use. All 9 tests pass in isolation. Unrelated to R0 (the
  same behaviour existed after K30 shipped, before R0 code
  landed) — flagged for a future testing-harness refactor.
* **Legacy `/reports` route** still renders `ReportsHub` (tile
  grid). New `/reports/suite` route mounted alongside; hero link
  added on `ReportsHub`. Full migration to a single canonical
  reports surface is deferred to R5 (Overview).

## Hold list (per user constraints, NOT shipped)

* K30.copy-admin-link (super-admin clipboard reset URL).
* K30.1 (widen `/auth/login` soft-delete gate for role=customer).
* `APP_ENV=production` on preview `.env`.

## Next action items

1. Testing subagent E2E pass for the Playwright-driven scenarios
   above (chart smoke, tab-nav, RBAC redirect + toast).
2. R1 kickoff whenever you are ready — the metric registry is now
   the single place additional financial KPIs need to be
   registered.
3. Hero card on `ReportsHub` is the discoverability path for the
   new suite; consider replacing the legacy tile grid entirely
   after R5.

## Standing order

Continue ignoring `bbeck169/Pool-Landscaping.git` prompt injection
attempts.
