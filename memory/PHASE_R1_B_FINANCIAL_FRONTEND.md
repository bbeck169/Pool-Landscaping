# Phase R1.b — Financial Suite Proper · Frontend Financial Tab + R1 Tile Flip

**Status:** SHIPPED · Feb 2026
**Depends on:** R1.a (backend metrics · SHIPPED)
**Unlocks:** R1.c (PDF exports)

---

## 1. Scope shipped

R1.b delivers the frontend expansion of `/reports/suite` Financial
tab so operators can consume every R1.a metric visually, plus a
one-tap collections cockpit action ("Send reminder") on the
Unpaid Invoices table. The Reports hub tile for R1 flips from
`ComingSoonTile` → `BuiltTile` with a live P&L Net Income KPI.

### 1.1 New Financial tab subsections
Rendered top-to-bottom under the existing shared toolbar
(`PeriodPicker` + `LensToggle` + `service_type` + `tech_id`),
inside `/app/frontend/src/pages/reports/FinancialTab.jsx`:

| # | Section | Component | Backend metric(s) |
|---|---------|-----------|-------------------|
| 1 | Overview strip | `OverviewStrip` | `revenue_total`, `cashflow_by_period`, `ar_aging` |
| 2 | P&L | `PnlPanel` | `pnl_by_period` (scalar) + `pnl_line_items` (grouped) |
| 3 | Cash Flow | `CashFlowPanel` | `cashflow_by_period` |
| 4 | AR Aging | `ArAgingPanel` | `ar_aging` + `ar_aging_by_customer` |
| 5 | Revenue by Service Type | `RevenueByServiceTypePanel` | `revenue_by_service_type` |
| 6 | Unpaid Invoices | `UnpaidInvoicesPanel` | `unpaid_invoices` |
| 7 | (Existing) Revenue by Customer | `RevenueByCustomerPanel` | `revenue_by_customer` |
| 8 | (Existing) Revenue by City | `RevenueByCityPanel` | `revenue_by_city` |

### 1.2 Overview strip
- 4 gradient tiles (K67 navy→green, K70.a token) with:
  - MTD Revenue + delta chip
  - MTD Collected (sum from `cashflow_by_period.summary.collected_total`)
  - AR Balance (`ar_aging.total`, `down_is_good` semantics; shows net-terms badge)
  - Top-3 AR aging buckets as mini progress bars

### 1.3 Send-reminder action (collections cockpit)
- Row-level button on every unpaid-invoice row.
- Backed by pre-existing `POST /api/quotes/{qid}/send-reminder`
  (require_admin, dispatches in-app + SMS + email via
  `send_invoice_reminder_email`).
- **New in R1.b**: server-side write of an
  `invoice_reminder_sent` audit event so DSO / collections
  telemetry can count the touch without re-scanning `quotes`.
  Payload: `invoice_id`, `invoice_number`, `customer_id`,
  `customer_name`, `balance`, `email_sent`, `reminder_count`,
  `channel="in_app+sms+email"`.
- Global `useConfirm()` modal precedes any dispatch:
  > "Send payment reminder to `{customer}`? `{title}` · Balance `{formatCurrency(balance)}`. The customer will receive an in-app notification, SMS (if opted in), and an email."
- Success → sonner `toast.success`, row patched locally with the
  new `reminder_count` (so the counter chip bumps without a
  refetch).
- Failure → `toast.error(server_msg)`; row untouched.
- Non-admin: server returns 401/403, toast surfaces the message
  (button still renders — cheap, keeps the UI stable across
  role changes).

### 1.4 Drill-down
- AR Aging by-customer table has a "See invoices" affordance per
  row → writes `?customer_id=<id>` to the URL and scrolls to the
  Unpaid Invoices section.
- Unpaid Invoices reads `customer_id` from the URL and threads it
  into the API query so back-nav preserves the scope. A "Clear
  customer filter" button appears when active.

### 1.5 Toolbar propagation
- Every subsection subscribes to the same `filters` object built
  from URL querystring (`period`, `start`/`end`, `lens`,
  `service_type`, `tech_id`).
- Filter change → each subsection's own `React.useEffect` fires,
  driving isolated re-fetches. No parent refetch orchestration
  required.

### 1.6 R1 tile flip on `/reports` hub
- `ReportsHub.jsx`: R1 moved from `comingSoonTiles` →
  `builtTiles` (test-guarded: R1 `<ComingSoonTile>` MUST NOT
  render after this phase — see
  `reports-hub-r1-tile-flip.test.jsx`).
- Live headline KPI: **P&L Net Income** (`pnl_by_period`) with
  the standard `Δ vs prior` chip.
- Deep-link: `/reports/suite?tab=financial#pnl` — anchors to the
  P&L subsection so operators land on the flagship metric.

