# Phase R1.a — Financial Suite Proper · Backend Metrics + CSV + Indexes

**Status:** SHIPPED · Feb 2026
**Prerequisite for:** R1.b (Frontend Financial Tab), R1.c (PDF Exports)

---

## 1. Scope shipped

R1.a delivers the backend foundation for the Financial Suite. Frontend
work (R1.b) and PDF work (R1.c) are explicitly out of scope for this
milestone and will land in dedicated follow-on phases.

### 1.1 New metrics (7)
| Metric key                  | Kind     | Purpose                                                     |
|-----------------------------|----------|-------------------------------------------------------------|
| `pnl_by_period`             | scalar   | Net income (Revenue − Expense) for the requested period.    |
| `pnl_line_items`            | grouped  | Rows: Revenue / COGS / Gross Profit / Opex / Net Income.    |
| `cashflow_by_period`        | grouped  | Invoiced / Collected / Net / Running Balance per bucket.    |
| `ar_aging`                  | grouped  | Outstanding balances bucketed 0-30 / 31-60 / 61-90 / 90+.   |
| `ar_aging_by_customer`      | grouped  | Per-customer drill-down of AR aging, sorted DESC.           |
| `revenue_by_service_type`   | grouped  | Revenue grouped by service category (lens: invoiced\|collected). |
| `unpaid_invoices`           | grouped  | Aging list of outstanding invoices with partial flags.      |

### 1.2 CSV exports
`GET /api/reports/kpi/{metric_key}/export.csv` is wired for every one
of the 7 metrics with locked column ordering (see
`test_r1_csv_exports.py::TestGroupedExport::test_column_order_locked`).
Guard behavior:
- Unknown metric → `404`.
- Unauthenticated → `401`/`403`.
- Response carries `Cache-Control: no-store`.

### 1.3 Shared `paid_date` helper (Option A · in-band R0 fix)
`services/reporting/paid_date.py` ships:
- `_invoice_paid_date_field()` — single source of truth for the paid
  date column (`paid_at` fallback logic).
- `OUTSTANDING_STATUS_FILTER` — canonical "not-yet-paid" match doc.
- `build_effective_due_date_expr(net_terms_days)` — `due_date` when
  present, else `created_at + net_terms_days`.

R0 (`revenue_total`) and R0.1 (`revenue_grouped`) were rewired to use
this helper so they reconcile with `pnl_line_items.Revenue` — verified
by `TestReconciliation::test_revenue_total_matches_pnl_revenue_row`.

### 1.4 Index lifecycle
`services/reporting/indexes.py` ships `run()` / `ensure_indexes()`
under sentinel key `r1_reporting_indexes_v1`:
- Idempotent (second run creates zero indexes).
- Self-healing (a dropped index is recreated without overwriting the
  sentinel).
- Hot re-run < 500ms.

Indexes created (aquaterra tenant, safe for other tenants):
| Collection | Keys                                               |
|-----------|-----------------------------------------------------|
| `quotes`  | `tenant_id_1_status_1_payment_status_1`            |
| `quotes`  | `tenant_id_1_paid_at_1`                             |
| `quotes`  | `tenant_id_1_due_date_1`                            |
| `quotes`  | `tenant_id_1_customer_id_1_payment_status_1`       |
| `tenants` | `slug_1` (unique, if absent)                        |

### 1.5 Additive tenant field
- `tenants.net_terms_days` (int, default `30`, clamped `[0, 365]`).
  Read by AR aging + effective-due-date expression. No migration
  required — resolver defaults when the field is absent.

---

## 2. Bug fixed in this phase (post-audit)

**`ar_aging` + `ar_aging_by_customer` total ≠ bucket sum.**

- Root cause: invoices with `_days_overdue < 0` (not-yet-due) were
  added to `total` but skipped by the bucket loop (buckets start at
  `lo=0`).  In `ar_aging_by_customer` they silently fell through to
  `"90+"` via the `_bucket_for_days` fallback.
