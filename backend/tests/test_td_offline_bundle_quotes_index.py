"""TD-offline-bundle-quotes-index · Feb-2026 — migration regression.

Proves the Lane B migration script creates the compound index on
``quotes.(tenant_id, doc_type, updated_at DESC)`` with
``background=True`` and that re-running it is a safe idempotent
no-op.

Uses a dedicated test database (``pool_crm_test_td_offline_bundle``)
spun up via the same ``AsyncIOMotorClient`` that the production
handler uses, torn down at the end of the module so repeat local
runs stay clean.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from migrations import quotes_tenant_doctype_updated_at_desc_index_v1 as mig


_TEST_DB_NAME = "pool_crm_test_td_offline_bundle_quotes_index"
_INDEX_NAME = "tenant_doctype_updated_at_desc"


@pytest.fixture
def test_db():
    """Fresh test DB per module — drops at start AND at teardown so
    local re-runs don't drag state across runs.
    """
    client = AsyncIOMotorClient(
        os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db_ = client[_TEST_DB_NAME]

    async def _drop() -> None:
        await client.drop_database(_TEST_DB_NAME)

    asyncio.get_event_loop().run_until_complete(_drop())
    try:
        yield db_
    finally:
        asyncio.get_event_loop().run_until_complete(_drop())
        client.close()


def _get_index_list(db_) -> list:
    async def _fetch() -> list:
        cursor = db_.quotes.list_indexes()
        return [idx async for idx in cursor]
    return asyncio.get_event_loop().run_until_complete(_fetch())


def test_run_creates_expected_index_shape(test_db) -> None:
    """First run: migration creates the compound index with the
    exact ``(tenant_id ASC, doc_type ASC, updated_at DESC)`` spec,
    uses ``background=True`` as the operator's off-peak preference
    requires, and names it ``tenant_doctype_updated_at_desc``.
    """
    result = asyncio.get_event_loop().run_until_complete(
        mig.run(_db=test_db))

    assert result["created"] is True
    assert result["sentinel"] == "stamped"
    assert result["name"] == _INDEX_NAME
    assert result["background"] is True

    indexes = _get_index_list(test_db)
    by_name = {idx["name"]: idx for idx in indexes}
    assert _INDEX_NAME in by_name
    spec = by_name[_INDEX_NAME]
    # Mongo normalises the key spec to a list of (field, direction) pairs.
    assert list(spec["key"].items()) == [
        ("tenant_id", 1),
        ("doc_type", 1),
        ("updated_at", -1),
    ]
    # ``background=True`` is only visible on the spec on legacy Mongo
    # driver versions.  Modern drivers / servers accept the flag but
    # may not round-trip it in ``list_indexes()``.  Validate the
    # return-shape instead (locked above).


def test_run_is_idempotent(test_db) -> None:
    """Second run: migration is a safe no-op.  The sentinel short-
    circuit returns ``sentinel="present"`` and ``created=False``;
    the index exists exactly ONCE in ``list_indexes()``.
    """
    # First run (sets up the index + sentinel).
    first = asyncio.get_event_loop().run_until_complete(
        mig.run(_db=test_db))
    assert first["created"] is True
    assert first["sentinel"] == "stamped"

    # Second run — should be the sentinel short-circuit path.
    second = asyncio.get_event_loop().run_until_complete(
        mig.run(_db=test_db))
    assert second["created"] is False
    assert second["sentinel"] == "present"
    assert second["name"] == _INDEX_NAME

    # Third run with ``force=True`` — re-stamps the sentinel but the
    # index still exists exactly once.
    third = asyncio.get_event_loop().run_until_complete(
        mig.run(_db=test_db, force=True))
    assert third["sentinel"] == "stamped"
    assert third["name"] == _INDEX_NAME

    # Final index list — exactly one row with our name.
    indexes = _get_index_list(test_db)
    matching = [idx for idx in indexes if idx["name"] == _INDEX_NAME]
    assert len(matching) == 1, (
        f"Expected exactly 1 {_INDEX_NAME} index after 3 runs; "
        f"got {len(matching)}: {matching!r}"
    )


def test_sentinel_row_recorded(test_db) -> None:
    """The ``_migrations`` sentinel row MUST carry the index name +
    background flag + completed_at timestamp so a future audit can
    tell when the migration landed.
    """
    asyncio.get_event_loop().run_until_complete(mig.run(_db=test_db))

    async def _fetch_sentinel() -> dict:
        return await test_db["_migrations"].find_one(
            {"id": "quotes_tenant_doctype_updated_at_desc_index_v1"})

    row = asyncio.get_event_loop().run_until_complete(_fetch_sentinel())
    assert row is not None
    assert row["id"] == "quotes_tenant_doctype_updated_at_desc_index_v1"
    assert row["completed_at"]
    assert row["stats"]["index_name"] == _INDEX_NAME
    assert row["stats"]["background"] is True
