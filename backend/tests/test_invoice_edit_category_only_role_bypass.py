"""
Invoice edit · Feb-2026 — narrow role bypass for category-only diffs.
====================================================================

Covers the Atomic A1 widening of ``_require_staff`` on
``PATCH /api/quotes/{invoice_id}``.  Manager + owner can execute
category-only PATCHes without being blocked by the pre-bypass
admin-only gate.  Non-category fields still require admin /
super_admin.

Pat Kail lock: this file NEVER seeds against customer_id
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


_CACHED_ADMIN_TOKEN: str = ""
_CACHED_TENANT_ID: str = ""
_CACHED_INCOME_CATS = None
_CACHED_SERVICE_CATS = None


def _login_admin() -> str:
    """Login as the standard admin account (role=admin, email
    ``admin@aquaterra.com`` — confirmed role=admin via DB)."""
    global _CACHED_ADMIN_TOKEN
    if _CACHED_ADMIN_TOKEN:
        return _CACHED_ADMIN_TOKEN
    last = None
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": "admin@aquaterra.com",
                       "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                _CACHED_ADMIN_TOKEN = r.json()["access_token"]
                return _CACHED_ADMIN_TOKEN
            last = r.text
        except requests.exceptions.RequestException as exc:
            last = str(exc)
    raise RuntimeError(f"admin login failed: {last}")


def _tenant_id() -> str:
    global _CACHED_TENANT_ID
    if _CACHED_TENANT_ID:
        return _CACHED_TENANT_ID
    tok = _login_admin()
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    tid = r.json().get("tenant_id") or ""
    assert tid != PAT_KAIL_LOCKED
    _CACHED_TENANT_ID = tid
    return tid


def _real_income_categories():
    global _CACHED_INCOME_CATS
    if _CACHED_INCOME_CATS is not None:
        return _CACHED_INCOME_CATS
    tenant = _tenant_id()
    rows = list(_sync_db.income_categories.find(
        {"tenant_id": tenant,
          "$or": [{"is_archived": {"$ne": True}},
                   {"is_archived": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1},
    ).limit(10))
    assert len(rows) >= 2, (
        f"need >=2 non-archived income_categories, got {len(rows)}"
    )
    _CACHED_INCOME_CATS = rows
    return rows


def _real_service_categories():
    """K71 validation on line_items requires service_category_id to
    reference a real row in db.service_categories."""
    global _CACHED_SERVICE_CATS
    if _CACHED_SERVICE_CATS is not None:
        return _CACHED_SERVICE_CATS
    tenant = _tenant_id()
    rows = list(_sync_db.service_categories.find(
        {"tenant_id": tenant,
          "$or": [{"is_archived": {"$ne": True}},
                   {"is_archived": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1},
    ).limit(10))
    assert len(rows) >= 1, (
        f"need >=1 non-archived service_category, got {len(rows)}"
    )
    _CACHED_SERVICE_CATS = rows
    return rows


def _mint_token(role: str) -> tuple[str, str]:
    """Seed a synthetic user with the given role and mint a JWT."""
    from utils import create_token, hash_password
    tenant = _tenant_id()
    uid = f"TEST-catbp-{role}-{uuid.uuid4().hex[:8]}"
    assert uid != PAT_KAIL_LOCKED
    user_doc = {
        "id":            uid,
        "tenant_id":     tenant,
        "email":         f"test-catbp-{uid}@example.test",
        "role":          role,
        "name":          f"TEST {role}",
        "password_hash": hash_password("x"),
        "deleted_at":    None,
        "is_active":     True,
    }
    _sync_db.users.insert_one(user_doc)
    return uid, create_token(user_doc)


def _seed_invoice(
    status: str = "draft",
    invoice_number: str | None = None,
    line_items=None,
) -> str:
    inv_id = f"TEST-catbp-inv-{uuid.uuid4().hex[:10]}"
    assert inv_id != PAT_KAIL_LOCKED
    if line_items is None:
        incats = _real_income_categories()
        svcats = _real_service_categories()
        line_items = [
            {"id": "li-1", "description": "TEST_service", "quantity": 1,
              "unit_price": 100.0,
              "category": incats[0]["name"],
              "income_category_id": incats[0]["id"],
              "service_category": svcats[0]["name"],
              "service_category_id": svcats[0]["id"]},
        ]
    doc = {
        "id":              inv_id,
        "tenant_id":       _tenant_id(),
        "customer_id":     "TEST-cust-catbp-1",
        "customer_name":   "TEST_cust",
        "customer_email":  "test-catbp@example.com",
        "invoice_number":  invoice_number or f"TEST-CATBP-{uuid.uuid4().hex[:6]}",
        "total":           100.0,
        "subtotal":        100.0,
        "tax":             0.0,
        "tax_rate":        0.0,
        "amount_paid":     100.0 if status == "paid" else 0.0,
        "status":          status,
        "currency":        "USD",
        "title":           "TEST_catbp_invoice",
        "doc_type":        "invoice",
        "line_items":      line_items,
        "created_at":      datetime.now(timezone.utc).isoformat(),
    }
    _sync_db.quotes.insert_one(doc)
    return inv_id


def _cleanup_invoice(inv_id: str) -> None:
    _sync_db.quotes.delete_one({"id": inv_id})
    _sync_db.invoice_edit_history.delete_many({"invoice_id": inv_id})


def _cleanup_user(uid: str) -> None:
    _sync_db.users.delete_one({"id": uid})


def _patch(inv_id: str, body: dict, token: str) -> requests.Response:
    return requests.patch(
        f"{API}/quotes/{inv_id}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQ_TIMEOUT,
    )


# ═══════════════════════════════════════════════════════════════════
# 1 · admin regression — any field
# ═══════════════════════════════════════════════════════════════════
def test_admin_can_patch_any_field_regression():
    tok = _login_admin()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"tax_rate": 7.5,
                             "notes": "TEST_admin_any",
                             "reason": "TEST_regression"}, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)


# ═══════════════════════════════════════════════════════════════════
# 2 · super_admin regression — any field
# ═══════════════════════════════════════════════════════════════════
def test_super_admin_can_patch_any_field_regression():
    uid, tok = _mint_token("super_admin")
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"discount_amount": 5.0,
                             "discount_type": "fixed"}, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 9 · super_admin can PATCH category-only (regression)
# ═══════════════════════════════════════════════════════════════════
def test_super_admin_can_patch_category_only_regression():
    uid, tok = _mint_token("super_admin")
    inv_id = _seed_invoice(status="draft")
    incats = _real_income_categories()
    try:
        r = _patch(inv_id, {"business_unit": incats[1]["name"],
                             "business_unit_id": incats[1]["id"]}, tok)
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 3 · manager can PATCH top-level business_unit alone (new allow)
# ═══════════════════════════════════════════════════════════════════
def test_manager_can_patch_business_unit_top_level():
    uid, tok = _mint_token("manager")
    inv_id = _seed_invoice(status="draft")
    incats = _real_income_categories()
    try:
        r = _patch(inv_id, {"business_unit": incats[1]["name"]}, tok)
        assert r.status_code == 200, (
            f"manager with category-only diff should pass narrow "
            f"bypass; got {r.status_code}: {r.text[:200]}"
        )
        body = r.json()
        assert body["changed"] is True
        assert body["invoice"]["business_unit"] == incats[1]["name"]
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 4 · manager can PATCH business_unit + business_unit_id paired
# ═══════════════════════════════════════════════════════════════════
def test_manager_can_patch_business_unit_paired_ids():
    uid, tok = _mint_token("manager")
    inv_id = _seed_invoice(status="draft")
    incats = _real_income_categories()
    try:
        r = _patch(inv_id, {"business_unit": incats[1]["name"],
                             "business_unit_id": incats[1]["id"]}, tok)
        assert r.status_code == 200, r.text
        assert r.json()["invoice"]["business_unit"] == incats[1]["name"]
        assert r.json()["invoice"]["business_unit_id"] == incats[1]["id"]
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 5 · manager can PATCH line_items with ONLY category + income_category_id
# ═══════════════════════════════════════════════════════════════════
def test_manager_can_patch_line_items_category_only():
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    old_cat = incats[0]
    new_cat = incats[1]
    inv_id = _seed_invoice(
        status="draft",
        line_items=[
            {"id": "li-1", "description": "TEST_service",
              "quantity": 1, "unit_price": 100.0,
              "category": old_cat["name"],
              "income_category_id": old_cat["id"],
              "service_category": svcats[0]["name"],
              "service_category_id": svcats[0]["id"]},
        ],
    )
    try:
        r = _patch(inv_id, {
            "line_items": [
                # ONLY ``category`` + ``income_category_id`` differ.
                # service_category_* preserved verbatim so K71 validator
                # passes AND the diff still counts as category-only.
                {"id": "li-1", "description": "TEST_service",
                  "quantity": 1, "unit_price": 100.0,
                  "category": new_cat["name"],
                  "income_category_id": new_cat["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["changed"] is True
        li = body["invoice"]["line_items"][0]
        assert li["category"] == new_cat["name"]
        assert li["income_category_id"] == new_cat["id"]
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 6a · manager 403 on line_items with quantity touched
# ═══════════════════════════════════════════════════════════════════
def test_manager_403_on_line_items_quantity_touched():
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"id": "li-1", "description": "TEST_service",
                  "quantity": 2, "unit_price": 100.0,
                  "category": incats[0]["name"],
                  "income_category_id": incats[0]["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 6b · manager 403 on line_items with unit_price touched
# ═══════════════════════════════════════════════════════════════════
def test_manager_403_on_line_items_unit_price_touched():
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"id": "li-1", "description": "TEST_service",
                  "quantity": 1, "unit_price": 150.0,
                  "category": incats[0]["name"],
                  "income_category_id": incats[0]["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 6c · manager 200 on line_items with description touched (β widen)
#      Feb-2026 β — ``description`` moved into the metadata-only
#      role widener so manager / owner can edit it. Shipped
#      narrower lock inverted.
# ═══════════════════════════════════════════════════════════════════
def test_manager_200_on_line_items_description_touched():
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"id": "li-1", "description": "TEST_service_edited",
                  "quantity": 1, "unit_price": 100.0,
                  "category": incats[0]["name"],
                  "income_category_id": incats[0]["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 7a · manager 403 on top-level tax_rate
# ═══════════════════════════════════════════════════════════════════
def test_manager_403_on_top_level_tax_rate():
    uid, tok = _mint_token("manager")
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"tax_rate": 8.25}, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 7b · manager 200 on top-level notes (β widen)
#      Feb-2026 β — top-level ``notes`` / ``memo`` / ``private_notes``
#      moved into the metadata-only role widener. Shipped narrower
#      lock inverted.
# ═══════════════════════════════════════════════════════════════════
def test_manager_200_on_top_level_notes():
    uid, tok = _mint_token("manager")
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"notes": "TEST_mgr_notes"}, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 8 · owner matrix — happy
# ═══════════════════════════════════════════════════════════════════
def test_owner_can_patch_business_unit_top_level():
    uid, tok = _mint_token("owner")
    incats = _real_income_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        tgt = incats[2]["name"] if len(incats) > 2 else incats[1]["name"]
        r = _patch(inv_id, {"business_unit": tgt}, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


def test_owner_can_patch_line_items_category_only():
    uid, tok = _mint_token("owner")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    old_cat = incats[0]
    new_cat = incats[1]
    inv_id = _seed_invoice(
        status="draft",
        line_items=[
            {"id": "li-1", "description": "TEST_service",
              "quantity": 1, "unit_price": 100.0,
              "category": old_cat["name"],
              "income_category_id": old_cat["id"],
              "service_category": svcats[0]["name"],
              "service_category_id": svcats[0]["id"]},
        ],
    )
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"id": "li-1", "description": "TEST_service",
                  "quantity": 1, "unit_price": 100.0,
                  "category": new_cat["name"],
                  "income_category_id": new_cat["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 8 · owner matrix — denied
# ═══════════════════════════════════════════════════════════════════
def test_owner_403_on_line_items_quantity_touched():
    uid, tok = _mint_token("owner")
    incats = _real_income_categories()
    svcats = _real_service_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {
            "line_items": [
                {"id": "li-1", "description": "TEST_service",
                  "quantity": 3, "unit_price": 100.0,
                  "category": incats[0]["name"],
                  "income_category_id": incats[0]["id"],
                  "service_category": svcats[0]["name"],
                  "service_category_id": svcats[0]["id"]},
            ],
        }, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


def test_owner_403_on_top_level_tax_rate():
    uid, tok = _mint_token("owner")
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"tax_rate": 9.9}, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 10 · technician / customer / dispatcher — 403 on everything
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["technician", "customer", "dispatcher"])
def test_non_privileged_roles_403_on_category_only(role):
    uid, tok = _mint_token(role)
    incats = _real_income_categories()
    inv_id = _seed_invoice(status="draft")
    try:
        r = _patch(inv_id, {"business_unit": incats[1]["name"]}, tok)
        assert r.status_code == 403, r.text
        assert r.json().get("detail") == "admin_only"
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


# ═══════════════════════════════════════════════════════════════════
# 11 · DOC-LOCK-POLICY-RELAX · Feb-2026 — sent invoice no longer
# requires confirmation. The ``acknowledged_lock_bypass`` flag is
# accepted on the body for back-compat but is no longer required.
# ═══════════════════════════════════════════════════════════════════
def test_sent_invoice_manager_now_succeeds_without_confirmation():
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    inv_id = _seed_invoice(status="sent")
    try:
        r = _patch(inv_id, {"business_unit": incats[1]["name"]}, tok)
        assert r.status_code == 200, (
            f"DOC-LOCK-POLICY-RELAX: sent invoice should accept the "
            f"manager-category-only PATCH without confirm; got "
            f"{r.status_code}: {r.text[:400]}"
        )
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)


def test_sent_invoice_manager_with_acknowledged_lock_bypass_succeeds():
    """Back-compat: the frontend still sends
    ``acknowledged_lock_bypass`` on PATCH; sent invoice continues to
    return 200 — the flag is now ignored by the gate but the shape
    stays stable so unmigrated callers aren't broken."""
    uid, tok = _mint_token("manager")
    incats = _real_income_categories()
    inv_id = _seed_invoice(status="sent")
    try:
        r = _patch(inv_id, {
            "business_unit": incats[1]["name"],
            "acknowledged_lock_bypass": True,
        }, tok)
        assert r.status_code == 200, (
            f"expected 200, got {r.status_code}: {r.text[:400]}"
        )
        assert r.json()["changed"] is True
    finally:
        _cleanup_invoice(inv_id)
        _cleanup_user(uid)
