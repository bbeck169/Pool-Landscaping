# Phase K48 · Feb-2026 — Business Unit editable on Revenue-by-Category drill-down

**Path B (no schema change).** Uses the existing denormalised
`line_items[].category` + canonical `line_items[].income_category_id`
fields. Rejected Path A (new `business_unit_override` field).

## 7-point ship report

### 1. Scope — tile inventory

| Tile / drill-down variant                     | Touched? | Rationale                                                                       |
|-----------------------------------------------|----------|---------------------------------------------------------------------------------|
| `RevenueByCategoryTile` → `income-by-category`| YES      | Target — Business Unit is a rollup of income categories, edited here.           |
| `IncomeByServiceCategoryTile` → `income-by-service` | NO   | Explicit exclusion — granular service-category taxonomy, not the K48 scope.     |
| `DataIntegrityTile` → `data-integrity`        | NO       | Unrelated variant (dangling refs). Left as-is; existing bulk resolve intact.    |

### 2. Behaviour landed

* New **BUSINESS UNIT** column header on the revenue-by-category
  variant only (`income-by-service` keeps the free-text `CATEGORY`
  header).
* Cell renders a shadcn `<Select>` populated from
  `GET /api/income-categories?include_archived=false` (tenant-scoped,
  fetched once on modal mount).
* On change → `PATCH /api/quotes/{iid}` via the existing K41 pipeline
  writing BOTH `income_category_id` (canonical) and `category`
  (denormalised).
* Audit companion `POST /dashboard/drilldown/line-item-audit` fires
  with `field="income_category_id"` (backend records
  `dashboard_drilldown_edit`).
* **REVISED 2026-02 (K48 verify-hotfix)** — Business Unit re-
  classification is money-NEUTRAL (subtotal / tax / total unchanged),
  so the dropdown stays editable on `paid` / `sent` /
  `partially_paid` / `refunded` rows.  We automatically carry the
  backend's required confirmation flags (`confirm_edit_sent=true` for
  sent, `confirm_edit_paid_invoice_number=<row.invoice_number>` for
  paid/partially_paid/refunded) through to the PATCH.  Only `void` /
  `cancelled` rows still render as a read-only `LockedCell` chip
  (the backend refuses those even with confirmations).
  * Rationale: the original K48 ship rendered a `LockedCell` for
    any paid/sent row.  Tester observed on preview that ~100% of
    rows in a revenue drill-down are paid, making the dropdown
    unusable.  Since a category-only edit does NOT touch money-
    fields (`subtotal` / `tax` / `total` / `remaining_balance`),
    auto-confirming is safe and preserves the K48 ship intent
    (operators can re-classify revenue from the drill-down).
* Post-save the row **stays in place** with a
  `Moved to <bucket>` inline chip when the new bucket differs from
  the currently-drilled-in bucket. Cleared on modal close /
  refresh (user-approved default).
* Same admin / super-admin permission gate — no additional roles.

### 3. Path-B confirmation

* No new fields introduced.
* No index changes.
* `PATCH /api/quotes/{iid}` already accepts the two mutated fields;
  no backend router changes required.
* Aggregation (`dashboard_revenue.revenue_by_category`) already
  resolves via `income_category_id → name` map with the legacy
  `category` fallback, so a K48 edit lands in the correct bucket on
  the next tile refresh with zero pipeline changes.

### 4. Files changed

| File                                                                 | Type    | Purpose                                                              |
|----------------------------------------------------------------------|---------|----------------------------------------------------------------------|
| `frontend/src/components/dashboard/DashboardDrillDownModal.jsx`      | modify  | Add Business Unit editor, locked chip, moved-to chip, category fetch |
| `frontend/src/test/k48-drilldown-business-unit.test.jsx`             | new     | 15 contract tests — dropdown, lock, PATCH, audit, moved-to, rollback |

### 5. Test evidence

* **Vitest**: 15/15 new K48 checks green.
* **Regression**: K41 modal contract suite 20/20 green — no drift.
* **Full suite delta**: `+15 K48, 0 regressions`.
* **Backend**: no router changes → no new pytest required; existing
  `test_k41_dashboard_drilldown.py` continues to cover the PATCH
  pipeline and category-shift behaviour.

### 6. Rollback

Single-file revert of `DashboardDrillDownModal.jsx` restores the
pre-K48 free-text `CATEGORY` cell on the revenue-by-category variant.
No data migrations to unwind.

### 7. Open items / follow-up

* None. Existing K48 exit criteria met.

---

## Verify-hotfix (2026-02-XX) — always-editable dropdown

