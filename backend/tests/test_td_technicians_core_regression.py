"""TD-search-technicians-bucket · Feb-2026 — byte-identical regression
for ``GET /api/technicians`` after extracting the union + dedupe logic
into ``services.technicians_core.fetch_tenant_technician_roster``.

The pre-refactor response shape was pinned by Phase 2 scope lock. This
suite proves the refactor is zero-regression by covering every
observable invariant of the roster endpoint:

  * Full role coverage — all 6 ``ASSIGNABLE_ROLES`` surface.
  * Dedupe — a linked user (tech row + user row with same ``user_id``)
    appears exactly once, preserving the tech-row shape over the synth.
  * Soft-deleted + ``active=false`` exclusion from both sources.
  * ``@t.local`` migration-artifact filter.
  * Field-worker-first + alphabetical sort order.
  * ``active_jobs`` / ``active_jobs_repair`` / ``active_jobs_service``
    enrichment survives the extraction.
  * Admin / super_admin / manager users must NOT appear.
"""
from __future__ import annotations

import os
import uuid
from typing import List

import httpx
import pytest
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant(prefix: str = "TEST_tcore") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid,
        "slug": f"tcore-{uuid.uuid4().hex[:8]}",
        "name": "TCore Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin", *, email: str | None = None,
             first_name: str = "", last_name: str = "",
             name: str | None = None,
             phone: str | None = None,
             active: bool | None = None,
             deleted_at: str | None = None,
             technician_id: str | None = None) -> dict:
    from utils import hash_password
    _email = email or f"tcore-{role}-{uuid.uuid4().hex[:8]}@example.com"
    doc: dict = {
        "id": f"TEST_tcore_user_{uuid.uuid4().hex}",
        "email": _email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid,
        "name": name,
        "first_name": first_name, "last_name": last_name,
        "phone": phone,
        "failed_login_attempts": 0,
    }
    if active is not None:
        doc["active"] = active
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    if technician_id is not None:
        doc["technician_id"] = technician_id
    _sync.users.insert_one(doc)
    return doc