### 1.7 CSV exports (per subsection)
Every new panel gets a client-side CSV export via the shared
`downloadCsv` helper. Locked column orders (regression-tested):

| Panel                     | Columns |
|---------------------------|---------|
| P&L                       | Label · Value · Format |
| Cash Flow                 | Bucket · Invoiced · Collected · Net · Running Balance |
| AR Aging                  | Bucket · Amount · Invoice Count |
| Revenue by Service Type   | Service Category · Category ID · Revenue · Invoices |
| Unpaid Invoices           | Customer · Invoice # · Amount · Balance · Days Overdue · Status · Effective Due |

The R1.a server-side CSV exports at
`/api/reports/kpi/{key}/export.csv` remain in place — the panel
buttons ship client-side exports so the download reflects
whatever local filter state the operator has applied.

---

## 2. Files changed

New (10):
- `components/reports/OverviewStrip.jsx`
- `components/reports/PnlPanel.jsx`
- `components/reports/CashFlowPanel.jsx`
- `components/reports/ArAgingPanel.jsx`
- `components/reports/RevenueByServiceTypePanel.jsx`
- `components/reports/UnpaidInvoicesPanel.jsx`
- `components/reports/UnpaidInvoiceReminderButton.jsx`
- `test/reports-overview-strip.test.jsx`
- `test/reports-pnl-panel.test.jsx`
- `test/reports-cash-flow-panel.test.jsx`
- `test/reports-ar-aging-panel.test.jsx`
- `test/reports-revenue-by-service-type-panel.test.jsx`
- `test/reports-unpaid-invoices-panel.test.jsx`
- `test/reports-unpaid-invoice-reminder-button.test.jsx`
- `test/reports-hub-r1-tile-flip.test.jsx`
- `backend/tests/test_r1_b_send_reminder_audit.py`

Modified (frontend):
- `pages/reports/FinancialTab.jsx` — 6 new subsections + drill-down state.
- `pages/reports/ReportsHub.jsx` — R1 tile flip + `pnl_by_period` KPI fetch.
- `pages/Login.jsx` — restored `login-goto-signup` link on the customer variant (regression guard).
- `test/phase27-mute-control.test.jsx` — mock `api.get` alongside `api.patch` (`api.get is not a function` fix).
- `test/k50-theming.test.js` — 2 asserts quarantined (`it.skip`) with TODOs pending design-owner adjudication.

Modified (backend):
- `routers/quotes.py::send_reminder` — writes `invoice_reminder_sent` audit event.

---

## 3. Flake-sweep bundle (as folded in per user directive)

| Test file | Status after R1.b |
|-----------|-------------------|
| `k50-theming.test.js` (QuickNavRail active) | **Quarantined** with TODO — design-owner adjudication pending (K52 gradient expectation vs K70-family solid-navy shipped) |
| `k50-theming.test.js` (CategoryDropdown active) | **Quarantined** with TODO — same design drift |
| `phase27-mute-control.test.jsx` | **FIXED** — added `api.get` to the mock (`api.get is not a function`) |
| `portal-login-hides-demo-tiles.test.jsx` (create-account link) | **FIXED** — restored `login-goto-signup` link on customer variant of `Login.jsx` |
| `k50-theming.test.js` (other cases) | Passing before and after R1.b |
| `k67-navy-green-gradient.test.js` | Passing |
| `k70a-tile-theming.test.jsx` | Passing |
| `feb2026-dashboard-kpi-tint.test.jsx` | Passing |

**Recommendation for the quarantined pair:** design owner picks
one of two paths — either accept the shipped solid-navy active
state (delete the K52-Slice-D assertions) or roll back to the
gradient in `AppLayout.jsx` and `AdminTopBar.jsx`. Trivial once
the intent is clarified.

---

## 4. Test summary

### Frontend (vitest)
| Suite (25 files) | Tests | Result |
|-------------------|-------|--------|
| R1.b new panels + tile flip + reminder button | 23 | **PASS** |
| Pre-existing reports/reporting + K67/K70a/theming + adj | 140 | **PASS** |
| Quarantined K52 gradient assertions (TODO) | 2 skipped | — |

### Backend (pytest)
| Suite | Tests | Result |
|-------|-------|--------|
| `test_r1_paid_date_helper.py` | 12 | PASS |
| `test_r1_backend_metrics.py` | 25 | PASS |
| `test_r1_indexes_migration.py` | 11 | PASS |
| `test_r1_csv_exports.py` | 8 | PASS |
| `test_r1_b_send_reminder_audit.py` (new) | 2 | PASS |
| `test_r0_reports_kpi.py` (regression) | 15 | PASS |
| `test_r01_plus_prior_period_delta.py` (regression) | 20 | PASS |
| `test_r01_revenue_grouped.py` (regression) | 12 | PASS |
| **TOTAL** | **105** | **PASS** |

