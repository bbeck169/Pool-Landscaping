"""Phase 26b · Feb-2026 — Category deactivation auto-map tests.

Covers:
  1. Archive fan-out across BOTH axes (income + service).
  2. Line-item + pricebook-item stamping on fan-out.
  3. K71 save-time soft-pass for archived refs.
  4. Restore does NOT re-hydrate null'd refs.
  5. Legacy-name match (income axis only — ``category: "Pool"``).
  6. Tenant isolation — fan-out doesn't cross tenants.
  7. Rollback on fan-out failure.

Direct Mongo + direct service-module unit tests — no HTTP layer
(the handlers are a thin wrapper around the service module +
category update, both covered here).  Keeps the test file fast
and deterministic.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _tenant_id() -> str:
    return f"test-phase26b-{uuid.uuid4()}"


async def _cleanup(db, tid):
    await db.income_categories.delete_many({"tenant_id": tid})
    await db.service_categories.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.items.delete_many({"tenant_id": tid})


# ─── Fan-out · income axis · id ref ──────────────────────────────
def test_income_archive_fans_out_nulls_id_and_stamps():
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())
    cat_name = "P26B-Chemicals"

    async def _setup_and_run(db):
        # Seed the archived cat + 1 pricebook item + 1 quote line referencing it.
        await db.income_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": cat_name,
            "is_archived": False,
        })
        await db.items.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "Item A",
            "income_category_id": cat_id,
        })
        quote_id = str(uuid.uuid4())
        await db.quotes.insert_one({
            "id": quote_id, "tenant_id": tid, "doc_type": "invoice",
            "line_items": [
                {"description": "L1", "income_category_id": cat_id,
                 "category": cat_id, "category_name": cat_name},
                {"description": "L2 — untouched",
                 "income_category_id": str(uuid.uuid4())},
            ],
        })

        from services.category_deactivation import fan_out_archive
        stats = await fan_out_archive(
            axis="income", tenant_id=tid, cat_id=cat_id, cat_name=cat_name)

        # Pricebook item was updated.
        it = await db.items.find_one({"tenant_id": tid, "name": "Item A"})
        assert it["income_category_id"] == ""
        assert it["category_auto_mapped"] is True
        assert it["original_category_id"] == cat_id
        assert it["original_category_name"] == cat_name

        # Quote line 0 was updated; line 1 untouched.
        q = await db.quotes.find_one({"id": quote_id})
        li0, li1 = q["line_items"]
        assert li0["income_category_id"] == ""
        assert li0["category_auto_mapped"] is True
        assert li0["original_category_id"] == cat_id
        assert li0["original_category_name"] == cat_name
        # Legacy fields also null'd.
        assert li0.get("category") == ""
        assert li0.get("category_name") == ""
        assert "category_auto_mapped" not in li1

        # Stats reflect the fan-out.
        assert stats["pricebook_items_updated"] == 1
        assert stats["quotes_updated_by_id"] == 1

    run_test(_setup_and_run)


# ─── Fan-out · income axis · legacy name ref ─────────────────────
def test_income_archive_fans_out_legacy_name_ref():
    """A line item that references the archived cat by legacy name
    string (``category: "Pool"``) also gets null'd + stamped."""
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())
    cat_name = "P26B-LegacyPool"

    async def _setup_and_run(db):
        await db.income_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": cat_name,
            "is_archived": False,
        })
        quote_id = str(uuid.uuid4())
        await db.quotes.insert_one({
            "id": quote_id, "tenant_id": tid, "doc_type": "invoice",
            "line_items": [
                # Legacy name match, case-insensitive — no FK id.
                {"description": "legacy ref",
                 "category": cat_name.lower()},
            ],
        })

        from services.category_deactivation import fan_out_archive
        stats = await fan_out_archive(
            axis="income", tenant_id=tid, cat_id=cat_id, cat_name=cat_name)

        q = await db.quotes.find_one({"id": quote_id})
        li = q["line_items"][0]
        assert li["category"] == ""
        assert li["category_auto_mapped"] is True
        assert li["original_category_id"] == cat_id
        assert li["original_category_name"] == cat_name
        assert stats["quotes_updated_by_legacy_name"] == 1

    run_test(_setup_and_run)


