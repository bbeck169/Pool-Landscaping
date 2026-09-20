"""MR-QoL · Feb-2026 — Bulk-approve / bulk-reject tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _super_headers():
    return _hdr("super@aquaterra.com")


def _customer_headers():
    return _hdr("customer@aquaterra.com")


def _tech_headers():
    tech = _sync.users.find_one({"role": "technician",
                                  "email": {"$exists": True, "$ne": None}})
    return _hdr(tech["email"])


@pytest.fixture
def three_pending():
    tid = _sync.users.find_one(
        {"email": "super@aquaterra.com"})["tenant_id"]
    ids = ["qol-b-1", "qol-b-2", "qol-b-3"]
    _sync.public_checkins.delete_many({"id": {"$in": ids + ["qol-b-approved"]}})
    docs = [{
        "id": pid, "tenant_id": tid, "state": "pending_review",
        "source_checkin_id": f"src-{pid}",
        "photo_license_ack": True,
        "service_name": f"Service {i}",
        "description": "", "tags": [], "photos": [],
        "raw_address": {"street": f"{100 + i} Main St", "city": "Peoria",
                         "state": "AZ", "zip": "85383", "country": "US"},
        "masked_address": None,
        "submitted_at": "2026-02-14T09:00:00Z",
        "created_at": "2026-02-14T09:00:00Z",
        "updated_at": "2026-02-14T09:00:00Z",
    } for i, pid in enumerate(ids, start=1)]
    # Also seed one row that's already approved so we can prove skips.
    docs.append({
        "id": "qol-b-approved", "tenant_id": tid, "state": "approved",
        "source_checkin_id": "src-qol-b-approved",
        "photo_license_ack": True,
        "service_name": "Already approved",
        "description": "", "tags": [], "photos": [],
        "raw_address": {"street": "1 Way", "city": "Peoria",
                         "state": "AZ", "zip": "85383", "country": "US"},
        "masked_address": {"street_name": "Way", "city": "Peoria",
                             "state": "AZ"},
        "submitted_at": "2026-02-14T08:00:00Z",
        "approved_at": "2026-02-14T08:30:00Z",
    })
    _sync.public_checkins.insert_many(docs)
    yield {"tenant_id": tid, "ids": ids, "extra": "qol-b-approved"}
    _sync.public_checkins.delete_many({"id": {"$in": ids + ["qol-b-approved"]}})
    _sync.audit_logs.delete_many(
        {"details": {"$regex": r"public_id=qol-b-"}})


# ─── Bulk approve ──────────────────────────────────────────────────

def test_bulk_approve_flips_only_pending(three_pending):
    ids = three_pending["ids"] + [three_pending["extra"]]
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                       json={"ids": ids, "reviewer_notes": "LGTM"},
                       headers=_super_headers(), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] == 3
    assert body["skipped"] == 1
    # Per-row shape
    by_id = {row["id"]: row for row in body["results"]}
    for pid in three_pending["ids"]:
        assert by_id[pid]["status"] == "approved"
    assert by_id[three_pending["extra"]]["status"] == "skipped"
    assert "state=approved" in by_id[three_pending["extra"]]["reason"]
    # Masked address computed per row.
    row = _sync.public_checkins.find_one({"id": three_pending["ids"][0]})
    assert row["state"] == "approved"
    assert row["masked_address"]["street_name"] == "Main St"
    assert row["masked_address"]["city"] == "Peoria"
    assert row["reviewer_notes"] == "LGTM"


def test_bulk_approve_second_call_all_skipped(three_pending):
    ids = three_pending["ids"]
    requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                    json={"ids": ids}, headers=_super_headers(), timeout=20)
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                       json={"ids": ids}, headers=_super_headers(), timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] == 0
    assert body["skipped"] == 3
    for row in body["results"]:
        assert row["status"] == "skipped"
        assert "state=approved" in row["reason"]


def test_bulk_approve_writes_audit_rows(three_pending):
    ids = three_pending["ids"]
    requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                    json={"ids": ids}, headers=_super_headers(), timeout=20)
    for pid in ids:
        rows = list(_sync.audit_logs.find(
            {"event": "public_checkin_approved",
              "details": {"$regex": pid}},
            {"_id": 0}))
        assert rows, f"no audit for {pid}"


def test_bulk_approve_hard_cap_100():
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                       json={"ids": ["x"] * 101},
                       headers=_super_headers(), timeout=15)
    assert r.status_code == 422


def test_bulk_approve_customer_forbidden():
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                       json={"ids": ["x"]},
                       headers=_customer_headers(), timeout=15)
    assert r.status_code == 403


def test_bulk_approve_tech_forbidden():
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-approve",
                       json={"ids": ["x"]},
                       headers=_tech_headers(), timeout=15)
    assert r.status_code == 403


# ─── Bulk reject ───────────────────────────────────────────────────

def test_bulk_reject_requires_notes(three_pending):
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-reject",
                       json={"ids": three_pending["ids"]},
                       headers=_super_headers(), timeout=15)
    assert r.status_code == 422


def test_bulk_reject_empty_notes_422(three_pending):
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-reject",
                       json={"ids": three_pending["ids"], "reviewer_notes": ""},
                       headers=_super_headers(), timeout=15)
    assert r.status_code == 422


def test_bulk_reject_flips_state_and_skips_non_pending(three_pending):
    ids = three_pending["ids"] + [three_pending["extra"]]
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-reject",
                       json={"ids": ids, "reviewer_notes": "Not on brand"},
                       headers=_super_headers(), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"] == 3 and body["skipped"] == 1
    for pid in three_pending["ids"]:
        row = _sync.public_checkins.find_one({"id": pid})
        assert row["state"] == "rejected"
        assert row["reviewer_notes"] == "Not on brand"


def test_bulk_reject_customer_forbidden():
    r = requests.post(f"{API}/admin/moderation/public-checkins/bulk-reject",
                       json={"ids": ["x"], "reviewer_notes": "no"},
                       headers=_customer_headers(), timeout=15)
    assert r.status_code == 403
