"""TD-invoice-customer-id-repair-on-merge · Feb-2026
================================================================

Pytest coverage for the backfill migration + the safety-belt in
the customer-merge engine.

Convention (same as ``test_k49b_customer_id_backfill.py``):
  * Sync ``pymongo`` for seed + teardown + assertion.  Motor is
    only invoked inside a single ``asyncio.run()`` per test for
    the async entrypoint under test; mixing per-test asyncio.run
    calls on Motor's shared loop-cache trips ``RuntimeError:
    Event loop is closed``.
  * Dedicated test tenant namespace keyed by ``uuid4().hex`` so
    parallel runs can't collide.

Covered scenarios:
  * Backfill picks up invoices on merged records and repoints
    them onto the canonical winner (single-hop + chain).
  * Backfill is idempotent (second run writes zero rows).
  * Chain-merge: ``X -> Y -> Z`` lands invoices on ``Z``.
  * ``--dry-run`` writes nothing.
  * ``--report-only`` writes nothing (and produces a table).
  * Safety-belt — merge-engine snapshot + rewire helpers record
    the invoice-only count in ``counts_out["quotes.invoices"]``.
  * Backfill does NOT touch non-invoice quotes.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync_db = _shared_db()


def _tnt() -> str:
    return f"_test_tenant_tdcidr_{uuid.uuid4().hex[:12]}"


def _mk_customer(tenant_id: str, name: str, *,
                   merged_into: Optional[str] = None) -> str:
    cid = f"cust_{uuid.uuid4().hex[:12]}"
    doc: Dict[str, Any] = {
        "id": cid,
        "tenant_id": tenant_id,
        "name": name,
        "is_active": True,
        "deleted_at": None,
    }
    if merged_into is not None:
        doc["merged_into"] = merged_into
        doc["merged_at"] = datetime.now(timezone.utc).isoformat()
    _sync_db.customers.insert_one(doc)
    return cid


def _mk_invoice(tenant_id: str, customer_id: str, *,
                  number: str = "INV-TEST") -> str:
    iid = f"inv_{uuid.uuid4().hex[:12]}"
    _sync_db.quotes.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": "test",
        "invoice_number": number,
        "doc_type": "invoice",
        "payment_status": "unpaid",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return iid


def _teardown(tenant_id: str) -> None:
    """Sync teardown — no asyncio involved so Motor's loop-cache
    doesn't trip."""
    _sync_db.customers.delete_many({"tenant_id": tenant_id})
    _sync_db.quotes.delete_many({"tenant_id": tenant_id})
    # Import here so a top-level import failure doesn't break
    # module collection.
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    _sync_db[mig._SENTINEL_COLLECTION].delete_many(
        {"key": mig._SENTINEL_KEY})


# ═════════════════════════════════════════════════════════════
# 1. Single-hop backfill
# ═════════════════════════════════════════════════════════════
def test_backfill_repoints_invoices_single_hop() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser", merged_into=winner)
        inv1 = _mk_invoice(tenant, loser, number="INV-T-1")
        inv2 = _mk_invoice(tenant, loser, number="INV-T-2")

        out = asyncio.run(mig.run(
            apply=True, tenant_id=tenant, force=True))
        assert out["status"] == "applied"
        assert out["stats"]["orphan_invoices"] == 2
        assert out["stats"]["invoices_moved"] == 2
        assert out["stats"]["orphan_invoices_after"] == 0

        for iid in (inv1, inv2):
            row = _sync_db.quotes.find_one(
                {"id": iid},
                {"_id": 0, "customer_id": 1,
                 "invoice_cid_repair_v1": 1})
            assert row["customer_id"] == winner
            assert row.get("invoice_cid_repair_v1", {}).get(
                "to_customer_id") == winner
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 2. Idempotency — second apply is a no-op
# ═════════════════════════════════════════════════════════════
def test_backfill_is_idempotent() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser", merged_into=winner)
        _mk_invoice(tenant, loser, number="INV-T-IDEM")

        first = asyncio.run(mig.run(
            apply=True, tenant_id=tenant, force=True))
        assert first["stats"]["invoices_moved"] == 1

        second = asyncio.run(mig.run(
            apply=True, tenant_id=tenant, force=True))
        assert second["stats"]["orphan_invoices"] == 0
        assert second["stats"]["invoices_moved"] == 0
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 3. Chain merge — X -> Y -> Z lands invoices on Z
# ═════════════════════════════════════════════════════════════
def test_backfill_walks_merge_chain() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        z = _mk_customer(tenant, "Z-canonical")
        y = _mk_customer(tenant, "Y-middle", merged_into=z)
        x = _mk_customer(tenant, "X-oldest", merged_into=y)

        iid_x = _mk_invoice(tenant, x, number="INV-T-CHAIN-X")
        iid_y = _mk_invoice(tenant, y, number="INV-T-CHAIN-Y")

        out = asyncio.run(mig.run(
            apply=True, tenant_id=tenant, force=True))
        assert out["stats"]["orphan_invoices"] == 2
        assert out["stats"]["invoices_moved"] == 2

        # Both invoices land on Z.
        for iid in (iid_x, iid_y):
            row = _sync_db.quotes.find_one(
                {"id": iid},
                {"_id": 0, "customer_id": 1,
                 "invoice_cid_repair_v1": 1})
            assert row["customer_id"] == z

        # Chain-length stamps.
        inv_x = _sync_db.quotes.find_one(
            {"id": iid_x},
            {"_id": 0, "invoice_cid_repair_v1": 1})
        assert inv_x["invoice_cid_repair_v1"]["chain_length"] == 3

        inv_y = _sync_db.quotes.find_one(
            {"id": iid_y},
            {"_id": 0, "invoice_cid_repair_v1": 1})
        assert inv_y["invoice_cid_repair_v1"]["chain_length"] == 2
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 4. Dry-run writes nothing
# ═════════════════════════════════════════════════════════════
def test_dry_run_writes_nothing() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser", merged_into=winner)
        iid = _mk_invoice(tenant, loser, number="INV-T-DRY")

        out = asyncio.run(mig.run(apply=False, tenant_id=tenant))
        assert out["status"] == "dry-run"
        assert out["stats"]["orphan_invoices"] == 1
        assert out["stats"]["invoices_moved"] == 0

        row = _sync_db.quotes.find_one(
            {"id": iid}, {"_id": 0, "customer_id": 1})
        assert row["customer_id"] == loser  # unchanged

        sentinel = _sync_db[mig._SENTINEL_COLLECTION].find_one(
            {"key": mig._SENTINEL_KEY})
        assert sentinel is None
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 5. Report-only writes nothing
# ═════════════════════════════════════════════════════════════
def test_report_only_writes_nothing_and_produces_table() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser", merged_into=winner)
        iid = _mk_invoice(tenant, loser, number="INV-T-REPORT")

        out = asyncio.run(mig.run(
            report_only=True, tenant_id=tenant))
        assert out["status"] == "report-only"
        assert out["stats"]["orphan_invoices"] == 1
        assert out["stats"]["invoices_moved"] == 0

        row = _sync_db.quotes.find_one(
            {"id": iid}, {"_id": 0, "customer_id": 1})
        assert row["customer_id"] == loser

        sentinel = _sync_db[mig._SENTINEL_COLLECTION].find_one(
            {"key": mig._SENTINEL_KEY})
        assert sentinel is None

        table = mig._format_report_table(out)
        assert tenant in table
        assert loser in table
        assert winner in table
        assert "INV-T-REPORT" in table
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 6. Report-only + apply are mutually exclusive
# ═════════════════════════════════════════════════════════════
def test_report_only_and_apply_mutually_exclusive() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    with pytest.raises(ValueError):
        asyncio.run(mig.run(apply=True, report_only=True))


