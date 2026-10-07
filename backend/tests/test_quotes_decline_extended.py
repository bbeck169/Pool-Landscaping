"""QUOTES-OPEN-TAB-DECLINE-EXTEND · Feb-2026 — extended decline coverage.

Complements the Phase-3 B1 coverage in ``test_quote_decline_reopen.py``
by closing the three gaps introduced by the policy extension:

* Transition from ``status=viewed`` → ``declined`` (view-tracker-bumped
  quotes used to be blocked by the frontend's narrow 3-status gate).
* Transition from ``status=cancelled`` → ``declined`` (soft-deleted
  quotes used to be effectively unreachable by Decline).
* ``cancelled_at`` + ``cancelled_by`` metadata survives the surgical
  ``$set`` and ``declined_at`` / ``declined_by`` are stamped fresh.
* ``doc_edit_audit`` row written with ``event="admin_decline"``,
  ``cancelled_at_preserved`` reflecting the pre-mutation shape, and
  the full editor identity triple.

Follows the ``_clean`` autouse fixture pattern already standardised
in ``test_quote_decline_reopen.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    import sys as _sys
    for mod in ("routers.quotes",):
        __import__(mod)
        _sys.modules[mod].db = _DB


PREFIX = f"qdx-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
_ADMIN      = {"id": f"{PREFIX}-u-admin",
                "role": "admin",
                "email": "admin@example.test"}
_SUPERADMIN = {"id": f"{PREFIX}-u-super",
                "role": "super_admin",
                "email": "super@example.test"}
_OWNER      = {"id": f"{PREFIX}-u-owner",
                "role": "owner",
                "email": "owner@example.test"}
_MANAGER    = {"id": f"{PREFIX}-u-manager",
                "role": "manager",
                "email": "manager@example.test"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}", "settings": {},
    })


async def _seed_quote(qid, tid, **fields):
    doc = {
        "id": qid,
        "tenant_id": tid,
        "doc_type": fields.pop("doc_type", "quote"),
        "status": fields.pop("status", "draft"),
        "title": f"Quote {qid}",
        "customer_id": fields.pop("customer_id", "cust-1"),
        "customer_name": "Carla Cust",
        "total": 500.0,
        "line_items": [{"description": "Line", "quantity": 1,
                         "unit_price": 500.0, "category": "service"}],
        "created_at": "2026-02-03T00:00:00+00:00",
    }
    doc.update(fields)
    await _DB.quotes.insert_one(doc)
    return doc


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "audit_logs", "doc_edit_audit"):
        await _DB[coll].delete_many({
            "$or": [{"id": rx}, {"tenant_id": rx},
                     {"doc_id": rx}, {"entity_id": rx}],
        })
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


# ═════════════════════════════════════════════════════════════════════
# Extended transition matrix — ``viewed`` and ``cancelled``
# ═════════════════════════════════════════════════════════════════════
def test_decline_from_viewed_stores_previous_status_viewed():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-viewed"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, status="viewed"))

    res = _run(decline_quote(qid=qid, user=_ADMIN,
                              tenant={"id": TENANT_A}))
    assert res["status"] == "declined"
    assert res["previous_status"] == "viewed"
    assert res["declined_at"]

    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["status"] == "declined"
    assert doc["previous_status"] == "viewed"
    assert doc["declined_by"] == _ADMIN["id"]


def test_decline_from_cancelled_preserves_cancelled_metadata():
    """Soft-cancelled → declined reclassification must preserve the
    historic ``cancelled_at`` / ``cancelled_by`` stamps while
    stamping ``declined_at`` / ``declined_by`` fresh."""
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-cancelled"
    cancelled_at = "2026-02-05T10:00:00+00:00"
    cancelled_by = f"{PREFIX}-u-prior"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(
        qid, TENANT_A, status="cancelled",
        cancelled_at=cancelled_at, cancelled_by=cancelled_by,
    ))

    res = _run(decline_quote(qid=qid, user=_ADMIN,
                              tenant={"id": TENANT_A}))
    assert res["status"] == "declined"
    assert res["previous_status"] == "cancelled"

    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["status"] == "declined"
    assert doc["previous_status"] == "cancelled"
    # Historic cancellation stamps survived.
    assert doc["cancelled_at"] == cancelled_at
    assert doc["cancelled_by"] == cancelled_by
    # Fresh decline stamps applied.
    assert doc["declined_at"]
    assert doc["declined_by"] == _ADMIN["id"]


# ═════════════════════════════════════════════════════════════════════
# RBAC — mirror the shape of the Issue-Credit role set
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user", [_ADMIN, _SUPERADMIN, _OWNER, _MANAGER])
def test_decline_role_matrix_succeeds_for_privileged_roles(user):
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-rbac-{user['role']}"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, status="sent"))

    res = _run(decline_quote(qid=qid, user=user,
                              tenant={"id": TENANT_A}))
    assert res["status"] == "declined"


# ═════════════════════════════════════════════════════════════════════
# ``doc_edit_audit`` — new audit trail
# ═════════════════════════════════════════════════════════════════════
def test_decline_writes_doc_edit_audit_row_for_sent_quote():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-audit-sent"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, status="sent"))

    _run(decline_quote(qid=qid, user=_ADMIN,
                        tenant={"id": TENANT_A}))

    rows = _run(_DB.doc_edit_audit
                .find({"doc_id": qid}, {"_id": 0})
                .to_list(length=None))
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "admin_decline"
    assert row["tenant_id"] == TENANT_A
    assert row["doc_id"] == qid
    assert row["doc_type"] == "estimate"
    assert row["status_before"] == "sent"
    assert row["editor_user_id"] == _ADMIN["id"]
    assert row["editor_email"] == _ADMIN["email"]
    assert row["editor_role"] == _ADMIN["role"]
    assert row["cancelled_at_preserved"] is False
    assert "T" in row["at"]  # ISO-8601 timestamp


def test_decline_writes_doc_edit_audit_row_flagging_cancelled_preserved():
    """Cancelled→declined row must flip the ``cancelled_at_preserved``
    boolean to True so ops can filter the audit feed."""
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-audit-cancelled"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(
        qid, TENANT_A, status="cancelled",
        cancelled_at="2026-02-05T10:00:00+00:00",
        cancelled_by=f"{PREFIX}-u-prior",
    ))

    _run(decline_quote(qid=qid, user=_ADMIN,
                        tenant={"id": TENANT_A}))

    rows = _run(_DB.doc_edit_audit
                .find({"doc_id": qid}, {"_id": 0})
                .to_list(length=None))
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "admin_decline"
    assert row["status_before"] == "cancelled"
    assert row["cancelled_at_preserved"] is True


def test_decline_does_not_write_doc_edit_audit_for_invoice_rejection():
    """Guard rejections (``not_a_quote``) must NOT leave a stray
    ``admin_decline`` audit row on the doc_edit_audit collection —
    the audit write happens AFTER the ``$set`` so a 400 short-circuit
    skips it entirely."""
    from fastapi import HTTPException
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-inv-reject"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid, TENANT_A, doc_type="invoice", status="draft"))

    with pytest.raises(HTTPException) as exc:
        _run(decline_quote(qid=qid, user=_ADMIN,
                            tenant={"id": TENANT_A}))
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "not_a_quote"

    rows = _run(_DB.doc_edit_audit
                .find({"doc_id": qid})
                .to_list(length=None))
    assert rows == []
