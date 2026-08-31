# Phase F2 · Feb-2026 — Data Integrity Repair (Admin, Dry-Run + Apply)

## Ship summary
Delivered two new super_admin endpoints for surgical data-repair with a
strict read-then-write workflow, plus the F1 authz-logging trivial
extra folded in.

### New surfaces (backend)
| Method + Path | Purpose |
|---|---|
| `GET /api/admin/data-repair/jobs/dry-run` | Classify every active job into `orphaned_customer_refs` / `orphaned_technician_refs` / `unassigned_pending_jobs`. Mints a `confirm_token` + `scan_timestamp`, persists the scan doc with 15-minute expiry. READ-ONLY. |
| `POST /api/admin/data-repair/jobs/apply` | Requires echoed `confirm_token` + `dry_run_scan_timestamp`. Re-validates the scan record, executes repairs, writes one row per repair into `data_integrity_repairs` (unique on `(run_id, target_id)`). |
| `GET /api/admin/data-repair/history` | Last 100 repair rows, grouped by `run_id`. |

### Repair strategy
- `orphaned_customer_ref` → **soft-delete** the job
  (`status='deleted'`, `deleted_reason='data_repair_orphaned_customer'`,
  `updated_at` stamped for parity with the tech path).
- `orphaned_technician_ref` → **null out `technician_id`** (preserve
  `technician_name` denorm for historical display).
- `unassigned_pending` → **flag only** (no write). Surfaces the 3
  legitimately-pending jobs for operator action.

### Files touched
| File | Change |
|---|---|
| `backend/routers/data_repair.py` | **NEW** — full F2 router (505 LOC). |
| `backend/services/authz.py` | ERROR-level log on the exception branch (F1 advisory folded in). |
| `backend/server.py` | Router registration + boot-time `ensure_indexes` hook. |
| `backend/scripts/ensure_indexes.py` | Added `data_repair` step so prod ops runbook creates the 3 indexes. |
| `backend/tests/test_data_repair_dry_run.py` | 4 tests. |
| `backend/tests/test_data_repair_apply_happy_path.py` | 3 tests. |
| `backend/tests/test_data_repair_apply_idempotency.py` | 1 test. |
| `backend/tests/test_data_repair_apply_stale_dry_run.py` | 3 tests. |
| `backend/tests/test_data_repair_bson_naive_datetime.py` | **NEW** — 3 tests pinning the BSON naive-datetime fix. |
| `backend/tests/test_authz_logs_on_exception.py` | 1 test. |

### Mongo indexes (all live now)
- `data_integrity_repairs (run_id, target_id)` — unique, enforces write idempotency.
- `data_integrity_scans (confirm_token)` — unique.
- `data_integrity_scans (expires_at)` — TTL, `expireAfterSeconds=0`, auto-reaps expired scan docs.

## Empirical proof (live preview URL)
| Step | Result |
|---|---|
| Pre-apply dry-run | 10 orphan-cust + 0 orphan-tech + 3 unassigned — matched audit exactly. All 10 names in `{Confirm Case, Water Bodies Test, Lynn Merril}`. |
| Apply | `run_id=92359233…`, `changes_applied=10`, 10 audit rows written. |
| Post-apply dry-run | `total_would_change=0`, `orphaned_customer_refs=[]`. |
| History | 1 run, 10 changes, all `soft_delete` / `orphaned_customer_ref`. |
| Re-apply (idempotency) | `no_op=true`, `changes_applied=0`. |

## Testing agent findings — all addressed
| Priority | Finding | Status |
|---|---|---|
| CRITICAL | Naive-vs-aware datetime comparison in `_load_scan` (BSON strips tz on read) → 500 on every live apply | **Fixed** (tester's patch verified). New test suite `test_data_repair_bson_naive_datetime.py` locks the fix. |
| HIGH | Unique indexes missing in live DB (`_RUN_STARTUP_INDEXES=false` in prod, `scripts/ensure_indexes.py` didn't include F2) | **Fixed** — added F2 to the ops script + also added the TTL index. All 3 indexes verified live. |
| Minor | Dry-run cache re-stamping comment was misleading | Comment rewritten to explain the actual behaviour (stable token within 60s, 15-min freshness enforced separately). |
| Minor | `data_integrity_scans` had no TTL index | Fixed alongside the HIGH item. |
| Minor | `orphaned_technician_ref` branch never hit live | Deferred — 0 orphan techs in live DB. Unit + naive-datetime coverage exists. |
| Code review | `_apply_orphan_customer` didn't stamp `updated_at` (inconsistent with tech path) | **Fixed** — now stamps `updated_at` on soft-delete. |

## Test totals
- **F2**: 15/15 pass (4 + 3 + 1 + 3 + 3 + 1).
- **F1 regression**: 19/19 unit + 30/30 integration still pass.
- **Combined**: 64/64.

## Open advisories (documented, deferred as scope expansion)
1. **`run_id` == `confirm_token` coupling**: a leaked history response
   exposes the token used to apply (within its 15-min window). Split
   the two by using a separate `run_id = new_id()` in
   `data_repair_apply` and storing the mapping. Non-blocking for F2
   since the history endpoint itself is super_admin-only.
2. **`data_repair_history` pagination**: `to_list(100)` truncates
   mid-run when a repair batch exceeds 100 rows. Fine for the 10-row
   scale we operate at; add pagination when the scale changes.
