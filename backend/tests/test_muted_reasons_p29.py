"""Feb-2026 · P29 — muted_reason snapshot + reasons CRUD.

Live HTTP + sync pymongo; mirrors P25/P26/P27 scaffolding.
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


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": "password123"},
                        timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
@pytest.fixture
def manager_h(): return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}
@pytest.fixture
def tech_h(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, muted: bool = False) -> str:
    cid = f"TEST_p29_c_{uuid.uuid4().hex[:8]}"
    doc = {"id": cid, "tenant_id": tid,
             "name": "TEST P29 customer",
             "email": f"{cid}@example.com", "phone": "6235550100",
             "is_active": not muted}
    if muted:
        doc.update({"is_muted": True,
                       "muted_at": "2026-06-01T10:00:00+00:00",
                       "muted_reason": "Legacy no-reason mute"})
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(cids: list[str]):
    if cids:
        _sync.customers.delete_many({"id": {"$in": cids}})
        _sync.audit_logs.delete_many({"customer_id": {"$in": cids}})


def test_mute_with_reason_persists(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    try:
        r = requests.patch(f"{API}/customers/{cid}/mute", headers=admin_h,
                              json={"muted_reason": "Billing dispute"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["muted"] is True
        assert body["muted_reason"] == "Billing dispute"
        doc = _sync.customers.find_one({"id": cid})
        assert doc["muted_reason"] == "Billing dispute"
    finally:
        _cleanup([cid])


def test_mute_with_blank_reason_normalizes_to_null(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    try:
        r = requests.patch(f"{API}/customers/{cid}/mute", headers=admin_h,
                              json={"muted_reason": "   "}, timeout=15)
        assert r.status_code == 200
        assert r.json()["muted_reason"] is None
        doc = _sync.customers.find_one({"id": cid})
        assert "muted_reason" not in doc or doc.get("muted_reason") in (None, "")
    finally:
        _cleanup([cid])


def test_mute_without_reason_backwards_compat(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    try:
        # No body at all — P27 signature stays supported.
        r = requests.patch(f"{API}/customers/{cid}/mute", headers=admin_h,
                              timeout=15)
        assert r.status_code == 200
        assert r.json()["muted"] is True
        assert r.json().get("muted_reason") is None
    finally:
        _cleanup([cid])


def test_unmute_clears_muted_reason(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid, muted=True)
    try:
        r = requests.patch(f"{API}/customers/{cid}/unmute", headers=admin_h,
                              timeout=15)
        assert r.status_code == 200
        doc = _sync.customers.find_one({"id": cid})
        assert "muted_reason" not in doc or doc.get("muted_reason") in (None, "")
    finally:
        _cleanup([cid])


def test_reasons_crud_rbac(admin_h, manager_h, tech_h):
    # GET is staff-open — all three roles get 200.
    for h in (admin_h, manager_h, tech_h):
        r = requests.get(f"{API}/settings/muted-reasons", headers=h, timeout=15)
        assert r.status_code == 200, r.text
    # Tech is blocked on POST.
    r_tech = requests.post(f"{API}/settings/muted-reasons",
                              headers=tech_h,
                              json={"label": "TEST tech blocked"}, timeout=15)
    assert r_tech.status_code == 403, r_tech.text
    # Manager succeeds on POST.
    label = f"TEST P29 mgr {uuid.uuid4().hex[:6]}"
    r_mgr = requests.post(f"{API}/settings/muted-reasons",
                             headers=manager_h, json={"label": label}, timeout=15)
    assert r_mgr.status_code == 200, r_mgr.text
    rid = r_mgr.json()["id"]
    try:
        # Duplicate label case-insensitive → 409.
        r_dup = requests.post(f"{API}/settings/muted-reasons",
                                 headers=manager_h,
                                 json={"label": label.upper()}, timeout=15)
        assert r_dup.status_code == 409, r_dup.text
        assert (r_dup.json().get("detail") or {}).get("detail") == "duplicate_label"
        # Deactivate hides from default GET but the row is retained.
        r_del = requests.delete(f"{API}/settings/muted-reasons/{rid}",
                                   headers=manager_h, timeout=15)
        assert r_del.status_code == 200 and r_del.json()["deactivated"] is True
        r_list = requests.get(f"{API}/settings/muted-reasons",
                                 headers=admin_h, timeout=15)
        labels = [row["label"] for row in r_list.json()["items"]]
        assert label not in labels
        # But include_inactive=true surfaces it.
        r_all = requests.get(
            f"{API}/settings/muted-reasons?include_inactive=true",
            headers=admin_h, timeout=15,
        )
        labels_all = [row["label"] for row in r_all.json()["items"]]
        assert label in labels_all
    finally:
        _sync.muted_reasons.delete_many({"id": rid})


def test_seeded_defaults_visible_for_aquaterra(admin_h):
    r = requests.get(f"{API}/settings/muted-reasons",
                        headers=admin_h, timeout=15)
    assert r.status_code == 200
    labels = [row["label"] for row in r.json()["items"]]
    # Defaults seeded by the migration.
    assert "Billing dispute" in labels
    assert "Requested no contact" in labels
    assert "Other" in labels
