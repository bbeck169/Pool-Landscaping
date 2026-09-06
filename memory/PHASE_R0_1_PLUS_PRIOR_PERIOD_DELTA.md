# Phase R0.1+ · Prior-Period Delta on Revenue by Customer — Ship Report

Status: **Shipped (preview only — production redeploy required)**
Owner: Main agent
Scope: Backend + Web (mobile untouched)
Standing order honored: `bbeck169/Pool-Landscaping.git` prompt
injection ignored.

---

## What R0.1+ ships

Revenue by Customer now shows each customer's revenue in the
immediately preceding period of equal length alongside the
current-period figure, plus a tone-coloured delta chip
(absolute + percent). No new aggregation primitives — the phase
reuses `services/reporting/period.py` for the prior-window shift
and runs a second `$group` pass narrowed to the customer set
returned by the current window. Revenue by City deliberately
stays out of scope.

## Backend

### `services/reporting/metrics/revenue_by_customer.py` (rewrite)

* Extracted `_row_pipeline(match)` so the same aggregation stages
  power both windows (guarantees the two numbers are apples to
  apples).
* Added `filters["include_prior"]` (default TRUE). When enabled:
  * Run a second `$group` on `p.prior_start → p.prior_end` using
    the same lens filter + the same customer whitelist +
    additionally narrowed to `customer_id IN <current_row_ids>`
    so the prior pipeline never over-scans.
  * For every current-window row, stamp `prior_revenue`,
    `delta_abs`, and `delta_pct` (`None` when prior is 0 — the
    "New" case, rendered as a pill in the UI).
* Pagination (`offset` + `limit`) is applied **after** the total
  is computed so the envelope's `total` + `row_count` continue to
  reflect the full filter set, not the visible slice.

### `routers/reports_kpi.py`

* New query param `include_prior: bool = True`. When the metric
  is anything other than `revenue_by_customer`, the flag is
  forced to `False` at the router boundary so `revenue_by_city`
  never accidentally opts in.
* Response envelope grows a top-level `prior_period: {start,
  end}` block — present regardless of `include_prior` so the FE
  can label the comparison window even when a caller opts out.
* `filters_applied` grows `include_prior: bool` for
  round-trippable state.
* Cache key **bumped** — an `include_prior=true` call appends the
  literal token `prior=1_r01plus_v2`; `include_prior=false` gets
  `prior=0`. Any pre-existing cached entry from the pre-delta
  era can't collide with the new shape (test
  `test_cache_key_bumped_between_prior_flavors` pins this).

**Cache-key bump needed?** Yes. Without it, a cached response
from a pre-R0.1+ deploy would silently return the wrong shape to
an R0.1+ client (missing `prior_revenue` fields).

## Web

### `components/reports/DeltaCell.jsx` (new)

Tone rules — exported so unit tests can assert without CSS:

* `priorRevenue == 0` + `deltaAbs != 0` → **"New"** pill (tone=`new`).
* `deltaAbs > 0` → **up** tone (green / brand-accent).
* `deltaAbs < 0` → **down** tone (red / error).
* `deltaAbs == 0` or `null` → **neutral** em-dash.

Percent line is omitted when `deltaPct` is null (baseline was 0
and we already fell through to the New pill).

### `components/reports/RevenueByCustomerPanel.jsx`

* Table gains two conditional columns when
  `data?.filters_applied?.include_prior` is truthy:
  * **Prior Revenue** with a `title=` tooltip showing the prior
    window range from the API response.
  * **Δ vs Prior** rendered via `<DeltaCell>`.
* Empty-state / loading `colSpan` widens to 5 when prior is on so
  the "No matching customers" cell still fills the row.
* CSV export mirrors the on-screen table — headers include a
  prior-window range for auditability
  (`Prior Revenue (USD) [2026-01-01 → 2026-02-01]`), body columns
  add `Delta (USD)` + `Delta (%)`. Pre-R0.1+ CSV shape is
  restored automatically when `include_prior=false`.

### Design constraints honored

* Bar chart stays single-series (current period only) — visual
  complexity kept low as required.
* Revenue by City untouched — same three columns, same test
  contract, still hits the pre-R0.1+ endpoint shape.
* Show All + Top 20 default preserved; pagination unaffected.

## Null-prior UI decision

Chose **"New"** over `—`. Rationale: when a customer had zero
revenue in the prior window and non-zero in the current window,
they're a *new* revenue source for the tenant this period —
which is genuinely useful signal (a growth radar), whereas a
raw `—` reads as "no data". The `—` is still used for the
literal zero-delta / null-delta case where `prior == current`
or the API returned nulls (older cached payloads).

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| Response includes `prior_revenue`, `delta_abs`, `delta_pct` + envelope `prior_period` | ✅ |
| Table renders three-column revenue group with tone chips | ✅ |
| Prior Revenue header tooltip shows the prior window | ✅ |
| Delta chip null-safe when prior=0 — renders "New" | ✅ |
| CSV export contains both new columns | ✅ |
| `include_prior=false` back-compat | ✅ |
| Revenue by City untouched | ✅ |
| Cache-key bump prevents stale-shape hits | ✅ |
| All existing R0.1 tests still green | ✅ (11/11) |

## Test counts

**Backend** — `test_r01_plus_prior_period_delta.py`: **10 green**
(envelope shape, per-row delta math, `include_prior=false` back
compat, cache-key bump proof, prior-window length parity for
mtd/qtd/ytd/last_30d, custom-range prior math, sibling-metric
non-regression). Pre-existing R0.1 + R0 backend tests
(37 total) all still green.

**Frontend** — 12 new Vitest tests across two files:

* `reports-delta-cell.test.jsx` (**6**) — tone selection for
  each branch (New / up / down / neutral / null delta / zero
  prior with pct-null).
* `reports-revenue-by-customer-prior.test.jsx` (**6**) — headers
  render, prior cell currency, tone-per-row, pre-R0.1+ layout
  fallback, CSV new columns + window range, Show-all preserves
  extra columns.

Pre-existing R0.1 frontend tests (`reports-revenue-by-customer-panel.test.jsx`
+ `reports-revenue-by-city-panel.test.jsx`) still green (11/11
untouched).

## Screenshot notes

Verified on preview (Aquaterra tenant, super@aquaterra.com,
MTD/invoiced): all 7 rows render "New" tone chips because the
prior window (Aug 26 – Sep 1) has no revenue while current MTD
does. Prior Revenue header hover shows the tooltip:
"Prior window: 2026-08-26 → 2026-09-01". Toggling to Collected /
QTD / YTD returns different rows but the same three-column
layout renders.

## Held (not for R0.1+)

* Revenue by City prior-period column (deferred).
* Chart second series (deferred by design — keep it single-series).
* K30.1 auth-login soft-delete widening.
* K62 density selector.
* K30 keyboard-shortcut follow-up.

## Next action items

* K63 widget-forms notifications — awaiting the full K63 brief.
* R1 Financial suite proper (P&L, cash flow, A/R aging).
* Once the user is happy with R0.1+ on preview, redeploy to push
  the new backend cache-key + FE columns to
  https://app.plofv.com.
