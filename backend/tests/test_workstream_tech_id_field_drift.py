"""Feb-2026 · P1 hotfix — Workstream tech-id field-name drift.

Real-tenant completed jobs stamp the assignee under any of four field
names (``technician_id`` / ``assigned_to`` / ``assigned_technician_id`` /
``tech_user_id``) depending on which write path last touched the row.
The Workstream aggregator historically only read ``technician_id`` and
silently rendered "Assigned to Unassigned" on every other shape.

This suite locks in the read-path union fix:

* Seeds five completed jobs on the ``aquaterra`` tenant, each with the
  tech identity stamped under exactly one field shape, plus a control
  where ``technician_id`` carries the ``users.id`` shape (cascade
  rung 3) instead of the ``technicians.id`` shape (cascade rung 1).
* Hits ``GET /api/workstream/jobs`` as admin and asserts every seeded
  job resolves a non-empty ``technician_name`` matching the tech's
  real name — proving both the four-field union AND the two-shape
  cascade.
* Unit-checks the role-allowlist extension (``tech`` / ``owner`` added
  in ``services/service_report_view.py``).

Cleanup: every seeded doc uses the ``TEST_TidDrift_`` title prefix
(jobs) or an ``@example.com`` email (users), both of which the session
teardown hook in ``conftest.py`` sweeps automatically. The module-scoped
autouse fixture also self-cleans on setup + teardown for isolation.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

_TITLE_PREFIX = "TEST_TidDrift_"
# Sits inside the ``test_m1_since_until_filters`` future window so
# non-test jobs never leak into our assertions.
_FUTURE_DATE = "2099-06-15"
_SINCE_MARKER = "2099-01-01"

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
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


async def _get_tenant_id(slug: str = "aquaterra") -> str:
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _get_mike_identity(tenant_id: str) -> dict:
    """Return the three id shapes + display name for Mike, the pool tech.

    Keys: ``user_id`` (``users.id``), ``tech_doc_id`` (``technicians.id``),
    ``name`` (best-effort display name).
    """
    mike = await _db().users.find_one(
        {"email": "mike@aquaterra.com", "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "technician_id": 1,
         "name": 1, "first_name": 1, "last_name": 1},
    )
    assert mike, "mike@aquaterra.com is a required seed for this test"
    uid = mike["id"]
    tid_hint = mike.get("technician_id")
    tdoc = await _db().technicians.find_one(
        {"tenant_id": tenant_id,
         "$or": [{"user_id": uid}] + ([{"id": tid_hint}] if tid_hint else [])},
        {"_id": 0, "id": 1, "user_id": 1, "name": 1},
    ) or {}
    name = (mike.get("name")
            or f"{mike.get('first_name', '')} {mike.get('last_name', '')}".strip()
            or tdoc.get("name"))
    return {
        "user_id": uid,
        "tech_doc_id": tdoc.get("id"),
        "name": name,
    }


async def _cleanup_seeds() -> None:
    await _db().jobs.delete_many({"title": {"$regex": f"^{_TITLE_PREFIX}"}})


async def _insert_seeds(tenant_id: str, ident: dict) -> None:
    """Insert five completed jobs, one per assignee-field shape.

    Each doc leaves ``technician_name = ""`` on purpose so the assertion
    proves the resolver actually ran (rather than the last-ditch cache
    falling through and masking a still-broken read path).
    """
    uid = ident["user_id"]
    tdoc_id = ident["tech_doc_id"] or uid  # fall back to uid if no tech doc

    seeds = [
        # (label, extra fields written on the seed job)
        ("technician_id_userIdShape",    {"technician_id": uid}),
        ("technician_id_techDocShape",   {"technician_id": tdoc_id}),
        ("assigned_to_only",             {"assigned_to": uid}),
        ("assigned_technician_id_only",  {"assigned_technician_id": tdoc_id}),
        ("tech_user_id_only",            {"tech_user_id": uid}),
    ]
    docs = []
    for label, fields in seeds:
        docs.append({
            "id": f"TEST-tid-drift-{label}-{uuid.uuid4().hex[:6]}",
            "tenant_id": tenant_id,
            "title": f"{_TITLE_PREFIX}{label}",
            "status": "completed",
            "scheduled_date": _FUTURE_DATE,
            "created_at": "2099-06-01T00:00:00+00:00",
            "updated_at": "2099-06-01T00:00:00+00:00",
            # Empty denorm cache — resolver MUST populate the name.
            "technician_name": "",
            **fields,
        })
    await _db().jobs.insert_many(docs)


@pytest.fixture(scope="module", autouse=True)
def seed_ctx():
    tenant_id = _run(_get_tenant_id())
    ident = _run(_get_mike_identity(tenant_id))
    _run(_cleanup_seeds())        # scrub leftovers from a prior run
    _run(_insert_seeds(tenant_id, ident))
    yield {"tenant_id": tenant_id, "ident": ident}
    _run(_cleanup_seeds())


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════
def test_all_four_field_shapes_resolve_to_tech_name(admin_headers, seed_ctx):
    """The core assertion: every seeded job must render a non-empty
    ``technician_name`` matching Mike's real name, regardless of which
    of the four assignee fields carries the identity."""
    expected = seed_ctx["ident"]["name"]
    assert expected, "cannot assert — Mike has no resolvable display name"

    r = requests.get(
        f"{API}/workstream/jobs?limit=200&since={_SINCE_MARKER}",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    jobs = r.json()["jobs"]
    seeded = [j for j in jobs
              if (j.get("title") or "").startswith(_TITLE_PREFIX)]
    assert len(seeded) == 5, (
        f"expected 5 seeded jobs in the 2099+ window, got {len(seeded)}: "
        f"{[j.get('title') for j in seeded]}"
    )

    unresolved = [j for j in seeded
                  if not (j.get("technician_name") or "").strip()]
    assert not unresolved, (
        "these seeded jobs rendered as 'Unassigned' — tech-id field-name "
        f"drift is not being unioned: {[j.get('title') for j in unresolved]}"
    )

    mismatched = [j for j in seeded
                  if j.get("technician_name") != expected]
    assert not mismatched, (
        "resolved a non-empty name but it doesn't match the seeded tech: "
        f"{[(j.get('title'), j.get('technician_name')) for j in mismatched]}"
    )


def test_response_technician_id_uses_effective_field(admin_headers, seed_ctx):
    """The response payload should surface the effective tech id on the
    canonical ``technician_id`` key even when the source doc stamped a
    different field — so downstream ``tech_id=`` filters keep working
    against the emitted rows."""
    uid = seed_ctx["ident"]["user_id"]
    tdoc_id = seed_ctx["ident"]["tech_doc_id"] or uid

    r = requests.get(
        f"{API}/workstream/jobs?limit=200&since={_SINCE_MARKER}",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200
    seeded = {
        (j.get("title") or ""): j.get("technician_id")
        for j in r.json()["jobs"]
        if (j.get("title") or "").startswith(_TITLE_PREFIX)
    }

    # Each drifted shape should surface the value the writer stamped:
    expectations = (
        ("assigned_to_only",             uid),
        ("assigned_technician_id_only",  tdoc_id),
        ("tech_user_id_only",            uid),
    )
    for label_suffix, expect in expectations:
        title = f"{_TITLE_PREFIX}{label_suffix}"
        assert seeded.get(title) == expect, (
            f"{title}: expected effective_tid={expect!r}, "
            f"got {seeded.get(title)!r}"
        )


def test_resolve_technician_names_accepts_role_tech_and_owner():
    """Regression: the cascade's users-collection allowlist must
    include ``tech`` (legacy singular shorthand) and ``owner`` roles,
    or callers holding an id pointing at such a user get an empty
    resolution and the caller falls back to 'Unassigned'."""
    from services.service_report_view import resolve_technician_names

    async def _go():
        tenant_id = await _get_tenant_id()
        uid_tech = f"TEST-user-role-tech-{uuid.uuid4().hex[:8]}"
        uid_owner = f"TEST-user-role-owner-{uuid.uuid4().hex[:8]}"
        await _db().users.insert_many([
            {"id": uid_tech, "tenant_id": tenant_id,
             "email": f"tech-{uid_tech}@example.com",
             "name": "TEST Tech Role", "role": "tech"},
            {"id": uid_owner, "tenant_id": tenant_id,
             "email": f"owner-{uid_owner}@example.com",
             "name": "TEST Owner Role", "role": "owner"},
        ])
        try:
            names = await resolve_technician_names(
                _db(), tenant_id, [uid_tech, uid_owner],
            )
            assert names.get(uid_tech) == "TEST Tech Role", (
                "resolve_technician_names dropped a role=tech user")
            assert names.get(uid_owner) == "TEST Owner Role", (
                "resolve_technician_names dropped a role=owner user")
        finally:
            await _db().users.delete_many(
                {"id": {"$in": [uid_tech, uid_owner]}})

    _run(_go())
