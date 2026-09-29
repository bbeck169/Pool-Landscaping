"""Reusable isolated event loop for ``_seed.py`` / migration tests.

Motor's ``AsyncIOMotorClient`` binds to whichever event loop is current
at first use.  Test modules that call ``asyncio.get_event_loop()`` share
the process default loop, which means the first test module to touch
Motor pins the client to that loop.  Once the loop is closed (by
another test module's teardown) or superseded, every downstream test
that touches ``config.db`` fails with ``AttributeError`` / ``TypeError``
/ ``RuntimeError: Event loop is closed``.

Phase EMAIL-MIGRATE · Batch 4 solved this per-file by giving each test
module a private ``_LOOP`` + a Motor client bound to it.  This helper
extracts that pattern so any test can adopt it in three lines:

    import pytest
    from tests._asyncio_loop_isolation import make_isolated_loop, bind_config_db

    _LOOP, _run = make_isolated_loop()

    @pytest.fixture(scope="module", autouse=True)
    def _bind_db():
        yield from bind_config_db(_LOOP)

Then use ``_run(coro)`` anywhere a legacy ``_run`` (which called
``asyncio.get_event_loop().run_until_complete(coro)``) used to appear.

For tests that MagicMock out the DB entirely, ``bind_config_db`` is a
harmless no-op on ``config.db`` — the swap is idempotent-safe.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Tuple


def make_isolated_loop() -> Tuple[asyncio.AbstractEventLoop, Callable]:
    """Create a fresh event loop dedicated to this test module.

    Returns ``(loop, run)`` where ``run(coro)`` synchronously drives the
    coroutine to completion on ``loop``.  Sets ``loop`` as the current
    event loop so any ``asyncio.get_event_loop()`` calls in the code
    under test see it (matches the Batch 4 template exactly).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run(coro):
        return loop.run_until_complete(coro)

    return loop, run


def bind_config_db(loop: asyncio.AbstractEventLoop, extra_modules=()):
    """Generator suitable for ``yield from`` inside a module-scope
    ``@pytest.fixture(scope="module", autouse=True)``.

    Constructs a fresh ``AsyncIOMotorClient`` bound to ``loop``, swaps
    ``config.db`` to the new client's DB handle, yields once so the
    tests can run, then restores the original ``config.db`` on
    teardown so downstream test modules don't inherit a closed loop's
    handle.

    ``extra_modules`` — iterable of dotted module paths whose
    module-level ``db`` attribute should ALSO be rebound to the fresh
    handle for the fixture's lifetime.  Needed for tests that
    exercise callables that import ``db`` at module top (i.e. the
    reference is captured at import time and won't follow a
    ``config.db =`` swap).  Restored on teardown.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import importlib
    import config as _cfg
    _orig_config_db = _cfg.db
    _cfg.db = fresh_db
    _orig_extras = {}
    for _mod_name in extra_modules:
        _mod = importlib.import_module(_mod_name)
        _orig_extras[_mod_name] = getattr(_mod, "db", None)
        setattr(_mod, "db", fresh_db)
    try:
        yield
    finally:
        _cfg.db = _orig_config_db
        for _mod_name, _orig in _orig_extras.items():
            setattr(importlib.import_module(_mod_name), "db", _orig)
