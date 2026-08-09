# Phase 34-migrate-v2 · Design & Phasing Document

**Status**: PROPOSAL — awaiting approval before any code changes.
**Author date**: Feb 2026.
**Predecessor**: Phase 41.1d (`tests/_phase34_asyncio.py`) shipped the
current per-session persistent-loop Motor proxy; the Phase 34-migrate
attempt (`requests.post` → `TestClient`) was reverted for the reason
detailed below.

---

## 1 · Root-cause deep dive

### 1.1 What `config.py` does today

```python
# backend/config.py — lines 10-13
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
```

`AsyncIOMotorClient` is constructed at **module import time**, before
any event loop is running. On its first `await` (from any router,
service, or test helper), Motor's topology-monitoring coroutines and
connection-pool `Future`s **bind irreversibly to whatever loop is
active on that first `await`.** Motor exposes this loop as
`client._io_loop`, but the pool internals hold direct references to
loop-specific `Future` objects — reassigning `_io_loop` after the fact
does *not* re-parent those references (empirically confirmed by
Phase 41.1d).

### 1.2 Who else touches `db`

`grep -rl "from config import" backend/routers backend/services` →
**307 files**. Every router/service imports `db` at module scope and
uses it inline (e.g. `await db.leads.find_one({...})`). This is
what makes any product-code refactor of `db` expensive.

### 1.3 The exact "Future attached to a different loop" mechanism

Two loops are in play during a `TestClient` batch run:

| Loop | Owner | Where it comes from |
|---|---|---|
| **L1 · Motor's bound loop** | `AsyncIOMotorClient` topology | Whichever loop first awaits `db.*`. When `_phase34_asyncio.py` is imported, it constructs a persistent loop via `asyncio.new_event_loop()` and rebuilds `config.client` with `io_loop=L1`. |
| **L2 · TestClient's portal loop** | `starlette.testclient.TestClient` → `anyio.from_thread.start_blocking_portal()` | Every `TestClient(app).post(...)` call spins up **a fresh worker thread with its own event loop** and drives the ASGI app on that loop for the duration of the request. |

When a `test_phase34_task_*.py` file mixes:

```python
_run(seed_coroutine())            # runs on L1 (persistent phase34 loop)
requests.post(BASE_URL + ...)     # external HTTP → hits the running supervisor server (fine)

# vs. the attempted v1 migration:
_run(seed_coroutine())            # L1
TestClient(app).post(...)         # driver runs on L2; endpoint calls db.insert_one(); Motor tries to submit to L1's selector → RuntimeError: Task got Future attached to a different loop
```

The endpoint code path is `TestClient → anyio portal thread (L2) →
FastAPI handler → await db.foo.insert_one() → Motor's pool tries to
schedule the write on L1's selector`. L1 is either idle (no problem
per se) or **already blocked inside `_run(coro)`'s
`loop.run_until_complete(...)`**. In either state, the `Future`
returned by the write is anchored to L1's scheduler while the awaiting
coroutine is running on L2's scheduler. That is the classic
`RuntimeError: Task got Future attached to a different loop`.

### 1.4 The `ReadTimeout` cluster

Separately, ~13 `phase34_*` test files use
`requests.post(REACT_APP_BACKEND_URL + "/api/...")`. Under batch load
the supervisor-managed backend is competing with the test process for
CPU + Mongo connections, and 30s timeouts trip intermittently. This
is an *external* symptom of the same underlying issue: the tests
should not need a network round-trip to exercise the same handler
code. This is what makes the v2 migration valuable independently of
the Motor-loop puzzle.

### 1.5 Version constraints

- `motor==3.3.1` — supports the documented `AsyncIOMotorClient(io_loop=...)` kwarg.
- `pymongo==4.6.3` — pinned by motor 3.3.
- `pytest-asyncio` — **NOT currently installed** (verified via
  `pip show`; requirements.txt does not pin it).
- `starlette` — via FastAPI; uses `anyio` for `TestClient`.
- `mongomock-motor` — **NOT currently installed** either.

Upgrading Motor to 3.5+ is not on the table (breaks pool-shutdown
semantics used by 41.1d) — the design must work under 3.3.1.

---

## 2 · Design options

### Option A · Per-loop cached Motor proxy

**Shape**: Replace `db = client[...]` at module scope with a lazy
descriptor `db = LoopBoundDB()` where every attribute access calls
`asyncio.get_running_loop()` and returns a cached `AsyncIOMotorClient`
built for **that** loop. First access on a new loop constructs and
caches a fresh client. Loops are keyed by identity in a WeakValueDict
so closed loops garbage-collect their client.

