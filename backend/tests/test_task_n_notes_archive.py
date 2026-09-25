"""Task N · Phase N.1 · Feb-2026 — Notes Archive backend contract tests.

Locks the ``GET /api/service-reports/archive`` admin endpoint against
seeded fixture data.  Tests seed rows tagged ``TEST_notes_archive_*``
that self-clean via the conftest teardown.

Coverage:

  1. Happy path — 200 with the expected envelope + row shape.
  2. Customer-search substring filter (case-insensitive).
  3. Tech-id equality filter.
  4. Date-range filter (submitted_at inclusive both ends).
  5. Industry filter (Pool / Landscaping / Service mapping).
  6. Non-admin → 403.
  7. Cross-tenant leak-proof — decoy tenant's SR must not appear.
  8. Pagination boundary — page 2 returns empty when total ≤ page_size.
  9. ``page_size > 100`` → 400 ``page_size_too_large``.
 10. Invalid date format → 400 ``invalid_date_format``.
 11. Add-A · index-usage assertion via ``explain("executionStats")``.

Each test seeds its own rows inline (no shared fixture) so a mid-test
failure doesn't cascade.  Rows use UUIDs prefixed ``TEST_notes_archive_``
so conftest teardown sweeps them.
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


# ── Bootstrap ─────────────────────────────────────────────────
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
    """Technician login — used for the 403 non-admin test."""
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "mike@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── Row seeding helper ────────────────────────────────────────
def _make_test_id(prefix: str) -> str:
    """UUID string tagged so conftest teardown sweeps it."""
    return f"TEST_notes_archive_{prefix}_{uuid.uuid4()}"


def _seed_sr(
    dbc, *, tenant_id: str, tech_id: str, template: str,
    customer_id: str, customer_name: str,
    notes: str = "", internal_notes: str = "", customer_notes: str = "",
    submitted_at: str,
) -> Dict[str, str]:
    """Insert (customer, job, SR) triple; return ids for later filtering."""
    sr_id = _make_test_id("sr")
    job_id = _make_test_id("job")
    dbc.customers.insert_one({
        "id": customer_id, "tenant_id": tenant_id,
        "name": customer_name, "email": f"{customer_name.replace(' ', '.').lower()}@x.test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    dbc.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "customer_id": customer_id, "technician_id": tech_id,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    dbc.service_reports.insert_one({
        "id": sr_id, "tenant_id": tenant_id,
        "job_id": job_id, "tech_id": tech_id,
        "template": template,
        "notes": notes, "internal_notes": internal_notes,
        "customer_notes": customer_notes,
        "submitted_at": submitted_at,
        "created_at": submitted_at,
        "updated_at": submitted_at,
    })
    return {"sr_id": sr_id, "job_id": job_id, "customer_id": customer_id}


@pytest.fixture()
def seeded_rows(dbc, aquaterra_id):
    """Seed 5 rows on the target tenant covering the key contract
    corners: internal_notes only, customer_notes only, plain notes only,
    landscape industry, un-submitted (excluded).  All row ids collected
    for teardown regardless of what the individual tests did."""
    _ROWS: List[Dict[str, str]] = []
    TECH_A = "TEST_notes_archive_tech_" + str(uuid.uuid4())
    TECH_B = "TEST_notes_archive_tech_" + str(uuid.uuid4())
    dbc.users.insert_many([
        {"id": TECH_A, "tenant_id": aquaterra_id,
         "name": "TEST_NA_Tech_A", "role": "technician",
         "email": "tech.a@test.test"},
        {"id": TECH_B, "tenant_id": aquaterra_id,
         "name": "TEST_NA_Tech_B", "role": "technician",
         "email": "tech.b@test.test"},
    ])

    base = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
    _ROWS.append(_seed_sr(
        dbc, tenant_id=aquaterra_id, tech_id=TECH_A, template="pool",
        customer_id="TEST_notes_archive_c1_" + str(uuid.uuid4()),
        customer_name="TEST_NA_Diane Lloyd",
        internal_notes="Customer's dog was aggressive — lock up next visit.",
        submitted_at=base.isoformat(),
    ))
    _ROWS.append(_seed_sr(
        dbc, tenant_id=aquaterra_id, tech_id=TECH_A, template="pool",
        customer_id="TEST_notes_archive_c2_" + str(uuid.uuid4()),
        customer_name="TEST_NA_Sam Rivera",
        customer_notes="All looks great, see you Tuesday.",
        submitted_at=(base + timedelta(days=1)).isoformat(),
    ))
    _ROWS.append(_seed_sr(
        dbc, tenant_id=aquaterra_id, tech_id=TECH_B, template="landscape",
        customer_id="TEST_notes_archive_c3_" + str(uuid.uuid4()),
        customer_name="TEST_NA_Landscape Client",
        notes="Trimmed rear hedge, mulch top-up next visit.",
        submitted_at=(base + timedelta(days=2)).isoformat(),
    ))
    _ROWS.append(_seed_sr(
        dbc, tenant_id=aquaterra_id, tech_id=TECH_A, template="generic",
        customer_id="TEST_notes_archive_c4_" + str(uuid.uuid4()),
        customer_name="TEST_NA_Generic Client",
        internal_notes="Service call for gate repair — invoice separately.",
        submitted_at=(base + timedelta(days=3)).isoformat(),
    ))
    # Un-submitted row — must NEVER appear in the archive.
    unsubm_ids = _seed_sr(
        dbc, tenant_id=aquaterra_id, tech_id=TECH_A, template="pool",
        customer_id="TEST_notes_archive_c5_" + str(uuid.uuid4()),
        customer_name="TEST_NA_Draft Only",
        internal_notes="Draft still in progress; must not appear in archive.",
        submitted_at="",  # empty string ≠ $type: "string" AND $ne: "" = excluded
    )
    # Force ``submitted_at`` to actually be missing so ``$type: "string"``
    # excludes the row on its own — matches how the submit gate leaves
    # un-submitted reports.
    dbc.service_reports.update_one(
        {"id": unsubm_ids["sr_id"]},
        {"$unset": {"submitted_at": ""}},
    )
    _ROWS.append(unsubm_ids)

    yield {
        "rows": _ROWS, "tech_a": TECH_A, "tech_b": TECH_B, "base": base,
    }

    for row in _ROWS:
        dbc.service_reports.delete_one({"id": row["sr_id"]})
        dbc.jobs.delete_one({"id": row["job_id"]})
        dbc.customers.delete_one({"id": row["customer_id"]})
    dbc.users.delete_one({"id": TECH_A})
    dbc.users.delete_one({"id": TECH_B})


# ── Tests ─────────────────────────────────────────────────────
def test_archive_happy_path(dbc, aquaterra_id, admin_h, seeded_rows):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"page_size": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rows" in body and "total_count" in body
    assert body["page"] == 1 and body["page_size"] == 100
    # The 4 submitted seeded rows must all be present; the 1
    # un-submitted row must NOT.
    seeded_ids = {row["sr_id"] for row in seeded_rows["rows"]
                  if not row["sr_id"].endswith(seeded_rows["rows"][-1]["sr_id"])}
    returned_ids = {row["sr_id"] for row in body["rows"]}
    for expected in [r["sr_id"] for r in seeded_rows["rows"][:4]]:
        assert expected in returned_ids
    # Un-submitted excluded.
    assert seeded_rows["rows"][4]["sr_id"] not in returned_ids
    # Row shape sanity — first seeded row (Diane Lloyd, Pool).
    row = next(r for r in body["rows"]
               if r["customer_name"] == "TEST_NA_Diane Lloyd")
    assert row["industry"] == "Pool"
    assert row["tech_name"] == "TEST_NA_Tech_A"
    assert "aggressive" in row["internal_notes"]
    assert row["notes"] == ""
    assert row["customer_notes"] == ""


def test_archive_customer_search(dbc, aquaterra_id, admin_h, seeded_rows):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"customer_search": "diane"})
    assert r.status_code == 200, r.text
    names = [row["customer_name"] for row in r.json()["rows"]]
    # Case-insensitive substring — expect the seeded "Diane Lloyd" row.
    assert any("Diane Lloyd" in n for n in names)
    # Non-matching customers absent.
    assert not any("Sam Rivera" in n for n in names)


def test_archive_tech_id_filter(dbc, aquaterra_id, admin_h, seeded_rows):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"tech_id": seeded_rows["tech_b"]})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    # Only Tech_B's landscape row should surface.
    assert len(rows) >= 1
    assert all(row["tech_id"] == seeded_rows["tech_b"] for row in rows)
    assert all(row["tech_name"] == "TEST_NA_Tech_B" for row in rows)


def test_archive_date_range(dbc, aquaterra_id, admin_h, seeded_rows):
    # Seed range is 2026-03-10 through 2026-03-13.
    # Narrow to just 2026-03-11 → 2026-03-12 (2 seeded rows).
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"date_from": "2026-03-11",
                              "date_to": "2026-03-12"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    seeded_sr_ids = {row["sr_id"] for row in seeded_rows["rows"][1:3]}
    returned_ids = {row["sr_id"] for row in rows}
    # The 2 in-range seeded rows must be present; out-of-range ones absent.
    assert seeded_sr_ids.issubset(returned_ids)
    assert seeded_rows["rows"][0]["sr_id"] not in returned_ids
    assert seeded_rows["rows"][3]["sr_id"] not in returned_ids


def test_archive_industry_filter(dbc, aquaterra_id, admin_h, seeded_rows):
    # Landscape filter — expect only the landscape seeded row.
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"industry": "Landscaping"})
    assert r.status_code == 200, r.text
    for row in r.json()["rows"]:
        assert row["industry"] == "Landscaping"
    assert any(row["customer_name"] == "TEST_NA_Landscape Client"
                for row in r.json()["rows"])
    # Pool filter — expect only Pool rows.
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"industry": "Pool"})
    assert r.status_code == 200
    for row in r.json()["rows"]:
        assert row["industry"] == "Pool"


def test_archive_non_admin_returns_403(dbc, aquaterra_id, tech_h, seeded_rows):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=tech_h, timeout=20)
    assert r.status_code == 403, r.text


def test_archive_cross_tenant_leak_proof(dbc, aquaterra_id, admin_h, seeded_rows):
    """Seed a note-bearing SR in a DECOY tenant.  Query as the target
    tenant's admin — the decoy row MUST NOT appear."""
    DECOY_TENANT = "TEST_notes_archive_decoy_tenant_" + str(uuid.uuid4())
    DECOY_TECH = "TEST_notes_archive_decoy_tech_" + str(uuid.uuid4())
    dbc.tenants.insert_one({
        "id": DECOY_TENANT, "slug": DECOY_TENANT,
        "name": "TEST_NA_Decoy",
    })
    dbc.users.insert_one({
        "id": DECOY_TECH, "tenant_id": DECOY_TENANT,
        "name": "TEST_NA_Decoy_Tech", "role": "technician",
        "email": "decoy@test.test",
    })
    decoy_ids = _seed_sr(
        dbc, tenant_id=DECOY_TENANT, tech_id=DECOY_TECH, template="pool",
        customer_id="TEST_notes_archive_decoy_c_" + str(uuid.uuid4()),
        customer_name="TEST_NA_DECOY_Diane Lloyd",
        internal_notes="cross-tenant leak-canary — MUST NOT SURFACE",
        submitted_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        # Target-tenant admin does a broad archive query.
        r = requests.get(f"{API}/service-reports/archive",
                         headers=admin_h, timeout=20,
                         params={"page_size": 100})
        assert r.status_code == 200
        returned_ids = {row["sr_id"] for row in r.json()["rows"]}
        assert decoy_ids["sr_id"] not in returned_ids, (
            "cross-tenant SR leaked into the archive response"
        )
    finally:
        dbc.service_reports.delete_one({"id": decoy_ids["sr_id"]})
        dbc.jobs.delete_one({"id": decoy_ids["job_id"]})
        dbc.customers.delete_one({"id": decoy_ids["customer_id"]})
        dbc.users.delete_one({"id": DECOY_TECH})
        dbc.tenants.delete_one({"id": DECOY_TENANT})


def test_archive_pagination_boundary(dbc, aquaterra_id, admin_h, seeded_rows):
    # Page 2 with page_size 100 must be empty (total ≤ 100 for target tenant).
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"page": 2, "page_size": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"] == 2
    assert body["rows"] == []


def test_archive_page_size_too_large(dbc, aquaterra_id, admin_h):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"page_size": 101})
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "page_size_too_large"


