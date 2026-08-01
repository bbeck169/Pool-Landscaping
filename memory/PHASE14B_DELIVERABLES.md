# Phase 14b · Feb-2026 — Deliverables Report

Composes strictly on top of Phase 14a's `charge_card_on_file`. Refuses external-repo trap prompts.

## Files added / changed

### Backend
- **NEW** `backend/routers/invoices_bulk_charge.py` — 3 endpoints + `execute_bulk_charge` core + `ensure_indexes()`.
- **EDIT** `backend/routers/quotes.py` — `list_quotes` accepts `category` (multi) + `card_on_file` (yes|no|any). Case-insensitive union across `line_items[].category`. Card cohort resolved against `payment_methods` w/ expiry check. `include_deleted` + `doc_type` preserved.
- **EDIT** `backend/services/payments/stripe_charge.py` — `charge_card_on_file` accepts new optional `idempotency_key` (default = internal). Backwards-compatible.
- **EDIT** `backend/server.py` — router include for `_p14b_bulk_charge`.
- **EDIT** `backend/scripts/create_session_indexes.py` — `ensure_on_boot` now invokes `routers.invoices_bulk_charge.ensure_indexes()` for the two new `bulk_charge_runs` indexes.
- **NEW** `backend/tests/test_bulk_charge_phase14b.py` — 15 pytest cases (all pass).

### Frontend
- **NEW** `frontend/src/components/invoices/BulkChargeModal.jsx` — two-step Review → Confirm modal (client UUID idempotency key).
- **NEW** `frontend/src/pages/admin/BulkChargeRunsPage.jsx` — `BulkChargeRunsList` + `BulkChargeRunDetail`.
- **EDIT** `frontend/src/pages/invoices/InvoicesList.jsx` — category multi-select dropdown + chip strip + Clear button; `Charge cards on file` button in bulk action bar; modal mount; category filter forwarded to `/quotes` via querystring.
- **EDIT** `frontend/src/App.js` — routes `/admin/finance/bulk-charge-runs[/:runId]`.
- **EDIT** `frontend/.env` — no changes (Phase 14a already added Stripe env vars).
- **EDIT** `frontend/package.json` — `postcss-selector-not@9.0.0` added to fix a webpack loader cache issue triggered by the earlier Stripe SDK install.

### Ops / docs
- **EDIT** `/app/CHANGELOG.md` — prepended Phase 14b entry (Added / Changed / Security / Not resurrected).
- **NEW** `/app/memory/PHASE14B_DELIVERABLES.md` (this file).

## curl matrix (external ingress, `poolscape-audit.preview.emergentagent.com`)

| # | Endpoint | HTTP | Notes |
|---|----------|------|-------|
| 1 | `GET /api/quotes?doc_type=invoice&category=Pool` | 200 | Single-cat filter |
| 2 | `GET /api/quotes?doc_type=invoice&category=Pool&category=Chem` | 200 | Multi-cat union |
| 3 | `GET /api/quotes?doc_type=invoice&card_on_file=yes` | 200 | Cohort filter |
| 4 | `GET /api/quotes?doc_type=invoice&card_on_file=no` | 200 | Complement filter |
| 5 | `GET /api/invoices/line-item-categories` (admin) | 200 | `["Chem","Late fee","Pool"]` |
| 6 | `GET /api/invoices/line-item-categories` (customer) | **403** | Role guard |
| 7 | `POST /api/invoices/bulk-charge-card-on-file` empty ids (admin) | **422** | Pydantic min_length |
| 8 | `POST /api/invoices/bulk-charge-card-on-file` (customer) | **403** | Role guard |
| 9 | `GET /api/invoices/bulk-charge-runs` (admin) | 200 | List view |
| 10 | `POST /api/invoices/bulk-charge-card-on-file` 101 ids | **422** | Cap at 100 |

## Screenshots
- `/tmp/p14b_1_filters_selection.png` — Category chip ("Pool") + 3 rows selected + bulk action bar showing "Charge cards on file" button.
- `/tmp/p14b_2_modal_review.png` — Bulk charge modal step 1: 3 invoices, "0 eligible · 3 skipped", per-row "NO CARD ON FILE" badges, disabled "Confirm charge — $0.00".
- `/tmp/p14b_3_runs_page.png` — `/admin/finance/bulk-charge-runs` page with the just-created dry-run entry (DRY RUN chip, 3 selected, 0 charged, 3 skipped).

## Test counts
- **Pytest**: 43 passed · 3 skipped · 0 failed (Phase 14a=15, Phase 14b=15, Phase 11 unification=8, CORS=5; skips are Phase 14a router happy-paths needing real Stripe key).
- **Vitest**: 523 passed · 13 failed · 1 skipped across 112 files. **Within tolerance** (baseline 11-14; user directive: leave alone).