# ─── Fan-out · service axis ───────────────────────────────────────
def test_service_archive_fans_out():
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())
    cat_name = "P26B-ServicePool"

    async def _setup_and_run(db):
        await db.service_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": cat_name,
            "is_archived": False,
        })
        await db.items.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "Item SVC",
            "service_category_id": cat_id,
        })
        quote_id = str(uuid.uuid4())
        await db.quotes.insert_one({
            "id": quote_id, "tenant_id": tid, "doc_type": "quote",
            "line_items": [
                {"description": "L1", "service_category_id": cat_id,
                 "service_category_name": cat_name},
            ],
        })

        from services.category_deactivation import fan_out_archive
        stats = await fan_out_archive(
            axis="service", tenant_id=tid, cat_id=cat_id, cat_name=cat_name)

        it = await db.items.find_one({"tenant_id": tid, "name": "Item SVC"})
        assert it["service_category_id"] == ""
        assert it["category_auto_mapped"] is True
        assert it["original_category_id"] == cat_id

        q = await db.quotes.find_one({"id": quote_id})
        li = q["line_items"][0]
        assert li["service_category_id"] == ""
        assert li["service_category_name"] == ""
        assert li["category_auto_mapped"] is True
        assert li["original_category_name"] == cat_name
        assert stats["pricebook_items_updated"] == 1
        assert stats["quotes_updated_by_id"] == 1

    run_test(_setup_and_run)


# ─── Tenant isolation ─────────────────────────────────────────────
def test_fan_out_does_not_cross_tenants():
    tid_a = _tenant_id()
    tid_b = f"test-phase26b-{uuid.uuid4()}"
    cat_id = str(uuid.uuid4())
    cat_name = "P26B-Isolated"

    async def _setup_and_run(db):
        try:
            # Tenant A: the cat being archived.
            await db.income_categories.insert_one({
                "id": cat_id, "tenant_id": tid_a, "name": cat_name,
                "is_archived": False,
            })
            # Tenant B: a quote whose line_items share the SAME cat_id
            # (unusual but worst-case — proves the match is tenant-scoped).
            quote_b_id = str(uuid.uuid4())
            await db.quotes.insert_one({
                "id": quote_b_id, "tenant_id": tid_b, "doc_type": "invoice",
                "line_items": [
                    {"description": "B1", "income_category_id": cat_id},
                ],
            })
            from services.category_deactivation import fan_out_archive
            await fan_out_archive(
                axis="income", tenant_id=tid_a,
                cat_id=cat_id, cat_name=cat_name)

            # Tenant B's line item is untouched.
            qb = await db.quotes.find_one({"id": quote_b_id})
            assert qb["line_items"][0]["income_category_id"] == cat_id
            assert "category_auto_mapped" not in qb["line_items"][0]
        finally:
            await db.quotes.delete_many({"tenant_id": tid_b})

    run_test(_setup_and_run)


# ─── K71 save-time soft-pass + auto-stamp ─────────────────────────
def test_k71_validator_soft_passes_archived_refs():
    """When the K71 validator sees a line pointing at an archived
    category, it mutates the line in-place (null + stamp) instead
    of raising HTTP 400."""
    tid = _tenant_id()
    svc_id = str(uuid.uuid4())
    inc_id = str(uuid.uuid4())

    async def _setup_and_run(db):
        # Seed one archived svc + one archived inc.
        await db.service_categories.insert_one({
            "id": svc_id, "tenant_id": tid, "name": "ArchivedSvc",
            "is_archived": True,
        })
        await db.income_categories.insert_one({
            "id": inc_id, "tenant_id": tid, "name": "ArchivedInc",
            "is_archived": True,
        })
        # Also seed at least one ACTIVE pair so the validator's
        # name regex / active-set lookup doesn't trip on empty.
        await db.service_categories.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "ActiveSvc",
            "is_archived": False,
        })
        await db.income_categories.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "ActiveInc",
            "is_archived": False,
        })

        line = {
            "description": "L1",
            "service_category_id": svc_id,
            "income_category_id": inc_id,
        }

        from routers.income_categories import validate_line_item_k71_categories
        # Should NOT raise — soft-pass + mutate in place.
        await validate_line_item_k71_categories(tid, [line])

        assert line["service_category_id"] == ""
        assert line["income_category_id"] == ""
        assert line.get("category_auto_mapped") is True
        assert line.get("original_category_id") in (svc_id, inc_id)
        # The last soft-pass wins the ``original_*`` stamp (inc runs
        # last).  Either axis is acceptable as long as auto_mapped
        # is True so the UI shows the amber chip.

    run_test(_setup_and_run)


