"""Feb-2026 · P41 — CSV import for customers.

Backend E2E tests hit the live server at ``localhost:8001``. Every test
seeds and cleans up its own rows via the tenant-scoped ``TEST_p41_`` id
prefix so parallel runs and shared-tenant noise stay isolated.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"
_TAG = "TEST_p41_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _mkcsv(rows, headers=None):
    """Build a CSV byte-string with the 12 P41 headers unless overridden."""
    hdr = headers or [
        "First Name", "Last Name", "Service Address", "Service City",
        "Service State", "Service Zip Code", "Billing Address",
        "Billing City", "Billing State", "Billing Zip Code",
        "Email", "Phone Number",
    ]
    buf = io.StringIO()
    buf.write(",".join(hdr) + "\n")
    for r in rows:
        buf.write(",".join(r) + "\n")
    return buf.getvalue().encode("utf-8")


def _upload(headers, csv_bytes, target_status="active", filename="x.csv"):
    files = {"file": (filename, csv_bytes, "text/csv")}
    data = {"target_status": target_status}
    return requests.post(
        f"{API}/customers/import-csv",
        headers=headers, files=files, data=data, timeout=30,
    )


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many({
            "tenant_id": aquaterra_tid,
            "$or": [
                {"email": {"$regex": f"^{_TAG.lower()}"}},
                {"phone": {"$regex": _TAG}},
                {"last_name": {"$regex": f"^{_TAG}"}},
            ],
        })
    _reset(); yield; _reset()


def _uniq_email():
    return f"{_TAG.lower()}{uuid.uuid4().hex[:8]}@example.com"


def _uniq_phone():
    d = uuid.uuid4().int
    return f"+1555{str(d)[:7]}"


# ── Happy path ──────────────────────────────────────────────────────
def test_valid_three_rows_lands_customers_active(admin_h, aquaterra_tid):
    csv = _mkcsv([
        [f"Alice", f"{_TAG}Aa", "1 Main St", "Phoenix", "AZ", "85001",
         "PO Box 1", "Phoenix", "AZ", "85001",
         _uniq_email(), _uniq_phone()],
        [f"Bob", f"{_TAG}Bb", "2 Main St", "Phoenix", "AZ", "85001",
         "", "", "", "",
         _uniq_email(), _uniq_phone()],
        [f"Carol", f"{_TAG}Cc", "3 Main St", "Phoenix", "AZ", "85001",
         "PO Box 3", "Phoenix", "AZ", "85001",
         _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 3
    assert body["updated"] == 0
    assert body["skipped_no_new_data"] == 0
    assert body["errored"] == 0
    # Landed with is_active=True.
    n_active = _sync.customers.count_documents({
        "tenant_id": aquaterra_tid,
        "last_name": {"$in": [f"{_TAG}Aa", f"{_TAG}Bb", f"{_TAG}Cc"]},
        "is_active": True,
    })
    assert n_active == 3


def test_target_status_inactive_lands_inactive(admin_h, aquaterra_tid):
    csv = _mkcsv([
        [f"Ivy", f"{_TAG}In", "9 Ivy", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "inactive")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    row = _sync.customers.find_one({
        "tenant_id": aquaterra_tid, "last_name": f"{_TAG}In"})
    assert row["is_active"] is False
    assert row["status"] == "inactive"


# ── Header normalization ────────────────────────────────────────────
def test_header_normalization_case_and_underscore(admin_h, aquaterra_tid):
    csv = _mkcsv(
        [[f"Xena", f"{_TAG}Xn", "1 Xenon Rd", "Phoenix", "AZ", "85001",
          "", "", "", "", _uniq_email(), _uniq_phone()]],
        headers=[
            "FIRST_NAME", "last name", "Service_Address", "SERVICE CITY",
            "Service_State", "service zip code", "Billing Address",
            "Billing_City", "billing state", "BILLING ZIP CODE",
            "email", "PHONE_NUMBER",
        ],
    )
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1


# ── Missing required per-row ────────────────────────────────────────
def test_missing_first_name_row_errors_others_succeed(admin_h, aquaterra_tid):
    csv = _mkcsv([
        ["Dave", f"{_TAG}Dd", "10 Elm", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
        ["", f"{_TAG}NoFirst", "11 Elm", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
        ["Eve", f"{_TAG}Ee", "12 Elm", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["errored"] == 1
    reasons = {e["row"]: e["reason"] for e in body["row_errors"]}
    # Row 3 (2nd data row, header is row 1).
    assert reasons.get(3) == "missing_required"


def test_missing_service_address_row_errors(admin_h, aquaterra_tid):
    csv = _mkcsv([
        ["Fay", f"{_TAG}Ff", "20 Oak", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
        ["Gil", f"{_TAG}NoAddr", "", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    body = r.json()
    assert r.status_code == 200
    assert body["created"] == 1
    assert body["errored"] == 1
    assert body["row_errors"][0]["row"] == 3
    assert body["row_errors"][0]["reason"] == "missing_required"


# ── Fill-in-blanks merge ─────────────────────────────────────────────
def test_merge_fills_blank_fields_but_preserves_populated(
        admin_h, aquaterra_tid):
    dup_email = _uniq_email()
    existing_id = f"{_TAG}pre-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        "name": "Jane Doe", "first_name": "Jane", "last_name": f"{_TAG}Doe",
        "email": dup_email,     # populated
        "phone": "",            # blank → eligible
        "service_city": "Phoenix",   # populated
        "service_state": "",         # blank → eligible
        "is_active": True,
    })
    fill_phone = _uniq_phone()
    csv = _mkcsv([
        ["J", f"{_TAG}Ignored", "999 New St", "Tempe", "AZ", "85281",
         "", "", "", "", dup_email, fill_phone],
    ])
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0
    assert body["updated"] == 1
    assert body["skipped_no_new_data"] == 0
    assert body["errored"] == 0
    row = _sync.customers.find_one({"id": existing_id})
    # Filled the blanks:
    assert row["phone"] == fill_phone
    assert row["service_state"] == "AZ"
    # Preserved the populated fields (spec: no overwrites):
    assert row["email"] == dup_email
    assert row["service_city"] == "Phoenix"
    assert row["first_name"] == "Jane"         # name not filled because
    assert row["last_name"] == f"{_TAG}Doe"   #   last_name was populated
    # And spec-critical: still marked as coming from a merge in audit.
    audit = _sync.audit_logs.find_one(
        {"tenant_id": aquaterra_tid, "event": "customer_csv_import"},
        sort=[("at", -1)])
    sample = audit["payload"]["merges_sample"]
    assert len(sample) == 1
    filled = set(sample[0]["fields_filled"])
    assert "phone" in filled and "service_state" in filled


def test_merge_fills_first_and_last_only_when_both_blank(
        admin_h, aquaterra_tid):
    dup_email = _uniq_email()
    existing_id = f"{_TAG}bo-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        # No name fields at all (import from a signup form that only
        # captured the email, common real-world case).
        "email": dup_email,
        "is_active": True,
    })
    csv = _mkcsv([
        ["Naomi", f"{_TAG}Nb", "1 Test", "Phoenix", "AZ", "85001",
         "", "", "", "", dup_email, _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    body = r.json()
    assert body["updated"] == 1 and body["created"] == 0
    row = _sync.customers.find_one({"id": existing_id})
    assert row["first_name"] == "Naomi"
    assert row["last_name"] == f"{_TAG}Nb"


def test_merge_does_not_overwrite_populated_field(admin_h, aquaterra_tid):
    dup_email = _uniq_email()
    existing_id = f"{_TAG}nop-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        "name": "Bo Boop", "first_name": "Bo", "last_name": f"{_TAG}Boop",
        "email": dup_email,
        "phone": "+15550001111",
        "service_address": "Existing Street",
        "service_city": "Phoenix", "service_state": "AZ",
        "service_zip": "85001",
        "billing_address": "Existing Billing",
        "billing_city": "Phoenix", "billing_state": "AZ",
        "billing_zip": "85001",
        "is_active": True,
    })
    csv = _mkcsv([
        ["Bo", f"{_TAG}Boop", "New Street", "Tempe", "CA", "90210",
         "New Bill", "Tempe", "CA", "90210",
         dup_email, "+19990002222"],
    ])
    r = _upload(admin_h, csv, "active")
    body = r.json()
    assert body["created"] == 0 and body["updated"] == 0
    assert body["skipped_no_new_data"] == 1
    row = _sync.customers.find_one({"id": existing_id})
    # Everything preserved.
    assert row["service_city"] == "Phoenix"
    assert row["service_state"] == "AZ"
    assert row["phone"] == "+15550001111"
    assert row["billing_address"] == "Existing Billing"


def test_ambiguous_duplicate_errors_row_and_writes_nothing(
        admin_h, aquaterra_tid):
    email_a = _uniq_email()
    phone_b = _uniq_phone()
    id_a = f"{_TAG}amba-{uuid.uuid4().hex[:6]}"
    id_b = f"{_TAG}ambb-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": id_a, "tenant_id": aquaterra_tid,
        "name": "A A", "first_name": "A", "last_name": f"{_TAG}Aambig",
        "email": email_a, "phone": "", "is_active": True,
    })
    _sync.customers.insert_one({
        "id": id_b, "tenant_id": aquaterra_tid,
        "name": "B B", "first_name": "B", "last_name": f"{_TAG}Bambig",
        "email": "", "phone": phone_b, "is_active": True,
    })
    csv = _mkcsv([
        ["Ambi", f"{_TAG}CsvA", "1 Cross St", "Phoenix", "AZ", "85001",
         "", "", "", "", email_a, phone_b],
    ])
    before_a = _sync.customers.find_one({"id": id_a})
    before_b = _sync.customers.find_one({"id": id_b})
    r = _upload(admin_h, csv, "active")
    body = r.json()
    assert body["created"] == 0 and body["updated"] == 0
    assert body["skipped_no_new_data"] == 0
    assert body["errored"] == 1
    err = body["row_errors"][0]
    assert err["reason"] == "ambiguous_duplicate"
    assert id_a in err["detail"] and id_b in err["detail"]
    # Untouched.
    assert _sync.customers.find_one({"id": id_a}) == before_a
    assert _sync.customers.find_one({"id": id_b}) == before_b


def test_merge_does_not_flip_is_active(admin_h, aquaterra_tid):
    dup_email = _uniq_email()
    existing_id = f"{_TAG}inact-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        "name": "Deb Doe", "first_name": "Deb", "last_name": f"{_TAG}Deb",
        "email": dup_email, "phone": "",
        "service_state": "",   # eligible
        "is_active": False, "status": "inactive",
    })
    csv = _mkcsv([
        ["Deb", f"{_TAG}Deb", "77 Deb St", "Phoenix", "AZ", "85001",
         "", "", "", "", dup_email, _uniq_phone()],
    ])
    # target_status=active — MUST NOT flip existing to active (spec).
    r = _upload(admin_h, csv, "active")
    assert r.json()["updated"] == 1
    row = _sync.customers.find_one({"id": existing_id})
    assert row["is_active"] is False
    assert row["service_state"] == "AZ"   # blank filled


# ── Cross-status match visibility (row-flag, not error) ─────────────
def test_matched_in_other_status_flag_active_target_hits_inactive(
        admin_h, aquaterra_tid):
    """Active-target import matches an inactive customer → merge fills
    blanks, is_active preserved, admin sees the row-flag."""
    dup_email = _uniq_email()
    existing_id = f"{_TAG}xs-inact-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        "name": "Xi X", "first_name": "Xi", "last_name": f"{_TAG}Xa",
        "email": dup_email, "phone": "",   # phone blank → eligible
        "is_active": False, "status": "inactive",
    })
    fill_phone = _uniq_phone()
    csv = _mkcsv([
        ["Xi", f"{_TAG}Xa", "1 Xi St", "Phoenix", "AZ", "85001",
         "", "", "", "", dup_email, fill_phone],
    ])
    r = _upload(admin_h, csv, "active")
    body = r.json()
    assert body["updated"] == 1
    # ``matched_in_other_status`` is NOT an error.
    assert body["errored"] == 0
    # Existing customer stays inactive, phone filled.
    row = _sync.customers.find_one({"id": existing_id})
    assert row["is_active"] is False
    assert row["phone"] == fill_phone
    # Row-flag visible to admin in row_errors.
    flags = [e for e in body["row_errors"]
                if e["reason"] == "matched_in_other_status"]
    assert len(flags) == 1
    assert flags[0]["row"] == 2
    # Direction-aware message.
    assert "Inactive" in flags[0]["detail"]
    assert "Active" in flags[0]["detail"]


def test_matched_in_other_status_flag_inactive_target_hits_active(
        admin_h, aquaterra_tid):
    """Symmetric: inactive-target import matches an active customer."""
    dup_email = _uniq_email()
    existing_id = f"{_TAG}xs-act-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": existing_id, "tenant_id": aquaterra_tid,
        "name": "Yo Y", "first_name": "Yo", "last_name": f"{_TAG}Yn",
        "email": dup_email, "phone": "",
        "is_active": True, "status": "active",
    })
    fill_phone = _uniq_phone()
    csv = _mkcsv([
        ["Yo", f"{_TAG}Yn", "1 Yo Rd", "Phoenix", "AZ", "85001",
         "", "", "", "", dup_email, fill_phone],
    ])
    r = _upload(admin_h, csv, "inactive")
    body = r.json()
    assert body["updated"] == 1
    assert body["errored"] == 0
    row = _sync.customers.find_one({"id": existing_id})
    assert row["is_active"] is True   # preserved
    assert row["phone"] == fill_phone
    flags = [e for e in body["row_errors"]
                if e["reason"] == "matched_in_other_status"]
    assert len(flags) == 1
    # Direction reversed vs the prior test.
    assert "Active" in flags[0]["detail"]
    assert "Inactive" in flags[0]["detail"]


def test_soft_deleted_customer_does_not_match(admin_h, aquaterra_tid):
    dup_email = _uniq_email()
    soft_id = f"{_TAG}sd-{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": soft_id, "tenant_id": aquaterra_tid,
        "name": "Old Ghost", "first_name": "Old",
        "last_name": f"{_TAG}Ghost",
        "email": dup_email,
        "deleted_at": "2026-01-01T00:00:00Z",   # soft-deleted
        "is_active": True,
    })
    csv = _mkcsv([
        ["Fresh", f"{_TAG}Fresh", "1 Fresh Rd", "Phoenix", "AZ", "85001",
         "", "", "", "", dup_email, _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    body = r.json()
    # Created NEW (didn't merge into the soft-deleted row).
    assert body["created"] == 1
    assert body["updated"] == 0
    # Soft-deleted row untouched.
    row = _sync.customers.find_one({"id": soft_id})
    assert row["deleted_at"] == "2026-01-01T00:00:00Z"
    # And a fresh row exists with the same email.
    n = _sync.customers.count_documents({
        "tenant_id": aquaterra_tid, "last_name": f"{_TAG}Fresh"})
    assert n == 1


# ── Billing fallback ────────────────────────────────────────────────
def test_empty_billing_falls_back_to_service(admin_h, aquaterra_tid):
    csv = _mkcsv([
        ["Hank", f"{_TAG}Hh", "50 Ash", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200, r.text
    row = _sync.customers.find_one({
        "tenant_id": aquaterra_tid, "last_name": f"{_TAG}Hh"})
    assert row["billing_address"] == "50 Ash"
    assert row["billing_city"] == "Phoenix"
    assert row["billing_state"] == "AZ"
    assert row["billing_zip"] == "85001"


# ── Header errors ───────────────────────────────────────────────────
def test_missing_header_returns_400_with_list(admin_h):
    # Drop First Name from the headers.
    csv = _mkcsv(
        [["skip", "skip", "skip", "skip", "skip", "skip",
          "", "", "", "", "", ""]],
        headers=[
            "Last Name", "Service Address", "Service City",
            "Service State", "Service Zip Code", "Billing Address",
            "Billing City", "Billing State", "Billing Zip Code",
            "Email", "Phone Number", "Extra",
        ],
    )
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # Detail is a dict with error + list.
    assert isinstance(detail, dict)
    assert detail["error"] == "missing_headers"
    assert "first_name" in detail["missing_headers"]


# ── Batch cap ───────────────────────────────────────────────────────
def test_over_5000_rows_returns_400_and_no_partial(admin_h, aquaterra_tid):
    # 5001 rows — build minimal valid rows so we prove the cap is
    # enforced BEFORE parsing/inserting each row.
    rows = [[f"F{i}", f"{_TAG}Big{i}", f"{i} Big Ave", "P", "AZ", "85001",
             "", "", "", "", "", ""] for i in range(5001)]
    csv = _mkcsv(rows)
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert isinstance(detail, dict) and detail["error"] == "too_many_rows"
    # Prove no partial import — none of the 5001 last_names landed.
    n = _sync.customers.count_documents({
        "tenant_id": aquaterra_tid,
        "last_name": {"$regex": f"^{_TAG}Big"},
    })
    assert n == 0


# ── RBAC ─────────────────────────────────────────────────────────────
def test_technician_gets_403(aquaterra_tid):
    tok = _login("carlos@aquaterra.com")
    csv = _mkcsv([
        ["Zed", f"{_TAG}Zz", "1 Zed", "Phoenix", "AZ", "85001",
         "", "", "", "", "", ""],
    ])
    r = _upload({"Authorization": f"Bearer {tok}"}, csv, "active")
    assert r.status_code == 403


# ── Audit log ────────────────────────────────────────────────────────
def test_audit_log_entry_written(admin_h, aquaterra_tid):
    csv = _mkcsv([
        ["Kay", f"{_TAG}Kk", "60 Birch", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "inactive")
    assert r.status_code == 200
    # The single most recent import-audit entry belongs to us.
    entry = _sync.audit_logs.find_one(
        {"tenant_id": aquaterra_tid, "event": "customer_csv_import"},
        sort=[("at", -1)])
    assert entry is not None
    assert entry["payload"]["target_status"] == "inactive"
    assert entry["payload"]["created"] >= 1
    assert entry["payload"]["total_rows"] >= 1


# ── Background geocoding queued ─────────────────────────────────────
def test_geocode_task_queued_for_created_rows(admin_h, aquaterra_tid):
    """The endpoint runs in a separate process, so we assert against
    the audit-log payload (observable from any process) instead of
    trying to spy on ``BackgroundTasks.add_task`` across processes."""
    csv = _mkcsv([
        ["Gia", f"{_TAG}Gg", "70 Poplar", "Phoenix", "AZ", "85001",
         "", "", "", "", _uniq_email(), _uniq_phone()],
    ])
    r = _upload(admin_h, csv, "active")
    assert r.status_code == 200
    audit = _sync.audit_logs.find_one(
        {"tenant_id": aquaterra_tid, "event": "customer_csv_import"},
        sort=[("at", -1)])
    assert audit is not None
    # 1 new customer created → 1 queued for geocoding. Merged rows
    # would NOT contribute to this count.
    assert audit["payload"]["geocode_queued"] == 1
    assert audit["payload"]["created"] == 1


# ── Unsupported file type ───────────────────────────────────────────
def test_empty_upload_returns_400(admin_h):
    r = _upload(admin_h, b"", "active")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # Either "empty_file" or "unsupported_file_type" — both are 400s.
    assert isinstance(detail, (str, dict))
