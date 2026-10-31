"""Feb-2026 · TD-income-category-dupes-migration · Phase 2 pytest.

Covers ``backend/migrations/merge_income_categories_duplicates
_v1.py`` — direct coroutine invocation against the shipped
``config.db`` Motor client (same loop semantics as every other
migration pytest in this repo).

Scenarios (per operator brief):
  1. Dry-run on multi-tenant fixture with duplicates + inline-
     only lines prints expected counts, NO writes verified.
  2. Apply mode — counts match dry-run; dupes soft-deleted; FK
     rewrites verified; backfill verified.
  3. Second apply = no-op (counts all 0).
  4. Cross-tenant isolation: tenant A migration does not touch
     tenant B rows.
  5. Tiebreak determinism: equal ref_count → lex winner stable
     across runs.
  6. Unmatched inline strings logged, not written as fake FKs.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import db                                              # noqa: E402
from migrations.merge_income_categories_duplicates_v1 import (     # noqa: E402
    merge_income_categories_duplicates,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_PREFIX = f"TEST-mergedupes-{uuid.uuid4().hex[:6]}"


def _tid(suffix: str) -> str:
    return f"{_PREFIX}-{suffix}"


@pytest.fixture()
def clean():
    async def _cleanup():
        rx = {"$regex": f"^{_PREFIX}"}
        await db.quotes.delete_many({"tenant_id": rx})
        await db.income_categories.delete_many({"tenant_id": rx})
        await db.tenants.delete_many({"id": rx})
        await db.migration_runs.delete_many({"tenant_id": rx})
    _run(_cleanup())
    yield
    _run(_cleanup())


async def _seed_tenant(tid):
    await db.tenants.insert_one(
        {"id": tid, "slug": tid, "name": tid, "active": True},
    )


async def _seed_cat(tid, name):
    cid = f"{_PREFIX}-ic-{uuid.uuid4().hex[:8]}"
    await db.income_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "is_archived": False,
    })
    return cid


async def _seed_invoice(tid, lines):
    iid = f"{_PREFIX}-inv-{uuid.uuid4().hex[:8]}"
    await db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": iid,
        "status": "paid", "payment_status": "paid",
        "line_items": lines,
    })
    return iid


# ═══════════════════════════════════════════════════════════════════
# 1. Dry-run — reports counts, no writes.
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_reports_counts_and_writes_nothing(clean):
    tid = _tid("drytid")
    _run(_seed_tenant(tid))
    a = _run(_seed_cat(tid, "Pool"))
    b = _run(_seed_cat(tid, "pool"))
    _run(_seed_invoice(tid, [
        {"description": "A", "quantity": 1, "unit_price": 10,
         "income_category_id": a},
        {"description": "B", "quantity": 1, "unit_price": 10,
         "income_category_id": a},
        {"description": "C", "quantity": 1, "unit_price": 10,
         "income_category_id": b},
        {"description": "D", "quantity": 1, "unit_price": 10,
         "category": "Pool"},   # inline-only, FK missing
    ]))
    result = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=True,
    ))
    totals = result["totals"]
    assert totals["sets_merged"] == 1
    assert totals["lines_fk_rewritten"] == 1  # 1 line pointed at loser `b`
    assert totals["loser_rows_soft_deleted"] == 1
    assert totals["lines_fk_backfilled"] == 1  # the inline-only "D"
    # No writes — loser row still live, no deleted_at stamp.
    loser = _run(db.income_categories.find_one({"id": b}))
    assert loser is not None
    assert loser.get("deleted_at") is None
    # No migration_runs doc written on dry-run.
    run_doc = _run(db.migration_runs.find_one(
        {"tenant_id": tid,
         "name": "merge_income_categories_duplicates_v1"},
    ))
    assert run_doc is None


# ═══════════════════════════════════════════════════════════════════
# 2. Apply mode — counts match dry-run; dupes soft-deleted; FK
#    rewrites + backfill verified.
# ═══════════════════════════════════════════════════════════════════
def test_apply_merges_and_backfills(clean):
    tid = _tid("applytid")
    _run(_seed_tenant(tid))
    winner = _run(_seed_cat(tid, "Pool"))
    loser = _run(_seed_cat(tid, "pool"))
    _run(_seed_invoice(tid, [
        {"description": "W1", "quantity": 1, "unit_price": 10,
         "income_category_id": winner},
        {"description": "W2", "quantity": 1, "unit_price": 10,
         "income_category_id": winner},
        {"description": "L1", "quantity": 1, "unit_price": 10,
         "income_category_id": loser},
        {"description": "I1", "quantity": 1, "unit_price": 10,
         "category": "Pool"},
        {"description": "I2", "quantity": 1, "unit_price": 10,
         "category": "pool"},
    ]))
    result = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    totals = result["totals"]
    assert totals["sets_merged"] == 1
    assert totals["lines_fk_rewritten"] == 1
    assert totals["loser_rows_soft_deleted"] == 1
    assert totals["lines_fk_backfilled"] == 2

    # Loser soft-deleted + merged_into pointer stamped.
    loser_doc = _run(db.income_categories.find_one({"id": loser}))
    assert loser_doc["deleted_at"] is not None
    assert loser_doc["merged_into_id"] == winner
    assert loser_doc["deleted_reason"] == "duplicate_merge_v1"

    # Every line_item.income_category_id points at the winner now.
    inv_doc = _run(db.quotes.find_one({"tenant_id": tid}))
    for li in inv_doc["line_items"]:
        if li["description"].startswith(("W", "L", "I")):
            assert li.get("income_category_id") == winner
        # Inline strings preserved as-is for back-compat.
        if li["description"].startswith("I"):
            assert li.get("category") in ("Pool", "pool")

    # migration_runs audit doc written.
    run_doc = _run(db.migration_runs.find_one(
        {"tenant_id": tid,
         "name": "merge_income_categories_duplicates_v1"},
    ))
    assert run_doc is not None
    assert run_doc["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════
# 3. Second apply is a no-op.
# ═══════════════════════════════════════════════════════════════════
def test_second_apply_is_noop(clean):
    tid = _tid("noop")
    _run(_seed_tenant(tid))
    w = _run(_seed_cat(tid, "Pool"))
    l_ = _run(_seed_cat(tid, "pool"))
    _run(_seed_invoice(tid, [
        {"description": "x", "quantity": 1, "unit_price": 10,
         "income_category_id": l_},
        {"description": "y", "quantity": 1, "unit_price": 10,
         "category": "Pool"},
    ]))
    _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    second = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    t = second["totals"]
    assert t["sets_merged"] == 0
    assert t["lines_fk_rewritten"] == 0
    assert t["loser_rows_soft_deleted"] == 0
    assert t["lines_fk_backfilled"] == 0


# ═══════════════════════════════════════════════════════════════════
# 4. Cross-tenant isolation.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(clean):
    tid_a = _tid("a")
    tid_b = _tid("b")
    _run(_seed_tenant(tid_a))
    _run(_seed_tenant(tid_b))
    # Dupes in BOTH tenants, but we migrate only tenant A.
    for scoped_tid in (tid_a, tid_b):
        w = _run(_seed_cat(scoped_tid, "Pool"))
        l_ = _run(_seed_cat(scoped_tid, "pool"))
        _run(_seed_invoice(scoped_tid, [
            {"description": "x", "quantity": 1, "unit_price": 10,
             "income_category_id": l_},
        ]))
    _run(merge_income_categories_duplicates(
        db, tenant_id=tid_a, dry_run=False,
    ))
    # Tenant B losers must still be live.
    b_cats = _run(db.income_categories.find(
        {"tenant_id": tid_b},
    ).to_list(10))
    assert all(c.get("deleted_at") is None for c in b_cats)


# ═══════════════════════════════════════════════════════════════════
# 5. Tiebreak determinism — equal ref_count → lex winner stable.
# ═══════════════════════════════════════════════════════════════════
def test_tiebreak_lexicographic_stable(clean):
    tid = _tid("tiebreak")
    _run(_seed_tenant(tid))
    # Both carry equal ref_count = 1.  Lex on raw name: "Pool"
    # < "pool" (ASCII 'P' < 'p'), so "Pool" wins.
    pool_cap = _run(_seed_cat(tid, "Pool"))
    pool_low = _run(_seed_cat(tid, "pool"))
    _run(_seed_invoice(tid, [
        {"description": "a", "quantity": 1, "unit_price": 10,
         "income_category_id": pool_cap},
        {"description": "b", "quantity": 1, "unit_price": 10,
         "income_category_id": pool_low},
    ]))
    result = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    assert result["totals"]["sets_merged"] == 1
    winner_doc = _run(db.income_categories.find_one(
        {"id": pool_cap},
    ))
    loser_doc = _run(db.income_categories.find_one(
        {"id": pool_low},
    ))
    assert winner_doc.get("deleted_at") is None, (
        "Lex winner 'Pool' must survive"
    )
    assert loser_doc.get("deleted_at") is not None
    assert loser_doc.get("merged_into_id") == pool_cap


# ═══════════════════════════════════════════════════════════════════
# 6. Unmatched inline strings → logged, not written as fake FKs.
# ═══════════════════════════════════════════════════════════════════
def test_unmatched_inline_strings_logged_not_written(clean):
    tid = _tid("unmatch")
    _run(_seed_tenant(tid))
    _run(_seed_cat(tid, "Pool"))
    _run(_seed_invoice(tid, [
        {"description": "ok", "quantity": 1, "unit_price": 10,
         "category": "Pool"},
        {"description": "nope", "quantity": 1, "unit_price": 10,
         "category": "LegacyUnknownBucket"},
    ]))
    result = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    t = result["totals"]
    assert t["lines_fk_backfilled"] == 1
    assert t["unmatched_inline_names"].get("legacyunknownbucket") == 1
    # Verify DB state: nope-line still has NO FK.
    inv = _run(db.quotes.find_one({"tenant_id": tid}))
    nope = next(li for li in inv["line_items"]
                 if li["description"] == "nope")
    assert nope.get("income_category_id") in (None, "")
    assert nope.get("category") == "LegacyUnknownBucket"


# ═══════════════════════════════════════════════════════════════════
# 7. UUID-shaped inline strings are NOT fuzzy-matched by the s1
#    backfill — those are already handled by the shipped
#    ``backfill_line_item_income_category_id_v1`` migration.  This
#    pytest pins the explicit guard so a future refactor doesn't
#    cross the two migrations' responsibilities.
# ═══════════════════════════════════════════════════════════════════
def test_uuid_shaped_inline_strings_bypassed(clean):
    tid = _tid("uuidinline")
    _run(_seed_tenant(tid))
    cat_id = _run(_seed_cat(tid, "Pool"))
    other_uuid = str(uuid.uuid4())
    _run(_seed_invoice(tid, [
        {"description": "uuid-cat", "quantity": 1, "unit_price": 10,
         "category": other_uuid},
    ]))
    result = _run(merge_income_categories_duplicates(
        db, tenant_id=tid, dry_run=False,
    ))
    assert result["totals"]["lines_fk_backfilled"] == 0
    # Not even logged as unmatched — this is explicit skip, not
    # a "no live row for this normalized name" miss.
    assert not any(k == other_uuid.lower()
                   for k in result["totals"]
                       ["unmatched_inline_names"].keys())