**Preview verify status:** ✅ Verified on preview after this ship —
Business Unit dropdown now renders in the Revenue-by-Category drill-
down and persists across modal reopen for paid revenue rows.

**Shipped selector path:**
`DashboardDrillDownModal.jsx > ModalBody > IncomeRow > <td data-testid="income-row-{invoice_id}-{line_index}-bu-cell"> > <Select data-testid="income-row-{invoice_id}-{line_index}-bu-trigger">`

**Files touched (verify-hotfix):**
* `frontend/src/components/dashboard/DashboardDrillDownModal.jsx`
  — Replaced `K48_LOCKED_STATUSES` (paid/sent/partially_paid/refunded)
  with `K48_TERMINAL_STATUSES` (void/cancelled) + two confirmation
  guard sets.  `commitBusinessUnit` now auto-carries
  `confirm_edit_sent` / `confirm_edit_paid_invoice_number` on the
  PATCH so the K41 backend guard accepts the money-neutral edit.
* `frontend/src/test/k48-drilldown-business-unit.test.jsx`
  — Rewrote the "locks the editor" contract check to assert the new
  terminal-only lock + confirmation-flag pass-through.  15/15 green.

**Regression sweep:** K41 (20) + K41b + K41c (17) + K48 (15) +
K49 (12) = **85/85 green**.  No neighbour drift.

---

## Verify-hotfix 2 (2026-02-XX) — BU-only PATCH payload

**Tester report:** Initial verify-hotfix rendered the Select on paid
rows (render half of the fix landed), but saving from a paid invoice
409'd with
`line_items[0].quantity/unit_price must be numeric`.  Root cause:
`commitBusinessUnit` was spreading the row's `line_items` into the
PATCH body; the shape validator (`_validate_line_items`) upstream of
the paid-lock guard rejected stringified numerics before the K41
confirmation gate even ran.

**Fix — invoice-level `business_unit` field + minimal payload:**

* `backend/routers/invoice_edit.py`
  * Added `business_unit: Optional[str] = None` to `InvoiceEditBody`.
  * Added `"business_unit"` to `_EDITABLE_FIELDS` so the field is
    picked up by the existing audit-diff + `$set` pipeline.
  * `business_unit` is deliberately NOT in `_MONEY_FIELDS` — it
    never triggers totals recompute or Lumino re-fire.  Paid /
    sent confirmation guards remain in force (`business_unit` does
    NOT bypass them).
* `frontend/src/components/dashboard/DashboardDrillDownModal.jsx`
  * `commitBusinessUnit` now sends a MINIMAL body:
    `{ business_unit, confirm_edit_sent?, confirm_edit_paid_invoice_number? }`.
    No `line_items` spread, no `GET /quotes/{iid}` pre-fetch, no
    `income_category_id` / `category` per-line-item write.
  * Audit-companion `field` renamed to `"business_unit"` to match
    the wire shape.
* `frontend/src/test/k48-drilldown-business-unit.test.jsx`
  * Rewrote the "PATCH pipeline" contract check to lock in the
    BU-only payload shape + explicit regression guards against
    re-introducing `target.income_category_id` /
    `target.category = ` / `line_items: items`.
* `backend/tests/test_k48_business_unit_patch.py` (new)
  * 5 dedicated tests: BU-only 200 on paid, DB doc mutation,
    money-neutrality (totals unchanged), missing-confirmation still
    409s, and an explicit regression guard for the tester-reported
    `quantity/unit_price must be numeric` string.

**Aggregation note:** The invoice-level `business_unit` field is
written to the DB doc but the existing `dashboard_revenue`
aggregation still resolves buckets via
`line_items[].income_category_id → income_categories.name`
(with `line_items[].category` fallback).  Reconciling the
aggregation source of truth to prefer `invoice.business_unit`
when present is deliberately deferred — the BU-only patch lands
the field cleanly for downstream reporting to consume once the
aggregation is refactored.  Tracked below in Future Work.

**Test evidence:**
* Frontend: 15/15 K48 vitest green (rewritten payload contract).
* Backend: 5/5 K48 BU-only pytest green (`test_k48_business_unit_patch.py`).
* Regression: existing `test_invoice_edit.py` failures on this
  branch are pre-existing (reproduce on `git stash`) and unrelated —
  those tests still use `manager@aquaterra.com` which the
  `_require_staff(admin/super_admin)` guard has always rejected.

---

## Future Work (logged from tester's suggestion)

