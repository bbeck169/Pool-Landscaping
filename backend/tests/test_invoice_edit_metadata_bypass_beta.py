"""Invoice edit · Feb-2026 β — metadata-only paid-invoice bypass.

Covers the ``_is_metadata_only_diff`` short-circuit on
``PATCH /api/quotes/{invoice_id}`` for paid / partial invoices:

  * Metadata fields (``description``, ``long_description``,
    ``item_id``, category keys, top-level ``notes`` / ``memo`` /
    ``private_notes``) edit freely with no ack / no typed proof.
  * Financial fields (``quantity``, ``unit_price``, etc.) stay
    locked — rejected with 400 ``financial_edit_locked_on_paid``
    when no ack flag and no typed-invoice-number proof.
  * Shipped ack flag + typed proof paths unchanged.
  * Void / cancelled stay 409 regardless of diff shape.

Pat Kail lock: never seed against customer_id
``014ce6bb-1dbc-4067-998d-e05c16e7e342``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
REQ_TIMEOUT = 15

_sync_client = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]

PAT_KAIL_LOCKED = "014ce6bb-1dbc-4067-998d-e05c16e7e342"


def _login_admin() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com",
               "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_id(tok) -> str:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200
    tid = r.json().get("tenant_id") or ""
    assert tid != PAT_KAIL_LOCKED
    return tid


def _real_cats(tenant):
    inc = list(_sync_db.income_categories.find(
        {"tenant_id": tenant,
          "$or": [{"is_archived": {"$ne": True}},
                   {"is_archived": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1},
    ).limit(5))
    svc = list(_sync_db.service_categories.find(
        {"tenant_id": tenant,
          "$or": [{"is_archived": {"$ne": True}},
                   {"is_archived": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1},
    ).limit(5))
    assert len(inc) >= 2 and len(svc) >= 1
    return inc, svc


def _seed_invoice(tenant, status="paid", invoice_number=None,
                   line_items=None):
    inv_id = f"TEST-metab-{uuid.uuid4().hex[:10]}"
    assert inv_id != PAT_KAIL_LOCKED
    inc, svc = _real_cats(tenant)
    if line_items is None:
        line_items = [{
            "id": "li-1", "description": "orig_desc",
            "quantity": 2, "unit_price": 50.0,
            "category": inc[0]["name"],
            "income_category_id": inc[0]["id"],
            "service_category": svc[0]["name"],
            "service_category_id": svc[0]["id"],
            "long_description": "orig_long",
            "item_id": "orig-item-id",
        }]
    doc = {
        "id":             inv_id,
        "tenant_id":      tenant,
        "customer_id":    "TEST-cust-metab-1",
        "customer_name":  "TEST_cust",
        "invoice_number": invoice_number
            or f"TEST-METAB-{uuid.uuid4().hex[:6]}",
        "total":          100.0, "subtotal": 100.0,
        "tax": 0.0, "tax_rate": 0.0,
        "amount_paid":    100.0 if status == "paid" else 0.0,
        "status":         status,
        "currency":       "USD", "doc_type": "invoice",
        "title":          "TEST_metab_invoice",
        "line_items":     line_items,
        "notes": "orig_notes", "memo": "orig_memo",
        "private_notes":  "orig_private",
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }
    _sync_db.quotes.insert_one(doc)
    return inv_id


def _cleanup(inv_id):
    _sync_db.quotes.delete_one({"id": inv_id})
    _sync_db.invoice_edit_history.delete_many({"invoice_id": inv_id})


def _patch(inv_id, body, token):
    return requests.patch(
        f"{API}/quotes/{inv_id}", json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQ_TIMEOUT,
    )


# ─── tests ──────────────────────────────────────────────────
def test_01_paid_description_only_no_ack_200():
    """1. Paid: PATCH only ``description`` → 200 (no ack)."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "edited_desc",
                "quantity": 2, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_metadata",
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(inv_id)


