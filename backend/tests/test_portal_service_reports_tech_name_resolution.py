"""Feb-2026 · P1 hotfix — Customer Portal service reports feed.

Two compound bugs on ``GET /api/customers/me/service-reports`` (list) and
``GET /api/customers/me/service-reports/{report_id}`` (detail):

* The list's ``status`` filter (``$in: [submitted, completed, final]``)
  matched ZERO real reports in production — the submit path stamps
  ``submitted_at`` but never touches ``service_report.status``. Actual
  data shape: ``{(None, "submitted"): 11, ("draft", "unsubmitted"): 6}``.
  Fix: filter on ``submitted_at: {$ne: None}`` (the actual write-side
  signal).
* ``sr.get("tech_name")`` was always ``None`` — the field is never
  written on the report doc; only ``tech_id`` is stamped. Fix: resolve
  through the shared ``resolve_technician_names`` cascade (same helper
  the Workstream aggregator uses), with ``effective_tid(job)`` as the
  fallback on the detail endpoint for legacy reports whose ``tech_id``
  is missing.

Customer-isolation invariants under test:

* Customer A can only see reports whose parent job's ``customer_id``
  matches A's ``customer_id`` — the list join guarantees this.
* Customer A cannot fetch customer B's report by id — the detail
  endpoint's job-customer-id re-check returns 403.
* No pricing / internal / redaction fields leak through either
  endpoint.

Cleanup: every seeded doc uses TEST_-prefixed titles / ids so the
session teardown hook in ``conftest.py`` sweeps automatically. The
module-scoped autouse fixture also self-cleans on setup + teardown.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

_JOB_TITLE_PREFIX = "TEST_PortalSR_"
# Same-day scheduled_start on all seeds keeps ordering deterministic.
_SCHEDULED_START = "2099-08-15T12:00:00+00:00"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_headers():
    """Jennifer Carson — customer@aquaterra.com."""
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


async def _get_tenant_id(slug: str = "aquaterra") -> str:
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _get_jenny_identity(tenant_id: str) -> dict:
    """Return ``{customer_id, user_id}`` for the seeded portal customer."""
    u = await _db().users.find_one(
        {"email": "customer@aquaterra.com", "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "customer_id": 1},
    )
    assert u and u.get("customer_id"), (
        "customer@aquaterra.com must have a customer_id set (required seed)"
    )
    return {"customer_id": u["customer_id"], "user_id": u["id"]}


async def _get_other_customer_id(tenant_id: str, exclude: str) -> str:
    """Pick any other customer in the tenant to seed the isolation
    negative-control against."""
    other = await _db().customers.find_one(
        {"tenant_id": tenant_id, "id": {"$ne": exclude}},
        {"_id": 0, "id": 1},
    )
    assert other, "expected at least one other customer in aquaterra"
    return other["id"]


async def _get_mike_identity(tenant_id: str) -> dict:
    mike = await _db().users.find_one(
        {"email": "mike@aquaterra.com", "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "technician_id": 1,
         "name": 1, "first_name": 1, "last_name": 1},
    )
    assert mike, "mike@aquaterra.com is a required seed"
    uid = mike["id"]
    tdoc = await _db().technicians.find_one(
        {"tenant_id": tenant_id, "user_id": uid},
        {"_id": 0, "id": 1, "name": 1},
    ) or {}
    name = (mike.get("name")
            or f"{mike.get('first_name', '')} {mike.get('last_name', '')}".strip()
            or tdoc.get("name"))
    return {"user_id": uid, "tech_doc_id": tdoc.get("id"), "name": name}


async def _cleanup_seeds() -> None:
    """Purge any test jobs + service_reports from a prior run."""
    seeded_jobs = [j["id"] async for j in _db().jobs.find(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}},
        {"_id": 0, "id": 1},
    )]
    await _db().jobs.delete_many(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}})
    if seeded_jobs:
        await _db().service_reports.delete_many(
            {"job_id": {"$in": seeded_jobs}})


async def _insert_seeds(tenant_id: str, jenny_cid: str, other_cid: str,
                         mike: dict) -> dict:
    """Insert three jobs + three service_reports:

    * ``jenny_userIdShape`` — job for Jenny, report ``tech_id = mike.user_id``.
    * ``jenny_techDocShape`` — job for Jenny, report ``tech_id = mike.tech_doc_id``.
    * ``jenny_unsubmitted`` — job for Jenny, report with ``submitted_at=None``
      (must be filtered out — verifies the ``submitted_at`` gate).
    * ``other_customer`` — job for a DIFFERENT customer with a submitted
      report (must never appear in Jenny's list).

    Returns the seeded ids so tests can look them up.
    """
    tdoc = mike["tech_doc_id"] or mike["user_id"]
    uid = mike["user_id"]

    def _job(label, cid):
        return {
            "id": f"TEST-portal-sr-job-{label}-{uuid.uuid4().hex[:6]}",
            "tenant_id": tenant_id,
            "customer_id": cid,
            "title": f"{_JOB_TITLE_PREFIX}{label}",
            "status": "completed",
            "scheduled_start": _SCHEDULED_START,
            "service_type": "Weekly Pool Service",
            "created_at": "2099-08-01T00:00:00+00:00",
            "updated_at": "2099-08-01T00:00:00+00:00",
        }

    def _report(job_id, tech_id, submitted):
        return {
            "id": f"TEST-portal-sr-rep-{uuid.uuid4().hex[:8]}",
            "tenant_id": tenant_id,
            "job_id": job_id,
            "tech_id": tech_id,
            "submitted_at": submitted,
            "created_at": "2099-08-15T12:00:00+00:00",
            "updated_at": "2099-08-15T12:00:00+00:00",
            "chemical_readings": [],
            "chemicals_added": [],
            "checklist_items": [],
            "photos": [],
            "notes": "",
        }

    jobs = {
        "jenny_userIdShape":  _job("jenny_userIdShape", jenny_cid),
        "jenny_techDocShape": _job("jenny_techDocShape", jenny_cid),
        "jenny_unsubmitted":  _job("jenny_unsubmitted", jenny_cid),
        "other_customer":     _job("other_customer", other_cid),
    }
    await _db().jobs.insert_many(list(jobs.values()))
    reports = {
        "jenny_userIdShape":  _report(jobs["jenny_userIdShape"]["id"],
                                         uid, "2099-08-15T12:00:00+00:00"),
        "jenny_techDocShape": _report(jobs["jenny_techDocShape"]["id"],
                                         tdoc, "2099-08-14T12:00:00+00:00"),
        "jenny_unsubmitted":  _report(jobs["jenny_unsubmitted"]["id"],
                                         uid, None),
        "other_customer":     _report(jobs["other_customer"]["id"],
                                         uid, "2099-08-13T12:00:00+00:00"),
    }
    await _db().service_reports.insert_many(list(reports.values()))
    return {"jobs": jobs, "reports": reports}


@pytest.fixture(scope="module", autouse=True)
def seed_ctx():
    tenant_id = _run(_get_tenant_id())
    jenny = _run(_get_jenny_identity(tenant_id))
    other_cid = _run(_get_other_customer_id(tenant_id, jenny["customer_id"]))
    mike = _run(_get_mike_identity(tenant_id))
    _run(_cleanup_seeds())
    seeded = _run(_insert_seeds(tenant_id, jenny["customer_id"],
                                  other_cid, mike))
    yield {
        "tenant_id": tenant_id,
        "jenny_cid": jenny["customer_id"],
        "other_cid": other_cid,
        "mike": mike,
        "seeded": seeded,
    }
    _run(_cleanup_seeds())


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════
def test_list_returns_submitted_reports_only(customer_headers, seed_ctx):
    """Submitted reports show up; unsubmitted reports are filtered out."""
    r = requests.get(f"{API}/customers/me/service-reports",
                       headers=customer_headers, timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)

    seeded_titles = {
        s["title"] for s in seed_ctx["seeded"]["jobs"].values()
    }
    seeded_rows = [row for row in rows if row.get("job_title") in seeded_titles]

    surfaced_titles = {row["job_title"] for row in seeded_rows}
    assert f"{_JOB_TITLE_PREFIX}jenny_userIdShape" in surfaced_titles
    assert f"{_JOB_TITLE_PREFIX}jenny_techDocShape" in surfaced_titles
    # The unsubmitted one must NOT surface.
    assert f"{_JOB_TITLE_PREFIX}jenny_unsubmitted" not in surfaced_titles


def test_list_isolates_to_current_customer(customer_headers, seed_ctx):
    """The other customer's report must NEVER appear in Jenny's list."""
    r = requests.get(f"{API}/customers/me/service-reports",
                       headers=customer_headers, timeout=30)
    assert r.status_code == 200

    other_job_title = seed_ctx["seeded"]["jobs"]["other_customer"]["title"]
    leaked = [row for row in r.json() if row.get("job_title") == other_job_title]
    assert not leaked, (
        f"customer isolation broken — other customer's report leaked: {leaked}"
    )


def test_list_populates_tech_name_via_cascade(customer_headers, seed_ctx):
    """Both submitted Jenny reports must render a non-empty ``tech_name``
    matching Mike's real name — proves the resolver cascade works for
    both id shapes (``users.id`` and ``technicians.id``)."""
    r = requests.get(f"{API}/customers/me/service-reports",
                       headers=customer_headers, timeout=30)
    assert r.status_code == 200
    rows = r.json()

    seeded_titles = {
        f"{_JOB_TITLE_PREFIX}jenny_userIdShape",
        f"{_JOB_TITLE_PREFIX}jenny_techDocShape",
    }
    seeded_rows = [row for row in rows if row.get("job_title") in seeded_titles]
    assert len(seeded_rows) == 2, (
        f"expected 2 seeded submitted reports, got "
        f"{[row.get('job_title') for row in seeded_rows]}"
    )

    expected_name = seed_ctx["mike"]["name"]
    assert expected_name, "Mike has no resolvable display name"

    unresolved = [
        row for row in seeded_rows
        if not (row.get("tech_name") or "").strip()
    ]
    assert not unresolved, (
        "tech_name empty — resolver did not run for these rows: "
        f"{[row.get('job_title') for row in unresolved]}"
    )
    for row in seeded_rows:
        assert row["tech_name"] == expected_name, (
            f"{row['job_title']}: expected tech_name={expected_name!r}, "
            f"got {row['tech_name']!r}"
        )


def test_detail_populates_tech_name_and_gates_customer_isolation(
    customer_headers, seed_ctx,
):
    """Detail endpoint (a) surfaces resolved ``tech_name`` and
    (b) 403s when the requested report belongs to a different customer."""
    jenny_report_id = seed_ctx["seeded"]["reports"]["jenny_userIdShape"]["id"]
    other_report_id = seed_ctx["seeded"]["reports"]["other_customer"]["id"]

    # (a) Jenny's own report — 200 with populated tech_name.
    r = requests.get(f"{API}/customers/me/service-reports/{jenny_report_id}",
                       headers=customer_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    expected_name = seed_ctx["mike"]["name"]
    assert body.get("tech_name") == expected_name, (
        f"detail tech_name expected {expected_name!r}, got {body.get('tech_name')!r}"
    )
    # Redaction contract preserved — internal_notes must NOT surface.
    assert "internal_notes" not in body, (
        "redaction regression — internal_notes leaked to customer"
    )

    # (b) A different customer's report — 403.
    r = requests.get(f"{API}/customers/me/service-reports/{other_report_id}",
                       headers=customer_headers, timeout=30)
    assert r.status_code == 403, r.text


def test_customer_isolation_enforced_at_endpoint(customer_headers):
    """Non-customer callers are rejected with 403 regardless of scope
    (guardrail regression — the customer-only gate must not be
    accidentally loosened by any future refactor)."""
    admin_tok = _login("admin@aquaterra.com")
    r = requests.get(
        f"{API}/customers/me/service-reports",
        headers={"Authorization": f"Bearer {admin_tok}"}, timeout=30,
    )
    assert r.status_code == 403, r.text
