"""
Feb-2026 · Editable Sent Docs · Phase 2 — versions endpoint tests.

Covers the Phase-2 alias endpoints
    * ``GET /api/invoices/{id}/versions``
    * ``GET /api/quotes/{qid}/versions``
plus the ``compute_change_summary`` helper that runs at write time.

The tests do NOT hit ASGI directly (avoiding another fresh-loop
motor client fight with the Phase-1 tests); they call the router
callables directly with fake ``user`` / ``tenant`` inputs, which
is sufficient to exercise:
  * tenant scoping / 404 discipline (invoice id → quote path → 404)
  * newest-first ordering + snapshot inline
  * created_by name hydration
  * baseline vs. non-baseline shape (change_summary: None on baseline)
  * write-time change_summary field content
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import pytest


_MARK = "phase2-versions"


_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro):
    assert _LOOP is not None, "session fixture not initialised"
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    global _LOOP
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.document_versions as _dv
    _dv.db = fresh_db
    import services.documents.versions as _sv
    _sv.db = fresh_db
    yield
    _LOOP.close()
    _LOOP = None


def _db():
    import config as _cfg
    return _cfg.db


@pytest.fixture()
def seeded():
    tid = f"{_MARK}-t"
    uid1 = f"{_MARK}-u1"
    uid2 = f"{_MARK}-u2"
    inv_id = f"{_MARK}-inv"
    est_id = f"{_MARK}-est"
    _run(_db().tenants.insert_one({
        "id": tid, "slug": _MARK, "company_name": "Phase-2 Co",
    }))
    _run(_db().users.insert_many([
        {"id": uid1, "email": "alice@p2.com", "first_name": "Alice",
         "last_name": "Anderson", "tenant_id": tid, "role": "admin"},
        {"id": uid2, "email": "bob@p2.com", "full_name": "Bob B",
         "tenant_id": tid, "role": "super_admin"},
    ]))
    _run(_db().quotes.insert_many([
        {"id": inv_id, "tenant_id": tid, "doc_type": "invoice",
         "customer_id": "c1", "customer_name": "Ck",
         "status": "sent", "invoice_number": "INV-2001",
         "total": 100.0, "amount_paid": 0.0, "line_items": []},
        {"id": est_id, "tenant_id": tid, "doc_type": "estimate",
         "customer_id": "c1", "customer_name": "Ck",
         "status": "sent", "invoice_number": "EST-11",
         "total": 500.0, "line_items": []},
    ]))
    yield {"tid": tid, "uid1": uid1, "uid2": uid2,
             "inv_id": inv_id, "est_id": est_id}
    _run(_db().tenants.delete_many({"id": tid}))
    _run(_db().users.delete_many({"id": {"$in": [uid1, uid2]}}))
    _run(_db().quotes.delete_many({"id": {"$in": [inv_id, est_id]}}))
    _run(_db().document_versions.delete_many({"tenant_id": tid}))
    _run(_db().doc_versions_rate.delete_many(
        {"user_id": {"$in": [uid1, uid2]}},
    ))


# ── compute_change_summary unit tests ────────────────────────────
def test_compute_change_summary_baseline_returns_none():
    from services.documents.versions import compute_change_summary
    r = compute_change_summary(None, {"total": 100.0})
    assert r == {"change_summary": None, "diff_field_count": 0}


def test_compute_change_summary_line_item_add_edit_remove():
    from services.documents.versions import compute_change_summary
    prev = {
        "line_items": [
            {"description": "Pool clean", "qty": 1, "unit_price": 100},
            {"description": "Filter swap", "qty": 1, "unit_price": 50},
        ],
        "subtotal": 150.0, "total": 162.5,
    }
    curr = {
        "line_items": [
            {"description": "Pool clean", "qty": 2, "unit_price": 100},
            {"description": "Chem balance", "qty": 1, "unit_price": 40},
        ],
        "subtotal": 240.0, "total": 259.2,
    }
    r = compute_change_summary(prev, curr)
    s = r["change_summary"] or ""
    assert "line item" in s and "edited" in s
    assert "subtotal +$90.00" in s
    assert "total +$96.70" in s
    assert r["diff_field_count"] >= 3


def test_compute_change_summary_notes_only():
    from services.documents.versions import compute_change_summary
    r = compute_change_summary({"notes": "old"}, {"notes": "new"})
    assert r["change_summary"] == "Notes updated"
    assert r["diff_field_count"] == 1


def test_compute_change_summary_identical_returns_none():
    from services.documents.versions import compute_change_summary
    snap = {"total": 100.0, "line_items": [{"description": "x", "qty": 1}]}
    r = compute_change_summary(snap, snap)
    assert r == {"change_summary": None, "diff_field_count": 0}


# ── Endpoint tests ───────────────────────────────────────────────
def test_list_invoice_versions_returns_ordered_snapshots(seeded):
    from routers.document_versions import list_invoice_versions
    tid, inv_id, uid1 = seeded["tid"], seeded["inv_id"], seeded["uid1"]
    async def _do():
        # Seed 3 versions manually — v1 baseline, v2, v3.
        rows = [
            {"id": "vid-1", "doc_type": "invoice", "doc_id": inv_id,
             "tenant_id": tid, "version": 1, "is_baseline": True,
             "snapshot": {"total": 100.0}, "saved_by_user_id": "system",
             "saved_by_user_email": "system", "saved_by_role": "system",
             "saved_at": "2026-02-01T00:00:00+00:00",
             "status_at_edit": "sent",
             "change_summary": None, "diff_field_count": 0,
             "signature_invalidated": False, "lock_bypass_ack": False},
            {"id": "vid-2", "doc_type": "invoice", "doc_id": inv_id,
             "tenant_id": tid, "version": 2, "is_baseline": False,
             "snapshot": {"total": 120.0}, "saved_by_user_id": uid1,
             "saved_by_user_email": "alice@p2.com", "saved_by_role": "admin",
             "saved_at": "2026-02-02T00:00:00+00:00",
             "status_at_edit": "sent",
             "change_summary": "total +$20.00", "diff_field_count": 1,
             "signature_invalidated": False, "lock_bypass_ack": False},
            {"id": "vid-3", "doc_type": "invoice", "doc_id": inv_id,
             "tenant_id": tid, "version": 3, "is_baseline": False,
             "snapshot": {"total": 150.0}, "saved_by_user_id": uid1,
             "saved_by_user_email": "alice@p2.com", "saved_by_role": "admin",
             "saved_at": "2026-02-03T00:00:00+00:00",
             "status_at_edit": "sent",
             "change_summary": "total +$30.00", "diff_field_count": 1,
             "signature_invalidated": False, "lock_bypass_ack": False},
        ]
        await _db().document_versions.insert_many(rows)

        res = await list_invoice_versions(
            id=inv_id,
            user={"id": uid1, "role": "admin", "tenant_id": tid,
                  "email": "alice@p2.com"},
        )
        assert res["total"] == 3
        assert [i["version"] for i in res["items"]] == [3, 2, 1]
        top = res["items"][0]
        assert top["version_id"] == "vid-3"
        assert top["change_summary"] == "total +$30.00"
        assert top["diff_field_count"] == 1
        assert top["document_snapshot"] == {"total": 150.0}
        assert top["created_by"]["email"] == "alice@p2.com"
        # display name hydrated from users collection.
        assert top["created_by"]["name"] == "Alice Anderson"
        # Baseline entry has change_summary=None.
        base = res["items"][-1]
        assert base["is_baseline"] is True
        assert base["change_summary"] is None
    _run(_do())


def test_list_invoice_versions_rejects_wrong_doc_type(seeded):
    from fastapi import HTTPException
    from routers.document_versions import list_invoice_versions
    tid, est_id, uid1 = seeded["tid"], seeded["est_id"], seeded["uid1"]
    async def _do():
        try:
            await list_invoice_versions(
                id=est_id,
                user={"id": uid1, "role": "admin", "tenant_id": tid},
            )
            pytest.fail("expected 404")
        except HTTPException as e:
            assert e.status_code == 404
    _run(_do())


def test_list_quote_versions_scopes_to_tenant(seeded):
    from fastapi import HTTPException
    from routers.document_versions import list_quote_versions
    est_id = seeded["est_id"]
    async def _do():
        # Wrong-tenant caller should see 404.
        try:
            await list_quote_versions(
                qid=est_id,
                user={"id": "other-u", "role": "admin",
                       "tenant_id": "other-tenant"},
            )
            pytest.fail("expected 404")
        except HTTPException as e:
            assert e.status_code == 404
        # Same-tenant → 200 with total 0 (no snapshots seeded).
        res = await list_quote_versions(
            qid=est_id,
            user={"id": seeded["uid2"], "role": "super_admin",
                  "tenant_id": seeded["tid"]},
        )
        assert res["total"] == 0
        assert res["items"] == []
    _run(_do())


def test_list_versions_rate_limited(seeded):
    from fastapi import HTTPException
    from routers.document_versions import (
        list_invoice_versions, _RATE_MAX_PER_MINUTE,
    )
    tid, inv_id, uid1 = seeded["tid"], seeded["inv_id"], seeded["uid1"]
    async def _do():
        for _ in range(_RATE_MAX_PER_MINUTE):
            await list_invoice_versions(
                id=inv_id,
                user={"id": uid1, "role": "admin", "tenant_id": tid},
            )
        # Next hit trips the limiter.
        try:
            await list_invoice_versions(
                id=inv_id,
                user={"id": uid1, "role": "admin", "tenant_id": tid},
            )
            pytest.fail("expected 429")
        except HTTPException as e:
            assert e.status_code == 429
            detail = e.detail if isinstance(e.detail, dict) else {}
            assert detail.get("error_code") == "rate_limited"
    _run(_do())


# ── Integration — snapshot_before_mutation writes change_summary ──
def test_snapshot_writer_stamps_change_summary(seeded):
    """End-to-end shape guard: two consecutive mutations produce a
    baseline (v1), a v2 with change_summary reflecting the FIRST
    edit's target state (line items added going from 0 → 1) and a
    v3 with change_summary reflecting the SECOND edit's delta."""
    from services.documents.versions import snapshot_before_mutation
    tid, inv_id, uid1 = seeded["tid"], seeded["inv_id"], seeded["uid1"]
    user = {"id": uid1, "email": "alice@p2.com", "role": "admin"}
    async def _do():
        current_v1 = {"id": inv_id, "tenant_id": tid, "doc_type": "invoice",
                      "status": "sent", "total": 100.0, "line_items": []}
        new_v2 = {**current_v1, "total": 250.0,
                  "line_items": [{"description": "Repair", "qty": 1,
                                    "unit_price": 150}]}
        await snapshot_before_mutation(
            doc_type="invoice", doc_id=inv_id, tenant_id=tid,
            current_doc=current_v1, new_doc=new_v2,
            saved_by_user=user, status_at_edit="sent",
        )
        # Simulate the update landing.
        current_v2 = new_v2
        new_v3 = {**current_v2, "notes": "Please review",
                  "total": 275.0}
        await snapshot_before_mutation(
            doc_type="invoice", doc_id=inv_id, tenant_id=tid,
            current_doc=current_v2, new_doc=new_v3,
            saved_by_user=user, status_at_edit="sent",
        )
        rows: List[Dict[str, Any]] = []
        async for r in _db().document_versions.find(
            {"doc_id": inv_id}, {"_id": 0},
        ).sort("version", 1):
            rows.append(r)
        assert len(rows) == 3
        v1, v2, v3 = rows
        assert v1["is_baseline"] is True
        assert v1["change_summary"] is None
        # v2 diff should mention the line-item add + total delta.
        s2 = v2["change_summary"] or ""
        assert "1 line item added" in s2
        assert "total +$150.00" in s2
        # v3 diff should mention notes updated + total +25.
        s3 = v3["change_summary"] or ""
        assert "Notes updated" in s3
        assert "total +$25.00" in s3
    _run(_do())
