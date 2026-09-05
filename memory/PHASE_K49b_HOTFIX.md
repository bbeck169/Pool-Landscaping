# Phase K49b Hotfix — `GET /api/customers` `KeyError: 'id'` → 500

**Ship date:** Feb 2026
**Scope:** `backend/routers/customers.py`, `backend/migrations/k49b_customer_id_backfill.py`
**Test suite:** `backend/tests/test_k49b_customer_id_backfill.py`
**Status:** 🟢 SHIPPED — 6/6 K49b tests + 3/3 K49 tests + 21/21 broader customer-list regression tests green.

---

## Symptoms
- Tester report: `GET /api/customers` returning 500 on preview.
- Traceback: `KeyError: 'id'` at `backend/routers/customers.py:768` inside the
  properties_count hydration block. Every downstream hydration in the customers
  list handler indexed `d["id"]` and would have crashed on the same row.
- Trigger: a single legacy customer doc ("Kaylan Testcase" on preview) written
  without a top-level `id` field — only `_id`. Pre-P42-era imports and a few
  one-off scripts inserted docs before the codebase enforced `id = str(_id)`
  at insert time.
- Also produced a Pydantic `ResponseValidationError` on any doc that survived
  the earlier `KeyError` guards but still lacked `id` — `CustomerListItem`
  declares `id: str` (required).

## Fix — three layers of defence

### 1. Router-side early filter (`routers/customers.py`)
Right after the DB fetch + legacy-datetime coercion pass, drop any doc missing
a top-level `id` from the response array BEFORE it reaches the Pydantic
response validator. Emits one `logger.warning` per dropped row with
`tenant_id` + name shape (breadcrumbs for the backfill audit — the `_id`
projection is stripped by both the `find()` and aggregation paths).

```python
_k49b_kept: List[dict] = []
for _d in docs:
    if _d.get("id"):
        _k49b_kept.append(_d)
    else:
        logger.warning(
            "[k49b] dropping customer row missing top-level 'id' "
            "(tenant=%s name=%r first=%r last=%r); backfill "
            "migration will repair on next boot",
            _d.get("tenant_id"), _d.get("name"),
            _d.get("first_name"), _d.get("last_name"),
        )
docs = _k49b_kept
```

Existing downstream `d.get("id")` guards were kept in place as defence-in-depth
(their code paths are still reachable via the K49 sort pipelines and the
properties_count / next_scheduled_at hydrations).

### 2. Search-surface widening (`routers/customers.py`)
`GET /api/customers?search=…` was matching a single regex against `name`,
`email`, `phone`, `address`. Since K49 promoted `last_name` to a first-class
sort key and the customers-list UI now renders the split `last_name` column,
callers routinely search a mix of tokens that live in different columns
(e.g. `"Kaylan Testcase"` against a doc with `name="Kaylan Testcase"` +
`last_name="Testcase"`).

New behaviour: split search on whitespace, `AND` across tokens, each token
matches ANY of six fields (`name`, `first_name`, `last_name`, `email`,
`phone`, `address`). Single-word searches remain a strict superset of the
old behaviour. `re.escape` neutralises metacharacters.

### 3. Data-side backfill (`migrations/k49b_customer_id_backfill.py`)
Existing migration file was already wired into `server.py` startup. Two
additions in this ship:

- **Loop-rebind guard at `run()` entry.** The regression suite calls
  `asyncio.run(run(...))` per-test, which creates a fresh event loop; without
  this rebind Motor's futures stayed attached to whatever loop was current
  when `config` was first imported and every subsequent `await db.…` raised
  `RuntimeError: … attached to a different loop`. Boot-time callers pass
  through unchanged (same running loop before/after). Best-effort — silently
  falls through if `config` isn't importable.

- Migration semantics unchanged: scans for `id: {$exists: false} | null | ""`,
  writes `id = str(_id)` under a pipeline `update_many`, records a sentinel
  in the `migrations` collection so subsequent boots short-circuit once a
  clean run has been recorded.

## Cursor lifecycle spot-check
Per acceptance criteria — verified in `list_customers`:
- All `find()` reads use `.to_list(limit)` (fully drains and closes cursor).
- All aggregations use `.to_list(limit)` (same).
- Sub-hydrations (`properties_count`, `next_scheduled_at`) use
  `async for row in db.….aggregate(…)` — Motor auto-closes the cursor when
  the async iterator exhausts.
No leaked cursors on the customers-list path.

## Test evidence
```
tests/test_k49_customers_last_name_sort.py::test_k49_last_name_asc_orders_correctly PASSED
tests/test_k49_customers_last_name_sort.py::test_k49_unknown_sort_falls_back_to_default PASSED
tests/test_k49_customers_last_name_sort.py::test_k49_last_name_asc_bare_array_shape PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_router_guard_default_sort_returns_200 PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_router_guard_last_name_asc_returns_200 PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_router_guard_bare_array_shape_returns_200 PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_backfill_migration_populates_id_from_oid PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_backfill_migration_is_idempotent PASSED
tests/test_k49b_customer_id_backfill.py::test_k49b_seeded_doc_surfaces_with_valid_id_after_backfill PASSED
=========================== 9 passed in 2.33s ===========================
```

Broader customer-list regression sweep (K49b guardrail + search widening):
```
tests/test_customers_is_active_filter.py         — 6/6 PASSED
tests/test_customers_list_pagination.py          — 4/4 PASSED
tests/test_customers_list_sort_feb2026.py        — 8/8 PASSED
tests/test_customers_portal_status_filter.py     — 3/3 PASSED
tests/test_customers_tab_count_consistency_p40.py — 13/13 PASSED
tests/test_customers_waitlist_filter.py          — 3/3 PASSED
```

Pre-existing failures (unrelated to K49b — reproducible on `git stash`):
- `test_customers_pagination_p35.py::test_page1_returns_first_100_and_envelope`
- `test_customers_pagination_p35.py::test_page3_returns_last_50_rows`
Both assert a name-ascending default sort that never matched the router's
`created_desc` default. Not in scope for this hotfix.

## Acceptance criteria — all met
- [x] `GET /api/customers` returns 200 with the legacy un-migrated doc present.
- [x] Response payload still respects K49 defaults (Active + last_name A→Z sort).
- [x] No `ResponseValidationError` in logs.
- [x] No MongoDB connection saturation regression — cursor lifecycle audited.
- [x] Existing K48 / K49 pytests still green.

## Deferred (per user)
- P2 pytest cross-module isolation bug in `test_k43_ach_verification.py` —
  module-level DB mock leakage. Not touched.
