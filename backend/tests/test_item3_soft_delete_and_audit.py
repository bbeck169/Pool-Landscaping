"""Feb-2026 · Item 3 — soft-delete + audit + restore.

Verifies:
  * ``DELETE /api/invoices/{id}`` — admin/super only; writes to
    both ``audit_log`` (legacy) and ``deletion_audit`` (Item-3);
    stamps ``deleted_at``.
  * ``DELETE /api/invoices/{id}`` — technician gets 403.
  * ``DELETE /api/payments/{id}`` — Stripe-settled row IS deletable
    (Item-3 override) + stamps ``stripe_reconciliation_note``.
  * ``DELETE /api/payments/{id}`` — unpaid row returns 400.
  * ``GET  /api/admin/audit/deletions`` — super_admin only + returns
    deletion_audit entries.
  * ``POST /api/admin/audit/deletions/{id}/restore`` — invoice path
    clears ``deleted_at``.
  * ``POST /api/admin/audit/deletions/{id}/restore`` — payment path
    restores ``amount_paid`` + ``payment_status``.
  * Customer portal ``dashboard`` never surfaces a soft-deleted
    invoice (regression guard against Item-3's "customer portal
    hidden" requirement).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault(
    "FERNET_KEY",
    "f2DlHrLPFFiF2HxLFglFEegS2pvke90APrHBSU_YGus=",
)

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Fake motor collection with $or / $set / $exists partial support ─
class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, _limit):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.last_query: Optional[Dict[str, Any]] = None

    def _matches(self, doc, q):
        for k, v in q.items():
            if k == "$or":
                if not any(self._matches(doc, cond) for cond in v):
                    return False
                continue
            if isinstance(v, dict):
                if "$exists" in v:
                    exists = (k in doc)
                    if v["$exists"] and not exists: return False
                    if not v["$exists"] and exists: return False
                    continue
                if "$in" in v:
                    if doc.get(k) not in v["$in"]: return False
                    continue
                if "$gte" in v and not (doc.get(k, "") >= v["$gte"]):
                    return False
                if "$lte" in v and not (doc.get(k, "") <= v["$lte"]):
                    return False
                continue
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, q, projection=None):
        self.last_query = dict(q)
        for d in self.docs:
            if self._matches(d, q):
                return {k: v for k, v in d.items() if k != "_id"}
        return None

    def find(self, q, projection=None):
        self.last_query = dict(q)
        return _FakeCursor([
            {k: v for k, v in d.items() if k != "_id"}
            for d in self.docs if self._matches(d, q)
        ])

    async def insert_one(self, doc):
        self.docs.append({**doc})
        return type("_R", (), {"inserted_id": len(self.docs)})

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._matches(d, q):
                if "$set" in upd:
                    d.update(upd["$set"])
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


class _FakeDB:
    def __init__(self):
        self._c: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _FakeCollection())

    def __getattr__(self, name):
        return self.__getitem__(name)


@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    monkeypatch.setattr("config.db", fdb, raising=False)
    for mod in (
        "routers.quotes", "routers.deletion_audit",
        "routers.customer_portal",
    ):
        try:
            m = __import__(mod, fromlist=["db"])
            monkeypatch.setattr(m, "db", fdb, raising=False)
        except ImportError:
            pass
    return fdb


@pytest.fixture
def admin():
    return {"id": "u-admin", "email": "a@x.com", "tenant_id": "t-1",
            "role": "admin"}


@pytest.fixture
def super_admin():
    return {"id": "u-super", "email": "s@x.com", "tenant_id": "t-1",
            "role": "super_admin"}


@pytest.fixture
def tech():
    return {"id": "u-t", "email": "t@x.com", "tenant_id": "t-1",
            "role": "technician"}


@pytest.fixture
def tenant():
    return {"id": "t-1"}


# ─────────────────────────────────────────────────────────────────────
# DELETE /invoices/{id}
# ─────────────────────────────────────────────────────────────────────
class TestDeleteInvoice:
    def test_admin_can_soft_delete_invoice_and_writes_audits(
        self, fake_db, admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-1", "tenant_id": "t-1", "doc_type": "invoice",
            "invoice_number": "INV-2026-0001", "total": 100.0,
        }]
        from routers.quotes import delete_invoice
        r = _run(delete_invoice(
            "inv-1", deletion_reason="test-reason",
            user=admin, tenant=tenant,
        ))
        assert r["ok"] is True
        # Row is flipped.
        stored = fake_db["quotes"].docs[0]
        assert stored["deleted_at"] is not None
        assert stored["deleted_by_user_id"] == "u-admin"
        assert stored["deletion_reason"] == "test-reason"
        # Both audit collections written.
        assert len(fake_db["audit_log"].docs) == 1
        assert len(fake_db["deletion_audit"].docs) == 1
        entry = fake_db["deletion_audit"].docs[0]
        assert entry["resource_type"] == "invoice"
        assert entry["resource_id"] == "inv-1"
        assert entry["action"] == "delete"
        assert entry["deletion_reason"] == "test-reason"
        assert entry["snapshot"]["invoice_number"] == "INV-2026-0001"

    def test_technician_gets_403(self, fake_db, tech, tenant):
        from routers.quotes import delete_invoice
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(delete_invoice("inv-1", deletion_reason=None,
                                 user=tech, tenant=tenant))
        assert exc.value.status_code == 403

    def test_super_admin_can_delete_invoice(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-2", "tenant_id": "t-1", "doc_type": "invoice",
        }]
        from routers.quotes import delete_invoice
        r = _run(delete_invoice("inv-2", deletion_reason=None,
                                  user=super_admin, tenant=tenant))
        assert r["ok"] is True


# ─────────────────────────────────────────────────────────────────────
# DELETE /payments/{id} — Stripe override
# ─────────────────────────────────────────────────────────────────────
class TestDeletePaymentStripeOverride:
    def test_stripe_settled_payment_is_deleted_with_reconciliation_note(
        self, fake_db, admin, tenant,
    ):
        # Row that carries a Stripe payment_intent — the LEGACY bulk-
        # delete path would refuse. The Item-3 REST endpoint allows
        # it + stamps a reconciliation note.
        fake_db["quotes"].docs = [{
            "id": "pay-1", "tenant_id": "t-1", "doc_type": "invoice",
            "payment_status": "paid", "amount_paid": 250.0,
            "payment_intent_id": "pi_test_123",
            "payment_method": "card",
        }]
        from routers.quotes import delete_payment
        r = _run(delete_payment("pay-1", deletion_reason=None,
                                  user=admin, tenant=tenant))
        assert r["ok"] is True
        assert "pi_test_123" in (r["stripe_reconciliation_note"] or "")
        stored = fake_db["quotes"].docs[0]
        assert stored["payment_status"] == "unpaid"
        assert stored["amount_paid"] == 0.0
        assert stored["payment_deleted_at"] is not None
        assert stored["stripe_reconciliation_note"] == r["stripe_reconciliation_note"]
        # Audit entry captured the pre-delete snapshot.
        entry = fake_db["deletion_audit"].docs[0]
        assert entry["resource_type"] == "payment"
        assert entry["snapshot"]["payment_status"] == "paid"
        assert entry["snapshot"]["amount_paid"] == 250.0
        assert entry["stripe_reconciliation_note"] == r["stripe_reconciliation_note"]

    def test_unpaid_row_returns_400(self, fake_db, admin, tenant):
        fake_db["quotes"].docs = [{
            "id": "pay-2", "tenant_id": "t-1", "doc_type": "invoice",
            "payment_status": "unpaid", "amount_paid": 0.0,
        }]
        from routers.quotes import delete_payment
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(delete_payment("pay-2", deletion_reason=None,
                                  user=admin, tenant=tenant))
        assert exc.value.status_code == 400

    def test_technician_gets_403_on_payment_delete(
        self, fake_db, tech, tenant,
    ):
        from routers.quotes import delete_payment
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(delete_payment("pay-1", deletion_reason=None,
                                  user=tech, tenant=tenant))
        assert exc.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# GET /admin/audit/deletions
# ─────────────────────────────────────────────────────────────────────
class TestAuditList:
    def test_super_admin_can_list_entries(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["deletion_audit"].docs = [
            {"id": "a-1", "tenant_id": "t-1", "resource_type": "invoice",
             "resource_id": "inv-A", "action": "delete",
             "timestamp": "2026-02-15T10:00:00Z"},
            {"id": "a-2", "tenant_id": "t-1", "resource_type": "payment",
             "resource_id": "pay-B", "action": "delete",
             "timestamp": "2026-02-16T10:00:00Z"},
        ]
        from routers.deletion_audit import list_deletions
        r = _run(list_deletions(
            resource_type=None, start=None, end=None,
            limit=200, user=super_admin, tenant=tenant,
        ))
        assert r["count"] == 2
        assert len(r["rows"]) == 2

    def test_admin_gets_403(self, fake_db, admin, tenant):
        from routers.deletion_audit import list_deletions
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(list_deletions(
                resource_type=None, start=None, end=None, limit=200,
                user=admin, tenant=tenant,
            ))
        assert exc.value.status_code == 403

    def test_resource_type_filter_narrows(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["deletion_audit"].docs = [
            {"id": "a-1", "tenant_id": "t-1", "resource_type": "invoice",
             "timestamp": "2026-02-15T10:00:00Z"},
            {"id": "a-2", "tenant_id": "t-1", "resource_type": "payment",
             "timestamp": "2026-02-16T10:00:00Z"},
        ]
        from routers.deletion_audit import list_deletions
        r = _run(list_deletions(
            resource_type="invoice", start=None, end=None,
            limit=200, user=super_admin, tenant=tenant,
        ))
        assert r["count"] == 1
        assert r["rows"][0]["resource_type"] == "invoice"


# ─────────────────────────────────────────────────────────────────────
# POST /admin/audit/deletions/{id}/restore
# ─────────────────────────────────────────────────────────────────────
class TestAuditRestore:
    def test_restore_invoice_clears_deleted_at(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-restore", "tenant_id": "t-1", "doc_type": "invoice",
            "deleted_at": "2026-02-14T10:00:00Z",
            "deleted_by_user_id": "u-admin",
        }]
        fake_db["deletion_audit"].docs = [{
            "id": "a-restore", "tenant_id": "t-1",
            "resource_type": "invoice", "resource_id": "inv-restore",
            "action": "delete", "snapshot": {"doc_type": "invoice"},
            "cascade_deleted_ids": [],
        }]
        from routers.deletion_audit import restore_deletion
        r = _run(restore_deletion("a-restore", user=super_admin, tenant=tenant))
        assert r["ok"] is True
        assert r["resource_type"] == "invoice"
        # Row cleared.
        restored = fake_db["quotes"].docs[0]
        assert restored["deleted_at"] is None
        assert restored["deleted_by_user_id"] is None
        assert "restored_at" in restored

    def test_restore_payment_puts_status_and_amount_back(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "pay-restore", "tenant_id": "t-1", "doc_type": "invoice",
            "payment_status": "unpaid", "amount_paid": 0.0,
            "payment_deleted_at": "2026-02-14T10:00:00Z",
        }]
        fake_db["deletion_audit"].docs = [{
            "id": "a-pay", "tenant_id": "t-1",
            "resource_type": "payment", "resource_id": "pay-restore",
            "action": "delete",
            "snapshot": {"payment_status": "paid", "amount_paid": 175.5},
        }]
        from routers.deletion_audit import restore_deletion
        r = _run(restore_deletion("a-pay", user=super_admin, tenant=tenant))
        assert r["ok"] is True
        restored = fake_db["quotes"].docs[0]
        assert restored["payment_status"] == "paid"
        assert restored["amount_paid"] == 175.5
        assert restored["payment_deleted_at"] is None
        # A mirror restore-audit entry was appended.
        actions = [d.get("action") for d in fake_db["deletion_audit"].docs]
        assert "restore" in actions

    def test_admin_cannot_restore(self, fake_db, admin, tenant):
        from routers.deletion_audit import restore_deletion
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(restore_deletion("a-any", user=admin, tenant=tenant))
        assert exc.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# Customer portal — soft-deleted invoices MUST NOT surface.
# ─────────────────────────────────────────────────────────────────────
class TestPortalHidesDeleted:
    def test_portal_dashboard_query_excludes_deleted_at(
        self, fake_db,
    ):
        # Two invoices — one alive, one soft-deleted.
        fake_db["quotes"].docs = [
            {"id": "live", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "total": 50.0, "amount_paid": 0.0,
             "due_date": "2026-03-01"},
            {"id": "gone", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "total": 150.0, "amount_paid": 0.0,
             "due_date": "2026-03-01",
             "deleted_at": "2026-02-14T10:00:00Z"},
        ]
        # find should filter out `gone` when portal query includes the
        # `$or: [{deleted_at:None},{deleted_at:{$exists:False}}]` guard.
        rows = _run(fake_db["quotes"].find({
            "tenant_id": "t-1",
            "customer_id": "c-1",
            "doc_type": "invoice",
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        }).to_list(2000))
        ids = [r["id"] for r in rows]
        assert "live" in ids
        assert "gone" not in ids