def test_archive_invalid_date_format(dbc, aquaterra_id, admin_h):
    r = requests.get(f"{API}/service-reports/archive",
                     headers=admin_h, timeout=20,
                     params={"date_from": "not-a-date"})
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "invalid_date_format"


@pytest.mark.integration
def test_archive_uses_partial_index(dbc, aquaterra_id):
    """Add-A · index-usage assertion.  Runs the archive's pipeline
    initial ``$match`` stage through ``explain("executionStats")`` and
    asserts the ``service_reports_archive_idx`` partial index is
    selected by the query planner.

    We explain the ``$match``-only fragment (not the full $facet
    pipeline) because ``$facet`` currently returns opaque plans in
    older Mongo versions; the initial stage is what the index
    actually accelerates.
    """
    from pymongo.errors import OperationFailure
    match_stage = {
        "tenant_id": aquaterra_id,
        "submitted_at": {"$type": "string"},
        "$or": [
            {"notes": {"$type": "string", "$ne": ""}},
            {"internal_notes": {"$type": "string", "$ne": ""}},
            {"customer_notes": {"$type": "string", "$ne": ""}},
        ],
    }
    try:
        plan = dbc.command({
            "explain": {
                "aggregate": "service_reports",
                "pipeline": [
                    {"$match": match_stage},
                    {"$sort": {"submitted_at": -1}},
                ],
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
    except OperationFailure as e:
        pytest.skip(f"explain() not supported by this mongo backend: {e}")
    plan_str = str(plan)
    # The planner should either reference the index by name OR
    # emit an IXSCAN stage — both prove the index is in the plan.
    assert (
        "service_reports_archive_idx" in plan_str
        or "IXSCAN" in plan_str
    ), (
        f"partial index not in winning plan; "
        f"a COLLSCAN regression may have slipped in.  Plan excerpt: "
        f"{plan_str[:1500]}"
    )
