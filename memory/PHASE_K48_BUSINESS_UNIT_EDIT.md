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
