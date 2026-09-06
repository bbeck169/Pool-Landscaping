# Phase K66 · ReportsHub Quick-Access Tiles — Ship Report

**Status:** COMPLETE (preview-verified).
**Scope:** Web-only landing surface at `/reports`. Replaces the legacy 11-tile grid + KPI strip + suite-hero on ReportsHub with a K66 quick-access tile grid: 3 built tiles with live headline KPIs + 7 coming-soon placeholders for R1–R7.

---

## 1 · What shipped

### Frontend

- **`frontend/src/pages/reports/ReportsHub.jsx`** — full rewrite as the K66 tile grid:
  - Header (`Reports` + subtitle) + `DateRangePicker` (period selector governing every live KPI on the page).
  - Responsive grid `grid-cols-1 md:grid-cols-3 gap-4` — 3-col desktop, 1-col mobile.
  - **3 built tiles** (icon · title · one-sentence description · live headline KPI · "Open report" pill):
    - `Revenue Total` → deep-links to `/reports/suite?tab=overview`. KPI: `revenue_total.value` formatted via shared `formatValue(v, "currency")`. Subtitle: prior-period delta `%`.
    - `Revenue by Customer` → deep-links to `/reports/suite?tab=financial#revenue-by-customer`. KPI: `revenue_by_customer.total`. Subtitle: `N customer(s)` from `row_count`.
    - `Revenue by City` → deep-links to `/reports/suite?tab=financial#revenue-by-city`. KPI: `revenue_by_city.total`. Subtitle: `N cit(y|ies)`.
  - **7 coming-soon placeholders**: R1 Financial, R2 Operations, R3 Customers, R4 Sales, R5 KPI Overview, R6 Custom Report Builder, R7 Scheduled Reports. Muted background (`colors.surfaceSecondary`), dashed border, `Coming soon` ribbon (`data-testid=reports-tile-coming-<phase>-ribbon`), `aria-disabled="true"`, no `<Link>` (keyboard tab order skips them), `Lock` icon + `Ships in R{n}` footer.
- **`frontend/src/pages/reports/ReportsSuite.jsx`** — accepts `?tab=<key>` URL hint (uses `useSearchParams`). Falls back to `overview` for unknown keys. Tab switches now sync back into the URL via `setSearchParams({...}, {replace:true})`. Added a hash-scroll effect that, when the active tab is `financial` and the URL carries a `#revenue-by-customer` / `#revenue-by-city` fragment, `scrollIntoView({behavior:"smooth"})` after `requestAnimationFrame` lets React commit first.
- **`frontend/src/pages/reports/FinancialTab.jsx`** — wrapped the two panels in `<div id="revenue-by-customer">` and `<div id="revenue-by-city">` so the hash targets resolve.

### Backend
- **No new endpoints.** Every tile KPI is fetched via existing `/api/reports/kpi/{metric_key}?period=custom&start=…&end=…`. Registry list (`GET /api/reports/kpi`) confirmed to still surface all 3 built metrics: `revenue_total`, `revenue_by_customer`, `revenue_by_city`.
- **No metric fabrication.** Every built tile's headline KPI is directly readable from the current registry.

### Tests
- **NEW `frontend/src/test/k66-reports-hub-quick-access-tiles.test.jsx`** — 5 vitest cases:
  1. Grid renders 3 built + 7 coming-soon tiles (verified by `data-testid` per phase).
  2. KPIs formatted via `formatValue` — `$124,500.75` / `$82,300.50` / `$55,000.00`; grouped-tile subtitles show correct row-count pluralization; scalar delta subtitle renders `+24.5% vs prior`.
  3. Built-tile `href` deep-links: total → `?tab=overview`, customer → `?tab=financial#revenue-by-customer`, city → `?tab=financial#revenue-by-city`.
  4. Coming-soon tiles are non-interactive: `aria-disabled="true"`, no anchor inside, no `Open report` affordance.
  5. Role-gating regression — asserts `App.js` still wraps `/reports` in `<AdminOnly>` around `<ReportsHub>` (source snapshot).

**Total: 5/5 PASS.**

### Adjacent regression
- 7 reports vitest files (PeriodPicker, RevenueByCity panel, RevenueByCustomer prior, DeltaCell, VarianceTile, HorizontalBarChart, downloadCsv) → **35/35 PASS.**
- Backend `/api/reports/kpi` registry list → confirmed 3 metrics via curl. Scalar + grouped payload shapes match the tile fetch expectations.

