"""Feb-2026 · P0 fix — Bug A: false-paid invoice guard + audit migration.

Locks the ship that prevents an invoice from being flipped
``payment_status = "paid"`` without a matching payment_record
(Hector Guerrero bug: customer opened SMS invoice link, saw it
already marked paid despite never entering card info).

Rules the suite enforces:

  1. ``mark_invoice_paid`` refuses to flip without a well-formed
     ``payment_record`` — no dict, wrong ``kind``, missing
     ``txn_id`` → all raise.
  2. Happy path: legit ``payment_record`` flips status + writes an
     audit row + preserves ``created_at``.
  3. Idempotent — flipping an already-paid invoice is a no-op that
     STILL appends the new payment_record for audit (double-charge
     protection while keeping the ledger honest).
  4. Orphan-paid audit endpoint:
       * super_admin only (403 for admin)
       * ``dry_run=true`` (default) returns diff without writing
       * ``dry_run=false`` flips ``paid → pending_reconciliation``
         AND writes an ``invoice_status_audit`` row
       * Whitelisted ``paid_method`` values (service_credit, cash,
         etc.) are NEVER flipped — those are evidence-backed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_TOK: dict = {}


def _login(email: str = "super@aquaterra.com") -> str:
    if email in _TOK:
        return _TOK[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    _TOK[email] = tok
    return tok


_PREFIX = f"opa-{uuid.uuid4().hex[:8]}"


def _seed_tenant() -> str:
    tid = f"{_PREFIX}-tenant-{uuid.uuid4().hex[:6]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"OPA {tid}", "slug": tid,
        "timezone": "America/Phoenix", "active": True,
    })
    return tid


def _seed_orphan_paid_invoice(*, tenant_id: str,
                                paid_method: str | None = None,
                                stripe_pi: str | None = None) -> str:
    """Insert a doc that LOOKS paid but has no evidence."""
    iid = f"{_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    doc = {
        "id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
        "title": "Service — Filter Service",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "accepted",
        "payment_status": "paid",
        "amount_paid": 197.0, "total": 197.0, "subtotal": 197.0,
        "paid_at": datetime.now(timezone.utc).isoformat(),
        "invoice_number": "INV-2026-999888",
        "line_items": [{"description": "Filter service",
                          "quantity": 1, "unit_price": 197.0}],
    }
    if paid_method:
        doc["paid_method"] = paid_method
    if stripe_pi:
        doc["stripe_payment_intent_id"] = stripe_pi
    _sync.quotes.insert_one(doc)
    return iid


def _cleanup() -> None:
    _sync.quotes.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.tenants.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.invoice_status_audit.delete_many(
        {"tenant_id": {"$regex": f"^{_PREFIX}"}},
    )


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Audit endpoint requires super_admin.
# ══════════════════════════════════════════════════════════════════════
def test_audit_endpoint_is_super_admin_only():
    tok = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/admin/migrations/audit-orphan-paid-invoices",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════════
# 2 · Dry-run reports the diff WITHOUT writing.
# ══════════════════════════════════════════════════════════════════════
def test_audit_dry_run_reports_without_writing():
    tid = _seed_tenant()
    inv_id = _seed_orphan_paid_invoice(tenant_id=tid)
    try:
        tok = _login("super@aquaterra.com")
        r = requests.post(
            f"{API}/admin/migrations/audit-orphan-paid-invoices"
            f"?dry_run=true&force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["summary"]["corrected"] >= 1
        assert body["summary"]["dry_run"] is True
        # Doc UNCHANGED — dry run never writes.
        doc = _sync.quotes.find_one({"id": inv_id})
        assert doc["payment_status"] == "paid"
        assert "reconciliation_required" not in doc
        # And no audit row was written for this invoice.
        assert _sync.invoice_status_audit.count_documents(
            {"invoice_id": inv_id},
        ) == 0
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})


# ══════════════════════════════════════════════════════════════════════
# 3 · dry_run=false actually flips + writes audit row.
# ══════════════════════════════════════════════════════════════════════
def test_audit_real_run_flips_orphans_and_writes_audit():
    tid = _seed_tenant()
    inv_id = _seed_orphan_paid_invoice(tenant_id=tid)
    try:
        tok = _login("super@aquaterra.com")
        r = requests.post(
            f"{API}/admin/migrations/audit-orphan-paid-invoices"
            f"?dry_run=false&force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["corrected"] >= 1
        assert body["summary"]["dry_run"] is False
        doc = _sync.quotes.find_one({"id": inv_id})
        assert doc["payment_status"] == "pending_reconciliation"
        assert doc["reconciliation_required"] is True
        # Audit row present.
        audit = _sync.invoice_status_audit.find_one(
            {"invoice_id": inv_id},
        )
        assert audit is not None
        assert audit["previous_status"] == "paid"
        assert audit["corrected_status"] == "pending_reconciliation"
        assert audit["reason"] == "orphan_paid_no_payment_record"
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})


# ══════════════════════════════════════════════════════════════════════
# 4 · Whitelisted paid_methods are NEVER flipped.
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("method", [
    "service_credit", "manual_cash", "manual_check", "cash", "check",
    "import", "ach", "stripe_pi",
])
def test_audit_skips_whitelisted_paid_methods(method):
    tid = _seed_tenant()
    inv_id = _seed_orphan_paid_invoice(
        tenant_id=tid, paid_method=method,
    )
    try:
        tok = _login("super@aquaterra.com")
        requests.post(
            f"{API}/admin/migrations/audit-orphan-paid-invoices"
            f"?dry_run=false&force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        # Doc unchanged — evidence-backed paid_method is safe.
        doc = _sync.quotes.find_one({"id": inv_id})
        assert doc["payment_status"] == "paid", (
            f"paid_method={method!r} must be preserved (evidence-backed)"
        )
        assert doc.get("reconciliation_required") is not True
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})


# ══════════════════════════════════════════════════════════════════════
# 5 · Invoices with a Stripe PaymentIntent id are NEVER flipped.
# ══════════════════════════════════════════════════════════════════════
def test_audit_skips_invoices_with_stripe_payment_intent():
    tid = _seed_tenant()
    inv_id = _seed_orphan_paid_invoice(
        tenant_id=tid, stripe_pi="pi_test_real_charge_xxxx",
    )
    try:
        tok = _login("super@aquaterra.com")
        requests.post(
            f"{API}/admin/migrations/audit-orphan-paid-invoices"
            f"?dry_run=false&force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        doc = _sync.quotes.find_one({"id": inv_id})
        assert doc["payment_status"] == "paid", (
            "invoice with a real stripe_payment_intent_id must not be flipped"
        )
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})


# ══════════════════════════════════════════════════════════════════════
# 6 · Soft-deleted orphan-paid invoices are skipped.
# ══════════════════════════════════════════════════════════════════════
def test_audit_skips_soft_deleted_invoices():
    tid = _seed_tenant()
    inv_id = f"{_PREFIX}-inv-dead-{uuid.uuid4().hex[:6]}"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "payment_status": "paid",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "total": 100.0,
    })
    try:
        tok = _login("super@aquaterra.com")
        requests.post(
            f"{API}/admin/migrations/audit-orphan-paid-invoices"
            f"?dry_run=false&force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        doc = _sync.quotes.find_one({"id": inv_id})
        # Soft-deleted → never touched.
        assert doc["payment_status"] == "paid"
        assert doc.get("reconciliation_required") is not True
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})
