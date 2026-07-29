"""MR0 · Feb-2026 — Public check-in submit + moderation queue tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.address_masker import mask_street, mask_address

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

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


# ─── Pure-function tests (address masking) ─────────────────────────

def test_mask_street_strips_leading_house_number():
    assert mask_street("1234 Main St") == "Main St"


def test_mask_street_preserves_name_only():
    assert mask_street("Main St") == "Main St"


def test_mask_street_handles_single_digit_prefix():
    assert mask_street("1 Way") == "Way"


def test_mask_street_preserves_po_box():
    # No leading numeric run — the "42" is not at the start.
    assert mask_street("PO Box 42") == "PO Box 42"


def test_mask_street_handles_alphanumeric_prefix():
    # "1234A" is still a valid house-number pattern.
    assert mask_street("1234A Oak Ave") == "Oak Ave"


def test_mask_street_empty_and_none():
    assert mask_street("") == ""
    assert mask_street(None) == ""


def test_mask_address_composes_public_shape():
    out = mask_address({"street": "50 First Rd", "city": "Peoria",
                          "state": "AZ", "zip": "85383"})
    assert out == {"street_name": "First Rd", "city": "Peoria", "state": "AZ"}


# ─── Fixtures ──────────────────────────────────────────────────────

def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


@pytest.fixture
def seeded_checkin():
    tid = _tenant_of("super@aquaterra.com")
    tech = _sync.users.find_one({"tenant_id": tid, "role": "technician"},
                                  {"_id": 0, "id": 1, "email": 1})
    # Pick or create a customer with a full address.
    cust = _sync.customers.find_one({"tenant_id": tid,
                                       "address_street": {"$exists": True,
                                                             "$ne": ""}})
    if not cust:
        cust_id = "mr0-test-cust"
        _sync.customers.insert_one({
            "id": cust_id, "tenant_id": tid,
            "name": "MR0 Test Customer",
            "address_street": "1234 Main St",
            "address_city": "Peoria",
            "address_state": "AZ",
            "address_zip": "85383",
            "address_country": "US",
        })
        created_cust = True
    else:
        cust_id = cust["id"]
        created_cust = False

    # Create a job/workorder + checkin.
    job_id = "mr0-test-job"
    _sync.jobs.insert_one({
        "id": job_id, "tenant_id": tid,
        "customer_id": cust_id,
        "service_name": "Weekly Pool Service",
        "service_category": "pool_service",
    })

    checkin_id = "mr0-test-checkin"
    _sync.checkins.insert_one({
        "id": checkin_id, "tenant_id": tid,
        "job_id": job_id,
        "technician_id": tech["id"],
        "technician_name": "Test Tech",
        "note": "Cleaned filter, balanced chemistry, brushed walls.",
        "photos": [
            "https://example.com/p1.jpg",
            {"url": "https://example.com/p2.jpg", "alt": "after"},
        ],
        "created_at": "2026-02-14T09:00:00Z",
    })

    yield {"tenant_id": tid, "tech": tech, "job_id": job_id,
            "checkin_id": checkin_id, "customer_id": cust_id}

    # Teardown
    _sync.public_checkins.delete_many({"source_checkin_id": checkin_id})
    _sync.jobs.delete_one({"id": job_id})
    _sync.checkins.delete_one({"id": checkin_id})
    _sync.audit_logs.delete_many({"details": {"$regex": f"public_id="}})
    if created_cust:
        _sync.customers.delete_one({"id": cust_id})


# ─── Submit gate ────────────────────────────────────────────────────

def test_submit_returns_opt_out_when_publish_false(seeded_checkin):
    r = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": False, "photo_license_ack": True},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"submitted": False, "reason": "opt_out_or_no_license"}
    assert _sync.public_checkins.count_documents(
        {"source_checkin_id": seeded_checkin["checkin_id"]}) == 0


def test_submit_returns_opt_out_when_license_false(seeded_checkin):
    r = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": False},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["submitted"] is False


def test_submit_creates_row_when_both_true(seeded_checkin):
    r = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True,
                "description": "Custom write-up", "tags": ["pool", "weekly"]},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] is True and body["public_checkin_id"]
    row = _sync.public_checkins.find_one({"id": body["public_checkin_id"]})
    assert row is not None
    assert row["state"] == "pending_review"
    assert row["description"] == "Custom write-up"
    assert row["tags"] == ["pool", "weekly"]
    assert row["photos"] and len(row["photos"]) == 2
    assert row["raw_address"]["street"] == "1234 Main St"
    assert row["masked_address"] is None  # not masked yet


def test_double_submit_returns_409(seeded_checkin):
    for _ in range(1):
        r = requests.post(
            f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
            json={"publish_to_website": True, "photo_license_ack": True},
            headers=_super_headers(), timeout=15,
        )
        assert r.status_code == 200 and r.json()["submitted"]
    r2 = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=_super_headers(), timeout=15,
    )
    assert r2.status_code == 409, r2.text


def test_submit_customer_forbidden(seeded_checkin):
    r = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=_customer_headers(), timeout=15,
    )
    assert r.status_code == 403, r.text


# ─── List + detail + patch ─────────────────────────────────────────

def _submit(seeded_checkin) -> str:
    r = requests.post(
        f"{API}/checkins/{seeded_checkin['checkin_id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=_super_headers(), timeout=15,
    )
    r.raise_for_status()
    return r.json()["public_checkin_id"]


def test_list_default_pending_review(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.get(f"{API}/admin/moderation/public-checkins",
                        headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert pid in ids
    # All items are pending_review
    for it in body["items"]:
        assert it["state"] == "pending_review"


def test_list_pagination(seeded_checkin):
    _submit(seeded_checkin)
    r = requests.get(
        f"{API}/admin/moderation/public-checkins",
        params={"limit": 1, "offset": 0},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["limit"] == 1 and body["offset"] == 0


def test_detail_returns_full_row(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.get(f"{API}/admin/moderation/public-checkins/{pid}",
                        headers=_super_headers(), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == pid
    assert "raw_address" in body


def test_patch_updates_editable_fields(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.patch(
        f"{API}/admin/moderation/public-checkins/{pid}",
        json={"service_name": "Custom Name",
                "tags": ["custom-tag"],
                "description": "Edited description"},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service_name"] == "Custom Name"
    assert body["tags"] == ["custom-tag"]
    assert body["description"] == "Edited description"


# ─── Approve / reject / unpublish ───────────────────────────────────

def test_approve_computes_masked_address(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/approve",
        json={"reviewer_notes": "LGTM"},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "approved"
    assert body["masked_address"] == {
        "street_name": "Main St",
        "city": "Peoria",
        "state": "AZ",
    }
    assert body["approved_at"] and body["approved_by_user_id"]
    assert body["reviewer_notes"] == "LGTM"


def test_reject_requires_notes(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/reject",
        json={},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 422, r.text


def test_reject_flips_state(seeded_checkin):
    pid = _submit(seeded_checkin)
    r = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/reject",
        json={"reviewer_notes": "Not a good fit"},
        headers=_super_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "rejected"


def test_unpublish_only_from_approved(seeded_checkin):
    pid = _submit(seeded_checkin)
    # Try unpublish while still pending → 409
    r0 = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/unpublish",
        json={}, headers=_super_headers(), timeout=15,
    )
    assert r0.status_code == 409, r0.text
    # Approve then unpublish → 200
    requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/approve",
        json={}, headers=_super_headers(), timeout=15,
    )
    r1 = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/unpublish",
        json={}, headers=_super_headers(), timeout=15,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["state"] == "unpublished"


def test_audit_rows_written(seeded_checkin):
    pid = _submit(seeded_checkin)
    requests.post(f"{API}/admin/moderation/public-checkins/{pid}/approve",
                    json={}, headers=_super_headers(), timeout=15)
    events = list(_sync.audit_logs.find(
        {"details": {"$regex": pid}}, {"_id": 0, "event": 1, "details": 1}))
    kinds = {e["event"] for e in events}
    assert "public_checkin_submitted" in kinds
    assert "public_checkin_approved" in kinds


# ─── RBAC ───────────────────────────────────────────────────────────

def test_moderation_list_tech_forbidden():
    r = requests.get(f"{API}/admin/moderation/public-checkins",
                        headers=_tech_headers(), timeout=15)
    assert r.status_code == 403


def test_moderation_list_customer_forbidden():
    r = requests.get(f"{API}/admin/moderation/public-checkins",
                        headers=_customer_headers(), timeout=15)
    assert r.status_code == 403
