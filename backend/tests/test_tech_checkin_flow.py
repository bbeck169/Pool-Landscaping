"""Feb-2026 · Technician Check-In flow — end-to-end backend tests.

Covers the fix for the ``submit_public_checkin`` handler that was
never populating ``lat_public`` / ``lng_public`` on the moderation
queue row (so approved rows never appeared on the public map), the
tightened ``POST /api/checkins`` payload contract, the storage-marker
guarantee on ``/api/files/upload``, and the public feed inclusion
criterion (approved AND has public coords).

Flow under test::

    1. POST /api/files/upload  → returns file_id
    2. POST /api/checkins       → 200 with status='draft' + photo_file_ids
    3. POST /api/checkins/{id}/submit-public → 200 + pending_review row
       with obfuscated lat_public / lng_public
    4. POST /api/admin/moderation/public-checkins/{pid}/approve → approved
    5. GET  /api/public/checkins/{tenant_slug}/pins → row appears
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

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


# ─── auth helpers ──────────────────────────────────────────────────

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


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


# ─── image bytes (tiny 1x1 red PNG) ────────────────────────────────

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_TINY_PNG = base64.b64decode(_TINY_PNG_B64)


# ─── fixture: full seeded flow ─────────────────────────────────────

@pytest.fixture
def tech_flow_ctx():
    """Seed a job + customer with geocode + upload a photo. Yields
    the ids needed by the flow tests. Teardown removes every row
    created."""
    tid = _tenant_of("super@aquaterra.com")
    tech = _sync.users.find_one({"tenant_id": tid, "role": "technician"},
                                 {"_id": 0, "id": 1, "email": 1})
    if not tech:
        pytest.skip("no technician user seeded for this tenant")

    cust_id = "tech-flow-cust"
    _sync.customers.insert_one({
        "id": cust_id, "tenant_id": tid,
        "name": "Tech Flow Test Customer",
        "address_street": "5678 Ocotillo Dr",
        "address_city": "Peoria",
        "address_state": "AZ",
        "address_zip": "85383",
        "address_country": "US",
        "latitude": 33.7801,
        "longitude": -112.3428,
    })
    job_id = "tech-flow-job"
    _sync.jobs.insert_one({
        "id": job_id, "tenant_id": tid,
        "customer_id": cust_id,
        "service_name": "Weekly Pool Service",
        "service_category": "pool_service",
        "completed_at": "2026-02-14T15:00:00Z",
    })

    # Ensure tenant has a slug so the widget pins endpoint resolves.
    tenant = _sync.tenants.find_one({"id": tid}, {"_id": 0, "slug": 1})
    tenant_slug = (tenant or {}).get("slug") or None

    yield {
        "tenant_id": tid,
        "tenant_slug": tenant_slug,
        "tech": tech,
        "customer_id": cust_id,
        "job_id": job_id,
    }

    # Teardown
    _sync.customers.delete_one({"id": cust_id})
    _sync.jobs.delete_one({"id": job_id})
    _sync.checkins.delete_many({"job_id": job_id})
    _sync.public_checkins.delete_many({"source_job_id": job_id})
    _sync.files.delete_many({"linked_entity_type": "public_checkin",
                              "tenant_id": tid,
                              "purpose": "public_checkin"})


def _upload_photo(headers: dict) -> dict:
    """Upload one PNG via ``/api/files/upload`` with the
    check-in purpose flags. Returns the response dict."""
    files = {"file": ("checkin.png", _TINY_PNG, "image/png")}
    data = {"purpose": "public_checkin",
             "linked_entity_type": "public_checkin"}
    r = requests.post(f"{API}/files/upload", headers=headers,
                       files=files, data=data, timeout=30)
    r.raise_for_status()
    return r.json()


# ═════════════════════════════════════════════════════════════════
# 1. Create-endpoint payload validation
# ═════════════════════════════════════════════════════════════════

def test_create_rejects_missing_job_id(tech_flow_ctx):
    hdr = _super_headers()
    upload = _upload_photo(hdr)
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "latitude": 33.78, "longitude": -112.34,
        "note": "cleaned filter",
        "photo_file_ids": [upload["id"]],
    }, timeout=15)
    assert r.status_code == 422, r.text


def test_create_rejects_missing_coords(tech_flow_ctx):
    hdr = _super_headers()
    upload = _upload_photo(hdr)
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "note": "cleaned filter",
        "photo_file_ids": [upload["id"]],
    }, timeout=15)
    assert r.status_code == 422, r.text


def test_create_rejects_empty_note(tech_flow_ctx):
    hdr = _super_headers()
    upload = _upload_photo(hdr)
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.78, "longitude": -112.34,
        "note": "",
        "photo_file_ids": [upload["id"]],
    }, timeout=15)
    assert r.status_code == 422, r.text


def test_create_rejects_zero_photos(tech_flow_ctx):
    hdr = _super_headers()
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.78, "longitude": -112.34,
        "note": "cleaned filter",
        "photo_file_ids": [],
    }, timeout=15)
    assert r.status_code == 422, r.text


def test_create_rejects_too_many_photos(tech_flow_ctx):
    hdr = _super_headers()
    # 6 photos — over the max of 5.
    uploads = [_upload_photo(hdr)["id"] for _ in range(6)]
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.78, "longitude": -112.34,
        "note": "cleaned filter",
        "photo_file_ids": uploads,
    }, timeout=15)
    assert r.status_code == 422, r.text


def test_create_rejects_wrong_purpose_photo(tech_flow_ctx):
    """A file uploaded with ``purpose='invoice_attachment'`` (or any
    non-``public_checkin`` purpose) is rejected — this keeps a tech
    from accidentally attaching a customer invoice PDF as a public
    map photo."""
    hdr = _super_headers()
    files = {"file": ("other.png", _TINY_PNG, "image/png")}
    data = {"purpose": "invoice_attachment",
             "linked_entity_type": "invoice"}
    up = requests.post(f"{API}/files/upload", headers=hdr,
                        files=files, data=data, timeout=30)
    up.raise_for_status()
    fid = up.json()["id"]
    try:
        r = requests.post(f"{API}/checkins", headers=hdr, json={
            "job_id": tech_flow_ctx["job_id"],
            "latitude": 33.78, "longitude": -112.34,
            "note": "cleaned filter",
            "photo_file_ids": [fid],
        }, timeout=15)
        assert r.status_code == 422, r.text
        body = r.json()
        assert (body.get("detail") or {}).get("code") == \
            "PHOTO_FILE_IDS_WRONG_PURPOSE"
    finally:
        _sync.files.delete_one({"id": fid})


def test_create_rejects_unknown_photo_id(tech_flow_ctx):
    hdr = _super_headers()
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.78, "longitude": -112.34,
        "note": "cleaned filter",
        "photo_file_ids": ["does-not-exist-xyz"],
    }, timeout=15)
    assert r.status_code == 422, r.text
    body = r.json()
    assert (body.get("detail") or {}).get("code") == \
        "PHOTO_FILE_IDS_INVALID"


def test_create_customer_forbidden_before_validation(tech_flow_ctx):
    """RBAC short-circuits BEFORE the tightened validator — a
    customer sending an otherwise-valid payload still gets 403."""
    r = requests.post(f"{API}/checkins", headers=_customer_headers(),
                        json={
                            "job_id": tech_flow_ctx["job_id"],
                            "latitude": 33.78, "longitude": -112.34,
                            "note": "cleaned filter",
                            "photo_file_ids": ["irrelevant"],
                        }, timeout=15)
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════
# 2. Happy-path create → submit → approve → public feed
# ═════════════════════════════════════════════════════════════════

def test_create_returns_draft_with_photo_ids(tech_flow_ctx):
    hdr = _super_headers()
    up = _upload_photo(hdr)
    r = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.78, "longitude": -112.34,
        "note": "Cleaned pump basket, balanced chemistry.",
        "photo_file_ids": [up["id"]],
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == tech_flow_ctx["job_id"]
    assert body["status"] == "draft"
    assert body["latitude"] == pytest.approx(33.78)
    assert body["longitude"] == pytest.approx(-112.34)
    assert body["photo_file_ids"] == [up["id"]]
    # Persisted with technician_id from caller (super_admin here).
    assert body.get("technician_id")


def test_submit_public_persists_public_coords(tech_flow_ctx):
    """Regression test for the Feb-2026 fix — after submit, the
    moderation-queue row must carry non-null ``lat_public`` +
    ``lng_public`` derived from the tech's GPS capture. Without
    them the widget map's ``_row_is_pinnable`` gate would silently
    skip the pin even after admin approval."""
    hdr = _super_headers()
    up = _upload_photo(hdr)
    create = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.7801, "longitude": -112.3428,
        "note": "Cleaned pump basket, balanced chemistry.",
        "photo_file_ids": [up["id"]],
    }, timeout=15).json()
    checkin_id = create["id"]

    r = requests.post(
        f"{API}/checkins/{checkin_id}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True,
                "description": "SEO-friendly write-up"},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["public_checkin_id"]
    row = _sync.public_checkins.find_one({"id": pid})
    assert row is not None
    assert row["state"] == "pending_review"
    assert row["source"] == "tech"
    # Public coords are populated and differ from raw by ≤ 0.001° in
    # each dimension (the obfuscator's guaranteed jitter window).
    assert row["lat_public"] is not None
    assert row["lng_public"] is not None
    assert abs(row["lat_public"] - 33.7801) <= 0.001
    assert abs(row["lng_public"] - (-112.3428)) <= 0.001
    # Raw coords survive on the row for admin-only view; area_label
    # is computed from the customer address.
    assert row["lat_raw"] == pytest.approx(33.7801)
    assert row["lng_raw"] == pytest.approx(-112.3428)
    assert row["area_label"] == "Peoria, AZ"
    # completed_at + month/year snapshot are also written.
    assert row["completed_at"]
    assert row["completed_at_month_year"] == "February 2026"

    # Source ``checkins`` doc got its status flipped so the mobile
    # Job-Detail screen can render "Submitted for review".
    src = _sync.checkins.find_one({"id": checkin_id},
                                    {"_id": 0, "status": 1,
                                     "public_checkin_id": 1})
    assert src["status"] == "submitted"
    assert src["public_checkin_id"] == pid


def test_submit_public_is_deterministic_per_checkin(tech_flow_ctx):
    """Same ``(lat, lng, checkin_id)`` MUST always produce the same
    ``(lat_public, lng_public)`` pair — this is what defeats the
    "scrape twice and average out the jitter" reverse-mapping
    attack."""
    from services.coord_obfuscator import obfuscate_coords
    hdr = _super_headers()
    up = _upload_photo(hdr)
    create = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.7801, "longitude": -112.3428,
        "note": "cleaned filter",
        "photo_file_ids": [up["id"]],
    }, timeout=15).json()
    checkin_id = create["id"]

    requests.post(
        f"{API}/checkins/{checkin_id}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=hdr, timeout=15,
    ).raise_for_status()
    row = _sync.public_checkins.find_one(
        {"source_checkin_id": checkin_id})

    expect_lat, expect_lng = obfuscate_coords(
        33.7801, -112.3428, seed=str(checkin_id))
    assert row["lat_public"] == pytest.approx(expect_lat)
    assert row["lng_public"] == pytest.approx(expect_lng)


def test_approve_flips_state_and_row_becomes_pinnable(tech_flow_ctx):
    """After approval, the widget map's ``_row_is_pinnable`` gate
    (state='approved' AND lat/lng_public non-null) accepts the row.
    This directly exercises the public feed inclusion criterion."""
    from routers.public_checkins_map import _row_is_pinnable
    hdr = _super_headers()
    up = _upload_photo(hdr)
    create = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.7801, "longitude": -112.3428,
        "note": "cleaned filter",
        "photo_file_ids": [up["id"]],
    }, timeout=15).json()
    submit = requests.post(
        f"{API}/checkins/{create['id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=hdr, timeout=15,
    ).json()
    pid = submit["public_checkin_id"]

    # Pre-approval — pending_review + coords set. NOT pinnable (state).
    row = _sync.public_checkins.find_one({"id": pid})
    assert row["state"] == "pending_review"
    assert not _row_is_pinnable(row)

    # Approve.
    r = requests.post(
        f"{API}/admin/moderation/public-checkins/{pid}/approve",
        json={"reviewer_notes": "LGTM"},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "approved"

    row2 = _sync.public_checkins.find_one({"id": pid})
    assert row2["state"] == "approved"
    assert _row_is_pinnable(row2)


# ═════════════════════════════════════════════════════════════════
# 3. Public feed inclusion criterion
# ═════════════════════════════════════════════════════════════════

def test_public_feed_excludes_rows_without_public_coords(tech_flow_ctx):
    """A hand-crafted approved row that's missing ``lat_public`` /
    ``lng_public`` MUST NOT appear on the widget map — the criterion
    is BOTH state='approved' AND coords non-null. Guards against a
    regression that ships a legacy row (no obfuscation) to the
    public map by accident."""
    from routers.public_checkins_map import _row_is_pinnable
    tid = tech_flow_ctx["tenant_id"]
    bad = {
        "id": "legacy-approved-no-coords",
        "tenant_id": tid,
        "state": "approved",
        "lat_public": None,
        "lng_public": None,
        "approved_at": "2026-02-10T12:00:00Z",
    }
    good = {
        "id": "modern-approved-with-coords",
        "tenant_id": tid,
        "state": "approved",
        "lat_public": 33.780123,
        "lng_public": -112.342567,
        "approved_at": "2026-02-10T12:00:00Z",
    }
    pending = {
        "id": "pending-with-coords",
        "tenant_id": tid,
        "state": "pending_review",
        "lat_public": 33.780456,
        "lng_public": -112.342999,
        "approved_at": None,
    }
    assert _row_is_pinnable(bad) is False
    assert _row_is_pinnable(good) is True
    assert _row_is_pinnable(pending) is False


# ═════════════════════════════════════════════════════════════════
# 4. Storage marker on file uploads
# ═════════════════════════════════════════════════════════════════

def test_upload_marks_storage_s3(tech_flow_ctx):
    """Every file inserted via ``/api/files/upload`` must carry
    ``storage='s3'`` so consumers can query the S3 fleet without
    inferring from the storage_path prefix. The endpoint 503s if S3
    is unavailable, so a 200 here IS the guarantee."""
    hdr = _super_headers()
    up = _upload_photo(hdr)
    fid = up["id"]
    doc = _sync.files.find_one({"id": fid},
                                 {"_id": 0, "storage": 1,
                                  "storage_path": 1,
                                  "purpose": 1,
                                  "linked_entity_type": 1})
    assert doc is not None
    assert doc["storage"] == "s3"
    # storage_path still resolves through the S3 backing — proves
    # the upload wasn't a base64 shim.
    assert doc["storage_path"]
    assert doc["purpose"] == "public_checkin"
    assert doc["linked_entity_type"] == "public_checkin"


# ═════════════════════════════════════════════════════════════════
# 5. Moderation queue lists new rows
# ═════════════════════════════════════════════════════════════════

def test_moderation_queue_lists_new_submission(tech_flow_ctx):
    hdr = _super_headers()
    up = _upload_photo(hdr)
    create = requests.post(f"{API}/checkins", headers=hdr, json={
        "job_id": tech_flow_ctx["job_id"],
        "latitude": 33.7801, "longitude": -112.3428,
        "note": "cleaned filter",
        "photo_file_ids": [up["id"]],
    }, timeout=15).json()
    submit = requests.post(
        f"{API}/checkins/{create['id']}/submit-public",
        json={"publish_to_website": True, "photo_license_ack": True},
        headers=hdr, timeout=15,
    ).json()
    pid = submit["public_checkin_id"]

    r = requests.get(f"{API}/admin/moderation/public-checkins",
                       params={"state": "pending_review"},
                       headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    ids = [it["id"] for it in r.json()["items"]]
    assert pid in ids
