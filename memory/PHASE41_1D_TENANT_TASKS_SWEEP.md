# Phase 41.1d — Motor Loop Rebind for Full-Batch Isolation

**Date:** 2026-02
**Verdict:** LANDED — verified by testing subagent (`/app/test_reports/iteration_19.json`).

---

## 1. Fix Approach Chosen

**Hybrid (a) + (b) + (c):** A per-test `pytest_runtest_setup` hook in `backend/tests/conftest.py` **plus** a session-persistent event loop + fresh Motor client rebuild in a dedicated helper `backend/tests/_phase34_asyncio.py` that fires at **import time** (not first-call time). The helper owns Motor lifecycle for the six Phase 34 tenant-tasks test files; the conftest hook defers to the helper (via `_REBUILT` flag) and otherwise handles Motor rebind for every other test in the batch.

**Rationale:** the pure session-scoped autouse fixture (option a) alone breaks unrelated tests that assume `asyncio.get_event_loop()` returns a fresh loop each time. The pure per-test rebind (option b) alone runs too late for module-scoped `db()` fixtures that cache a stale `config.db` reference before their tests run. The import-time rebuild in `_phase34_asyncio.py` fires before any fixture resolves, and the conftest hook keeps the shared Motor client valid for the rest of the batch. See both files' inline docstrings for the full reasoning.

## 2. Files Touched

| File | Purpose |
|---|---|
| `backend/tests/conftest.py` (+61 lines) | Added `pytest_runtest_setup` hook `_phase41_1d_ensure_motor_loop()`. Ensures current thread has an open loop, defers to the helper if `_phase34_asyncio._REBUILT` is set, otherwise rebinds `config.client._io_loop` to the current loop. Idempotent, one attribute write per test. |
| `backend/tests/_phase34_asyncio.py` (NEW, ~100 lines) | Session-persistent `_MODULE_LOOP` (never closed). `_rebuild_motor_client_on_loop(loop)` replaces `config.client` with a fresh `AsyncIOMotorClient(mongo_url, io_loop=loop)` and repoints `config.db`. Rebuild runs at import time (before `db()` fixture caches). `batch_safe_run(coro)` drives coroutines on the persistent loop. |
| `backend/tests/test_phase34_task_bb_cc.py` | Replaced local `def _run(coro): asyncio.get_event_loop()...` with `from tests._phase34_asyncio import batch_safe_run as _run`. |
| `backend/tests/test_phase34_task_hh_ii_gg.py` | Same swap. |
| `backend/tests/test_phase34_task_jj_kk_ee_digest.py` | Same swap. |
| `backend/tests/test_phase34_task_ll_p2.py` | Same swap. |
| `backend/tests/test_phase34_task_nn_p1.py` | Same swap. |
| `backend/tests/test_phase34_task_t_review_gating.py` | Same swap. Also: replaced inline `asyncio.get_event_loop().run_until_complete(_go())` in `demo_customer_id` fixture with `_run(_go())`. |

**No changes to:**
- Phase 41.1c seed-drift fixture, Phase 46 RC guard, Phase 42.4 Stripe audit code, or any Phase 49/50/50.1/50.2 code.
- Any tenant-tasks runtime code — no real runtime bug surfaced.
- Any of the three prior hotfixes: `/api/config/public` (backend), `/portal/login` (frontend), `/api/stripe/webhook` alias.

## 3. `phase34_task_*` Cluster: Before → After

| Metric | Before 41.1d | After 41.1d |
|---|---:|---:|
| Solo run (all 6 files) | 127 passed (transient 1 pre-existing date-arithmetic failure) | **127 passed** ✅ |
| Full-batch failures in the phase34_task_* cluster | 69 | **69** (unchanged) |

**Verdict on the phase34_task cluster:** the 69 in-batch failures **remain**, but the root cause is **NOT** Motor loop bleed — main-agent investigation and testing subagent confirm they are `httpx.ReadTimeout` errors from `requests.post(preview_url, ...)` inside module-scoped `super_headers` fixtures under batch load. This is a different failure mode (preview-URL saturation) that requires porting the tests from `requests` → FastAPI `TestClient` — that's Phase 41.5b/c territory. Not fixable at the Motor-rebind layer.

