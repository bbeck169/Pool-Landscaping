"""Phase 34-migrate-v2 · Phase 34-v2-a · Feb 2026 — in-process HTTP
shim for the Phase 34 test batch.

Why this exists
---------------
Phase 41.1d (``_phase34_asyncio.py``) pinned Motor's ``AsyncIOMotorClient``
to a session-persistent event loop (L1) so the six Phase-34 tenant-tasks
test files could seed data via ``_run(coro)`` without hitting
``RuntimeError: Task got Future attached to a different loop``.

The v1 migration attempt swapped ``requests.post(preview_url, ...)`` for
``TestClient(app).post(...)``. That reverted because
``starlette.testclient.TestClient`` uses
``anyio.from_thread.start_blocking_portal()`` which allocates a **new
worker-thread event loop (L2)** per request. Handlers on L2 await
``db.insert_one(...)`` on Motor's L1-pinned pool → cross-loop
``Future`` → ``RuntimeError``.

This shim solves that by driving ``httpx.AsyncClient(transport=
ASGITransport(app=server.app))`` **on the phase34 persistent loop
itself** via ``batch_safe_run(coro)``. Every HTTP request the tests
issue therefore runs on L1 — the same loop Motor is bound to. There
is no worker thread, no fresh loop, no ``anyio.from_thread`` portal.

Public API
----------
Drop-in replacement for the ``requests`` subset the Phase-34 test
files actually use::

    from tests._phase34_http_shim import http

    r = http.post("/api/leads/bulk-delete", json=body, headers=hdrs)
    r.status_code      # int
    r.json()           # dict / list
    r.text             # str
    r.headers          # httpx.Headers (mapping-like, requests-compatible)

Absolute URLs are accepted too — the host portion is stripped and the
path (from ``/api/...`` onward) is dispatched into the ASGI app::

    http.post("https://tenant.example.com/api/auth/login", json=body)
    # is equivalent to
    http.post("/api/auth/login", json=body)

No network I/O ever occurs. No new top-level dependency; ``httpx`` is
already installed as a FastAPI transitive.

Rollback
--------
Delete this file and revert the callers' import lines. Motor
lifecycle (``_phase34_asyncio.py``) is untouched — this module is
purely additive.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx


# ────────────────────────────────────────────────────────────────────
# Lazy singleton — the AsyncClient is built on first use so we don't
# import ``server`` (which is heavy) until a phase34 test actually
# asks for it. Once built the client is reused for every subsequent
# call to avoid per-request setup cost.
#
# Critically, ``_phase34_asyncio`` is ALSO imported lazily — its
# import-time bootstrap rebuilds ``config.client`` against a session-
# persistent loop, which is safe for the phase34 batch but poisons
# unrelated tests that use their own event loops. Deferring the
# import to first shim call means collecting this module (or
# importing it in a stray helper) has zero side effects.
# ────────────────────────────────────────────────────────────────────
_CLIENT: Optional[httpx.AsyncClient] = None
_RUN = None  # populated by _bootstrap on first shim call


def _bootstrap() -> None:
    """Idempotent: pull in ``_phase34_asyncio.batch_safe_run`` (which
    triggers the persistent-loop Motor rebuild) and build the httpx
    AsyncClient bound to ``server.app``. Called on the FIRST shim
    request only."""
    global _CLIENT, _RUN  # noqa: PLW0603
    if _CLIENT is not None and _RUN is not None:
        return
    from tests._phase34_asyncio import batch_safe_run as _brun  # noqa: PLC0415
    import server  # noqa: PLC0415
    _RUN = _brun
    transport = httpx.ASGITransport(app=server.app)
    _CLIENT = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=httpx.Timeout(30.0, connect=5.0),
        follow_redirects=False,
    )


def _normalize_path(url: str) -> str:
    """Accept either a relative path (``/api/...``) or an absolute
    URL (``https://.../api/...``); return the path portion (with
    query string) suitable for dispatch against
    ``base_url="http://testserver"``.

    This mechanical normalization is what lets the Phase-34 test
    files keep their existing ``f"{API}/leads/bulk-delete"``
    interpolation unchanged — the shim strips the host silently.
    """
    if url.startswith(("http://", "https://")):
        parts = urlsplit(url)
        p = parts.path
        if parts.query:
            p = f"{p}?{parts.query}"
        return p
    return url


# ────────────────────────────────────────────────────────────────────
# Request runner
# ────────────────────────────────────────────────────────────────────
def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Drive an httpx AsyncClient request on the persistent L1 loop.

    ``kwargs`` accepts the ``requests``-style parameters used by the
    Phase-34 test files: ``json``, ``headers``, ``params``, ``data``,
    ``timeout``, ``files``. ``timeout`` is honoured but network
    timeouts don't happen in-process anyway.
    """
    _bootstrap()
    assert _CLIENT is not None and _RUN is not None  # for the type checker
    path = _normalize_path(url)
    client = _CLIENT
    runner = _RUN

    async def _do() -> httpx.Response:
        return await client.request(method, path, **kwargs)

    return runner(_do())


# ────────────────────────────────────────────────────────────────────
# Public surface — mirrors ``requests`` for the methods actually used
# by the Phase-34 test files. httpx.Response already exposes the same
# ``.status_code / .json() / .text / .headers`` surface as
# ``requests.Response`` for the read-only subset the tests use.
# ────────────────────────────────────────────────────────────────────
class _Http:
    @staticmethod
    def get(url: str, *, headers: Optional[Mapping[str, str]] = None,
             params: Optional[Mapping[str, Any]] = None,
             timeout: Any = None) -> httpx.Response:
        del timeout  # accepted for signature parity; ignored in-process
        return _request("GET", url, headers=dict(headers or {}),
                        params=dict(params or {}))

    @staticmethod
    def post(url: str, *, json: Any = None,
              headers: Optional[Mapping[str, str]] = None,
              params: Optional[Mapping[str, Any]] = None,
              data: Any = None,
              files: Any = None,
              timeout: Any = None) -> httpx.Response:
        del timeout
        kw: dict[str, Any] = {"headers": dict(headers or {}),
                              "params": dict(params or {})}
        if json is not None:  kw["json"] = json
        if data is not None:  kw["data"] = data
        if files is not None: kw["files"] = files
        return _request("POST", url, **kw)

    @staticmethod
    def put(url: str, *, json: Any = None,
             headers: Optional[Mapping[str, str]] = None,
             params: Optional[Mapping[str, Any]] = None,
             timeout: Any = None) -> httpx.Response:
        del timeout
        kw: dict[str, Any] = {"headers": dict(headers or {}),
                              "params": dict(params or {})}
        if json is not None: kw["json"] = json
        return _request("PUT", url, **kw)

    @staticmethod
    def patch(url: str, *, json: Any = None,
               headers: Optional[Mapping[str, str]] = None,
               params: Optional[Mapping[str, Any]] = None,
               timeout: Any = None) -> httpx.Response:
        del timeout
        kw: dict[str, Any] = {"headers": dict(headers or {}),
                              "params": dict(params or {})}
        if json is not None: kw["json"] = json
        return _request("PATCH", url, **kw)

    @staticmethod
    def delete(url: str, *, headers: Optional[Mapping[str, str]] = None,
                params: Optional[Mapping[str, Any]] = None,
                timeout: Any = None) -> httpx.Response:
        del timeout
        return _request("DELETE", url, headers=dict(headers or {}),
                        params=dict(params or {}))


# Module-level singleton. Import as ``from tests._phase34_http_shim
# import http`` — matches the "http.post(...)" call shape used across
# the phase34 test files after migration.
http = _Http()