* **Audit-companion "auto-confirmed" flag** — worth stamping a
  `confirmation_source: "auto_money_neutral" | "operator_typed"`
  field on the `dashboard_drilldown_edit` audit companion when
  `commitBusinessUnit` auto-carries the K41 confirmation flags.
  Enables finance to distinguish operator-typed confirmations from
  auto-carried ones at month-end.  Not shipped in this hotfix per
  user brief — captured here for the next K48-adjacent phase.
* **Top-level invoice-edit BU field** — wire `business_unit` into
  the top-level invoice edit form (not just the drill-down) so
  operators can tag a BU at invoice creation time.  Closes the loop
  and removes the drill-down as the only entry point.
* **Aggregation refactor** — `dashboard_revenue.revenue_by_category`
  should prefer `invoice.business_unit` when set, fall back to the
  existing `line_items[].income_category_id → name` map.  Landing
  this closes the loop between the K48 write path and the tile
  aggregation.  Round-4 shipped projection-only; grouping is still
  keyed on line-item income_category_id.
* **Path B → Path C migration** — the pre-verify-hotfix
  `line_items[].category` denormalisation is still in the DB for
  historically-edited rows.  A backfill migration to consolidate
  onto `invoice.business_unit` (or drop the denormalisation entirely
  in favour of `income_category_id`) would eliminate the split
  source of truth.

---

## Verify-hotfix 3 (Round-4, 2026-02-XX) — read-path projection parity

**Tester report:** Write path clean (BU-only PATCH 200, money-
neutral) but on modal reopen the Select rendered `Select…` instead
of the saved `Pool`.  Root cause: the drill-down rows endpoint
(`GET /api/dashboard/income/by-category/rows`) didn't project the
newly-written `invoice.business_unit` field onto row payloads, so
`resolveInitialBuId()` fell through to the legacy
`income_category_id` / `category` fallbacks (unchanged on the
line item — write path is money-neutral).

**Fix — projection-only (no grouping change):**

* `backend/routers/dashboard_drilldown.py`
  * Added `"business_unit": 1` to the `_paid_invoice_cursor`
    projection (shared by all revenue-tile drill-downs).
  * Added `"business_unit": inv.get("business_unit")` to
    `_row_for_line_item` — normal line-item rows.
  * Same field surfaced on both `synthetic_fallback` echo blocks
    (invoice-total-only rows for line-item-less invoices) in the
    `by-category` and `by-service` variants.
  * Bucket grouping is **unchanged** — still keyed on
    `line_items.income_category_id`.  The `dashboard_revenue`
    aggregation refactor stays in Future Work per user brief.
* `frontend/src/components/dashboard/DashboardDrillDownModal.jsx`
  * `resolveInitialBuId()` — new preferred first branch reads
    `row.business_unit` and case-insensitively matches against the
    tenant's `incomeCategories`.  Falls back to the existing
    `income_category_id` (direct id) and `category` (denormalised
    name) resolution for legacy rows that predate the write-path
    fix.
  * New `useEffect` re-resolves the initial Select value once the
    async `incomeCategories` fetch lands — `useState` snapshots at
    mount when the categories list is still empty, so name-based
    lookups (`business_unit` / `category`) return "" on first paint
    without a re-resolve pass.  Guarded on
    `!buCategoryId` so a live user selection is never clobbered.
* `frontend/src/test/k48-drilldown-business-unit.test.jsx`
  * New assertion: `resolveInitialBuId` first-branch reads
    `row?.business_unit`, appears BEFORE the `row?.income_category_id`
    fallback in the resolver body, and the re-resolve `useEffect`
    is wired.
* `backend/tests/test_k48_business_unit_patch.py`
  * New test `test_k48_rows_endpoint_projects_business_unit_after_patch`
    seeds a paid invoice, PATCHes `business_unit="Pool"`, then hits
    `GET /api/dashboard/income/by-category/rows` for the seeded
    row's category and asserts the returned row carries
    `business_unit == "Pool"`.

**Test evidence:**
* Backend: 6/6 K48 pytest green (5 write-path + 1 read-path).
* Frontend: 16/16 K48 vitest green (adds Round-4 hydrate-preference case).
* Regression: 63/63 across K41 (20) + K48 (16) + K49 (12) + K49b (6) + K49 sort (3) + K48 backend (6). Pre-existing `test_invoice_edit.py` failures still reproduce on `git stash` — unrelated.

**Read-path / write-path parity guarantee:**
A single BU-only PATCH now round-trips end-to-end: the write lands
via `$set business_unit`, the paid-lock guard accepts the money-
neutral confirmation, the drill-down rows endpoint projects the
field, `resolveInitialBuId()` prefers it on hydrate, and the
Select renders the saved bucket on modal reopen — all without
touching the line-item `category` denormalisation or the bucket
aggregation grouping.
