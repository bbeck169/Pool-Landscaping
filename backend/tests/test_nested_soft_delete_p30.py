"""Feb-2026 · P30 — nested customer-scoped soft-delete audit tests.

Extends the P25 read-filter guarantee (``/api/customers``) to the
three routers that read/write customer-scoped data via a nested
customer-id in the path or body:

  * ``backend/routers/properties.py``
  * ``backend/routers/invoices_mp15.py``
  * ``backend/routers/ringcentral_customer.py``

Contract (mirrors P25):
  * Soft-deleted parent customer → **404** (not 403) on every
    nested read + write.
  * Non-deleted parent customer → happy-path 200 stays green.
  * ``/api/openapi.json`` still 200 (patched routers register cleanly).

Live HTTP + sync ``pymongo`` for setup, following the P25 conventions.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, *, deleted: bool = False) -> str:
    cid = f"TEST_p30_c_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P30 {'(deleted)' if deleted else '(active)'}",
        "email": f"{cid}@example.com",
        "phone": "6235550100",
        "address": "1 Test St",
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if deleted:
        doc["deleted_at"] = "2026-06-01T10:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(cids: list[str]) -> None:
    if cids:
        _sync.customers.delete_many({"id": {"$in": cids}})
        _sync.properties.delete_many({"customer_id": {"$in": cids}})
        _sync.quotes.delete_many({"customer_id": {"$in": cids}})
        _sync.call_logs.delete_many({"customer_id": {"$in": cids}})
        _sync.voicemails.delete_many({"matched_customer_id": {"$in": cids}})
        _sync.faxes.delete_many({"matched_customer_id": {"$in": cids}})
        _sync.sms_messages.delete_many({"customer_id": {"$in": cids}})


# ─── openapi still healthy ────────────────────────────────────────────

def test_openapi_still_lists_the_patched_nested_routes():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200, r.text
    paths = r.json().get("paths") or {}
    # A representative endpoint from each of the three touched routers.
    assert "/api/customers/{cid}/properties" in paths
    assert "/api/customers/{cid}/pending-invoices" in paths
    assert "/api/customers/{cid}/call-logs" in paths


# ─── properties.py — GET /customers/{cid}/properties ──────────────────

def test_list_customer_properties_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}/properties",
                            headers=admin_h, timeout=15)
        assert r.status_code == 404, r.text
    finally:
        _cleanup([deleted_id])


def test_list_customer_properties_200_when_parent_active(
    admin_h, aquaterra_tid,
):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.get(f"{API}/customers/{active_id}/properties",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        # Body is a list (possibly with lazy-backfill Main property).
        assert isinstance(r.json(), list)
    finally:
        _cleanup([active_id])


# ─── properties.py — POST /customers/{cid}/properties ─────────────────

def test_create_property_404_when_soft_deleted_parent(admin_h, aquaterra_tid):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.post(
            f"{API}/customers/{deleted_id}/properties",
            headers=admin_h,
            json={"label": "Should not create",
                    "address": {"address_line1": "1 Nowhere Ln", "city": "PHX",
                                  "state": "AZ", "zip": "85001"}},
            timeout=15,
        )
        assert r.status_code == 404, r.text
        assert r.json().get("detail") == "Customer not found"
    finally:
        _cleanup([deleted_id])


# ─── properties.py — PATCH /customers/{cid}/master-billing ────────────

def test_patch_master_billing_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.patch(
            f"{API}/customers/{deleted_id}/master-billing",
            headers=admin_h,
            json={"mode": "consolidated",
                    "master_billing_contact_email": "x@example.com",
                    "master_billing_contact_phone": None},
            timeout=15,
        )
        assert r.status_code == 404, r.text
    finally:
        _cleanup([deleted_id])


def test_patch_master_billing_200_when_parent_active(admin_h, aquaterra_tid):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.patch(
            f"{API}/customers/{active_id}/master-billing",
            headers=admin_h,
            json={"mode": "off",
                    "master_billing_contact_email": None,
                    "master_billing_contact_phone": None},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("master_billing_mode") == "off"
    finally:
        _cleanup([active_id])


# ─── invoices_mp15.py — GET /customers/{cid}/pending-invoices ─────────

def test_customer_pending_invoices_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}/pending-invoices",
                            headers=admin_h, timeout=15)
        assert r.status_code == 404, r.text
        assert r.json().get("detail") == "Customer not found"
    finally:
        _cleanup([deleted_id])


def test_customer_pending_invoices_200_when_parent_active(
    admin_h, aquaterra_tid,
):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.get(f"{API}/customers/{active_id}/pending-invoices",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        # Empty groups is fine — the shape is what matters.
        body = r.json()
        assert body.get("customer_id") == active_id
        assert isinstance(body.get("groups"), list)
    finally:
        _cleanup([active_id])


# ─── invoices_mp15.py — POST /invoices/consolidate ────────────────────

def test_consolidate_invoices_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.post(f"{API}/invoices/consolidate",
                             headers=admin_h,
                             json={"customer_id": deleted_id, "dry_run": True},
                             timeout=15)
        assert r.status_code == 404, r.text
    finally:
        _cleanup([deleted_id])


# ─── invoices_mp15.py — POST /invoices/preview-recipient ──────────────

def test_preview_recipient_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.post(f"{API}/invoices/preview-recipient",
                             headers=admin_h,
                             json={"customer_id": deleted_id},
                             timeout=15)
        assert r.status_code == 404, r.text
    finally:
        _cleanup([deleted_id])


def test_preview_recipient_200_when_parent_active(admin_h, aquaterra_tid):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.post(f"{API}/invoices/preview-recipient",
                             headers=admin_h,
                             json={"customer_id": active_id},
                             timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("customer_id") == active_id
    finally:
        _cleanup([active_id])


# ─── ringcentral_customer.py — the four nested GETs ───────────────────

@pytest.mark.parametrize("path", [
    "call-logs", "voicemails", "faxes", "sms-threads",
])
def test_ringcentral_customer_endpoints_404_when_soft_deleted_parent(
    admin_h, aquaterra_tid, path,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}/{path}",
                            headers=admin_h, timeout=15)
        assert r.status_code == 404, r.text
        assert r.json().get("detail") == "customer not found"
    finally:
        _cleanup([deleted_id])


@pytest.mark.parametrize("path", [
    "call-logs", "voicemails", "faxes", "sms-threads",
])
def test_ringcentral_customer_endpoints_200_when_parent_active(
    admin_h, aquaterra_tid, path,
):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.get(f"{API}/customers/{active_id}/{path}",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
    finally:
        _cleanup([active_id])


# ─── Tech JWT hits the same 404 on soft-deleted parent ────────────────
#
# The P25 threat model called out "a technician who knows a customer
# id" as the primary attack vector. This proves the guard trips before
# any role-scoping logic tries to short-circuit.

def test_technician_jwt_gets_404_on_soft_deleted_parent_read(
    tech_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}/properties",
                            headers=tech_h, timeout=15)
        assert r.status_code == 404, r.text
    finally:
        _cleanup([deleted_id])
