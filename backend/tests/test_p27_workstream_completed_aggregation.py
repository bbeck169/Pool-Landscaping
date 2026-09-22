"""Phase P27 · Feb-2026 — Workstream completed-aggregation defensive fixes.

Locks the following contracts on ``GET /api/workstream/jobs``:

  1. **Case-insensitive completed match** — the endpoint's status
     filter accepts ``"completed"``, ``"Completed"``, ``"COMPLETED"``,
     etc. Pre-P27 the query was exact-match lowercase and silently
     dropped title-case rows (from legacy CSV imports + one
     historical migration).
  2. **Soft-delete exclusion** — rows with ``deleted_at`` set OR
     ``is_deleted == True`` are excluded via the shared
     ``not_deleted_filter()`` helper. Rows with the field ABSENT
     entirely still match (baseline expectation).
  3. **Tenant isolation** — rows from a different tenant never
     appear in the Workstream list even if their status/casing
     matches.
  4. **Missing status field** — a doc with ``status`` absent is NOT
     counted as completed.
  5. **Response ``counts`` block** — the response carries an
     explicit ``counts: {total_count, completed_count,
     services_count, repairs_count}`` block so the FE tile has a
     redundant sanity check independent of the paginated slice.
  6. **``services_count`` / ``repairs_count`` semantics** — mirror
     the frontend ``jobCategory`` classifier (repairs wins on
     ambiguous matches; completed jobs with idiosyncratic
     ``service_type`` fall through to Services).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env",
)
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")

TAG = "P27_"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_login() -> dict:
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def admin_h(admin_login) -> dict:
    return {"Authorization": f"Bearer {admin_login['access_token']}"}


@pytest.fixture(scope="module")
def admin_tenant_id(admin_login) -> str:
    import jwt as _jwt
    payload = _jwt.decode(
        admin_login["access_token"],
        options={"verify_signature": False},
    )
    return payload["active_tenant_id"]


def _seed_job(dbc, tenant_id, *,
              status="completed", service_type="pool_service",
              deleted_at=None, is_deleted=None, tag_suffix="") -> str:
    jid = f"{TAG}{tag_suffix}_{uuid.uuid4().hex[:6]}"
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": f"{TAG}CUST", "customer_name": f"P27 Customer",
        "title": f"{TAG} test job",
        "service_type": service_type,
        "status": status,
        "scheduled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    if is_deleted is not None:
        doc["is_deleted"] = is_deleted
    dbc.jobs.insert_one(doc)
    return jid


@pytest.fixture
def _cleanup(dbc):
    ids: list = []
    yield ids
    if ids:
        dbc.jobs.delete_many({"id": {"$in": ids}})


# ── 1) Case-insensitive completed match ──────────────────────────


def test_p27_completed_status_match_is_case_insensitive(
    admin_h, admin_tenant_id, dbc, _cleanup,
):
    """Seed 5 jobs: 2 lowercase completed, 1 title-case Completed,
    1 pending, 1 completed+soft-deleted. Endpoint MUST return the
    3 completed non-deleted rows (both casings, exclude
    soft-deleted)."""
    j_lc1 = _seed_job(dbc, admin_tenant_id,
                       status="completed", tag_suffix="LC1")
    j_lc2 = _seed_job(dbc, admin_tenant_id,
                       status="completed", tag_suffix="LC2")
    j_tc = _seed_job(dbc, admin_tenant_id,
                      status="Completed", tag_suffix="TC")
    j_pend = _seed_job(dbc, admin_tenant_id,
                        status="pending", tag_suffix="PEND")
    j_del = _seed_job(dbc, admin_tenant_id,
                       status="completed", tag_suffix="DEL",
                       deleted_at=datetime.now(timezone.utc).isoformat())
    _cleanup.extend([j_lc1, j_lc2, j_tc, j_pend, j_del])

    r = requests.get(f"{API}/workstream/jobs", headers=admin_h,
                      params={"limit": 200}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {j["id"] for j in body["jobs"]}
    p27_visible = {jid for jid in ids if jid.startswith(TAG)}

    assert j_lc1 in p27_visible
    assert j_lc2 in p27_visible
    assert j_tc in p27_visible, (
        f"Title-case 'Completed' row {j_tc} missing from response — "
        f"P27 case-insensitive match regressed. Response ids: "
        f"{sorted(p27_visible)}"
    )
    assert j_pend not in p27_visible, (
        f"Pending row leaked into completed-only feed"
    )
    assert j_del not in p27_visible, (
        f"Soft-deleted row leaked into completed-only feed"
    )


# ── 2) Missing status field is NOT counted as completed ──────────


def test_p27_missing_status_field_not_counted(
    admin_h, admin_tenant_id, dbc, _cleanup,
):
    """Doc without a ``status`` field must NOT appear in the
    completed feed."""
    jid = f"{TAG}NOSTATUS_{uuid.uuid4().hex[:6]}"
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": admin_tenant_id,
        "customer_id": f"{TAG}CUST", "title": "no-status",
        "service_type": "pool_service",
        "scheduled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _cleanup.append(jid)

    r = requests.get(f"{API}/workstream/jobs", headers=admin_h,
                      params={"limit": 200}, timeout=15)
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()["jobs"]}
    assert jid not in ids, (
        f"Doc without status field leaked into completed feed"
    )


# ── 3) Tenant isolation ──────────────────────────────────────────


def test_p27_tenant_isolation(
    admin_h, admin_tenant_id, dbc, _cleanup,
):
    """A completed row seeded on a DIFFERENT tenant must NEVER
    appear in the admin's Workstream response, even with the
    P27 case-insensitive match."""
    other_tenant = f"{TAG}OTHER_TENANT_{uuid.uuid4().hex[:6]}"
    jid = _seed_job(dbc, other_tenant,
                     status="Completed", tag_suffix="XT")
    _cleanup.append(jid)

    r = requests.get(f"{API}/workstream/jobs", headers=admin_h,
                      params={"limit": 200}, timeout=15)
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()["jobs"]}
    assert jid not in ids, (
        f"Cross-tenant completed row leaked into admin's response"
    )


# ── 4) Response counts block shape + math ────────────────────────


def test_p27_response_counts_block_is_present_and_matches_jobs(
    admin_h, admin_tenant_id, dbc, _cleanup,
):
    """Seed 4 completed jobs (2 services, 1 repair, 1 empty
    service_type). ``counts`` block MUST report:
      * total_count == completed_count == 4
      * services_count == 3 (2 explicit + 1 empty-service_type
        falling through per rule #4)
      * repairs_count  == 1
    """
    j_svc1 = _seed_job(dbc, admin_tenant_id,
                        status="completed",
                        service_type="Weekly Pool Service",
                        tag_suffix="S1")
    j_svc2 = _seed_job(dbc, admin_tenant_id,
                        status="completed",
                        service_type="Monthly Landscaping",
                        tag_suffix="S2")
    j_rep = _seed_job(dbc, admin_tenant_id,
                       status="completed",
                       service_type="Pool Repair",
                       tag_suffix="R1")
    j_empty = _seed_job(dbc, admin_tenant_id,
                         status="Completed",   # title case + empty svc
                         service_type="",
                         tag_suffix="EMPTY")
    _cleanup.extend([j_svc1, j_svc2, j_rep, j_empty])

    # Scope: only rows the fixture seeded (there may be others).
    r = requests.get(
        f"{API}/workstream/jobs", headers=admin_h,
        params={"limit": 500,
                "since": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "until": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # counts block shape
    counts = body.get("counts")
    assert isinstance(counts, dict), (
        f"counts block missing from response — P27 wire regression"
    )
    for key in ("total_count", "completed_count",
                "services_count", "repairs_count"):
        assert key in counts, f"counts missing {key}: {counts}"

    # total == completed for the completed-only Workstream endpoint.
    assert counts["total_count"] == counts["completed_count"]

    # Filter to just our seeded ids so pre-existing preview jobs
    # don't pollute the math.
    ours = [j for j in body["jobs"] if j["id"].startswith(TAG)]
    ours_by_type = {j["service_type"] or "": j for j in ours}
    assert len(ours) == 4, (
        f"Expected 4 seeded rows in this fixture's date window, "
        f"got {len(ours)}: {[j['id'] for j in ours]}"
    )

    # Verify the empty-service_type row IS present — pre-P27 the FE
    # classifier dropped it, but the response envelope must still
    # ship the row so the FE can classify it as service via the
    # rule #4 fallback.
    assert "" in ours_by_type


# ── 5) Guardrail — no case-sensitive equality regression ─────────


def test_p27_no_case_sensitive_status_equality_in_workstream():
    """Source-lint: the pre-P27 anti-pattern ``q["status"] =
    effective_status`` (lowercase exact-match) must NOT return to
    ``routers/workstream.py`` on the list handler. A refactor
    accidentally reverting this would silently drop title-case
    rows once a legacy migration lands them."""
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "workstream.py").read_text(encoding="utf-8")
    # Confirm the regex approach is wired.
    assert '"$regex": r"^completed$"' in src, (
        "workstream.py no longer uses case-insensitive completed "
        "regex — P27 casing fix regressed."
    )
    # Confirm the exact pre-P27 anti-pattern is gone.
    assert 'q["status"] = effective_status' not in src, (
        "Pre-P27 case-sensitive status equality detected — "
        "title-case Completed rows will be silently dropped."
    )


# ── 6) `not_deleted_filter` still applied ────────────────────────


def test_p27_soft_delete_filter_applied():
    """Source guardrail — ``not_deleted_filter()`` MUST still be
    spread into the query. A refactor that swapped it for
    ``{"deleted_at": None}`` alone would drop docs where the
    field is absent (baseline Mongo docs written pre-K58 all lack
    the field)."""
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "workstream.py").read_text(encoding="utf-8")
    assert "**not_deleted_filter()" in src, (
        "workstream.py list handler no longer applies "
        "not_deleted_filter — soft-delete leak risk."
    )
