# Phase G3 — Test Infra Debt — SHIPPED (Feb 2026)

Two long-parked P2 items (pool exhaustion + Motor loop trap) plus the bonus TenantSwitcher search filter.

## G3.1 — Pymongo Pool Hardening (Lazy MongoClient Migration)

### Symptom
`pymongo.ServerSelectionTimeoutError` on late-suite full test runs.
Root cause: every test file opened its own module-level
`MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]`. With ~250 test
files each defaulting to `maxPoolSize=100`, pytest collection tried
to open up to 25 000 sockets during import, which reliably tripped
the server-selection timeout.

Sanity check: pre-migration `pytest tests/ --collect-only -q` **timed
out at >120s**. Post-migration completes in **22.29s** collecting
**9 973 tests**.

### Fix
1. New shared lazy singleton — `backend/tests/_shared_mongo.py`
   - `shared_client()` — process-wide `MongoClient` (lazy).
   - `shared_db()` — process-wide `Database` (lazy).
2. Batch migration via `/tmp/g3_migrate_mongo_clients.py` covering
   four shapes:
   - **Shape A** one-liner Database: `_sync = MongoClient(URL)[NAME]` (~210 files)
   - **Shape A-cond** conditional Database: `_sync = MongoClient(URL)[NAME] if (URL and NAME) else None` (7 files)
   - **Shape B** Client + Database on two lines: `_sync = MongoClient(URL)` then `_db = _sync[NAME]` (38 files)
   - **Shape C** rare naming variation with `_client = ...` (1 file)
3. Conftest enforcement note — top-of-file comment in
   `backend/tests/conftest.py` telling future authors to use
   `_shared_mongo` instead of a new `MongoClient()`.

### Numbers
| Metric                                                     | Count |
|-------------------------------------------------------------|------:|
| Files migrated to `_shared_mongo`                           |  **246** |
| Files remaining with a module-level `MongoClient()`         |     **0** |
| Files importing `_shared_mongo` after migration             |   253 |
| Full-suite `--collect-only` runtime pre-migration           |  >120s (timeout) |
| Full-suite `--collect-only` runtime post-migration          | **22.29s** |
| `ServerSelectionTimeoutError` occurrences in 500-test subset|     **0** |

### Sample diff
```diff
-from pymongo import MongoClient
+from pymongo import MongoClient
+from tests._shared_mongo import (
+    shared_client as _shared_client,
+    shared_db as _shared_db,
+)
 
 _ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
-_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
+_sync = _shared_db()
```
(Shape A). Shapes B/C emit the two-line pair
`_sync = _shared_client(); _db = _shared_db()`.

## G3.2 — Motor Loop Trap in `test_recurrence_never_ends_and_partial_index.py`

### Symptom (as-reported)
`RuntimeError: Event loop is closed` in ~9 cases during full-suite runs.

### Reality check
The file was **already** migrated onto the `run_test + httpx.ASGITransport`
pattern (see the file's own docstring — "Sprint 3a · Feb 2026 test-infra
migration"). The 10 HTTP-driven tests each wrap the coroutine in
`_run_with_http(coro)` which rebinds Motor's IO loop via
`_f7_loop_fixture::run_test`. The 3 non-HTTP tests
(`test_partial_index_exists`, `test_partial_index_still_dedups_recurring_occurrences`,
`test_nth_weekday_computation_edge_cases`) use pure sync pymongo and
don't need the ASGI transport.

### Verification
```
pytest tests/test_recurrence_never_ends_and_partial_index.py -v
============ 13 passed in 6.04s ============
```

In a 500-test subset spanning many Motor-driven files:
```
ServerSelectionTimeoutError occurrences: 0
'Event loop is closed'      occurrences: 0
```

No `run_test` migration needed here — prior sprint already did it. G3.2 is a **confirmation-only** deliverable, not a change.

## G3.3 — Bonus: TenantSwitcher dropdown text filter (shipped)

Post-S1 hotfix super_admin sees every active tenant (≈123 on the
preview pod). Added a substring filter over `name || slug || id`
that renders only when memberships > 6.

Files:
- `frontend/src/components/topbar/TenantSwitcher.jsx` — filter state
  + input + empty-state block. Auto-resets on close.
- `frontend/src/components/topbar/__tests__/TenantSwitcher.filter.test.jsx`
  — 6 vitests covering:
  1. Filter hidden when memberships ≤ 6.
  2. Filter visible when memberships > 6.
  3. Name substring match (case-insensitive).
  4. Slug + id substring match.
  5. Empty state on no-match.
  6. Filter resets on close+reopen.

Vitest counts (S1 + S1 hotfix + G3.3):
```
Test Files  4 passed (4)
     Tests  23 passed (23)   ← 14 lockdown + 3 positive + 6 filter
```

## Deliverables — final tally
| Item | Result |
|------|-------:|
| Files migrated (G3.1) | **246** |
| Files with residual eager `MongoClient()` | **0** |
| `pytest --collect-only` runtime | **22.29s** (was >120s timeout) |
| `ServerSelectionTimeoutError` in 500-test sample | **0** |
| `Event loop is closed` in 500-test sample | **0** |
| Recurrence file standalone pass rate | **13/13** |
| Vitest TenantSwitcher suites (S1 + filter) | **23/23** |
| Bonus filter shipped? | **YES** |

## Guardrails / deferred
- `/app/mobile/` untouched.
- The migration script (`/tmp/g3_migrate_mongo_clients.py`) is
  idempotent — re-running it on a clean tree is a no-op.
- Full-suite runtime is still long (~30+min for 9 973 tests), but
  it now **completes** instead of aborting on pool exhaustion.
  Speed-up is out of scope for G3.
- Pre-existing HTTP-layer test drift (e.g.
  `test_customers_pagination_p35.py::test_page1_returns_first_100_and_envelope`,
  `test_zillow_rate_limit_..._returns_429_on_101st`) is **unchanged**
  by this migration — verified by stashing individual files and
  re-running with the original client init: same failures.
