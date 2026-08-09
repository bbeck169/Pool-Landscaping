# Phase 34-migrate · Feb-2026 — HTTP ReadTimeout cluster (PAUSED — surfaced)

## Executive summary

**Status: PAUSED per guardrail.** The lightweight ``requests`` →
``TestClient`` shim approach was tried and **reverted** because it
exposes a preexisting Motor + event-loop isolation defect (Phase
41.1d ``Future attached to a different loop``). No runtime code was
patched. The full test batch is back to the pre-migration state.

Recommendation: defer this migration to a proper Phase 34-migrate-v2
that does BOTH the transport swap AND the Motor-loop isolation
refactor together (~2× the scope of this ticket). Details below.

## What was tried

1. Enumerated the ``phase34_task_*`` cluster — **14 files, 162 tests
   total**. Only **6 files use ``requests``** (108 tests); the other
   8 already use in-process helpers.

   | File | HTTP-using tests |
   |------|-----:|
   | `test_phase34_task_bb_cc.py` | 21 |
   | `test_phase34_task_hh_ii_gg.py` | 27 |
   | `test_phase34_task_jj_kk_ee_digest.py` | 24 |
   | `test_phase34_task_ll_p2.py` | 6 |
   | `test_phase34_task_nn_p1.py` | 22 |
   | `test_phase34_task_t_review_gating.py` | 8 |
   | **Total** | **108** |

2. Built a minimal shim `tests/_phase34_http_shim.py` that exposes a
   ``requests``-shaped facade backed by
   ``fastapi.testclient.TestClient(app)``. The shim maps:
   - `requests.post(url, json=..., headers=..., timeout=30)` →
     `TestClient(app).post(strip_origin(url), json=..., headers=...)`
   - `timeout` silently dropped (in-process, nothing to time out on).
   - `allow_redirects` → `follow_redirects` compat rewrite.
   - `requests.exceptions.ReadTimeout` sentinel class exposed for
     any caller that catches it.

3. Applied a single-line import swap to all 6 files:
   ```
   -import requests
   +from tests import _phase34_http_shim as requests
   ```
   That's the entire migration diff — every call site continued to
   work by name, no assertion changes needed.

## Why it doesn't work

Running the migrated suite immediately trips **every** test at the
`_login()` fixture:

```
RuntimeError: Task <Task pending ...> got Future <Future pending ...>
attached to a different loop
```

Root cause — the same Phase 41.1d defect flagged multiple times in
prior memos:

- ``config.py`` creates ``db = AsyncIOMotorClient(...)[DB_NAME]`` at
  import time. The Motor client binds itself to whatever event loop
  first ``await``s against it. In the running-server case this is
  the uvicorn worker's loop.
- `TestClient(app)` under the hood runs `starlette.testclient.run`
  which spins up **a fresh loop per request** via `anyio.from_thread`.
- The auth-login endpoint eventually reads `db.users.find_one(...)`.
  Motor tries to complete the ``find_one`` on its bound (uvicorn)
  loop, which isn't running inside the test process → the future
  never resolves and starlette wraps the timeout as the "different
  loop" runtime error.

This is a **test-infra incompatibility**, not a runtime bug. The
production HTTP path (async client → uvicorn → single-loop Motor)
works perfectly. Every migrated test hits this the moment it touches
the db.

## Why the fix is bigger than "just swap transport"

Making TestClient viable for this cluster requires all three of:

1. **Rebind Motor per-test-loop** — either replace `config.db` with
   a lazy accessor that returns an `AsyncIOMotorClient` bound to
   `asyncio.get_event_loop()`, or migrate every router that reads
   `config.db` to a FastAPI ``Depends(get_db)`` injection so
   TestClient can swap in a fresh client per request.
2. **Wrap tests with `pytest-asyncio` + `asyncio_mode = "auto"`**
   so the fixtures + assertions share the same event loop as the
   ASGI app.
3. **Actually swap `requests` → `TestClient`** — the tiny part.

Steps 1–2 are cross-cutting refactors: `config.db` is imported at
module scope by ~180 files across `backend/routers/`,
`backend/services/`, and every existing test. Doing it safely is a
dedicated 2-3 day mini-phase, not a same-slice extension of this
ticket.

## Alternative surface I evaluated + rejected

* **`httpx.AsyncClient(app=fastapi_app)` via `pytest-asyncio`.**
  Same Motor-loop conflict — the async client also runs in a fresh
  test-owned loop, distinct from Motor's bound loop.
* **`httpx.AsyncClient(base_url="http://localhost:8001")` (real
  HTTP).** Doesn't fix ReadTimeouts — it's the same transport model
  the tests already use, just with `httpx` instead of `requests`.
* **Retry/backoff on the login helper.** Papers over the flake
  instead of fixing the transport, and the ingress-side ReadTimeout
  isn't limited to `/auth/login` — happens on any preview-URL POST
  under load.

None of these dodge Motor's loop binding without one of the
cross-cutting refactors listed above.

## Current test-batch state (post-revert)

Isolation runs still pass fully:

- `test_phase34_task_bb_cc.py`               → 21/21 (0.7s)
- `test_phase34_task_hh_ii_gg.py`            → 27/27 (~15s)
- `test_phase34_task_jj_kk_ee_digest.py`     → 24/24 (~10s)
- `test_phase34_task_ll_p2.py`               →  6/6  (~2s)
- `test_phase34_task_nn_p1.py`               → 22/22 (~8s)
- `test_phase34_task_t_review_gating.py`     →  8/8  (~4s)

Batched runs still exhibit transient ReadTimeouts (~40 error-at-setup
under load) — the same behavior that motivated this ticket. No delta
from baseline; nothing was made worse.

Full baseline (isolation, unchanged):
- Vitest **1469/1469** ✅
- Mobile Jest **271/271** ✅
- `yarn lint` exit 0 ✅

## Files touched (final state after revert)

*None.* Every file returns to its pre-Phase-34-migrate state. The
shim + migrated imports were reverted at the same commit level.

## Recommendation for Phase 34-migrate-v2

Bundle these three changes together into a discrete follow-up phase
(estimated 2-3 days engineering):

1. Add `backend/config_db.py::get_db()` — a per-loop cached Motor
   accessor keyed on `id(asyncio.get_event_loop())`. Existing
   `config.db` becomes a lazy proxy that calls `get_db()` on
   attribute access.
2. Add `backend/tests/conftest.py::_scope_asyncio` — pytest-asyncio
   session-mode config so fixtures inherit the ASGI-app loop.
3. Add `tests/_in_process_client.py` — the exact shim from this
   attempt, but promoted from experimental to canonical.
4. Migrate the 6 phase34_task_* files. Same one-line import diff
   as this attempt, plus module-scope `@pytest.mark.asyncio` mark
   for the login fixture.

Scope compare:
- Phase 34-migrate (this ticket): ~10 lines of test infra + 6 import
  swaps.
- Phase 34-migrate-v2 (recommended): the above + touching
  `config.py` + every router import path that reads `config.db`.

## Deviations from scope

Per the ticket guardrail — "**If any file exposes a runtime bug
during migration (not a transport issue), PAUSE and surface — do NOT
silently patch runtime.**" — this memo IS the surface. Nothing was
patched, nothing was hidden. The lift is bigger than the ticket
budgets; kicking to v2 keeps this MVP-lean.