# ═════════════════════════════════════════════════════════════
# 7. Safety-belt — merge engine captures invoice sub-count
# ═════════════════════════════════════════════════════════════
def test_merge_safety_belt_records_invoice_count() -> None:
    """``_snapshot_child_record_ids`` captures the invoice subset
    separately; ``_rewire_children`` records it in ``counts_out``
    under ``quotes.invoices``.
    """
    from config import db as motor_db  # noqa: PLC0415
    from services.customers import merge as merge_svc  # noqa: PLC0415
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser")
        _mk_invoice(tenant, loser, number="INV-SB-1")
        _mk_invoice(tenant, loser, number="INV-SB-2")
        qid = f"q_{uuid.uuid4().hex[:12]}"
        _sync_db.quotes.insert_one({
            "id": qid, "tenant_id": tenant, "customer_id": loser,
            "doc_type": "quote",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        async def _exercise():
            # Rebind Motor loop so this test's fresh event loop
            # drives the client.
            try:
                from config import client as _client
                _client._io_loop = asyncio.get_running_loop()
            except Exception:
                pass
            snapshot = await merge_svc._snapshot_child_record_ids(
                motor_db, tenant_id=tenant, loser_id=loser)
            counts: Dict[str, int] = {}
            await merge_svc._rewire_children(
                motor_db, tenant_id=tenant,
                winner_id=winner, loser_id=loser,
                snapshot_ids=snapshot, counts_out=counts,
            )
            return snapshot, counts

        snapshot, counts = asyncio.run(_exercise())
        assert len(snapshot.get("quotes") or []) == 3
        assert len(snapshot.get("quotes.invoices") or []) == 2
        assert counts.get("quotes") == 3
        assert counts.get("quotes.invoices") == 2

        # Verify the rewire landed via sync pymongo.
        remaining = _sync_db.quotes.count_documents(
            {"tenant_id": tenant, "customer_id": loser,
             "doc_type": "invoice"})
        assert remaining == 0
        moved = _sync_db.quotes.count_documents(
            {"tenant_id": tenant, "customer_id": winner,
             "doc_type": "invoice"})
        assert moved == 2
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 8. Non-invoice quotes are NOT touched by the backfill
# ═════════════════════════════════════════════════════════════
def test_backfill_leaves_quotes_and_estimates_alone() -> None:
    from migrations import invoice_customer_id_repoint_merged_v1 as mig
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "winner")
        loser = _mk_customer(tenant, "loser", merged_into=winner)
        iid = _mk_invoice(tenant, loser, number="INV-T-ONLY")
        qid = f"q_{uuid.uuid4().hex[:12]}"
        _sync_db.quotes.insert_one({
            "id": qid, "tenant_id": tenant, "customer_id": loser,
            "doc_type": "quote",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        asyncio.run(mig.run(
            apply=True, tenant_id=tenant, force=True))

        inv = _sync_db.quotes.find_one(
            {"id": iid}, {"_id": 0, "customer_id": 1})
        assert inv["customer_id"] == winner
        q = _sync_db.quotes.find_one(
            {"id": qid}, {"_id": 0, "customer_id": 1})
        assert q["customer_id"] == loser  # NOT touched
    finally:
        _teardown(tenant)
