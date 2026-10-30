"""Feb-2026 · pytest for the ``backfill_line_item_income_category_id_v1``
migration — Commit 2 of TD-new-invoice-category-dropdown-persist.

Operator spec cases:
  (1) Backfill fixture with 3 stuck lines → all stamped correctly.
  (2) Re-run → zero updates (idempotent).
  (3) Unresolvable name → logged, line left untouched.

Pattern mirrors the shipped
``test_backfill_paid_invoice_status_v1.py`` — pymongo sync for
assertions + Motor on an isolated event loop for the async call.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

_PFX = "TESTbfici_"
_TENANT = f"{_PFX}tenant"

_sync_client = MongoClient(MONGO_URL)
_sync_db = _sync_client[DB_NAME]


def _wipe():
    _sync_db.quotes.delete_many({"id": {"$regex": f"^{_PFX}"}})
    _sync_db.income_categories.delete_many({"id": {"$regex": f"^{_PFX}"}})
    _sync_db.migration_runs.delete_many(
        {"migration": "backfill_line_item_income_category_id_v1",
         "tenant_id": {"$regex": f"^{_PFX}"}},
    )


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


def _seed_cat(name: str, *, archived: bool = False) -> str:
    cid = f"{_PFX}cat_{uuid.uuid4().hex[:8]}"
    _sync_db.income_categories.insert_one({
        "id": cid, "tenant_id": _TENANT, "name": name,
        "is_archived": archived,
    })
    return cid


def _seed_invoice(line_specs):
    """``line_specs`` = list of ``{category, income_category_id?}``.
    Returns the invoice id."""
    iid = f"{_PFX}inv_{uuid.uuid4().hex[:10]}"
    lines = []
    for i, spec in enumerate(line_specs):
        li = {"description": f"line {i}", "quantity": 1, "unit_price": 10}
        li.update(spec)
        lines.append(li)
    _sync_db.quotes.insert_one({
        "id": iid, "tenant_id": _TENANT, "doc_type": "invoice",
        "line_items": lines,
    })
    return iid


def _run(**kwargs):
    from motor.motor_asyncio import AsyncIOMotorClient
    from migrations.backfill_line_item_income_category_id_v1 import (
        backfill_line_item_income_category_id,
    )
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        mdb = AsyncIOMotorClient(MONGO_URL, io_loop=loop)[DB_NAME]
        return loop.run_until_complete(
            backfill_line_item_income_category_id(mdb, **kwargs),
        )
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
# §1 · Operator case (1) — 3 stuck lines stamp correctly
# ═══════════════════════════════════════════════════════════════════
def test_backfill_stamps_three_stuck_lines():
    cid_pool  = _seed_cat("Pool")
    cid_other = _seed_cat("Other")
    cid_late  = _seed_cat("Late Fee")
    iid = _seed_invoice([
        {"category": "Pool"},
        {"category": "other"},      # case-insensitive
        {"category": "Late Fee"},
    ])

    dry = _run(tenant_id=_TENANT, dry_run=True)
    assert dry["matched_invoices"] == 1
    assert dry["lines_stamped"] == 3
    assert dry["lines_unresolved"] == 0
    # DB untouched on dry.
    for li in _sync_db.quotes.find_one({"id": iid})["line_items"]:
        assert "income_category_id" not in li

    real = _run(tenant_id=_TENANT, dry_run=False)
    assert real["matched_invoices"] == 1
    assert real["modified_invoices"] == 1
    assert real["lines_stamped"] == 3
    assert real["lines_unresolved"] == 0

    lines = _sync_db.quotes.find_one({"id": iid})["line_items"]
    assert lines[0]["income_category_id"] == cid_pool
    assert lines[1]["income_category_id"] == cid_other
    assert lines[2]["income_category_id"] == cid_late
    # Legacy ``category`` string preserved on every line.
    assert lines[0]["category"] == "Pool"
    assert lines[1]["category"] == "other"
    assert lines[2]["category"] == "Late Fee"
    # Provenance.
    for li in lines:
        assert li["backfilled_by"] == "backfill_line_item_income_category_id_v1"
        assert "backfilled_at" in li

    # Audit row written.
    audit = _sync_db.migration_runs.find_one({
        "migration": "backfill_line_item_income_category_id_v1",
        "tenant_id": _TENANT,
    })
    assert audit is not None
    assert audit["modified_invoices"] == 1
    assert audit["lines_stamped"] == 3


# ═══════════════════════════════════════════════════════════════════
# §2 · Operator case (2) — rerun is idempotent (zero updates)
# ═══════════════════════════════════════════════════════════════════
def test_backfill_rerun_is_idempotent():
    _seed_cat("Pool")
    _seed_invoice([{"category": "Pool"}])

    first = _run(tenant_id=_TENANT, dry_run=False)
    assert first["lines_stamped"] == 1
    assert first["modified_invoices"] == 1

    second = _run(tenant_id=_TENANT, dry_run=False)
    assert second["matched_invoices"] == 0, (
        f"re-run should be no-op: {second!r}"
    )
    assert second["modified_invoices"] == 0
    assert second["lines_stamped"] == 0


# ═══════════════════════════════════════════════════════════════════
# §3 · Operator case (3) — unresolvable name is skipped, not invented
# ═══════════════════════════════════════════════════════════════════
def test_backfill_leaves_unresolvable_names_untouched():
    cid_pool = _seed_cat("Pool")
    iid = _seed_invoice([
        {"category": "Pool"},                # resolves
        {"category": "DoesNotExist"},        # does not resolve
        {"category": "AnotherGhost"},        # does not resolve
    ])

    real = _run(tenant_id=_TENANT, dry_run=False)
    assert real["matched_invoices"] == 1
    assert real["modified_invoices"] == 1
    assert real["lines_stamped"] == 1
    assert real["lines_unresolved"] == 2

    lines = _sync_db.quotes.find_one({"id": iid})["line_items"]
    assert lines[0]["income_category_id"] == cid_pool
    # Unresolvable rows left untouched — the backfill NEVER invents
    # an id. ``income_category_id`` must stay absent.
    assert "income_category_id" not in lines[1]
    assert "income_category_id" not in lines[2]
    assert "backfilled_at" not in lines[1]
    assert "backfilled_at" not in lines[2]


# ═══════════════════════════════════════════════════════════════════
# §4 · UUID-shaped category values resolve via the by_id branch
# ═══════════════════════════════════════════════════════════════════
def test_backfill_resolves_uuid_shaped_category_values():
    """Some stuck lines carry a UUID in ``category`` (legacy data
    artifact from a shipped-but-not-fully-wired path). These must
    resolve via the ``category == id`` branch."""
    cid = _seed_cat("Pool")
    iid = _seed_invoice([{"category": cid}])  # UUID in category slot

    real = _run(tenant_id=_TENANT, dry_run=False)
    assert real["lines_stamped"] == 1
    lines = _sync_db.quotes.find_one({"id": iid})["line_items"]
    assert lines[0]["income_category_id"] == cid


# ═══════════════════════════════════════════════════════════════════
# §5 · Archived rows are NOT candidates
# ═══════════════════════════════════════════════════════════════════
def test_backfill_skips_archived_category_matches():
    """A category name that only matches an ARCHIVED income
    category must NOT be stamped — the shipped validator soft-
    passes archived refs via a separate helper
    (``soft_pass_archived_ref_in_line_item``) and we leave that
    path to the live write, don't re-invent here."""
    _seed_cat("Pool", archived=True)  # only archived match
    iid = _seed_invoice([{"category": "Pool"}])

    real = _run(tenant_id=_TENANT, dry_run=False)
    assert real["lines_stamped"] == 0
    assert real["lines_unresolved"] == 1
    assert "income_category_id" not in _sync_db.quotes.find_one(
        {"id": iid},
    )["line_items"][0]
