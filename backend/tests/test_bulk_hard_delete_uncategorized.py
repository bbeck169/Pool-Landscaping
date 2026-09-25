"""Feb-2026 — Bulk hard-delete for uncategorized line items.

End-to-end pytest suite for
``POST /api/reports/uncategorized-items/bulk-hard-delete`` and its
companion undo endpoint.

Locks the 15+ behaviours from the Phase 2 spec:

  1. happy path (3 lines across 2 invoices)
  2. ``line_index_out_of_bounds`` skip
  3. ``not_found_or_cross_tenant`` skip
  4. ``content_shifted`` skip (description mismatch)
  5. ``locked_paid`` without ack
  6. ``locked_paid`` with ack → deletes, remaining_balance clamped
  7. ``already_deleted`` (payload duplicate)
  8. cap overshoot (101 rows) → 422 bulk_cap_exceeded
  9. empty payload → 422 empty_rows
 10. non-admin → 403
 11. cross-tenant invoice → 404 posture (skipped w/ not_found_or_cross_tenant)
 12. audit rows shape + shared bulk_op_id
 13. undo happy path
 14. undo idempotency (double-undo)
 15. signature invalidation on delete

All tests self-clean via a ``finally`` block that removes seeded
invoices + audit rows so re-runs remain green.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_TEST_DIR = Path(__file__).resolve().parent

_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def tech_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "mike@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def customer_id(dbc, aquaterra_id):
    doc = dbc.customers.find_one(
        {"tenant_id": aquaterra_id}, {"id": 1},
    )
    return doc["id"]


# ─────────────────────────────────────────────────────────────
# Seed helpers
# ─────────────────────────────────────────────────────────────
def _seed_invoice(dbc, *, tenant_id: str, customer_id: str,
                    lines: List[Dict[str, Any]],
                    payment_status: str = "unpaid",
                    amount_paid: float = 0.0,
                    tax_rate: float = 0.0,
                    status: str = "sent") -> str:
    """Insert a synthetic invoice with the given line items.
    Returns the invoice id."""
    now_iso = datetime.now(timezone.utc).isoformat()
    subtotal = sum(float(li["quantity"]) * float(li["unit_price"]) for li in lines)
    tax = round(subtotal * tax_rate / 100, 2)
    total = round(subtotal + tax, 2)
    remaining = round(max(total - amount_paid, 0.0), 2)
    inv_id = str(uuid.uuid4())
    dbc.quotes.insert_one({
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "customer_id": customer_id,
        "customer_name": "Test Customer",
        "title": "Bulk hard-delete test invoice",
        "line_items": lines,
        "tax_rate": tax_rate,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "amount_paid": amount_paid,
        "remaining_balance": remaining,
        "payment_status": payment_status,
        "status": status,
        "created_at": now_iso,
        "updated_at": now_iso,
    })
    return inv_id


def _cleanup(dbc, *, invoice_ids: List[str], tenant_id: str) -> None:
    if not invoice_ids:
        return
    dbc.quotes.delete_many({"tenant_id": tenant_id, "id": {"$in": invoice_ids}})
    dbc.audit_logs.delete_many({
        "tenant_id": tenant_id,
        "event": {"$in": ["line_item.hard_delete", "line_item.hard_delete.undo"]},
        "invoice_id": {"$in": invoice_ids},
    })
    dbc.document_versions.delete_many({
        "doc_type": "invoice", "doc_id": {"$in": invoice_ids},
    })


def _line(desc: str, up: float, qty: float = 1.0) -> Dict[str, Any]:
    return {
        "description": desc,
        "quantity": qty,
        "unit_price": up,
        "category": "Pool",
    }


# ═════════════════════════════════════════════════════════════
# §1 · Happy path
# ═════════════════════════════════════════════════════════════
def test_happy_path_3_lines_across_2_invoices(admin_h, aquaterra_id,
                                                   dbc, customer_id):
    inv_a = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Row A0", 10), _line("Row A1", 20),
                _line("Row A2 (keep)", 30)],
    )
    inv_b = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Row B0", 50), _line("Row B1 (keep)", 60)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv_a, "line_item_index": 0,
                      "description": "Row A0", "unit_price": 10},
                    {"invoice_id": inv_a, "line_item_index": 1,
                      "description": "Row A1", "unit_price": 20},
                    {"invoice_id": inv_b, "line_item_index": 0,
                      "description": "Row B0", "unit_price": 50},
                ],
            }, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["requested"] == 3
        assert body["deleted"] == 3
        assert body["skipped"] == []
        assert body["bulk_op_id"]

        inv_a_doc = dbc.quotes.find_one({"id": inv_a})
        assert len(inv_a_doc["line_items"]) == 1
        assert inv_a_doc["line_items"][0]["description"] == "Row A2 (keep)"
        assert inv_a_doc["subtotal"] == 30.0
        assert inv_a_doc["total"] == 30.0

        inv_b_doc = dbc.quotes.find_one({"id": inv_b})
        assert len(inv_b_doc["line_items"]) == 1
        assert inv_b_doc["line_items"][0]["description"] == "Row B1 (keep)"
        assert inv_b_doc["subtotal"] == 60.0
    finally:
        _cleanup(dbc, invoice_ids=[inv_a, inv_b], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §2 · line_index_out_of_bounds
# ═════════════════════════════════════════════════════════════
def test_line_index_out_of_bounds(admin_h, aquaterra_id, dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Row 0", 10)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Row 0", "unit_price": 10},
                    {"invoice_id": inv, "line_item_index": 5,
                      "description": "Row 5", "unit_price": 99},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 1
        assert len(body["skipped"]) == 1
        assert body["skipped"][0]["code"] == "line_index_out_of_bounds"
        assert body["skipped"][0]["line_item_index"] == 5
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §3 · not_found_or_cross_tenant
# ═════════════════════════════════════════════════════════════
def test_not_found_or_cross_tenant(admin_h, aquaterra_id, dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Row 0", 10)],
    )
    fake_id = str(uuid.uuid4())
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": fake_id, "line_item_index": 0,
                      "description": "x", "unit_price": 0},
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Row 0", "unit_price": 10},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 1
        assert any(s["code"] == "not_found_or_cross_tenant" and s["invoice_id"] == fake_id
                   for s in body["skipped"])
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §4 · content_shifted
# ═════════════════════════════════════════════════════════════
def test_content_shifted_description_mismatch(admin_h, aquaterra_id,
                                                   dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Real description", 42)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Stale description",
                      "unit_price": 42},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 0
        assert len(body["skipped"]) == 1
        assert body["skipped"][0]["code"] == "content_shifted"
        # Doc untouched.
        d = dbc.quotes.find_one({"id": inv})
        assert len(d["line_items"]) == 1
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §5 · locked_paid without acknowledged_lock_bypass
# ═════════════════════════════════════════════════════════════
def test_locked_paid_without_ack(admin_h, aquaterra_id, dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Paid row", 100)],
        payment_status="paid", amount_paid=100.0, status="paid",
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Paid row", "unit_price": 100},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 0
        assert body["skipped"][0]["code"] == "locked_paid"
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §6 · locked_paid WITH ack → deletes, remaining_balance clamped
# ═════════════════════════════════════════════════════════════
def test_locked_paid_with_ack_clamps_remaining_balance(admin_h, aquaterra_id,
                                                            dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Paid A", 60), _line("Paid B (keep)", 40)],
        payment_status="paid", amount_paid=100.0, status="paid",
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Paid A", "unit_price": 60},
                ],
                "acknowledged_lock_bypass": True,
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 1

        d = dbc.quotes.find_one({"id": inv})
        assert d["subtotal"] == 40.0
        assert d["total"] == 40.0
        # amount_paid (100) > new total (40) → clamp to 0.
        assert d["remaining_balance"] == 0.0
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §7 · already_deleted (payload duplicate)
# ═════════════════════════════════════════════════════════════
def test_payload_duplicate_marked_already_deleted(admin_h, aquaterra_id,
                                                     dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Row 0", 25)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Row 0", "unit_price": 25},
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Row 0", "unit_price": 25},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 1
        assert body["skipped"][0]["code"] == "already_deleted"
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §8 · Cap overshoot → 422
# ═════════════════════════════════════════════════════════════
def test_cap_overshoot(admin_h):
    rows = [
        {"invoice_id": "x", "line_item_index": 0,
          "description": "y", "unit_price": 0}
        for _ in range(101)
    ]
    r = requests.post(
        f"{API}/reports/uncategorized-items/bulk-hard-delete",
        headers=admin_h, json={"rows": rows}, timeout=10,
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "bulk_cap_exceeded"
    assert detail.get("cap") == 100
    assert detail.get("attempted") == 101


# ═════════════════════════════════════════════════════════════
# §9 · Empty payload → 422
# ═════════════════════════════════════════════════════════════
def test_empty_rows(admin_h):
    r = requests.post(
        f"{API}/reports/uncategorized-items/bulk-hard-delete",
        headers=admin_h, json={"rows": []}, timeout=10,
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "empty_rows"


# ═════════════════════════════════════════════════════════════
# §10 · Non-admin → 403
# ═════════════════════════════════════════════════════════════
def test_non_admin_forbidden(tech_h):
    r = requests.post(
        f"{API}/reports/uncategorized-items/bulk-hard-delete",
        headers=tech_h,
        json={"rows": [{"invoice_id": "x", "line_item_index": 0,
                          "description": "y", "unit_price": 0}]},
        timeout=10,
    )
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════
# §11 · Cross-tenant leakage
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_leakage_blocked(admin_h, aquaterra_id, dbc):
    """A tenant's admin cannot delete lines on an invoice owned by
    another tenant — such rows return the ``not_found_or_cross_tenant``
    skip code (same as truly-missing invoices; matches the B2.B
    tenant-membership-probe posture)."""
    other_tenant = f"h2-uncat-cross-tenant-{uuid.uuid4().hex[:6]}"
    inv = _seed_invoice(
        dbc, tenant_id=other_tenant, customer_id="fake-cust",
        lines=[_line("Secret", 999)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h,
            json={"rows": [{"invoice_id": inv, "line_item_index": 0,
                              "description": "Secret", "unit_price": 999}]},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["skipped"][0]["code"] == "not_found_or_cross_tenant"

        # Cross-tenant doc must be UNTOUCHED.
        d = dbc.quotes.find_one({"id": inv})
        assert d and len(d["line_items"]) == 1
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=other_tenant)


# ═════════════════════════════════════════════════════════════
# §12 · Audit rows: N deleted → N audit_logs rows w/ shared bulk_op_id
# ═════════════════════════════════════════════════════════════
def test_audit_rows_shape_and_shared_bulk_op(admin_h, aquaterra_id,
                                                  dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("A", 10), _line("B", 20), _line("C", 30)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "A", "unit_price": 10},
                    {"invoice_id": inv, "line_item_index": 2,
                      "description": "C", "unit_price": 30},
                ],
                "deletion_reason": "operator cleanup",
            }, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 2
        bulk_op = body["bulk_op_id"]

        audit_rows = list(dbc.audit_logs.find(
            {"event": "line_item.hard_delete",
              "bulk_op_id": bulk_op},
        ))
        assert len(audit_rows) == 2
        # Every row carries the required shape.
        for ar in audit_rows:
            assert ar["tenant_id"] == aquaterra_id
            assert ar["invoice_id"] == inv
            assert ar["deletion_reason"] == "operator cleanup"
            assert ar["actor_role"] in ("admin", "super_admin", "owner")
            assert ar["line_snapshot"]
            assert "description" in ar["line_snapshot"]
            assert "unit_price" in ar["line_snapshot"]
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §13 · Undo happy path
# ═════════════════════════════════════════════════════════════
def test_undo_happy_path(admin_h, aquaterra_id, dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("First", 10), _line("Second", 20), _line("Third", 30)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "First", "unit_price": 10},
                    {"invoice_id": inv, "line_item_index": 2,
                      "description": "Third", "unit_price": 30},
                ],
            }, timeout=15,
        )
        bulk_op = r.json()["bulk_op_id"]

        d = dbc.quotes.find_one({"id": inv})
        assert len(d["line_items"]) == 1
        assert d["line_items"][0]["description"] == "Second"

        # Undo.
        ur = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete/"
            f"{bulk_op}/undo",
            headers=admin_h, timeout=15,
        )
        assert ur.status_code == 200, ur.text
        ub = ur.json()
        assert ub["restored"] == 2
        assert ub["already_undone"] == 0
        assert ub["skipped"] == []

        d = dbc.quotes.find_one({"id": inv})
        assert len(d["line_items"]) == 3
        # G.6c: undo appends to the END, not the original index.
        assert d["line_items"][0]["description"] == "Second"
        # Order of the appended lines mirrors the deleted_snapshots
        # (ascending original index).
        appended = {li["description"] for li in d["line_items"][1:]}
        assert appended == {"First", "Third"}
        # Totals restored.
        assert d["subtotal"] == 60.0
        assert d["total"] == 60.0

        # An undo audit row exists per re-inserted line.
        undo_rows = list(dbc.audit_logs.find(
            {"event": "line_item.hard_delete.undo",
              "undo_of": bulk_op},
        ))
        assert len(undo_rows) == 2
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §14 · Undo idempotency (double-undo)
# ═════════════════════════════════════════════════════════════
def test_undo_double_call_is_noop(admin_h, aquaterra_id, dbc, customer_id):
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("A", 10), _line("B", 20)],
    )
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [{"invoice_id": inv, "line_item_index": 0,
                          "description": "A", "unit_price": 10}],
            }, timeout=15,
        )
        bulk_op = r.json()["bulk_op_id"]

        # First undo.
        r1 = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete/"
            f"{bulk_op}/undo",
            headers=admin_h, timeout=15,
        )
        assert r1.status_code == 200
        assert r1.json()["restored"] == 1

        # Second undo — should be a no-op.
        r2 = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete/"
            f"{bulk_op}/undo",
            headers=admin_h, timeout=15,
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["restored"] == 0
        assert body["already_undone"] == 1

        # Invoice has exactly the 2 original lines (1 kept + 1 restored),
        # not 3.
        d = dbc.quotes.find_one({"id": inv})
        assert len(d["line_items"]) == 2
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §15 · Signature invalidation on delete
# ═════════════════════════════════════════════════════════════
def test_signature_invalidated_on_delete(admin_h, aquaterra_id, dbc,
                                              customer_id):
    """If the target invoice has a signed, not-yet-superseded
    signature, deleting a line MUST supersede that signature."""
    inv = _seed_invoice(
        dbc, tenant_id=aquaterra_id, customer_id=customer_id,
        lines=[_line("Signed row", 100), _line("Keep", 50)],
    )
    # Plant a signature row (matches services.documents.versions
    # convention).
    sig_id = str(uuid.uuid4())
    dbc.signatures.insert_one({
        "id": sig_id,
        "tenant_id": aquaterra_id,
        "doc_id": inv,
        "doc_type": "invoice",
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "superseded_at": None,
        "signer_name": "Test Signer",
    })
    try:
        r = requests.post(
            f"{API}/reports/uncategorized-items/bulk-hard-delete",
            headers=admin_h, json={
                "rows": [
                    {"invoice_id": inv, "line_item_index": 0,
                      "description": "Signed row", "unit_price": 100},
                ],
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] == 1

        sig = dbc.signatures.find_one({"id": sig_id})
        assert sig["superseded_at"] is not None
        assert sig.get("superseded_reason") == "doc_edited_after_signature"

        # Doc side surfaces the signature_status flip.
        d = dbc.quotes.find_one({"id": inv})
        assert d.get("signature_status") == "superseded"
    finally:
        _cleanup(dbc, invoice_ids=[inv], tenant_id=aquaterra_id)
        dbc.signatures.delete_one({"id": sig_id})


# ═════════════════════════════════════════════════════════════
# §16 · undo 404 on unknown bulk_op_id
# ═════════════════════════════════════════════════════════════
def test_undo_unknown_bulk_op_id(admin_h):
    fake = str(uuid.uuid4())
    r = requests.post(
        f"{API}/reports/uncategorized-items/bulk-hard-delete/{fake}/undo",
        headers=admin_h, timeout=10,
    )
    assert r.status_code == 404, r.text
    assert (r.json().get("detail") or {}).get("code") == "bulk_op_not_found"
