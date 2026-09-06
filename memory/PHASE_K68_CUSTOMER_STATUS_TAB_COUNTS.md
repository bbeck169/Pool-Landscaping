# Phase K68 · Feb-2026 — Customer Status Tab Counts

## Audit finding
`/api/customers` was already paginated (P35, Feb-2026) and returns an envelope `{items, total, page, page_size, total_pages}` when `page` or `page_size` is supplied. The frontend already renders 4 tab counts (`Active`, `Inactive`, `Muted`, `Waitlist`) — but sourced them via **4 separate `?count_only=true` requests** fired in parallel on every filter/tab/page change (`loadCounts()`). The `All` tab was defined but wired to `count: null` (never populated). No `counts_by_status` block existed on the envelope.

**Decision**: Extend the envelope with `counts_by_status: {active, inactive, muted, waitlist, all}` computed in a single `$facet` aggregation. Drop the 4-request fanout in the primary filter-change effect. Retain `loadCounts()` as a defensive fallback (mutation paths still call it — harmless because it now recomputes the same values).

## Backend changes
- `routers/customers.py`
  * `CustomerListPage` Pydantic model gains `counts_by_status: Optional[Dict[str, int]] = None`.
  * `list_customers` snapshots the base query (`_k68_base_q`) BEFORE the waitlisted / is_active / is_muted status predicates are compounded in. The snapshot preserves search + city + multi-tag + data-quality + portal-status + soft-delete + merge filters.
  * When the paginated envelope is returned, one `$facet` aggregation over `_k68_base_q` produces 5 buckets:
    - `active` = `is_active∈{true,missing}` AND `is_muted!=true`
    - `inactive` = `is_active=false` AND `is_muted!=true`
    - `muted` = `is_muted=true` (orthogonal to active/inactive)
    - `waitlist` = `waitlisted=true` (orthogonal to everything else — a waitlisted-active row double-counts by design)
    - `all` = the base query verbatim (equivalent to `total` when no post-filter is active)
  * On aggregation failure the counts default to zero and a warning breadcrumb is emitted; the envelope still returns.

**Note on `unscheduled` + `missing_card` post-filters** — these run in Python after the Mongo query and are NOT reflected in the facet counts. The affected tabs are advisory in that combination; documented here rather than fought at the DB layer.

## Frontend changes
- `pages/customers/CustomersList.jsx`
  * `counts` initializer widened to 5 buckets (`{active, inactive, muted, waitlist, all}`).
  * `load()` now consumes `data.counts_by_status` and writes it into `setCounts` — envelope becomes the primary source.
  * `TAB_DEFS["all"]` wired to `counts.all` (was hardcoded `count: null`).
  * Filter/tab/page useEffect no longer invokes `loadCounts()` — envelope carries the counts.
  * `loadCounts()` fallback retained; extended to also compute the `all` bucket for the envelope-missing edge case.

## Tests
- Backend: `backend/tests/test_k68_customer_status_tab_counts.py` — 5 pass, 1 skip (customer role brute-force lockout — see `test_credentials.md`):
  1. Legacy bare-array response omits `counts_by_status` (backwards-compat).
  2. Paginated envelope ships all 5 buckets with correct types and totals matching a deterministic 7-customer fixture (3 active + 2 inactive + 1 muted + 1 waitlist).
  3. Counts respect the current search filter.
  4. Counts are identical regardless of which status tab (`is_active=true`/`false`/`is_muted=true`) the caller is on — facet strips those predicates.
  5. Non-admin still 403 (skipped due to environmental lockout — verified via curl).
  6. Perf p50 < 500ms (measured **p50 ≈ 120ms** across 10 warm calls).
- Frontend: `frontend/src/test/k68-customer-status-tab-counts.test.jsx` — 5 source-shape assertions, all pass.
- Regression: `k49-customers-filter-defaults`, `k40-default-filters`, `waitlist-bulk-invite` — 46 tests, all green.

## Perf note
`$facet` adds one aggregation over the same index-hit query set the paginated response already scans. Measured p50 = **120ms** end-to-end (over public preview URL) — 4x under budget. Two-fold savings vs. the pre-K68 fanout:
- Round-trips: 5 → 1 per filter change on the admin tab (Active + Inactive + Muted + Waitlist + primary list).
- Wall-time: waterfall of 4 parallel `count_documents` + 1 list ≈ ~350ms end-to-end pre-K68; envelope path measured 120ms.

## Backlog / follow-ups
- The `unscheduled` and `missing_card` counts drift when those filters are active (they run in Python post-filter). Deferred — those filters are rare and the count is a hint, not a source of truth.
- The Waitlist bucket double-counts against Active by design (matches the frontend's orthogonal-tab UX). Consider mutually-exclusive semantics as a future ergonomic knob if operators complain.
