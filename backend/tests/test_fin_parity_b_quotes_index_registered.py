"""FIN-PARITY-B · Feb-2026 — verify the compound index the FE
server-side filter relies on is registered in the k44 bootstrap
catalogue and is idempotent on repeat runs.

Does NOT run against a live Mongo (no cost / no cleanup); asserts
the catalogue contains the required tuple + calls ``run()`` twice
to verify the second-run cost is a no-op cache hit.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


INDEX_NAME = "k44_quotes_tenant_doctype_paymentstatus_deleted"
EXPECTED_KEYS = [
    ("tenant_id", 1),
    ("doc_type", 1),
    ("payment_status", 1),
    ("deleted_at", 1),
]


def test_fin_parity_b_index_is_in_k44_catalogue():
    """Source-check: the compound index tuple appears verbatim in
    the ``_INDEXES`` catalogue so every boot lands it."""
    from migrations.k44_perf_indexes import _INDEXES

    matches = [
        entry for entry in _INDEXES
        if entry[1] == INDEX_NAME
    ]
    assert len(matches) == 1, (
        f"expected exactly one k44 entry named {INDEX_NAME!r}, "
        f"got {len(matches)}: {matches!r}"
    )
    coll_name, idx_name, keys = matches[0]
    assert coll_name == "quotes"
    assert idx_name == INDEX_NAME
    assert keys == EXPECTED_KEYS


def test_fin_parity_b_index_creates_and_is_idempotent_on_repeat_run():
    """Run the k44 bootstrap twice — the second pass must count
    the index as ``already_present``, never as a fresh ``created``.

    Uses the ``config.db`` binding (same loop / driver as k44's
    module import) so the create_index calls target the same
    motor client that the bootstrap uses in production.
    """
    from migrations import k44_perf_indexes as k44_mod
    from config import db as _CONFIG_DB  # noqa: N814

    async def _go():
        first = await k44_mod.run()
        second = await k44_mod.run()
        first_targets = {
            t["index"]: t.get("status")
            for t in first["summary"]["targets"]
        }
        second_targets = {
            t["index"]: t.get("status")
            for t in second["summary"]["targets"]
        }
        assert INDEX_NAME in first_targets
        assert INDEX_NAME in second_targets
        # Second run MUST be already_present — proves idempotency.
        assert second_targets[INDEX_NAME] == "already_present", (
            f"second run status was {second_targets[INDEX_NAME]!r}; "
            f"expected 'already_present' for idempotent index"
        )
        # Verify the index landed on the actual quotes collection
        # via config.db (same event loop as k44's driver).
        names = set()
        async for idx in _CONFIG_DB.quotes.list_indexes():
            names.add(idx.get("name") or "")
        assert INDEX_NAME in names

    # Run on the config.db loop so motor's futures resolve on the
    # same event loop as the module-level driver initialisation.
    import asyncio as _asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    _cfg_client = _CONFIG_DB.client
    _cfg_loop = _cfg_client.get_io_loop() if hasattr(
        _cfg_client, "get_io_loop") else _asyncio.get_event_loop()
    _asyncio.set_event_loop(_cfg_loop)
    _cfg_loop.run_until_complete(_go())


def test_fin_parity_b_index_physically_present_on_quotes():
    """After running the bootstrap once, ``db.quotes`` must expose
    the compound index in ``list_indexes()`` output."""
    from migrations import k44_perf_indexes as k44_mod
    from config import db as _CONFIG_DB  # noqa: N814
    import asyncio as _asyncio

    async def _go():
        await k44_mod.run()
        names = set()
        async for idx in _CONFIG_DB.quotes.list_indexes():
            names.add(idx.get("name") or "")
        assert INDEX_NAME in names, (
            f"index {INDEX_NAME!r} missing from db.quotes; "
            f"found: {sorted(names)!r}"
        )

    _cfg_client = _CONFIG_DB.client
    _cfg_loop = _cfg_client.get_io_loop() if hasattr(
        _cfg_client, "get_io_loop") else _asyncio.get_event_loop()
    _asyncio.set_event_loop(_cfg_loop)
    _cfg_loop.run_until_complete(_go())


def test_fin_parity_b_index_no_duplicate_entry_in_catalogue():
    """Belt-and-braces: catalogue must not accidentally contain a
    second entry with the same name (would create ambiguous
    already_present tracking)."""
    from migrations.k44_perf_indexes import _INDEXES

    names = [entry[1] for entry in _INDEXES]
    assert names.count(INDEX_NAME) == 1
