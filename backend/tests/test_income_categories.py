"""Income category picklist + enforcement · Feb-2026."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                               json={"email": email, "password": "password123"},
                               timeout=30)
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _admin_ctx() -> dict:
    if _CACHE.get("admin_ctx"):
        return _CACHE["admin_ctx"]
    # Feb-2026 · fixture-drift fix: this fixture historically used
    # ``manager@aquaterra.com`` (role="manager"), which pre-dates the
    # income-category CRUD tightening to ``admin | super_admin`` (see
    # ``routers/income_categories.py::_require_admin``).  Every test
    # that relied on this ctx to CRUD categories/invoices now needs
    # the elevated role.  Switch to ``admin@aquaterra.com`` so the
    # fixture matches the current handler contract.  Grandfathered
    # read-only tests (``test_grandfathered_invoice_readable``,
    # ``test_uncategorized_count_endpoint``) also pass under admin.
    tok = _login("admin@aquaterra.com")
    me = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=15).json()
    _CACHE["admin_ctx"] = {
        "token": tok,
        "tenant_id": me.get("tenant_id"),
        "customer_id": me.get("customer_id"),
    }
    return _CACHE["admin_ctx"]


def _cust_tok():
    return _login("customer@aquaterra.com")


def _seed_isolated_tenant() -> str:
    tid = f"TEST-inccat-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid,
                             "slug": f"test-inccat-{uuid.uuid4().hex[:6]}",
                             "name": "TEST_inccat_tenant", "active": True})
    return tid


def _seed_admin_for(tid: str) -> tuple[str, str, str]:
    from utils import hash_password
    uid = f"TEST-inccat-u-{uuid.uuid4().hex[:6]}"
    email = f"inccat-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_inccat_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return uid, email, _login(email)


def _cleanup_tenant(tid: str):
    _db.tenants.delete_one({"id": tid})
    _db.income_categories.delete_many({"tenant_id": tid})
    _db.quotes.delete_many({"tenant_id": tid})
    _db.customers.delete_many({"tenant_id": tid})


def _seed_customer(tid: str) -> str:
    cid = f"TEST-inccat-cust-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "TEST cust",
        "email": "t@example.com", "phone": "+15555550100",
    })
    return cid


# ─────────────── 1. Admin CRUD happy path ─────────────────────
def test_admin_can_crud_categories():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    try:
        # Trigger seed via GET.
        r = requests.get(f"{API}/income-categories",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        # Phase K71 · Feb-2026 — seed count is now 14 (6 pre-K71 + 8
        # K71 additive defaults).
        assert len(r.json()["items"]) == 14
        # Create.
        r = requests.post(f"{API}/income-categories",
                          json={"name": "TEST_Salt", "description": "d",
                                 "color": "#123456", "sort_order": 5},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        new = r.json()
        # Patch.
        r = requests.patch(f"{API}/income-categories/{new['id']}",
                            json={"name": "TEST_Salt_Edited"},
                            headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "TEST_Salt_Edited"
        # Archive.
        r = requests.post(f"{API}/income-categories/{new['id']}/archive",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200 and r.json()["is_archived"] is True
        # Restore.
        r = requests.post(f"{API}/income-categories/{new['id']}/restore",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200 and r.json()["is_archived"] is False
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 2. Non-admin blocked ────────────────────────
def test_non_admin_cannot_crud_403():
    r = requests.get(f"{API}/income-categories",
                      headers={"Authorization": f"Bearer {_cust_tok()}"},
                      timeout=15)
    assert r.status_code == 403


# ─────────────── 3. Uniqueness ────────────────────────────────
def test_uniqueness_within_tenant():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    try:
        requests.get(f"{API}/income-categories",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        r = requests.post(f"{API}/income-categories",
                          json={"name": "Pool"},  # already seeded
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "duplicate_name"
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 4. Seed defaults ─────────────────────────────
def test_seed_defaults_on_first_access():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    try:
        # Before first call: zero cats for this tenant.
        assert _db.income_categories.count_documents({"tenant_id": tid}) == 0
        r = requests.get(f"{API}/income-categories",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        names = {c["name"] for c in r.json()["items"]}
        # Phase K71 · Feb-2026 — seed list expanded with 8 additive K71
        # defaults; the pre-K71 6 defaults must still all be present.
        assert {"Pool", "Chemicals", "Landscaping", "Repair", "Late Fee",
                 "Other"}.issubset(names)
        assert {"Service Revenue", "Product Sales",
                 "Recurring Maintenance", "One-time Project",
                 "Warranty Work", "Labor Income", "Materials",
                 "Other Income"}.issubset(names)
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 5. Invoice without category now ALLOWED ─────
def test_new_invoice_without_category_400_category_required():
    """Feb-2026 · invoice-category hard-block removal — invoice
    save with missing legacy ``category`` is now permitted
    (200 + audit row). Pre-removal: 400 ``category_required``.
    Test name kept intentionally for grep continuity with the
    old contract.
    """
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        # Trigger default seed.
        requests.get(f"{API}/income-categories",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        payload = {
            "customer_id": cid,
            "title": "TEST_no_cat", "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                {"description": "TEST_x", "quantity": 1, "unit_price": 50,
                  "category": ""},
            ],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("doc_type") == "invoice"
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 6. Invoice with valid category succeeds ──────
def test_new_invoice_with_valid_category_200():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        r = requests.get(f"{API}/income-categories",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
        pool_id = next(c["id"] for c in r["items"] if c["name"] == "Pool")
        payload = {
            "customer_id": cid,
            "title": "TEST_with_cat", "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                {"description": "TEST_svc", "quantity": 1, "unit_price": 100,
                  "category": pool_id},
            ],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 7. Edit line-items without category rejected ─
def test_edit_invoice_line_item_without_category_400():
    """Editing an invoice's line_items without categories should also
    be rejected via the invoice_edit PATCH endpoint."""
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]
    # Trigger default seed on this real tenant if not present.
    requests.get(f"{API}/income-categories",
                  headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15)
    inv_id = f"TEST-inccat-inv-{uuid.uuid4().hex[:6]}"
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "TEST-cust-x", "customer_name": "x",
        "invoice_number": inv_id, "status": "draft",
        "total": 50, "subtotal": 50, "tax": 0, "tax_rate": 0,
        "currency": "USD",
        "line_items": [{"description": "old", "quantity": 1, "unit_price": 50}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.patch(
            f"{API}/quotes/{inv_id}",
            json={"line_items": [
                {"description": "TEST_edited", "quantity": 2, "unit_price": 40},
            ]},
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        # Feb-2026 · invoice-category hard-block removal —
        # legacy ``category_required`` 400 was demoted to a
        # non-blocking warning + audit row.
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ─────────────── 8. Grandfather — old invoice readable ────────
def test_grandfathered_invoice_readable():
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]
    inv_id = f"TEST-inccat-grand-{uuid.uuid4().hex[:6]}"
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "TEST-cust-y", "customer_name": "y",
        "invoice_number": inv_id, "status": "sent",
        "total": 200, "subtotal": 200, "tax": 0, "tax_rate": 0,
        "currency": "USD",
        # No category on the line — pre-existing shape.
        "line_items": [{"description": "grand", "quantity": 1,
                          "unit_price": 200}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(f"{API}/quotes/{inv_id}",
                          headers={"Authorization": f"Bearer {ctx['token']}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["line_items"][0]["description"] == "grand"
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ─────────────── 9. Editing a grandfathered invoice forces category ──
def test_edit_invoice_forces_category_on_touched_lines():
    """Same behaviour as test 7 — the moment you touch line_items, the
    new payload must carry categories on every row."""
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]
    inv_id = f"TEST-inccat-touch-{uuid.uuid4().hex[:6]}"
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "TEST-cust-z", "customer_name": "z",
        "invoice_number": inv_id, "status": "draft",
        "total": 50, "subtotal": 50, "tax": 0, "tax_rate": 0,
        "currency": "USD",
        # Pre-existing null category — grandfathered.
        "line_items": [{"description": "old", "quantity": 1, "unit_price": 50,
                          "category": None}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Feb-2026 · invoice-category hard-block removal — PATCH
        # with missing category on a touched line is now 200
        # (audit row written). Pre-removal: 400 category_required.
        r = requests.patch(
            f"{API}/quotes/{inv_id}",
            json={"line_items": [
                {"description": "old", "quantity": 1, "unit_price": 50},
            ]},
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        # Adding a valid category still succeeds.
        r = requests.patch(
            f"{API}/quotes/{inv_id}",
            json={"line_items": [
                {"description": "old", "quantity": 1, "unit_price": 50,
                  "category": "Pool"},
            ]},
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ─────────────── 10. Archived category rejected ────────────────
def test_archived_category_not_selectable_on_new_invoice():
    """Phase 26b · Feb-2026 — contract flipped: archive now
    auto-maps instead of blocking save.

    Before Phase 26b: POST /quotes with a line pointing at an
    archived income category returned HTTP 400 ``category_invalid``.

    After Phase 26b: the K71 + legacy validators soft-pass archived
    refs — the save succeeds HTTP 200, the ``category`` on the line
    is null'd, and the line is stamped with
    ``category_auto_mapped: true`` + ``original_category_id`` +
    ``original_category_name`` so the editor renders an amber
    "Needs re-pick" chip until the operator manually re-assigns.
    """
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        r = requests.get(f"{API}/income-categories",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
        other_id = next(c["id"] for c in r["items"] if c["name"] == "Other")
        other_name = next(c["name"] for c in r["items"] if c["id"] == other_id)
        # Archive Other.
        requests.post(f"{API}/income-categories/{other_id}/archive",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        payload = {
            "customer_id": cid,
            "title": "TEST_archived", "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                {"description": "z", "quantity": 1, "unit_price": 10,
                  "category": other_id},
            ],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        # Phase 26b soft-pass → 200 OK, no block.
        assert r.status_code == 200, r.text
        body = r.json()
        line = body["line_items"][0]
        assert line["category"] == ""
        assert line["category_auto_mapped"] is True
        assert line["original_category_id"] == other_id
        assert line["original_category_name"] == other_name
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────── 11. Uncategorized count endpoint ─────────────
def test_uncategorized_count_endpoint():
    ctx = _admin_ctx()
    r = requests.get(f"{API}/reports/uncategorized-count",
                      headers={"Authorization": f"Bearer {ctx['token']}"},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["count"], int)
    assert isinstance(body["sample_invoices"], list)
    assert body["count"] >= 0


# ─────────────── 12. Portal booking — no category needed ──────
def test_portal_booking_uses_default_category():
    """The portal ``/me/book`` endpoint creates a JOB (no line_items),
    so no category enforcement runs. This test pins that contract so a
    future refactor that adds line_items to portal bookings must also
    add category handling — either by exposing a picker OR by
    auto-assigning the first active category. See report notes."""
    tok = _cust_tok()
    r = requests.post(
        f"{API}/me/book",
        json={"date": "2027-06-01", "label": "TEST_slot"},
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    # 200 with a message payload; no line_items => no category rejection.
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body.get("message") is not None
    # Cleanup the job we just created.
    _db.jobs.delete_many({"notes": {"$regex": "TEST_slot"}})