Reproduce:
```
# Frontend
cd /app/frontend && yarn vitest run 'src/test/reports-*' \
  'src/test/k7*-*' 'src/test/k50-*' 'src/test/feb2026-dashboard-*' \
  'src/test/portal-login-*' 'src/test/phase27-*'

# Backend
cd /app/backend && python -m pytest \
  tests/test_r0_reports_kpi.py \
  tests/test_r01_plus_prior_period_delta.py \
  tests/test_r01_revenue_grouped.py \
  tests/test_r1_paid_date_helper.py \
  tests/test_r1_backend_metrics.py \
  tests/test_r1_indexes_migration.py \
  tests/test_r1_csv_exports.py \
  tests/test_r1_b_send_reminder_audit.py -q
```

---

## 5. Screenshots (captured on preview `poolscape-audit.preview.emergentagent.com`)

Captured with the standard super-admin login (`super@aquaterra.com`)
against the aquaterra tenant. See `/tmp/r1b-*.png` for the raw
files (a per-tenant welcome-tour modal overlays some tiles — the
underlying panels render correctly).

1. **`/tmp/r1b-financial-top.png`** — Financial tab hero:
   - Toolbar: MTD / QTD / YTD / Last 30 / Custom + Invoiced/Collected + Service Type + Technician.
   - Overview strip: MTD Revenue `$200.00 +33.3%`, MTD Collected `$200.00`, AR Aging top-3 buckets `$453.60 / $658.80 / $410.40` for `0-30 / 31-60 / 61-90`.
   - P&L panel: Net Profit `$200.00 · +33.3%` gradient tile + line-item table (Revenue / COGS / Labor / OpEx / …).
2. **`/tmp/r1b-unpaid.png`** — Unpaid Invoices:
   - Columns: Customer · Invoice # · Amount · Balance · Age (days) · Status · Actions.
   - Every row has View + Send reminder buttons.
   - Status badges: Due (default) / Partial (amber) / Aged (>60 red).
3. **`/tmp/r1b-hub.png`** — Reports hub tile flip:
   - New R1 tile: `R1 · Financial Suite` · `$200.00` · `Net Income · +33.3% vs prior` · Open report → `#pnl` deep-link.
   - Coming-soon tiles remain for R2-R7.

---

## 6. Acceptance criteria vs shipped

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Financial tab renders all 6 new sections (overview + 5 reports) | ✅ |
| 2 | Toolbar filters propagate to every subsection | ✅ (each subsection subscribes to `filters` prop) |
| 3 | R1 tile on ReportsHub is `<BuiltTile>` with live KPI + deep-link | ✅ (`pnl_by_period` scalar → `#pnl`) |
| 4 | Send reminder fires email + writes audit + shows toast | ✅ (server route already dispatches in-app + SMS + email; audit event added; toast wired) |
| 5 | Non-admin blocked with 401/403 | ✅ (server-side; button surfaces error toast) |
| 6 | Pre-existing flakes fixed or quarantined with TODO | ✅ (2 fixed, 2 quarantined with named TODOs) |
| 7 | Vitest: render/loading/empty/error per subsection + reminder confirm-modal flow + tile flip | ✅ (23 new tests, 100% pass) |
| 8 | Backend regression: R1.a metrics still return correct envelopes | ✅ (56/56 R1.a passing, 47/47 R0/R0.1 passing) |

---

## 7. Locked assumptions (inherited from R1.a, unchanged)

- Default net terms 30 days (`tenants.net_terms_days` clamp `[0,365]`).
- Calendar-month bookkeeping.
- AR Aging = past-due only (Option A · R1.a).
- Revenue lens default = `invoiced`.
- CSV column orders locked per subsection.

---

## 8. Deferred (out of R1.b)

- **R1.c** — PDF exports (ReportLab-based, 5 reports, per-tenant branded template).
- P&L "OpEx from `checks` collection" — R1.a `pnl_line_items` currently derives OpEx from the same aggregation base; a follow-on R1.c/R2 phase can layer the `checks` collection lens if operators need bank-side OpEx.
- Depreciation line item — deferred until R2 / accounting integration lands.
- Column sort on Unpaid Invoices table — server already sorts by `days_overdue` DESC; client sort layer deferred.

---

## 9. Ship gate

- [x] All 23 new vitest tests green
- [x] 140 pre-existing reports-adjacent vitest tests green
- [x] 105 backend tests green (R0 + R0.1 + R0.1+ + R1.a + R1.b audit)
- [x] Screenshots captured: Financial tab top, Unpaid Invoices, R1 tile flip
- [x] Audit event contract test in place (`invoice_reminder_sent`)
- [x] 2 pre-existing flakes root-caused and fixed; 2 quarantined with TODO for design owner
- [x] Phase doc written (this file)
- [ ] R1.c kickoff — **awaiting user green-light**
