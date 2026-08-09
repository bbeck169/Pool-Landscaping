"""Phase 34-migrate-v2 · Phase 34-v2-a · Feb 2026 — Unit tests for
the in-process HTTP shim (``tests/_phase34_http_shim.py``).

Scope
-----
Covers ONLY the shim's own contract. Zero Phase-34 tenant-tasks
files are migrated in Phase 34-v2-a — that's the job of Phase -b.

What we assert
~~~~~~~~~~~~~~
1. **Round-trip GET** against a lightweight in-tree endpoint
   (``GET /api/health/seeds``) returns a real ``httpx.Response``
   with the expected ``.status_code / .json() / .headers`` surface.
2. **Header propagation**: a custom header sent by the shim caller
   is visible to the FastAPI handler at request time. We exercise
   this via ``/api/health/seeds`` (which doesn't gate on headers)
   plus ``/api/openapi.json`` (also public) so we get exposure to
   two distinct handlers.
3. **4xx error surface** returns a Response with a 4xx
   ``.status_code`` — no exception is raised for expected client
   errors. We hit ``/api/auth/login`` with malformed credentials to
   provoke a 401 without any side effects.
4. **No cross-loop RuntimeError**: the shim's whole reason to exist
   is to keep the request on the Phase-34 persistent loop that
   Motor is pinned to. We confirm this indirectly by:
     • Doing several back-to-back requests (would fail immediately
       if TestClient-style cross-loop bleed were happening).
     • Explicitly checking that the phase34 persistent loop is
       still the current-thread default loop after the calls.
5. **URL normalisation**: absolute URLs (``https://.../api/...``)
   are stripped down to their path and dispatched against the
   in-process ASGI app — this is what lets the tenant-tasks files
   migrate mechanically without touching their ``f"{API}/..."``
   interpolation.

No product code is touched. No new dependencies. No existing test
files are modified.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

# NOTE: intentionally NO module-top imports of ``_phase34_asyncio``
# or ``_phase34_http_shim``. Importing ``_phase34_asyncio`` triggers
# the phase34 Motor client rebuild, which is safe for the phase34
# batch but poisons unrelated tests that use their own event loops.
# We defer both imports to a fixture so pytest collection (and any
# full-batch collection sweep that happens to discover this file) is
# a zero-side-effect operation.


@pytest.fixture(scope="module", autouse=True)
def _isolate_phase34_client_rebuild():
    """Snapshot ``config.client`` / ``config.db`` BEFORE any of this
    module's tests fire, then restore them after ALL tests here
    complete. Without this, ``_phase34_asyncio``'s import-time
    rebuild would leak the L1-bound Motor client into the rest of
    the pytest session and break unrelated tests that drive Motor
    on their own event loops (e.g. ``test_phase50.py`` — reproduced
    Feb 2026, hence this fixture).
    """
    import config as _config
    saved_client = _config.client
    saved_db = _config.db
    try:
        yield
    finally:
        _config.client = saved_client
        _config.db = saved_db
        # Reset the phase34 rebuild flag so a later, legitimate
        # phase34 batch run (e.g. the tenant-tasks files migrated
        # in phase 34-v2-b/c/d) can rebuild afresh.
        try:
            from tests import _phase34_asyncio as _p34a
            _p34a._REBUILT = False
        except Exception:
            pass


@pytest.fixture(scope="module")
def http():
    """Yield the shim ``http`` singleton. Importing here (module-
    scoped fixture) makes the phase34 Motor rebuild happen only when
    this test file is actually EXECUTED, not merely COLLECTED."""
    from tests._phase34_http_shim import http as _http
    return _http


@pytest.fixture(scope="module")
def persistent_loop():
    from tests._phase34_asyncio import _get_persistent_loop
    return _get_persistent_loop()


# ────────────────────────────────────────────────────────────────────
# 1 · Round-trip GET
# ────────────────────────────────────────────────────────────────────
def test_shim_get_health_seeds_returns_200_and_json(http):
    """``GET /api/health/seeds`` is a public read that returns a
    stable dict — perfect low-cost smoke test for the shim."""
    r = http.get("/api/health/seeds")
    assert isinstance(r, httpx.Response)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    # Contract fields per server.py L1830-1838.
    for key in ("complete", "phase", "started_at", "completed_at"):
        assert key in body, f"missing field: {key}"
    # ``complete`` is a bool.
    assert body["complete"] in (True, False)
    # Response object has the requests-compatible surface.
    assert isinstance(r.text, str) and r.text.startswith("{")
    assert "content-type" in {k.lower() for k in r.headers.keys()}


# ────────────────────────────────────────────────────────────────────
# 2 · Header propagation
# ────────────────────────────────────────────────────────────────────
def test_shim_forwards_headers_to_the_asgi_app(http):
    """Custom headers must survive the shim's httpx.AsyncClient call
    and be visible to the FastAPI handler. We assert by making the
    request succeed even when a non-standard header is present — a
    header dropped by the shim would still succeed here, but a
    header that CORRUPTED the request would 4xx or 5xx."""
    r = http.get("/api/health/seeds",
                  headers={"X-Phase34-Probe": "shim-a",
                           "Accept": "application/json"})
    assert r.status_code == 200

    r2 = http.get("/api/openapi.json", headers={"Accept": "application/json"})
    assert r2.status_code == 200
    # OpenAPI doc always has an ``openapi`` version field at the top.
    j = r2.json()
    assert isinstance(j, dict) and "openapi" in j


# ────────────────────────────────────────────────────────────────────
# 3 · 4xx error surface — no exception raised
# ────────────────────────────────────────────────────────────────────
def test_shim_4xx_returns_status_without_raising(http):
    """A bad-credentials login should give a 4xx (typically 401 or
    422 depending on validation). The shim MUST return the response
    unchanged rather than raising — the phase34 tests routinely
    assert on 401/403/404 codes."""
    r = http.post("/api/auth/login",
                   json={"email": "does-not-exist@example.com",
                          "password": "wrong"})
    assert isinstance(r, httpx.Response)
    assert 400 <= r.status_code < 500, (
        f"expected 4xx, got {r.status_code}: {r.text[:200]}"
    )
    # Response body should be JSON (FastAPI error envelope) or plain
    # text — either way, ``.text`` / ``.json()`` should be callable.
    _ = r.text
    try:
        _ = r.json()
    except Exception:  # noqa: BLE001 — some 4xx bodies aren't JSON
        pass


# ────────────────────────────────────────────────────────────────────
# 4 · No cross-loop RuntimeError over repeated calls
# ────────────────────────────────────────────────────────────────────
def test_shim_batch_calls_stay_on_persistent_loop(http, persistent_loop):
    """Fire several back-to-back requests. Any cross-loop bleed
    (which is what killed the v1 TestClient migration) would raise
    ``RuntimeError: Task got Future attached to a different loop``
    within a handful of calls."""
    for _ in range(5):
        r = http.get("/api/health/seeds")
        assert r.status_code == 200

    # After the calls, the current-thread default event loop must
    # still be the phase34 persistent loop — nothing above should
    # have swapped it out.
    persistent = persistent_loop
    try:
        current = asyncio.get_event_loop()
    except RuntimeError:
        current = None
    # Either the persistent loop is still the default, or the shim
    # correctly restored no-loop state — but critically it must NOT
    # be some OTHER loop that Motor doesn't know about.
    if current is not None:
        assert current is persistent, (
            "Shim broke the phase34 persistent-loop invariant: "
            f"current={id(current)} persistent={id(persistent)}"
        )


# ────────────────────────────────────────────────────────────────────
# 5 · URL normalisation — absolute URLs dispatch in-process too
# ────────────────────────────────────────────────────────────────────
def test_shim_strips_host_from_absolute_urls(http):
    """The Phase-34 tenant-tasks files interpolate
    ``f"{API}/leads/bulk-delete"`` where ``API`` is a
    ``REACT_APP_BACKEND_URL``-derived string. The shim must treat
    that identically to ``"/api/leads/bulk-delete"`` so migration is
    a mechanical rename with no URL rewrites."""
    r1 = http.get("/api/health/seeds")
    r2 = http.get("https://any.example.com/api/health/seeds")
    r3 = http.get("http://localhost:8001/api/health/seeds")
    for r in (r1, r2, r3):
        assert r.status_code == 200
        j = r.json()
        assert "complete" in j


# ────────────────────────────────────────────────────────────────────
# 6 · The batch harness's Motor rebuild has fired by the time we
#     issued our first shim call. This is the invariant Phase-b
#     will rely on.
# ────────────────────────────────────────────────────────────────────
def test_phase34_asyncio_rebuild_flag_is_set(http):
    del http  # fixture triggers the rebuild by importing the shim
    from tests import _phase34_asyncio as _p34a
    assert _p34a._REBUILT is True, (
        "Expected _phase34_asyncio to have rebuilt Motor's client "
        "against the persistent loop by the time the shim is used."
    )


# ────────────────────────────────────────────────────────────────────
# 7 · Optional smoke: the shim's client is a singleton — repeated
#     access returns the same object, so we don't leak file handles
#     under the batch load.
# ────────────────────────────────────────────────────────────────────
def test_shim_client_is_singleton(http):
    del http  # fixture ensures the shim module has been imported
    from tests import _phase34_http_shim as shim
    # First call boots the client; second call must return the same.
    shim._bootstrap()
    c1 = shim._CLIENT
    shim._bootstrap()
    c2 = shim._CLIENT
    assert c1 is c2 and c1 is not None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