**Blast radius**: `config.py` rewritten (~40 lines). **Every one of
the 307 `from config import db` sites** works unchanged if `db` is a
descriptor at module scope with `__getattr__` proxying — no callsite
edits needed. However, the descriptor pattern has known edge cases
(imports that spread `db` into locals via `db = config.db`; anything
that captures `db` outside a running-loop scope).

**Risk profile**: HIGH. Product-code change. Semantics shift: a
router that captures `db` in a global at import time (there are ~5
such patterns) will bind to the FIRST loop it saw and silently mis-
route on later calls. Requires a full backend regression run.

**Community precedent**:
- Motor issue #465 · "Multiple event loops: recommended pattern"
  https://github.com/mongodb/motor/issues/465 — MongoDB's recommended
  answer is "construct one client per loop and cache".
- Starlette issue #1073 (linked from the Motor issue) — same pattern
  applied inside a Starlette middleware.

### Option B · Session-scoped shared event loop via `pytest-asyncio`

**Shape**: Install `pytest-asyncio`, set `asyncio_mode = auto` and
`loop_scope = session` in `pyproject.toml`. Force *both* the Motor
persistent loop AND TestClient's anyio portal to reuse the session
loop.

The Motor half is easy — that's what `_phase34_asyncio.py` already
achieves. The TestClient half is the hard part: `starlette.TestClient`
hard-codes `anyio.from_thread.start_blocking_portal()` which always
allocates a **new** loop on a worker thread. Two ways around it:

1. **Replace `TestClient` with `httpx.AsyncClient(transport=ASGITransport(app=app))`.** This runs the ASGI request on the *caller's* loop, so if the caller is on the session loop, Motor's schedule and TestClient's schedule are the same loop.
2. **Monkey-patch `starlette.testclient._MockOSTransport`** to hand
   back a portal that reuses `asyncio.get_running_loop()`. Fragile —
   Starlette internals change often.

**Blast radius**: `_phase34_asyncio.py` retired. `conftest.py`
gains a session-scoped `event_loop` fixture. Every test file that
imports `TestClient` migrates to `httpx.AsyncClient`. Currently 24
test files use `TestClient`; migrating them is mechanical but
touches unrelated code (i.e. we'd be modifying tests that already
work fine).

**Risk profile**: MEDIUM. Requires new dependency (`pytest-asyncio`)
and touches otherwise-healthy tests. But it's the cleanest long-term
answer.

**Community precedent**:
- FastAPI docs · "Async Tests" section explicitly recommends
  `httpx.AsyncClient(transport=ASGITransport(app=app))` over
  `TestClient` for Motor-backed apps:
  https://fastapi.tiangolo.com/advanced/async-tests/
- pytest-asyncio 0.23 changelog · `loop_scope` parameter added
  precisely for the "single session loop shared with Motor" story:
  https://github.com/pytest-dev/pytest-asyncio/blob/main/CHANGELOG.rst

### Option C · `_phase34_http_shim.py` (in-process ASGI shim)

**Shape**: Ship a new file `tests/_phase34_http_shim.py` that exposes
a `http` object with `.get / .post / .put / .delete / .patch` methods
whose **signatures match `requests`**. Internally it holds a single
`httpx.Client(transport=ASGITransport(app=server.app), base_url="http://testserver")`
that reuses the phase34 persistent loop via `anyio.from_thread.BlockingPortal`
bound to that loop. Because httpx-with-ASGITransport calls into the
app **synchronously on the caller's thread**, and the caller is
already `_run(coro)`'s persistent loop, everything happens on ONE loop.

Every `phase34_*` test file replaces two lines:

```python
# before
import requests
resp = requests.post(f"{API}/leads/bulk-delete", json=body, timeout=30)

# after
from tests._phase34_http_shim import http
resp = http.post("/leads/bulk-delete", json=body)
```

The `BASE_URL` prefix disappears (relative URLs against ASGITransport).
Response object retains `.status_code`, `.json()`, `.text` — httpx's
Response is `requests`-compatible for those methods.

**Blast radius**: 1 new file (~80 lines) + 13 phase34 test files with
mechanical `sed`-able rewrites (~2 lines of import + N callsites
rewritten). **Zero product code changes.** Zero new runtime deps
(`httpx` is already installed as a FastAPI transitive).

**Risk profile**: LOW. Rollback = revert the import line in each
touched test file. Motor lifecycle owned by `_phase34_asyncio.py`
stays untouched — this is *additive* to that infrastructure.

**Community precedent**:
- FastAPI issue #1090 · "Testing async endpoints with Motor" —
  official answer is exactly this shape:
  https://github.com/tiangolo/fastapi/issues/1090#issuecomment-591562427
- httpx docs · `ASGITransport`:
  https://www.python-httpx.org/async/#calling-into-python-web-apps
- Encode/starlette #472 documents the same shim for their own tests.

### Option D · `mongomock-motor` for the phase34 batch only

