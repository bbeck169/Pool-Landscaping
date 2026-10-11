"""Pricebook Category UX fixes · Feb-2026 — Task A.

Backend verification that ``PATCH /items/{id}`` persists a new
``service_category_id`` and ``income_category_id`` with the
following contract (locked by the new native-<select> inline cell
in the Pricebook list):

  * Valid active ``service_category_id`` → 200, Mongo row updated.
  * Unknown ``service_category_id``       → 400 service_category_invalid.
  * Archived ``service_category_id``      → 400 service_category_invalid.
  * ``service_category_id: null``         → 400 service_category_required
                                             (service is required).
  * Valid active ``income_category_id``   → 200, Mongo row updated.
  * ``income_category_id: null``          → 200 — row's income_category_id
                                             cleared (nullable server-side).
  * ``income_category_id: ""``            → 200 — same effect as null
                                             (empty-string sentinel normalised
                                             to ``None``).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_tenant():
    tid = f"TEST-pbcat-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid,
                             "slug": f"test-pbcat-{uuid.uuid4().hex[:6]}",
                             "name": "TEST_pbcat", "active": True})
    return tid


def _seed_admin(tid):
    from utils import hash_password
    uid = f"TEST-pbcat-u-{uuid.uuid4().hex[:6]}"
    email = f"pbcat-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_pbcat_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return uid, email, _login(email)


def _cleanup(tid, uid, email):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.service_categories.delete_many({"tenant_id": tid})
    _db.income_categories.delete_many({"tenant_id": tid})
    _db.items.delete_many({"tenant_id": tid})
    _CACHE.pop(f"tok:{email}", None)


def _seed_svc_cat(tid, name, archived=False):
    cid = f"TEST-pbcat-svc-{uuid.uuid4().hex[:6]}"
    _db.service_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "is_archived": archived, "sort_order": 0, "color": "#000000",
    })
    return cid


def _seed_income_cat(tid, name):
    cid = f"TEST-pbcat-inc-{uuid.uuid4().hex[:6]}"
    _db.income_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "is_archived": False, "sort_order": 0, "color": "#000000",
    })
    return cid


def _seed_item(tid, svc_id, income_id=None):
    iid = f"TEST-pbcat-item-{uuid.uuid4().hex[:6]}"
    _db.items.insert_one({
        "id": iid, "tenant_id": tid, "name": "TEST_PBcat_item",
        "service_category_id": svc_id,
        "income_category_id": income_id,
        "unit_price": 100.0, "tax_rate": 0.0,
        "item_type": "product",
    })
    return iid


def test_patch_service_category_valid_id_persists():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc_a = _seed_svc_cat(tid, "Alpha")
        svc_b = _seed_svc_cat(tid, "Bravo")
        item_id = _seed_item(tid, svc_a)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"service_category_id": svc_b},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "service_category_id": 1})
        assert row["service_category_id"] == svc_b
    finally:
        _cleanup(tid, uid, email)


def test_patch_service_category_unknown_id_rejected_400():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc = _seed_svc_cat(tid, "Alpha")
        item_id = _seed_item(tid, svc)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"service_category_id": "svc-does-not-exist"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "service_category_invalid"
        # Row should NOT have been mutated.
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "service_category_id": 1})
        assert row["service_category_id"] == svc
    finally:
        _cleanup(tid, uid, email)


def test_patch_service_category_archived_id_rejected_400():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc_active   = _seed_svc_cat(tid, "Alpha")
        svc_archived = _seed_svc_cat(tid, "Zed", archived=True)
        item_id = _seed_item(tid, svc_active)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"service_category_id": svc_archived},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "service_category_invalid"
    finally:
        _cleanup(tid, uid, email)


def test_patch_service_category_null_rejected_400_service_required():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc = _seed_svc_cat(tid, "Alpha")
        item_id = _seed_item(tid, svc)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"service_category_id": None},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "service_category_required"
        # Row unchanged.
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "service_category_id": 1})
        assert row["service_category_id"] == svc
    finally:
        _cleanup(tid, uid, email)


def test_patch_income_category_valid_id_persists():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc = _seed_svc_cat(tid, "Alpha")
        inc_a = _seed_income_cat(tid, "Service Revenue")
        inc_b = _seed_income_cat(tid, "Chemical Sales")
        item_id = _seed_item(tid, svc, income_id=inc_a)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"income_category_id": inc_b},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "income_category_id": 1})
        assert row["income_category_id"] == inc_b
    finally:
        _cleanup(tid, uid, email)


def test_patch_income_category_null_clears_value():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc = _seed_svc_cat(tid, "Alpha")
        inc = _seed_income_cat(tid, "Service Revenue")
        item_id = _seed_item(tid, svc, income_id=inc)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"income_category_id": None},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "income_category_id": 1})
        assert row["income_category_id"] is None
    finally:
        _cleanup(tid, uid, email)


def test_patch_income_category_empty_string_normalised_to_null():
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        svc = _seed_svc_cat(tid, "Alpha")
        inc = _seed_income_cat(tid, "Service Revenue")
        item_id = _seed_item(tid, svc, income_id=inc)
        r = requests.patch(
            f"{API}/items/{item_id}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"income_category_id": ""},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        row = _db.items.find_one({"id": item_id, "tenant_id": tid},
                                   {"_id": 0, "income_category_id": 1})
        assert row["income_category_id"] is None, (
            "empty-string sentinel on income_category_id must be "
            "normalised to Mongo null, not stored as the string \"\""
        )
    finally:
        _cleanup(tid, uid, email)