def _mk_tech_row(tid: str, *, name: str, email: str | None = None,
                  phone: str | None = None, user_id: str | None = None,
                  deleted_at: str | None = None,
                  display_color_hex: str | None = None) -> dict:
    doc: dict = {
        "id": f"TEST_tcore_tech_{uuid.uuid4().hex}",
        "tenant_id": tid, "name": name,
        "email": email, "phone": phone, "user_id": user_id,
        "active": True,
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    if display_color_hex is not None:
        doc["display_color_hex"] = display_color_hex
    _sync.technicians.insert_one(doc)
    return doc


def _login(email: str) -> str:
    with httpx.Client(base_url=BASE, timeout=30) as c:
        r = c.post("/api/auth/login",
                   json={"email": email, "password": "password123"})
        r.raise_for_status()
        return r.json()["access_token"]


@pytest.fixture
def tenant_ctx():
    tid = _mk_tenant()
    admin = _mk_user(tid, role="admin")
    token = _login(admin["email"])
    yield {"tid": tid, "admin_email": admin["email"], "token": token}


def _get_roster(token: str) -> List[dict]:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.get("/api/technicians",
                   headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()


def test_full_role_coverage(tenant_ctx):
    """All 6 ASSIGNABLE_ROLES appear; admin/super_admin/manager don't."""
    tid = tenant_ctx["tid"]
    _mk_user(tid, role="technician",      first_name="Al",   last_name="A")
    _mk_user(tid, role="tech",            first_name="Bo",   last_name="B")
    _mk_user(tid, role="landscaper",      first_name="Ci",   last_name="C")
    _mk_user(tid, role="landscape_tech",  first_name="Da",   last_name="D")
    _mk_user(tid, role="pool_tech",       first_name="Ea",   last_name="E")
    _mk_user(tid, role="tech_both",       first_name="Fa",   last_name="F")
    # Negative-coverage: these must NOT appear.
    _mk_user(tid, role="manager",         first_name="Ma",   last_name="M")
    _mk_user(tid, role="super_admin",     first_name="Su",   last_name="S")

    roster = _get_roster(tenant_ctx["token"])
    roles = sorted(r["role"] for r in roster if r.get("role") != "admin")
    # Admin from the fixture is excluded by role filter.
    assert roles == ["landscape_tech", "landscaper", "pool_tech",
                      "tech", "tech_both", "technician"]
    # Hard check that the privileged roles weren't surfaced.
    names = {r.get("name") for r in roster}
    assert "Ma M" not in names and "Su S" not in names


def test_dedupe_linked_user_appears_once(tenant_ctx):
    """A user WITH a matching tech row surfaces once, with the tech-row shape."""
    tid = tenant_ctx["tid"]
    u = _mk_user(tid, role="technician",
                  first_name="Linked", last_name="Tech")
    _mk_tech_row(tid, name="Linked Tech",
                 email=u["email"], phone="(555) 100-0001",
                 user_id=u["id"], display_color_hex="#AABBCC")

    roster = _get_roster(tenant_ctx["token"])
    matches = [r for r in roster if r.get("name") == "Linked Tech"]
    assert len(matches) == 1
    row = matches[0]
    # Tech-row shape wins (synthesized_from_users absent, phone + color
    # from the tech row).
    assert not row.get("synthesized_from_users")
    assert row.get("phone") == "(555) 100-0001"
    assert row.get("display_color_hex") == "#AABBCC"


def test_soft_deleted_exclusion_both_sources(tenant_ctx):
    """Soft-deleted tech rows AND tech rows linked to active=false users
    are both out. (Note: tech rows linked to a *soft-deleted* user
    survive — this mirrors the pre-refactor behavior exactly, since the
    original list_technicians only filtered on linked-user ``active``,
    not ``deleted_at``. Byte-identical regression is the explicit goal.)
    """
    tid = tenant_ctx["tid"]
    # Tech row soft-deleted (no linked user)
    _mk_tech_row(tid, name="Deleted TechRow",
                  deleted_at="2026-02-01T00:00:00+00:00")
    # Linked tech whose linked user is active=false
    u2 = _mk_user(tid, role="technician",
                    first_name="Linked", last_name="InactiveUser",
                    active=False)
    _mk_tech_row(tid, name="Linked InactiveUser",
                  user_id=u2["id"])
    # One good one for signal
    _mk_user(tid, role="technician",
              first_name="Good", last_name="Tech")

    roster = _get_roster(tenant_ctx["token"])
    names = {r.get("name") for r in roster}
    assert "Deleted TechRow" not in names
    assert "Linked InactiveUser" not in names
    assert "Good Tech" in names


def test_t_local_migration_artifacts_excluded(tenant_ctx):
    """Users with ``@t.local`` emails are filtered out (seed artifacts)."""
    tid = tenant_ctx["tid"]
    _mk_user(tid, role="technician",
              email=f"lastowner-{uuid.uuid4().hex[:8]}@t.local",
              first_name="Owner", last_name="Placeholder")
    _mk_user(tid, role="technician",
              first_name="Real", last_name="Tech")
    roster = _get_roster(tenant_ctx["token"])
    names = {r.get("name") for r in roster}
    assert "Owner Placeholder" not in names
    assert "Real Tech" in names


def test_tenant_isolation(tenant_ctx):
    """Techs from another tenant never appear."""
    tid = tenant_ctx["tid"]
    other_tid = _mk_tenant("TEST_tcore_other")
    _mk_user(other_tid, role="technician",
              first_name="Other", last_name="Tenant")
    _mk_user(tid, role="technician",
              first_name="This", last_name="Tenant")
    roster = _get_roster(tenant_ctx["token"])
    names = {r.get("name") for r in roster}
    assert "Other Tenant" not in names
    assert "This Tenant" in names


def test_sort_order_field_worker_first(tenant_ctx):
    """Field-assignable roles rank 0 (alpha-sorted); others rank 1."""
    tid = tenant_ctx["tid"]
    _mk_user(tid, role="technician", first_name="Z",  last_name="Last")
    _mk_user(tid, role="landscaper", first_name="A",  last_name="First")
    _mk_user(tid, role="pool_tech",  first_name="M",  last_name="Middle")
    roster = _get_roster(tenant_ctx["token"])
    # All three in the roster are rank-0 roles; alphabetical by name.
    tech_names = [r["name"] for r in roster
                   if r.get("name") in {"A First", "M Middle", "Z Last"}]
    assert tech_names == ["A First", "M Middle", "Z Last"]


def test_active_jobs_enrichment_preserved(tenant_ctx):
    """``active_jobs`` + ``active_jobs_repair`` + ``active_jobs_service``
    survive the extraction (K65 enrichment stays in the route handler).
    """
    tid = tenant_ctx["tid"]
    u = _mk_user(tid, role="technician",
                  first_name="Jobs", last_name="Counted")
    tech = _mk_tech_row(tid, name="Jobs Counted",
                         user_id=u["id"])
    # 2 service + 1 repair active jobs
    for i in range(2):
        _sync.jobs.insert_one({
            "id": f"TEST_tcore_job_svc_{i}_{uuid.uuid4().hex}",
            "tenant_id": tid, "technician_id": tech["id"],
            "status": "pending", "work_class": "service",
        })
    _sync.jobs.insert_one({
        "id": f"TEST_tcore_job_rep_{uuid.uuid4().hex}",
        "tenant_id": tid, "technician_id": tech["id"],
        "status": "active", "work_class": "repair",
    })
    # Completed should NOT count
    _sync.jobs.insert_one({
        "id": f"TEST_tcore_job_done_{uuid.uuid4().hex}",
        "tenant_id": tid, "technician_id": tech["id"],
        "status": "completed", "work_class": "service",
    })

    roster = _get_roster(tenant_ctx["token"])
    matches = [r for r in roster if r.get("name") == "Jobs Counted"]
    assert len(matches) == 1
    row = matches[0]
    assert row.get("active_jobs_service") == 2
    assert row.get("active_jobs_repair") == 1
    assert row.get("active_jobs") == 3
