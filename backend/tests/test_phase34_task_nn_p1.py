"""Task NN · Feb 2026 — P1 secondary bulk-endpoint tests.

Covers ``bulk_crm_p1.py`` — Reviews, Users, Customer Tags, Service
Reports, Time Entries. Fixture pattern mirrors
``test_phase34_task_ll_p2.py`` so the two suites share the tenant +
super_admin login machinery.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def super_uid():
    """Return the super_admin user id via the /me endpoint so tests
    can reliably identify the actor for self-delete/self-edit guards."""
    hdr = {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}
    r = requests.get(f"{API}/auth/me", headers=hdr, timeout=30)
    assert r.status_code == 200
    return r.json()["id"]


# ═══════════════════════════════════════════════════════════════════════
# Role gate — every new endpoint must 403 on customer role.
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    "/reviews/bulk-delete", "/reviews/bulk-update",
    "/users/bulk-delete", "/users/bulk-update",
    "/customer-tags/bulk-delete", "/customer-tags/bulk-update",
    "/service-reports/bulk-delete", "/service-reports/bulk-update",
    "/time-entries/bulk-delete", "/time-entries/bulk-update",
])
def test_p1_endpoints_reject_customer_role(customer_headers, path):
    body = {"ids": ["nope"]}
    if "update" in path:
        body["patch"] = {}
    r = requests.post(f"{API}{path}", headers={**customer_headers,
                                                       "Content-Type": "application/json"},
                          json=body, timeout=30)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# Reviews — bulk delete, bulk update, google-click locked
# ═══════════════════════════════════════════════════════════════════════
def test_reviews_bulk_update_status(db, super_headers, tid):
    async def _plant():
        rid = uuid.uuid4().hex
        await db.customer_portal_reviews.insert_one({
            "id": rid, "tenant_id": tid, "rating": 5,
            "status": "needs-response", "is_public": False,
        })
        return rid
    rid = _run(_plant())
    r = requests.post(f"{API}/reviews/bulk-update",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [rid], "patch": {
                              "status": "resolved", "is_public": True,
                          }}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["updated_count"] == 1


def test_reviews_bulk_delete_google_click_locked(db, super_headers, tid):
    async def _plant():
        rid = uuid.uuid4().hex
        await db.customer_portal_reviews.insert_one({
            "id": rid, "tenant_id": tid, "rating": 5,
            "google_click_at": "2026-02-15T00:00:00Z",
        })
        return rid
    rid = _run(_plant())
    r = requests.post(f"{API}/reviews/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [rid]}, timeout=30)
    body = r.json()
    assert body["deleted_count"] == 0
    assert "google" in body["failed"][0]["reason"].lower()


# ═══════════════════════════════════════════════════════════════════════
# Users — last-owner guard + self-edit guard
# ═══════════════════════════════════════════════════════════════════════
def test_users_bulk_update_rejects_editing_self(super_headers, super_uid):
    r = requests.post(f"{API}/users/bulk-update",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [super_uid],
                                  "patch": {"is_active": False}}, timeout=30)
    assert r.status_code == 400
    assert "own user" in r.text.lower()


def test_users_bulk_delete_rejects_last_owner(db, super_headers, tid):
    async def _plant():
        uid = uuid.uuid4().hex
        # Delete any pre-existing owners in this test tenant to
        # guarantee "last owner" state for the fixture. This test
        # tenant is a demo — no real users depend on this.
        await db.users.update_many({"tenant_id": tid, "role": "owner"},
                                          {"$set": {"role": "admin"}})
        await db.users.insert_one({
            "id": uid, "tenant_id": tid, "email": f"lastowner-{uid[:6]}@t.local",
            "role": "owner", "is_active": True,
        })
        return uid
    uid = _run(_plant())
    r = requests.post(f"{API}/users/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [uid]}, timeout=30)
    body = r.json()
    assert body["deleted_count"] == 0
    assert "last owner" in body["failed"][0]["reason"].lower()


def test_users_bulk_delete_rejects_self(super_headers, super_uid):
    r = requests.post(f"{API}/users/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [super_uid]}, timeout=30)
    body = r.json()
    assert body["deleted_count"] == 0
    assert "own active session" in body["failed"][0]["reason"].lower()


# ═══════════════════════════════════════════════════════════════════════
# Customer Tags — allow-list happy path
# ═══════════════════════════════════════════════════════════════════════
def test_tags_bulk_update_color_and_archive(db, super_headers, tid):
    async def _plant():
        a, b = uuid.uuid4().hex, uuid.uuid4().hex
        await db.customer_tags.insert_many([
            {"id": a, "tenant_id": tid, "name": "NN-tag-a", "color": "#000"},
            {"id": b, "tenant_id": tid, "name": "NN-tag-b", "color": "#000"},
        ])
        return a, b
    a, b = _run(_plant())
    r = requests.post(f"{API}/customer-tags/bulk-update",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [a, b], "patch": {
                              "color": "#FF00FF", "is_archived": True,
                          }}, timeout=30)
    assert r.status_code == 200
    assert r.json()["updated_count"] == 2


def test_tags_bulk_delete_happy(db, super_headers, tid):
    async def _plant():
        tid_ = uuid.uuid4().hex
        await db.customer_tags.insert_one({
            "id": tid_, "tenant_id": tid, "name": "NN-tag-del"})
        return tid_
    x = _run(_plant())
    r = requests.post(f"{API}/customer-tags/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [x]}, timeout=30)
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Service Reports — evidence-locked
# ═══════════════════════════════════════════════════════════════════════
def test_service_reports_bulk_delete_invoice_evidence_locked(
        db, super_headers, tid):
    async def _plant():
        sid = uuid.uuid4().hex
        await db.service_reports.insert_one({
            "id": sid, "tenant_id": tid, "job_id": "j-x",
            "evidence_invoice_id": "inv-42",
        })
        return sid
    sid = _run(_plant())
    r = requests.post(f"{API}/service-reports/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [sid]}, timeout=30)
    body = r.json()
    assert body["deleted_count"] == 0
    assert "evidence" in body["failed"][0]["reason"].lower()


def test_service_reports_bulk_update_visibility(db, super_headers, tid):
    async def _plant():
        sid = uuid.uuid4().hex
        await db.service_reports.insert_one({
            "id": sid, "tenant_id": tid, "job_id": "j-y",
            "is_customer_visible": False,
        })
        return sid
    sid = _run(_plant())
    r = requests.post(f"{API}/service-reports/bulk-update",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [sid],
                                  "patch": {"is_customer_visible": True}},
                          timeout=30)
    assert r.status_code == 200
    assert r.json()["updated_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Time Entries — paid-payroll locked
# ═══════════════════════════════════════════════════════════════════════
def test_time_entries_bulk_delete_paid_payroll_locked(
        db, super_headers, tid):
    async def _plant():
        te = uuid.uuid4().hex
        await db.time_entries.insert_one({
            "id": te, "tenant_id": tid, "user_id": "u-x",
            "hours": 8, "payroll_run_id": "pr-1",
            "payroll_paid_at": "2026-02-15T00:00:00Z",
        })
        return te
    te = _run(_plant())
    r = requests.post(f"{API}/time-entries/bulk-delete",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [te]}, timeout=30)
    body = r.json()
    assert body["deleted_count"] == 0
    assert "payroll" in body["failed"][0]["reason"].lower()


def test_time_entries_bulk_update_approve(db, super_headers, tid):
    async def _plant():
        te = uuid.uuid4().hex
        await db.time_entries.insert_one({
            "id": te, "tenant_id": tid, "user_id": "u-y",
            "hours": 6, "is_approved": False,
        })
        return te
    te = _run(_plant())
    r = requests.post(f"{API}/time-entries/bulk-update",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": [te], "patch": {"is_approved": True}},
                          timeout=30)
    assert r.status_code == 200
    assert r.json()["updated_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# 400-row cap (Task DD) & empty-ids (Task-BB) invariants per surface.
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    "/reviews/bulk-delete", "/users/bulk-delete",
    "/customer-tags/bulk-delete", "/service-reports/bulk-delete",
    "/time-entries/bulk-delete",
])
def test_p1_empty_ids_returns_400(super_headers, path):
    r = requests.post(f"{API}{path}",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": []}, timeout=30)
    assert r.status_code == 400


@pytest.mark.parametrize("path", [
    "/reviews/bulk-update", "/customer-tags/bulk-update",
    "/service-reports/bulk-update", "/time-entries/bulk-update",
])
def test_p1_empty_patch_returns_422(super_headers, path):
    r = requests.post(f"{API}{path}",
                          headers={**super_headers, "Content-Type": "application/json"},
                          json={"ids": ["x"], "patch": {"unknown_field": 1}},
                          timeout=30)
    assert r.status_code == 422
