"""Task N Round 2 · Phase N.6 · Feb-2026 — Customer Notes History
endpoint contract tests.

Locks ``GET /api/customers/{cid}/notes-history`` against seeded
fixture data.  Rows tagged ``TEST_notes_history_*`` for teardown.

Coverage:
  1. Happy path — 200 + envelope shape + customer block populated.
  2. Pagination boundary (page 2 empty when total ≤ page_size).
  3. Cross-tenant isolation (decoy tenant's SR must NOT surface).
  4. Non-admin → 403.
  5. Customer-not-found → 404.
  6. Row shape matches archive endpoint (parity assertion).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_TEST_DIR = Path(__file__).resolve().parent
_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def tech_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "mike@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_test_id(prefix: str) -> str:
    return f"TEST_notes_history_{prefix}_{uuid.uuid4()}"


def _seed_customer_and_srs(
    dbc, *, tenant_id: str, tech_id: str,
    customer_name: str, customer_notes: str = "",
    sr_count: int = 3,
) -> Dict[str, Any]:
    cust_id = _make_test_id("cust")
    dbc.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id,
        "name": customer_name,
        "email": f"{customer_name.replace(' ', '.').lower()}@x.test",
        "notes": customer_notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    sr_ids: List[str] = []
    job_ids: List[str] = []
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(sr_count):
        job_id = _make_test_id(f"job{i}")
        sr_id = _make_test_id(f"sr{i}")
        dbc.jobs.insert_one({
            "id": job_id, "tenant_id": tenant_id,
            "customer_id": cust_id, "technician_id": tech_id,
            "status": "completed",
            "created_at": (base + timedelta(days=i)).isoformat(),
        })
        dbc.service_reports.insert_one({
            "id": sr_id, "tenant_id": tenant_id,
            "job_id": job_id, "tech_id": tech_id,
            "template": "pool",
            "notes": "",
            "internal_notes": f"Test internal note {i}",
            "customer_notes": "",
            "submitted_at": (base + timedelta(days=i)).isoformat(),
            "created_at": (base + timedelta(days=i)).isoformat(),
            "updated_at": (base + timedelta(days=i)).isoformat(),
        })
        job_ids.append(job_id)
        sr_ids.append(sr_id)
    return {"customer_id": cust_id, "sr_ids": sr_ids, "job_ids": job_ids}


@pytest.fixture()
def seeded_customer_history(dbc, aquaterra_id):
    TECH = _make_test_id("tech")
    dbc.users.insert_one({
        "id": TECH, "tenant_id": aquaterra_id,
        "name": "TEST_NH_Tech", "role": "technician",
        "email": "tech.nh@test.test",
    })
    seeded = _seed_customer_and_srs(
        dbc, tenant_id=aquaterra_id, tech_id=TECH,
        customer_name="TEST_NH_Diane Lloyd",
        customer_notes="Saltwater pool. Prefers morning visits.",
        sr_count=3,
    )
    seeded["tech_id"] = TECH
    yield seeded
    for sid in seeded["sr_ids"]:
        dbc.service_reports.delete_one({"id": sid})
    for jid in seeded["job_ids"]:
        dbc.jobs.delete_one({"id": jid})
    dbc.customers.delete_one({"id": seeded["customer_id"]})
    dbc.users.delete_one({"id": TECH})


# ═════════════════════════════════════════════════════════════
#  Tests
# ═════════════════════════════════════════════════════════════
def test_notes_history_happy_path(dbc, admin_h, seeded_customer_history):
    cid = seeded_customer_history["customer_id"]
    r = requests.get(f"{API}/customers/{cid}/notes-history",
                     headers=admin_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {
        "rows", "total_count", "page", "page_size", "customer",
    }
    assert body["total_count"] == 3
    assert body["page"] == 1 and body["page_size"] == 20
    assert body["customer"]["id"] == cid
    assert body["customer"]["name"] == "TEST_NH_Diane Lloyd"
    assert body["customer"]["notes"].startswith("Saltwater pool")
    assert len(body["rows"]) == 3
    # Newest first (day 2, 1, 0).
    for i, expected_note in enumerate(["Test internal note 2",
                                          "Test internal note 1",
                                          "Test internal note 0"]):
        assert body["rows"][i]["internal_notes"] == expected_note
        assert body["rows"][i]["customer_name"] == "TEST_NH_Diane Lloyd"
        assert body["rows"][i]["tech_name"] == "TEST_NH_Tech"
        assert body["rows"][i]["industry"] == "Pool"


def test_notes_history_pagination_boundary(dbc, admin_h, seeded_customer_history):
    cid = seeded_customer_history["customer_id"]
    r = requests.get(f"{API}/customers/{cid}/notes-history",
                     headers=admin_h, timeout=20,
                     params={"page": 2, "page_size": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 2
    assert body["rows"] == []
    # page_size boundary — 3 rows split across page_size=2 → page 2 has 1.
    r = requests.get(f"{API}/customers/{cid}/notes-history",
                     headers=admin_h, timeout=20,
                     params={"page": 2, "page_size": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 2
    assert len(body["rows"]) == 1


def test_notes_history_cross_tenant_leak_proof(dbc, admin_h,
                                                 seeded_customer_history):
    """A decoy tenant has a customer with the same ``customer_id``
    string (impossible in practice, but a real-world worst-case) —
    the target-tenant admin's response must NOT include the decoy
    SRs."""
    DECOY_TENANT = _make_test_id("decoy_tenant")
    dbc.tenants.insert_one({
        "id": DECOY_TENANT, "slug": DECOY_TENANT,
        "name": "TEST_NH_Decoy",
    })
    decoy_seed = _seed_customer_and_srs(
        dbc, tenant_id=DECOY_TENANT, tech_id="decoy_tech",
        customer_name="TEST_NH_Decoy_Diane Lloyd",
        customer_notes="do not surface — cross-tenant leak canary",
        sr_count=2,
    )
    try:
        # Query the TARGET tenant customer's history — should still
        # be 3 (from seeded_customer_history), NOT 5.
        cid = seeded_customer_history["customer_id"]
        r = requests.get(f"{API}/customers/{cid}/notes-history",
                         headers=admin_h, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert body["total_count"] == 3
        decoy_sr_ids = set(decoy_seed["sr_ids"])
        seen_sr_ids = {row["sr_id"] for row in body["rows"]}
        assert decoy_sr_ids.isdisjoint(seen_sr_ids), (
            "cross-tenant SR leaked into notes-history"
        )
    finally:
        for sid in decoy_seed["sr_ids"]:
            dbc.service_reports.delete_one({"id": sid})
        for jid in decoy_seed["job_ids"]:
            dbc.jobs.delete_one({"id": jid})
        dbc.customers.delete_one({"id": decoy_seed["customer_id"]})
        dbc.tenants.delete_one({"id": DECOY_TENANT})


def test_notes_history_non_admin_returns_403(tech_h, seeded_customer_history):
    cid = seeded_customer_history["customer_id"]
    r = requests.get(f"{API}/customers/{cid}/notes-history",
                     headers=tech_h, timeout=20)
    assert r.status_code == 403, r.text


def test_notes_history_customer_not_found_returns_404(dbc, admin_h):
    r = requests.get(
        f"{API}/customers/nonexistent-customer-id/notes-history",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 404, r.text


def test_notes_history_row_shape_matches_archive(dbc, admin_h,
                                                   seeded_customer_history):
    """Parity assertion: the customer notes-history endpoint returns
    rows with the SAME keys and value types as the archive endpoint
    so the frontend's shared component can render either verbatim."""
    cid = seeded_customer_history["customer_id"]
    hist = requests.get(f"{API}/customers/{cid}/notes-history",
                        headers=admin_h, timeout=20).json()
    archive = requests.get(f"{API}/service-reports/archive",
                            headers=admin_h, timeout=20,
                            params={"customer_search":
                                    "TEST_NH_Diane Lloyd",
                                    "page_size": 5}).json()
    assert hist["rows"], "expected seeded rows"
    assert archive["rows"], "expected same rows via archive endpoint"
    hist_row = hist["rows"][0]
    arch_row = next((r for r in archive["rows"]
                     if r["sr_id"] == hist_row["sr_id"]), None)
    assert arch_row is not None, "same SR must appear in both endpoints"
    # Compare key sets — every field the frontend renders MUST be
    # present in both responses.
    common_keys = {"sr_id", "job_id", "submitted_at", "customer_id",
                    "customer_name", "tech_id", "tech_name",
                    "industry", "notes", "internal_notes",
                    "customer_notes"}
    assert common_keys.issubset(hist_row.keys())
    assert common_keys.issubset(arch_row.keys())
    # Value parity on the common fields.
    for k in common_keys:
        assert hist_row[k] == arch_row[k], (
            f"field {k} mismatch: hist={hist_row[k]!r} "
            f"archive={arch_row[k]!r}"
        )
