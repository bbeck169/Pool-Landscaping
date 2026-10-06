"""Phase 41.1d · Feb 2026 — Batch-safe async driver for the six Phase-34
tenant-tasks test files.

Why this exists
---------------
The six Phase-34 tenant-tasks test files (bb_cc, hh_ii_gg, jj_kk_ee_digest,
ll_p2, nn_p1, t_review_gating) drive Motor coroutines from sync fixtures
via a tiny `_run(coro)` helper. Historically that helper used::

    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

Solo, all 127 tests pass — every call to `asyncio.get_event_loop()`
returns the same still-open default loop, Motor lazily binds to it on
first use, and subsequent operations reuse the binding.

In the full backend batch (~3500 tests), earlier tests call
``asyncio.run(...)`` which creates + closes fresh loops. Once the loop
Motor bound to is closed, subsequent Motor calls raise::

    RuntimeError: Task got Future attached to a different loop

Motor's connection-pool topology holds Future references pinned to the
FIRST loop it saw — simply rebinding ``client._io_loop`` isn't enough
because the topology's internals still target the original loop.

Fix
---
On first use, ``batch_safe_run`` (a) creates a session-persistent
event loop that is never closed, (b) tears down the stale
``config.client`` and rebuilds it as a fresh ``AsyncIOMotorClient``
bound explicitly to that loop via ``io_loop=loop``, and (c) points
``config.db`` at the new client's database. Every subsequent call
reuses the same loop + same freshly-built client, so Motor's Future
graph is coherent for the entire session.

Design notes
------------
- The persistent loop is NEVER closed during the session. Closing it
  would immediately re-introduce the failure on the next call.
- The rebuild happens ONCE per session (guarded by a module-level
  flag). All subsequent ``batch_safe_run`` calls skip the rebuild.
- We only mutate the pytest process's ``config.client`` /
  ``config.db``. The running backend server is a separate Python
  interpreter (supervisor-managed) and is entirely unaffected.
- Blast radius is scoped to the six files that import
  ``batch_safe_run as _run``. Every other test path is untouched.
"""
from __future__ import annotations

import asyncio
import os

_MODULE_LOOP: "asyncio.AbstractEventLoop | None" = None
_REBUILT: bool = False


def _get_persistent_loop() -> "asyncio.AbstractEventLoop":
    """Return the process-wide persistent event loop, lazily creating
    it on first use. If a prior test closed the previous loop, a
    fresh one is minted. STRIPE-TEST-ISOLATION · Feb-2026 — when a
    new loop is minted, we also reset ``_REBUILT`` so the next
    ``_rebuild_motor_client_on_loop`` call rebinds Motor onto the
    fresh loop. Without this reset, the Motor client stays pinned
    to the closed loop and every subsequent Motor call raises
    ``RuntimeError: Event loop is closed``."""
    global _MODULE_LOOP, _REBUILT  # noqa: PLW0603
    if _MODULE_LOOP is None or _MODULE_LOOP.is_closed():
        _MODULE_LOOP = asyncio.new_event_loop()
        _REBUILT = False  # force rebuild on the fresh loop
    return _MODULE_LOOP


def _rebuild_motor_client_on_loop(loop: "asyncio.AbstractEventLoop") -> None:
    """Replace ``config.client`` with a fresh ``AsyncIOMotorClient``
    bound explicitly to ``loop`` via the documented ``io_loop=``
    kwarg. Also repoint ``config.db`` at the new client's database.

    STRIPE-TEST-ISOLATION · Feb-2026 — rebuild on every call. The
    original one-shot design (``_REBUILT`` flag) and the subsequent
    identity-based fast-path both failed under broader batches:

      * ``_REBUILT`` pinned the client to a closed persistent loop
        when a later test closed it (pytest-asyncio cleanup, etc.).
      * ``_io_loop is loop`` fast-path matches when
        ``_phase41_1d_ensure_motor_loop`` rebinds ``_io_loop``, but
        Motor's connection-pool futures remain pinned to the
        original loop (per Motor topology; see module docstring).

    New policy: unconditionally rebuild on every invocation. The
    ``AsyncIOMotorClient`` constructor is lazy — the connection
    pool is deferred until first I/O — so the per-call cost is
    negligible but the correctness win is total.
    """
    global _REBUILT  # noqa: PLW0603
    try:
        import config  # noqa: PLC0415
        from motor.motor_asyncio import AsyncIOMotorClient  # noqa: PLC0415
    except Exception:
        return  # config not importable — nothing to rebuild
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        return
    config.client = AsyncIOMotorClient(mongo_url, io_loop=loop)
    config.db = config.client[db_name]
    _REBUILT = True  # kept for backwards-compat with any external
                     # introspection; no longer gates the rebuild.


def _rebind_service_module_dbs() -> None:
    """STRIPE-TEST-ISOLATION · Feb-2026 — rebind service modules that
    captured ``db`` from ``config`` at THEIR import time. Idempotent;
    safe to call on every ``batch_safe_run`` invocation. MUST run
    AFTER ``config.db`` has been set/rebuilt by
    ``_rebuild_motor_client_on_loop`` so each rebind picks up the
    freshly-bound Motor database. Deliberately UNguarded by
    ``_REBUILT`` because the one-shot rebuild above fires before our
    Stripe-cluster test files get a chance to import this helper —
    without this unconditional rebind, their ``sc.db`` would still
    reference the stale pre-rebuild database."""
    try:
        import config  # noqa: PLC0415
        import importlib  # noqa: PLC0415
    except Exception:
        return
    for _modname in (
        "services.payments.stripe_charge",
        "services.payments.stripe_webhook_ledger",
        "services.payments.mark_invoice_paid",
    ):
        try:
            _mod = importlib.import_module(_modname)
            if hasattr(_mod, "db"):
                _mod.db = config.db
        except Exception:
            # Module may not be importable in every test session.
            # Affected tests will surface the issue directly.
            pass


def batch_safe_run(coro):
    """Drive an awaitable to completion on the session-persistent loop.

    See module docstring for the full rationale.
    """
    loop = _get_persistent_loop()
    # Install as the current-thread default so any nested
    # ``asyncio.get_event_loop()`` inside Motor's plumbing returns
    # the same loop.
    asyncio.set_event_loop(loop)
    # Belt-and-braces: rebuild Motor's client on the current loop if
    # someone hasn't already done so. Import-time rebuild below is
    # the primary path; this is a safety net for anyone importing
    # this helper outside of pytest collection order.
    _rebuild_motor_client_on_loop(loop)
    # Unconditional service-module rebind — fires every call so
    # Stripe tests pick up the fresh ``config.db`` even when a
    # Phase-34 test triggered the one-shot rebuild earlier in the
    # session (which would have flipped ``_REBUILT=True`` before
    # the Stripe tests got a chance to import this helper).
    _rebind_service_module_dbs()
    return loop.run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════
# Import-time bootstrap
# ═══════════════════════════════════════════════════════════════════════
# The six Phase-34 test files each do ``from config import db as _db``
# inside their module-scoped ``db()`` fixture. Fixtures resolve AFTER
# module import, so if we rebuild ``config.client`` / ``config.db``
# right here at import time, every subsequent ``from config import db``
# picks up the fresh objects bound to the persistent loop. This is the
# critical timing detail — waiting until the first ``batch_safe_run``
# call is TOO LATE because by then the fixture has already captured
# the stale ``config.db`` reference.
_rebuild_motor_client_on_loop(_get_persistent_loop())
_rebind_service_module_dbs()
