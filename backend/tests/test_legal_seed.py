"""Feb 2026 · Legal documents seed — Pool + Landscaping ToS.

Covers:
* ``ensure_seeded()`` inserts BOTH docs on a clean DB.
* Idempotent on second run.
* Version bump upgrades the stored copy in place.
* Pool ToS carries the new Pool Drain paragraph shipped Feb 2026.
* Landscaping ToS carries the verbatim customer copy.
* Title relabel — old title "Pool Maintenance Terms of Service" is
  no longer used; new title is "Pool Terms of Service".
"""
from __future__ import annotations

import asyncio

import pytest

from config import db
from routers import legal as legal_router


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_legal_docs():
    async def _clear():
        await db.legal_documents.delete_many({
            "slug": {"$in": [
                legal_router.POOL_TOS_SLUG,
                legal_router.LANDSCAPING_TOS_SLUG,
            ]},
        })
    _run(_clear())
    yield
    _run(_clear())


class TestEnsureSeededBothDocs:
    def test_both_documents_are_seeded_on_a_clean_db(self):
        async def go():
            await legal_router.ensure_seeded()
            pool = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            land = await db.legal_documents.find_one(
                {"slug": legal_router.LANDSCAPING_TOS_SLUG},
            )
            assert pool is not None
            assert land is not None
            assert pool["version"] == legal_router.POOL_TOS_VERSION
            assert land["version"] == legal_router.LANDSCAPING_TOS_VERSION
        _run(go())

    def test_pool_title_relabel_no_longer_uses_maintenance_word(self):
        async def go():
            await legal_router.ensure_seeded()
            pool = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            # New title is "Pool Terms of Service".
            assert pool["title"] == "Pool Terms of Service"
            # Old title must NOT persist after upgrade.
            assert "Maintenance Terms" not in pool["title"]
        _run(go())

    def test_pool_markdown_contains_pool_drain_paragraph(self):
        async def go():
            await legal_router.ensure_seeded()
            pool = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            body = pool["body_markdown"]
            # Exact bolded lede.
            assert "**Pool Drain.**" in body
            # Key phrases from the copy.
            assert "every 2\u20133 years" in body  # unicode en-dash
            assert "water testing results" in body
            # Preserved surrounding content — regression guard on
            # the insertion location (must be inside section 3).
            assert "### 3. Additional Maintenance" in body
            assert "Salt Cell Cleanings" in body
            assert "Premier service plan" in body
        _run(go())

    def test_landscaping_markdown_carries_verbatim_customer_copy(self):
        async def go():
            await legal_router.ensure_seeded()
            land = await db.legal_documents.find_one(
                {"slug": legal_router.LANDSCAPING_TOS_SLUG},
            )
            assert land["title"] == "Landscaping Terms of Service"
            body = land["body_markdown"]
            # Spot-check five phrases across different sections
            # so a stray copy-paste regression trips one of them.
            assert "lawn maintenance, trimming, pruning, weed control" in body
            assert "Winter overseeding" in body
            assert "underground utilities, irrigation lines" in body
            assert "Recurring Services" in body
            assert "acknowledges that they have reviewed and agree" in body
        _run(go())


class TestEnsureSeededIdempotency:
    def test_second_run_is_a_no_op(self):
        async def go():
            await legal_router.ensure_seeded()
            first_pool = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            first_land = await db.legal_documents.find_one(
                {"slug": legal_router.LANDSCAPING_TOS_SLUG},
            )
            await legal_router.ensure_seeded()  # 2nd call
            after_pool = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            after_land = await db.legal_documents.find_one(
                {"slug": legal_router.LANDSCAPING_TOS_SLUG},
            )
            # id + updated_at must NOT change on the no-op call.
            assert first_pool["id"] == after_pool["id"]
            assert first_pool["updated_at"] == after_pool["updated_at"]
            assert first_land["id"] == after_land["id"]
        _run(go())

    def test_version_bump_upgrades_existing_row_in_place(self):
        async def go():
            # Simulate legacy v1 pool doc without the Pool Drain
            # paragraph (matches the pre-Feb-2026 state).
            await db.legal_documents.insert_one({
                "id": "legacy-pool-doc",
                "slug": legal_router.POOL_TOS_SLUG,
                "title": "Pool Maintenance Terms of Service",  # old title
                "body_markdown": "## Pool Service Terms (legacy stub)",
                "effective_date": "2026-07-13",
                "version": 1,
                "updated_at": "2026-07-13T00:00:00+00:00",
                "created_at": "2026-07-13T00:00:00+00:00",
            })
            await legal_router.ensure_seeded()
            row = await db.legal_documents.find_one(
                {"slug": legal_router.POOL_TOS_SLUG},
            )
            # In-place upgrade preserves ``id`` but bumps version,
            # relabels title, refreshes body.
            assert row["id"] == "legacy-pool-doc"
            assert row["version"] == legal_router.POOL_TOS_VERSION
            assert row["title"] == "Pool Terms of Service"
            assert "**Pool Drain.**" in row["body_markdown"]
        _run(go())