---

## 2 · Files changed

| Kind | File | Lines |
|------|------|-------|
| REWRITE | `frontend/src/pages/reports/ReportsHub.jsx` | 315 |
| MOD | `frontend/src/pages/reports/ReportsSuite.jsx` | +38/-3 |
| MOD | `frontend/src/pages/reports/FinancialTab.jsx` | +6/-2 (id anchors) |
| NEW | `frontend/src/test/k66-reports-hub-quick-access-tiles.test.jsx` | 175 (5 tests) |
| DOC | `/app/memory/PHASE_K66_REPORTSHUB_QUICK_ACCESS_TILES.md` | this file |
| DOC | `/app/memory/PRD.md` | entry prepended |

No backend files changed. No `.env` changes. No dependency additions.

---

## 3 · Screenshot notes

Desktop (1920×800) verification captured at `/tmp/k66_desktop.png`:

- Header row: `Reports` (H1) + subtitle "Quick-access tiles for every available report. Coming-soon tiles surface future phases." (left) · `This month · 2026-09-01 → 2026-09-30` DateRangePicker (right).
- Row 1: three built tiles. Revenue Total shows `$200.00 · +33.3% vs prior · Open report ›`. Revenue by Customer shows `$1,000.00 · 7 customers · Open report ›`. Revenue by City shows `$1,000.00 · 5 cities · Open report ›`.
- Rows 2–4: seven coming-soon tiles with `COMING SOON` ribbon top-right, `Ships in R{n}` footer, dashed muted styling. `R1 Financial · R2 Operations · R3 Customers` on row 2, `R4 Sales · R5 KPI Overview · R6 Custom Report Builder` on row 3, `R7 Scheduled Reports` alone on row 4 (3-col grid overflow).

Mobile (390×800) verification captured at `/tmp/k66_mobile.png`: same 10 tiles stacked in a single column via `grid-cols-1`; every tile remains legible without horizontal scroll.

**Visual style verdict:** acceptable pending K70 retheming. Current styling reuses `colors.surface` / `colors.brandTertiary` / `colors.onBrandTertiary` from `theme.js` — K70 will replace the built-tile chip and "Open report" affordance with the navy→green gradient + green-fill white-outline button. K66 tile structure will not need to change; K70 is a pure `style={}` swap.

---

## 4 · Acceptance criteria verification

1. ✅ `/reports` renders 3-col desktop / 1-col mobile grid (`data-testid=reports-hub-grid` with `grid-cols-1 md:grid-cols-3`).
2. ✅ Each built tile shows the live headline KPI with the correct formatter (currency vs count, verified in vitest test 2 + preview screenshot).
3. ✅ Each placeholder shows "Coming soon" ribbon, is `aria-disabled="true"`, has muted styling, and has no anchor / button (verified in vitest test 4).
4. ✅ Built-tile "Open report" pill navigates to the right destination — verified by asserting `href` fragments (test 3) + `ReportsSuite.jsx` handles the `?tab=` param + hash scroll.
5. ✅ Non-admin blocked — `App.js:1050` still wraps `/reports` in `<AdminOnly>` (asserted by test 5).
6. ✅ Tests: 5 new vitest + 35 adjacent reports vitest + backend registry curl smoke.

---

## 5 · Contract preservation

- `/api/reports/kpi/*` payloads unchanged (only new consumer added).
- Existing `/reports/business-summary`, `/reports/forecast`, `/reports/revenue-by-city`, etc. individual routes still reachable via URL / admin menu — the legacy tiles that pointed at them from ReportsHub are gone, but the destination pages are untouched.
- `/reports/suite` still opens on `overview` when no `?tab=` param is present — legacy callers unaffected.
- `FinancialTab.jsx` visual layout unchanged; the `<div id="…">` wrappers add zero styling.
- K30 / K61 / R0 / R0.1 / R0.1+ / K63 / K64 / K65 / K69 behavior preserved (adjacent tests all green).

---

## 6 · What's next

- **K67** — gradient palette sitewide (navy→green stops).
- **K68** — customer status tab counts.
- **K70** — retheme K66 tiles (navy→green gradient bg + green-fill white-outline `Open report` button). Structure ready; pure style swap.
- **K63.test-dispatch** — per-recipient test-dispatch button on LeadAlertsSettings.
- **R1** — full Financial suite (P&L, cash flow, A/R aging) — will flip the R1 tile from placeholder to built.