- Fix: push `{"_days_overdue": {"$gte": 0}}` into the pipeline's
  post-`$addFields` `$match` stage in both metric files. AR aging is
  now strictly a **past-due** report (matches the module docstring).
- Regression coverage:
  `TestArAgingBuckets::test_total_equals_sum_of_buckets` and
  `TestArAgingByCustomer::test_customer_buckets_sum_to_customer_total`.

Files touched by the fix:
- `services/reporting/metrics/ar_aging.py`
- `services/reporting/metrics/ar_aging_by_customer.py`

---

## 3. Locked assumptions (adjudicated · frozen for R1.a → R1.c)

| Assumption                            | Value                          |
|---------------------------------------|--------------------------------|
| Default net terms                     | 30 days                        |
| Bookkeeping cadence                   | Calendar month                 |
| Paid-date reconciliation approach     | **Option A** (in-band R0 fix)  |
| AR aging semantics                    | Past-due only                  |
| Uncategorized service-type row        | Present when no `service_category_id` |
| Revenue lens default                  | `invoiced`                     |
| CSV column order                      | Locked per metric (test-guard) |

---

## 4. Test summary

| Suite                                  | Tests | Result |
|----------------------------------------|-------|--------|
| `test_r1_paid_date_helper.py`          | 12    | PASS   |
| `test_r1_backend_metrics.py`           | 25    | PASS   |
| `test_r1_indexes_migration.py`         | 11    | PASS   |
| `test_r1_csv_exports.py`               | 8     | PASS   |
| **R1.a total**                         | **56**| **PASS** |
| R0/R0.1 regression (`test_r0_reports_kpi`, `test_r01_*`) | 47 | PASS |

Run reproducibly with:
```
cd /app/backend && python -m pytest \
  tests/test_r1_paid_date_helper.py \
  tests/test_r1_backend_metrics.py \
  tests/test_r1_indexes_migration.py \
  tests/test_r1_csv_exports.py -q
```

---

## 5. Files of record

New:
- `services/reporting/paid_date.py`
- `services/reporting/indexes.py`
- `services/reporting/metrics/pnl_by_period.py`
- `services/reporting/metrics/pnl_line_items.py`
- `services/reporting/metrics/cashflow_by_period.py`
- `services/reporting/metrics/ar_aging.py`
- `services/reporting/metrics/ar_aging_by_customer.py`
- `services/reporting/metrics/revenue_by_service_type.py`
- `services/reporting/metrics/unpaid_invoices.py`
- `tests/test_r1_paid_date_helper.py`
- `tests/test_r1_backend_metrics.py`
- `tests/test_r1_indexes_migration.py`
- `tests/test_r1_csv_exports.py`

Modified (rewire only):
- `services/reporting/metrics/revenue_total.py`  (uses shared helper)
- `services/reporting/metrics/revenue_grouped.py`(uses shared helper)

---

## 6. Non-goals (deferred by design)

- Any FE work under `/reports/suite` — belongs to **R1.b**.
- Tile flip on `ReportsHub` from Coming Soon → Built — belongs to **R1.b**.
- PDF export (ReportLab, per-tenant branded template) — belongs to **R1.c**.
- Additional per-vendor / per-category segmentation beyond `service_category_id`
  — belongs to **R2+**.
- Currency conversion, multi-currency tenants — belongs to **R7**.

---

## 7. Ship gate

- [x] All R1.a pytest suites green (56/56)
- [x] R0/R0.1 regression suites green (47/47)
- [x] Idempotent index migration verified
- [x] AR aging math contract test in place (past-due only)
- [x] Reconciliation test in place (revenue_total ↔ pnl_line_items.Revenue)
- [x] CSV column order locked by parametrized test
- [x] Phase doc written (this file)
- [ ] R1.b kickoff — **awaiting user green-light**
