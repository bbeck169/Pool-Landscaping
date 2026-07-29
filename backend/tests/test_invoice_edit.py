"""Invoice edit · Feb-2026 — Admin PATCH endpoint + audit history tests.

Uses direct HTTP against the running backend (like ``test_lz2_dispatcher``),
seeds throwaway rows into ``db.invoices`` with the ``TEST_`` prefix so
``conftest.py`` cleans them up at session teardown.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"

_sync_client = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]


# ── Helpers ────────────────────────────────────────────────────────
def _login(email: str) -> str:
    """Login helper with retry — the bcrypt-backed /auth/login can be
    slow enough to trip a 10s default timeout on cold pods."""
    last = None
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["access_token"]
            last = r.text
        except requests.exceptions.RequestException as exc:
            last = str(exc)
    raise RuntimeError(f"login failed for {email}: {last}")


def _admin_token() -> str:
    return _login("manager@aquaterra.com")


def _customer_token() -> str:
    return _login("customer@aquaterra.com")


# Module-level caches — login is slow (bcrypt) and every test would
# otherwise re-login twice. Fixture-level would be cleaner but this
# file uses plain function tests to match the existing lz2 style.
_CACHED_ADMIN_TOKEN: str = ""
_CACHED_TENANT_ID: str = ""


def _cached_admin_token() -> str:
    global _CACHED_ADMIN_TOKEN
    if not _CACHED_ADMIN_TOKEN:
        _CACHED_ADMIN_TOKEN = _admin_token()
    return _CACHED_ADMIN_TOKEN


def _tenant_id() -> str:
    global _CACHED_TENANT_ID
    if _CACHED_TENANT_ID:
        return _CACHED_TENANT_ID
    tok = _cached_admin_token()
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    _CACHED_TENANT_ID = r.json().get("tenant_id") or "TEST_tenant"
    return _CACHED_TENANT_ID


def _seed_invoice(status: str = "draft",
                   lumino_url: str | None = None,
                   invoice_number: str = "TEST-EDIT-001",
                   line_items=None,
                   collection: str = "invoices",
                   tenant_id: str | None = None,
                   title: str = "TEST_edit_invoice") -> str:
    inv_id = f"TEST-edit-inv-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": inv_id,
        "tenant_id": tenant_id or _tenant_id(),
        "customer_id": "TEST-cust-edit-1",
        "customer_name": "TEST_editcust",
        "customer_email": "test-edit@example.com",
        "invoice_number": invoice_number,
        "total": 100.0,
        "subtotal": 100.0,
        "tax": 0.0,
        "tax_rate": 0.0,
        "amount_paid": 100.0 if status == "paid" else 0.0,
        "status": status,
        "currency": "USD",
        "title": title,
        "doc_type": "invoice",
        "line_items": line_items or [
            {"description": "TEST_service", "quantity": 1, "unit_price": 100.0}
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if lumino_url:
        doc["lumino_payment_url"] = lumino_url
        doc["lumino_payment_ref"] = "lum_ref_test"
    _sync_db[collection].insert_one(doc)
    return inv_id


def _cleanup_invoice(inv_id: str):
    _sync_db.invoices.delete_one({"id": inv_id})
    _sync_db.quotes.delete_one({"id": inv_id})
    _sync_db.invoice_edit_history.delete_many({"invoice_id": inv_id})


def _patch(inv_id: str, body: dict, token: str) -> requests.Response:
    return requests.patch(
        f"{API}/quotes/{inv_id}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )


# ─────────────── 1. admin can edit draft line_items ────────────────
def test_admin_can_edit_draft_invoice_line_items():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"description": "TEST_service_edited", "quantity": 2,
                  "unit_price": 60.0},
            ],
            "reason": "TEST_pricing_change",
        }, tok)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["changed"] is True
        assert j["invoice"]["total"] == 120.0
        assert j["invoice"]["subtotal"] == 120.0
        assert j["audit_id"]
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 2. non-admin gets 403 ─────────────────────────────
def test_non_admin_cannot_edit_403():
    tok = _customer_token()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"notes": "TEST_hax"}, tok)
        assert r.status_code == 403, r.text
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 3. sent w/o confirm → 409 ─────────────────────────
def test_edit_sent_without_confirm_returns_409_requires_confirmation():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="sent")
    try:
        r = _patch(inv_id, {"notes": "TEST_note"}, tok)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "requires_confirmation"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 4. sent w/ confirm succeeds ───────────────────────
def test_edit_sent_with_confirm_succeeds():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="sent")
    try:
        r = _patch(inv_id, {
            "notes": "TEST_confirmed_edit",
            "confirm_edit_sent": True,
        }, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 5. paid w/o number → 409 ──────────────────────────
def test_edit_paid_without_number_returns_409():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="paid", invoice_number="TEST-PAID-01")
    try:
        r = _patch(inv_id, {"notes": "TEST_note"}, tok)
        assert r.status_code == 409, r.text
        j = r.json()["detail"]
        assert j["error"] == "paid_edit_requires_invoice_number"
        assert j["expected_invoice_number"] == "TEST-PAID-01"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 6. paid w/ wrong number → 409 ─────────────────────
def test_edit_paid_with_wrong_number_returns_409():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="paid", invoice_number="TEST-PAID-02")
    try:
        r = _patch(inv_id, {
            "notes": "TEST_note",
            "confirm_edit_paid_invoice_number": "WRONG",
        }, tok)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "paid_edit_requires_invoice_number"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 7. paid w/ correct number succeeds ────────────────
def test_edit_paid_with_correct_number_succeeds():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="paid", invoice_number="TEST-PAID-03")
    try:
        r = _patch(inv_id, {
            "notes": "TEST_paid_edit",
            "confirm_edit_paid_invoice_number": "TEST-PAID-03",
        }, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 8. void → 409 ─────────────────────────────────────
def test_edit_void_returns_409_invoice_terminal():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="void")
    try:
        r = _patch(inv_id, {"notes": "TEST_void_edit"}, tok)
        assert r.status_code == 409, r.text
        j = r.json()["detail"]
        assert j["error"] == "invoice_terminal"
        assert j["status"] == "void"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 9. invoice_number conflict → 409 ──────────────────
def test_change_invoice_number_conflict_returns_409():
    tok = _cached_admin_token()
    tenant = _tenant_id()
    inv_a = _seed_invoice(status="draft", invoice_number="TEST-EDIT-CONFLICT-A",
                          tenant_id=tenant)
    inv_b = _seed_invoice(status="draft", invoice_number="TEST-EDIT-CONFLICT-B",
                          tenant_id=tenant)
    try:
        r = _patch(inv_a, {"invoice_number": "TEST-EDIT-CONFLICT-B"}, tok)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "invoice_number_conflict"
    finally:
        _cleanup_invoice(inv_a)
        _cleanup_invoice(inv_b)


# ─────────────── 10. unique invoice_number succeeds ────────────────
def test_change_invoice_number_unique_succeeds():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="draft",
                            invoice_number="TEST-EDIT-UNIQUE-A")
    try:
        r = _patch(inv_id, {
            "invoice_number": f"TEST-EDIT-UNIQUE-{uuid.uuid4().hex[:6]}",
        }, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 11. audit entry contains diff ─────────────────────
def test_edit_creates_audit_entry_with_correct_diff():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "tax_rate": 8.25,
            "notes": "TEST_new_notes",
            "reason": "TEST_audit_check",
        }, tok)
        assert r.status_code == 200, r.text
        audit_id = r.json()["audit_id"]
        # Verify the audit doc landed in mongo.
        audit = _sync_db.invoice_edit_history.find_one({"id": audit_id})
        assert audit is not None
        cf = audit["changed_fields"]
        assert "tax_rate" in cf
        assert cf["tax_rate"]["old"] == 0.0
        assert cf["tax_rate"]["new"] == 8.25
        assert cf["notes"]["new"] == "TEST_new_notes"
        assert audit["edited_by_user_email"] == "manager@aquaterra.com"
        assert audit["edited_by_role"] in ("admin", "super_admin")
        assert audit["reason"] == "TEST_audit_check"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 12. no-op does not create audit entry ─────────────
def test_no_change_does_not_create_audit_entry():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="draft", invoice_number="TEST-NOOP-01")
    try:
        r = _patch(inv_id, {
            "notes": None,  # exclude_unset — pydantic strips this
            "reason": "TEST_noop",
        }, tok)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["changed"] is False
        assert "audit_id" not in j
        count = _sync_db.invoice_edit_history.count_documents(
            {"invoice_id": inv_id})
        assert count == 0
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 13. money-change triggers lumino re-fire ──────────
def test_line_item_change_triggers_lumino_link_regeneration():
    """We can't monkeypatch the backend process's schedule_dispatch from
    this test process, so we verify the observable effects instead:
      - lumino_payment_url is cleared on the invoice
      - the audit doc has an ``auto_effects`` entry of kind
        ``lumino_link_cleared_and_refired`` (or the ``…refire_failed``
        sibling if the Zap URL isn't configured in the pod — either
        proves the code path fired).
    """
    tok = _cached_admin_token()
    inv_id = _seed_invoice(
        status="draft",
        lumino_url="https://pay.lumino.io/checkout/OLD",
    )
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"description": "TEST_new_item", "quantity": 3,
                  "unit_price": 40.0},
            ],
        }, tok)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["changed"] is True
        assert j["invoice"]["lumino_payment_url"] is None
        assert j["invoice"]["lumino_payment_ref"] is None
        # Audit doc records the auto-effect.
        audit = _sync_db.invoice_edit_history.find_one({"id": j["audit_id"]})
        kinds = [e.get("kind") for e in (audit.get("auto_effects") or [])]
        assert any(k and k.startswith("lumino_link_cleared") for k in kinds), \
            f"expected lumino_link_cleared_* auto_effect, got {kinds}"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 14. non-money change keeps URL untouched ──────────
def test_non_money_change_does_not_trigger_regeneration():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(
        status="draft",
        lumino_url="https://pay.lumino.io/checkout/KEEP",
    )
    try:
        r = _patch(inv_id, {"notes": "TEST_just_notes"}, tok)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["changed"] is True
        assert j["invoice"]["lumino_payment_url"] == \
            "https://pay.lumino.io/checkout/KEEP"
        # Audit doc must NOT carry a lumino auto_effect.
        audit = _sync_db.invoice_edit_history.find_one({"id": j["audit_id"]})
        kinds = [e.get("kind") for e in (audit.get("auto_effects") or [])]
        assert not any(k and k.startswith("lumino_link_cleared")
                        for k in kinds), \
            f"unexpected lumino auto_effect on non-money edit: {kinds}"
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 15. GET edit history — admin ─────────────────────
def test_get_edit_history_admin_lists_items():
    tok = _cached_admin_token()
    inv_id = _seed_invoice(status="draft")
    try:
        # First edit
        _patch(inv_id, {"notes": "TEST_first"}, tok)
        # Second edit
        _patch(inv_id, {"terms": "TEST_terms"}, tok)
        r = requests.get(
            f"{API}/quotes/{inv_id}/edit-history",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 2
        # Descending by edited_at — the second edit is the terms one.
        assert body["items"][0]["invoice_id"] == inv_id
    finally:
        _cleanup_invoice(inv_id)


# ─────────────── 16. GET edit history — non-admin ─────────────────
def test_get_edit_history_non_admin_403():
    admin_tok = _cached_admin_token()
    cust_tok = _customer_token()
    inv_id = _seed_invoice(status="draft")
    try:
        _patch(inv_id, {"notes": "TEST_seed_history"}, admin_tok)
        r = requests.get(
            f"{API}/quotes/{inv_id}/edit-history",
            headers={"Authorization": f"Bearer {cust_tok}"}, timeout=10,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup_invoice(inv_id)