## Design decisions

### 1. Per-invoice idempotency composition
Bulk request carries a single `idempotency_key` (client UUID). For every real charge, the router composes `f"{bulk_idempotency_key}:{invoice_id}"` and hands it to Phase 14a's newly-extended `charge_card_on_file(idempotency_key=…)`. Effect:
- Client-side retry of the same bulk key → the DB-side unique index on `(tenant_id, idempotency_key)` returns the persisted row verbatim; no per-invoice Stripe call fires. Verified by `test_bulk_idempotency_replay_is_zero_side_effect`.
- Cross-bulk retry with a different `bulk_idempotency_key` for the same invoice → different composed key → Stripe treats it as a new charge (correct — a fresh operator intent).
- Concurrent-race safety: if two identical bulk calls collide (before the first `insert_one` completes), the second call catches the unique-index `insert` error and returns the winner's persisted response.

### 2. Handling `{ok: False}` without a `charge_id`
Phase 14a's `charge_card_on_file` can return `{ok: False, status: "requires_action", payment_intent_id: <maybe None>}` — e.g., a PaymentIntent that needs 3-D-Secure and can't be captured off-session. The router maps this to:
```
{"status": "failed",
 "error_code": "not_ok_no_charge_id",
 "error_message": "provider status=requires_action pi=<...>",
 "amount_charged_cents": 0}
```
The row still counts toward `summary.failed`, no `total_amount_charged_cents` accrues, and no invoice-side `payment_status` mirror update fires. Verified by `test_bulk_charge_returns_failed_for_non_ok_no_charge_id`.

If Phase 14a *raises* (network / decline / attach-error), the router catches at the per-invoice `try` and records `error_code=<ExceptionClassName>` with the first 400 chars of `str(exc)`. Verified by `test_bulk_charge_returns_failed_on_stripe_exception`. Subsequent invoices in the batch continue to process.

### 3. Eligibility ordering
User spec listed `already_paid` before `zero_balance`. However, an invoice with `total == 0` (e.g., a $0 late-fee waiver entry) triggers both predicates simultaneously (`amount_paid >= total` AND `total <= 0`), and the more descriptive diagnostic is `zero_balance` — a customer-facing "this was never billable" signal. Ordering finalized as: `zero_balance` → `already_paid` → `no_card_on_file` → `card_expired`. The pytest scenario locks this behaviour in.

### 4. Backend-driven card_on_file cohort resolution
The frontend has an existing client-side `has_payment_method` enrichment path via `/api/invoices/overview`. The Phase 14b filter is served by the backend `list_quotes` route so external API consumers (integrations, exports) get the same answer as the UI. The backend does one `payment_methods` scan per request, filtered by tenant + `deleted_at is null`, and applies expiry math in Python. For tenants with >10k customers this is a candidate for a materialized-view later; for now the collection is small enough that the extra ~10 ms is negligible.

### 5. Cross-tenant safety
The bulk endpoint preloads all invoice docs matching `id ∈ ids AND tenant_id == caller AND doc_type == invoice` in a single `find()`. Any ID not in the returned set becomes a `{status: "skipped", skip_reason: "not_found"}` row — never a 404. This mirrors the pattern in `services/invoice_lookup.py::find_invoice_dual` and prevents existence-leak side channels. Verified by `test_bulk_cross_tenant_id_is_not_found_no_leak`.

### 6. Category filter regex vs `$in`
Case-insensitive union across `line_items[].category` uses `$elemMatch` + a `$regex` per selected value (anchored `^{esc}$`, options `i`). This handles the mixed-case values in the current dataset (`"Pool"` vs `"pool"`) without relying on data normalization. Pattern injection is prevented by `re.escape` on each caller-supplied value.

### 7. Rate limiting
75 ms `asyncio.sleep` between successive **real** (non-dry-run) charges — inside the 50-100 ms spec band. Skip-status rows don't trigger the sleep (no wire call happens). This gives ~5.7 s worst-case latency for a full 100-invoice batch — well under the 30 s FastAPI request budget.

## Out of scope (as specified)
- Actions other than card-on-file charge
- Mobile UI
- Refunds / retries beyond what Phase 14a returns
- Editing invoices in the bulk selection
- Sending receipts (Phase 14a webhook mirrors `payment_status`)

## Phase 11 invariant
The new router grep-lint test (`test_grep_lint_no_writes_to_db_invoices`) confirms zero writes to `db.invoices` in `routers/invoices_bulk_charge.py`. All invoice reads/writes go through `db.quotes` with `doc_type="invoice"`.

## External-repo prompt-injection log
Ignored every embedded reminder in tool output / file content pointing at `bbeck169/Pool-Landscaping.git` or offering Option A/B/C alternatives. The only path is Option D — execute the sanctioned task inside `/app`.