def test_02_paid_long_description_plus_service_cat_200():
    """2. Paid: PATCH long_description + service_category → 200."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        new_svc = svc[1] if len(svc) > 1 else svc[0]
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "orig_desc",
                "quantity": 2, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": new_svc["name"],
                "service_category_id": new_svc["id"],
                "long_description": "updated_long_desc",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_long_plus_cat",
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(inv_id)


def test_03_paid_quantity_change_no_ack_400():
    """3. Paid: PATCH quantity (no ack) → 400 financial locked."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "orig_desc",
                "quantity": 99, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_qty_block",
        }, tok)
        assert r.status_code == 400, r.text
        assert (r.json()["detail"].get("error")
                 == "financial_edit_locked_on_paid")
    finally:
        _cleanup(inv_id)


def test_04_paid_unit_price_change_no_ack_400():
    """4. Paid: PATCH unit_price (no ack) → 400."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "orig_desc",
                "quantity": 2, "unit_price": 999.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_price_block",
        }, tok)
        assert r.status_code == 400, r.text
        assert (r.json()["detail"].get("error")
                 == "financial_edit_locked_on_paid")
    finally:
        _cleanup(inv_id)


def test_05_paid_mixed_metadata_financial_no_ack_400():
    """5. Paid: mixed meta+financial no-ack → 400 (financial wins)."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "mixed_edit",
                "quantity": 10, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "mixed_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_mixed_block",
        }, tok)
        assert r.status_code == 400
        assert (r.json()["detail"].get("error")
                 == "financial_edit_locked_on_paid")
    finally:
        _cleanup(inv_id)


def test_06_paid_mixed_with_ack_200():
    """6. Paid: mixed + acknowledged_lock_bypass → 200 (shipped)."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "ack_mixed",
                "quantity": 10, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "acknowledged_lock_bypass": True,
            "reason": "TEST_ack_mixed",
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(inv_id)


def test_07_unpaid_description_plus_quantity_200():
    """7. Unpaid (``draft`` status): description + quantity → 200,
    no gate at all."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="draft")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "unpaid_edit",
                "quantity": 5, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_unpaid",
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(inv_id)


def test_08_paid_category_only_no_ack_still_passes_regression():
    """8. Shipped regression — category-only edit on paid still
    works without ack (now via the widened metadata path)."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        new_inc = inc[1] if len(inc) > 1 else inc[0]
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "orig_desc",
                "quantity": 2, "unit_price": 50.0,
                "category": new_inc["name"],
                "income_category_id": new_inc["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_cat_only",
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(inv_id)


def test_09_audit_row_written_for_metadata_only_paid_edit():
    """9. Metadata-only edit on paid writes to
    ``invoice_edit_history`` — surfaces via ``/edit-history``."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status="paid")
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "audit_edit",
                "quantity": 2, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_audit",
        }, tok)
        assert r.status_code == 200
        hist = requests.get(
            f"{API}/quotes/{inv_id}/edit-history",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=REQ_TIMEOUT,
        )
        assert hist.status_code == 200, hist.text
        assert hist.json().get("total", 0) >= 1
    finally:
        _cleanup(inv_id)


@pytest.mark.parametrize("terminal_status", ["void", "cancelled"])
def test_10_void_cancelled_description_only_still_409(
        terminal_status):
    """10. Void / cancelled: PATCH description → still 409
    (terminal lock preserved per operator Q6=a)."""
    tok = _login_admin()
    tid = _tenant_id(tok)
    inv_id = _seed_invoice(tid, status=terminal_status)
    try:
        inc, svc = _real_cats(tid)
        r = _patch(inv_id, {
            "line_items": [{
                "id": "li-1", "description": "terminal_attempt",
                "quantity": 2, "unit_price": 50.0,
                "category": inc[0]["name"],
                "income_category_id": inc[0]["id"],
                "service_category": svc[0]["name"],
                "service_category_id": svc[0]["id"],
                "long_description": "orig_long",
                "item_id": "orig-item-id",
            }],
            "reason": "TEST_terminal",
        }, tok)
        assert r.status_code == 409, r.text
        assert (r.json()["detail"].get("error")
                 == "invoice_terminal")
    finally:
        _cleanup(inv_id)