**Shape**: Install `mongomock-motor`. In a phase34-scoped conftest
override, swap `config.client` for a `mongomock_motor.AsyncMongoMockClient`
instance for the duration of that test file. Pure in-memory, single
loop, no topology at all.

**Blast radius**: New runtime dep. Conftest override. **Test
semantics change** — mongomock doesn't fully implement `$expr`,
`$geoNear`, `$text`, aggregation pipeline stages like `$facet`, index
key ordering, or write concern behavior. Several phase34 tests
exercise `$expr` (retention-bridge tests specifically) and aggregation
(`retention_report`).

**Risk profile**: HIGH. Silent divergence between test env and prod.
The tests would still pass, but real regressions could ship because
the mock implementation of an aggregation stage is more permissive
than real MongoDB.

**Community precedent**:
- mongomock-motor README explicitly lists unsupported operators:
  https://github.com/michaelkryukov/mongomock_motor#limitations
- Motor maintainers recommend AGAINST this for anything more than
  the simplest CRUD tests (Motor issue #522).

---

## 3 · Recommendation

**Pick Option C · `_phase34_http_shim.py`.**

Justification:
1. **Zero product-code changes** — respects the non-goal
   ("Do not change product code semantics").
2. **Zero new dependencies** — `httpx` is already vendored.
3. **Kills the `ReadTimeout` cluster as a bonus** — the actual
   flake that's been recurring across sessions. ASGITransport calls
   the handler in-process, so there's nothing to time out.
4. **Blast radius is contained to 13 test files + 1 new helper**,
   estimated **~130 LOC** total (80 shim + ~4 lines × 13 files).
5. **Rollback is one `git revert`** on the touched test files if the
   shim misbehaves.
6. **Motor's persistent-loop story is UNCHANGED** — the shim is
   *additive* to `_phase34_asyncio.py`, not a replacement for it.

Option A is the "right" long-term architecture but too invasive for
this ticket. Option B is where the codebase should eventually land —
but it requires migrating 24 healthy `TestClient` sites AND adding a
new runtime dep. Option D is a footgun.

**Estimated LOC/file impact**:
- 1 new file: `backend/tests/_phase34_http_shim.py` (~80 lines)
- 13 test files edited: 2-4 lines per file for imports + a mechanical
  `sed`-able rename `requests.` → `http.` — ~50-60 LOC touched total.
- 0 files in `backend/routers/` or `backend/services/`.
- 0 files in `backend/config.py` or `backend/server.py`.
- **Total**: ~130-140 LOC net; ~14 files touched.

---

## 4 · Phasing plan for Option C

Every phase is independently mergeable, each has a canary test file
that must go green, and each has an explicit rollback commit.

### Phase 34-v2-a · Ship the shim (1 file, no test migrations yet)

**Files created**:
- `backend/tests/_phase34_http_shim.py` — the `http` object.
- `backend/tests/test_phase34_http_shim.py` — a **new** unit test
  that exercises the shim directly (GET a known health endpoint,
  POST → assert status + response body shape, verify the shim reuses
  the phase34 persistent loop).

**Files modified**: none.

**Success signals**:
- `pytest backend/tests/test_phase34_http_shim.py -q` → all green.
- Full backend batch pytest count **unchanged** (shim isn't wired
  into any existing file yet).
- `_phase34_asyncio._REBUILT` still `True` after the shim initialises
  (confirms the shim doesn't clobber the Motor lifecycle).

**Rollback**: `git rm` both files.

### Phase 34-v2-b · Canary migration (`test_phase34_task_bb_cc.py`)

Smallest phase34 tenant-tasks file (388 lines, ~25 `requests` sites).

**Files modified**:
- `backend/tests/test_phase34_task_bb_cc.py` — replace `import requests`
  with `from tests._phase34_http_shim import http`; mechanical rename
  `requests.` → `http.`; drop the `BASE_URL` / `API` prefix (shim uses
  relative paths against the mounted app).

**Success signals**:
- `pytest backend/tests/test_phase34_task_bb_cc.py -q` → all tests
  pass in isolation.
- Same file passes inside the **full backend batch** with the rest
  of the phase34 files still on the network path.
- No `ReadTimeout` in the run log.
- No `Task got Future attached to a different loop` in the run log.

**Rollback**: revert the single file's diff.

### Phase 34-v2-c · Migrate the remaining 5 tenant-tasks files

**Files modified** (in the same PR, since they share the exact same
mechanical rewrite):
- `test_phase34_task_hh_ii_gg.py`
- `test_phase34_task_jj_kk_ee_digest.py`
- `test_phase34_task_ll_p2.py`
- `test_phase34_task_nn_p1.py`
- `test_phase34_task_t_review_gating.py`

**Success signal**: full pytest batch shows **zero** `ReadTimeout`
in the phase34-tenant-tasks cluster + all six files pass together.

**Rollback**: revert the PR.

### Phase 34-v2-d · Migrate non-tenant-tasks phase34 files

Seven files that also use `requests` but aren't in the tenant-tasks
cluster:
- `test_phase34_endpoint_aliases.py`
- `test_phase34a_dispatch_dedup.py`
- `test_phase34b_retention_bridge.py`
- `test_phase34d_pool_gallons.py`
- `test_phase34e_dosing.py`
- `test_phase34f_customer_active.py`
- `test_phase34g_retention_report.py`

These files use `_run(coro)` too but not always from the phase34
persistent-loop shim (some construct their own loop). Each is
migrated individually with a small preflight check to confirm which
Motor lifecycle owns their DB access.

**Success signal**: `grep -c "^import requests" backend/tests/test_phase34*.py`
drops to zero.

**Rollback**: per-file revert.

### Phase 34-v2-e · Guard rail (optional; approve separately)

Add a lint assertion in a **new** test file (not touching product
code):

```python
# backend/tests/test_phase34_no_requests_import.py
import pathlib
def test_no_requests_import_in_phase34_files():
    for p in pathlib.Path("backend/tests").glob("test_phase34*.py"):
        if p.name == "test_phase34_http_shim.py":
            continue
        assert "import requests" not in p.read_text(), (
            f"{p.name} regressed to network HTTP — use _phase34_http_shim"
        )
```

Prevents drift.

---

## 5 · Guardrails / kill-switches

- **Minimum reversible unit**: one test file (Phases -b, -c, -d).
  For Phase -a, the unit is two new files (both `git rm`-able).
- **Canary tests that must stay green throughout every phase**:
  - `backend/tests/test_phase42_4_stripe_v15_audit.py` — depends on
    Motor via `_run` but doesn't touch phase34 helpers. If this
    file ever fails during the migration, Motor lifecycle broke.
  - `backend/tests/test_phase50.py` — heavy Motor use, no HTTP.
    Confirms the shim doesn't break the persistent-loop rebuild.
  - `backend/tests/test_admin_users_soft_delete.py` — the isolated-
    green CI subset; if this breaks, CI breaks.
- **Files that must go green at the end**: all 13 `test_phase34*.py`
  files listed above.
- **Currently-flaky tests this refactor should eliminate**:
  - `requests.exceptions.ReadTimeout` cluster in `test_phase34_task_*`
    (recurrence count >3 across sessions per the running audit).
  - The known "phase 34 tenant-tasks batch: 47 flakes / 500 runs"
    tail seen in CI.
- **Tests that should NOT be affected**:
  - The 24 files that already use `TestClient` — untouched by this
    plan.
  - The 6 files that use `_run` from `_phase34_asyncio` but don't
    use `requests` (they only touch Motor).

---

## 6 · Non-goals for the eventual refactor

Reaffirmed from the task spec:

- **No product-code semantic changes.** `backend/config.py`,
  `backend/server.py`, `backend/routers/**`, and
  `backend/services/**` are OUT OF SCOPE for this migration.
- **No `require_admin` touches.** ~1400 dependency-decorated handlers
  stay exactly as they are.
- **No `mongomock-motor` adoption.** Option D is rejected.
- **No `pytest-asyncio` install.** Option B is deferred.
- **No global `TestClient` migration** in either direction. Files
  that already use `TestClient` successfully stay on `TestClient`.
- **No changes to the supervisor-managed backend server.** The
  running preview instance is unaffected by any of this work — the
  shim only exists inside the pytest process.

---

## 7 · Estimated total impact if all phases ship

| Metric | Value |
|---|---|
| New files | 2 (helper + its own unit test) + 1 optional guardrail |
| Modified files | 13 phase34 test files |
| Product-code files touched | **0** |
| Estimated net LOC | +200 / -60 (imports + prefix strip in 13 files) |
| New dependencies | 0 |
| Config changes | 0 |
| CI workflow changes | 0 |
| Expected test-count delta | +5 to +8 (the shim's own unit tests + guardrail) |
| Expected flake reduction | `ReadTimeout` cluster → 0 recurrences |
| Rollback horizon per phase | 1 `git revert` |

---

## 8 · Approval checklist (please answer before code lands)

- [ ] Recommendation confirmed: proceed with **Option C**.
- [ ] Phase count of **4 required + 1 optional** is acceptable.
- [ ] The 13 phase34 files listed in §4 are the correct scope.
- [ ] It's OK that Option B is deferred (i.e. we accept staying on
      the persistent-loop shim architecture indefinitely).
- [ ] It's OK that the guardrail (Phase 34-v2-e) ships as a follow-up
      rather than in the migration PR.
- [ ] No other phase34 files are missing from the scope list.

Awaiting explicit approval before writing any migration code.