def test_k71_validator_allows_auto_mapped_empty_rows():
    """A line already stamped ``category_auto_mapped: true`` with
    empty K71 fields is treated as a legacy row — allowed through
    save without raising."""
    tid = _tenant_id()

    async def _setup_and_run(db):
        # Minimal seed so ensure_defaults works.
        await db.income_categories.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "Seed",
            "is_archived": False,
        })
        await db.service_categories.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "Seed",
            "is_archived": False,
        })
        line = {
            "description": "post-archive auto-mapped row",
            "service_category_id": "",
            "income_category_id": "",
            "category_auto_mapped": True,
            "original_category_id": "x",
            "original_category_name": "x",
        }
        from routers.income_categories import validate_line_item_k71_categories
        # Must not raise.
        await validate_line_item_k71_categories(tid, [line])

    run_test(_setup_and_run)


# ─── Legacy validator soft-pass ───────────────────────────────────
def test_legacy_validator_soft_passes_archived_name_ref():
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())

    async def _setup_and_run(db):
        await db.income_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": "LegacyArchName",
            "is_archived": True,
        })
        await db.income_categories.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "name": "LiveCat",
            "is_archived": False,
        })
        line = {"description": "x", "category": "LegacyArchName"}
        from routers.income_categories import validate_line_item_categories
        await validate_line_item_categories(tid, [line])
        assert line["category"] == ""
        assert line.get("category_auto_mapped") is True
        assert line["original_category_id"] == cat_id
        assert line["original_category_name"] == "LegacyArchName"

    run_test(_setup_and_run)


# ─── Restore does NOT re-hydrate ──────────────────────────────────
def test_restore_does_not_rehydrate_null_refs():
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())

    async def _setup_and_run(db):
        await db.income_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": "P26B-Restore",
            "is_archived": False,
        })
        quote_id = str(uuid.uuid4())
        await db.quotes.insert_one({
            "id": quote_id, "tenant_id": tid, "doc_type": "invoice",
            "line_items": [{"description": "L1",
                              "income_category_id": cat_id}],
        })
        from services.category_deactivation import fan_out_archive
        await fan_out_archive(
            axis="income", tenant_id=tid, cat_id=cat_id,
            cat_name="P26B-Restore")

        # Restore the cat.
        await db.income_categories.update_one(
            {"id": cat_id, "tenant_id": tid},
            {"$set": {"is_archived": False}},
        )

        # Line item is STILL null'd + stamped.
        q = await db.quotes.find_one({"id": quote_id})
        li = q["line_items"][0]
        assert li["income_category_id"] == ""
        assert li["category_auto_mapped"] is True
        assert li["original_category_id"] == cat_id

    run_test(_setup_and_run)


# ─── Rollback on fan-out failure ──────────────────────────────────
def test_rollback_archive_unarchives():
    tid = _tenant_id()
    cat_id = str(uuid.uuid4())

    async def _setup_and_run(db):
        await db.income_categories.insert_one({
            "id": cat_id, "tenant_id": tid, "name": "P26B-Rollback",
            "is_archived": True,
        })
        from services.category_deactivation import rollback_archive
        await rollback_archive(
            axis="income", tenant_id=tid, cat_id=cat_id)
        row = await db.income_categories.find_one(
            {"id": cat_id, "tenant_id": tid})
        assert row["is_archived"] is False

    run_test(_setup_and_run)