## 4. Full Backend Batch: Before → After

Curated CI batch (`-m "not live and not destructive and not legacy_iteration" --ignore-glob=test_stripe_phase* --ignore-glob=test_phase47c_*`):

| Metric | Before 41.1d | After 41.1d | Δ |
|---|---:|---:|---:|
| Passed | 3291 | **3337** | **+46** |
| Failed | 249 | **210** | **−39** |
| Errors | 86 | 81 | −5 |

Testing subagent confirms: `−39 failures, +46 passes` net improvement. The improvement came from **other** clusters (~40 tests that WERE suffering the Motor loop bleed the fix addresses), not from the phase34_task cluster itself.

## 5. Suites Green

Per testing subagent verification (`iteration_19.json`, all confirmed on live preview URL):

| Gate | Result |
|---|---|
| Solo `phase34_task_*` (6 files) | **127 / 127 passed** ✅ |
| Backend curated coverage gate | **155 / 157 passed**, coverage **23.35%** (floor 2%) — **PASS** ✅ |
| Frontend Vitest | **1272 / 1272 passed** ✅ |
| Mobile Jest | **132 / 132 passed** ✅ |
| Frontend ESLint `--max-warnings=0` | exit **0** ✅ |
| `/api/config/public` (Hotfix #1) | 200 `{show_demo_logins, app_env}` ✅ |
| `/portal/login` variant (Hotfix #2) | Tiles hidden ✅ |
| `/api/stripe/webhook` alias (Hotfix #3) | 400 (was 404) ✅ |
| `/api/payments/stripe/webhook` primary (Hotfix #3) | 400 ✅ |

Note on the 2 flaky tests in the coverage gate: `test_ae3_tenant_scoping_no_cross_tenant_data` fails solo too (asserts `total_deals==200`, gets `212` due to residual TEST_-tagged Mongo data from prior sessions — pre-existing, not a 41.1d regression). `test_common_event_types_return_2xx[payment_intent.succeeded]` is batch-flaky, passes solo. Both confirmed pre-existing by testing subagent.

## 6. Residual Failures + Recommended Next Phase

| Cluster | Failures | Root cause | Recommended phase |
|---|---:|---|---|
| **6× `phase34_task_*` in full batch** | ~69 | HTTP `ReadTimeout` from `requests.post(preview_url, ...)` in module-scoped `super_headers` fixtures under batch load. NOT Motor loop bleed. | **Phase 41.5b/c** — port these tests from `requests` → FastAPI `TestClient` (in-process, no network I/O). |
| Stripe RBAC / Phase 47c batch clusters | ~76 | Stripe mock hook lifecycles leak. | **Phase 47c/48b** (already queued). |
| Preview-URL localhost timeouts (misc HTTP tests) | ~9 | `requests.post("localhost:8001", ...)` race under batch. | Same as above — port to `TestClient`. |
| Pymongo `ServerSelectionTimeoutError` | ~35 errors | Mongo connection-pool starvation during full-batch collection. | Environmental / non-code. Consider `pytest-xdist` tuning or a session-scoped pool. |
| Data-drift schema failures (`test_comms_backend` `code` key, `test_phase55_notifications` `push` field, `test_ae3_tenant_scoping` count 212 vs 200) | ~3 | Test schemas out of date vs current API + residual TEST_-tagged data. | Trivial follow-up micro-phase. Not blocking. |

## 7. Guardrails Confirmed Held

- ✅ Three prior hotfix code paths untouched (verified by testing subagent live-URL curl).
- ✅ No Phase 49/50/50.1/50.2/41.1b/41.1c/41.2/41.3/41.4/41.5/42.4/43/46 code touched.
- ✅ No Stripe / Mapbox / Time-Off / RingCentral runtime code touched.
- ✅ No tenant-tasks router/service code touched — no real runtime bug surfaced.
- ✅ Motor's `_io_loop` mutation is confined to the pytest process. The running backend server (separate supervisor-managed interpreter) is entirely unaffected.
- ✅ Vitest 1272/1272, Mobile Jest 132/132, `yarn lint` exit 0, backend coverage gate PASS.

**End of Phase 41.1d report.**
