"""Phase 9 · Feb-2026 — Crew multi-member save end-to-end contract.

Root cause ownership
--------------------
The historical bug was a frontend stale-closure in
``OpsHub.jsx::Crews::save`` — the toggle handler closed over the
outer ``form`` reference and used ``setForm({ ...form, ... })``
instead of the functional updater, so clicking two member chips
rapidly collapsed ``tech_ids`` to just the latest click.  The
backend accepted whatever payload the FE sent and persisted it
correctly, including a single-element array.

Phase 9 ships:
  * FE fix (functional updater) — covered by the companion vitest
    ``frontend/src/test/crews-multi-member-save.test.jsx``.
  * BE defense in depth — PATCH /crews/{cid} now validates
    ``tech_ids`` as an array of non-empty tenant-resolved strings.
    Any non-array / stale cross-tenant payload now fails loudly
    with a 400 instead of silently landing a bad array.

This suite locks the BE round-trip + defensive validation.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid: str, email: str, tid: str, role: str) -> str:
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant() -> str:
    tid = f"p9-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one(
        {"id": tid, "name": "P9 crews smoke", "slug": tid, "active": True},
    )
    return tid


def _seed_user(tenant_id: str, role: str, name: str) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p9.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": name, "email": email,
    })
    return {
        "id": uid, "email": email, "name": name,
        "tenant_id": tenant_id, "role": role,
        "token": _tok(uid, email, tenant_id, role),
    }


@pytest.fixture
def tenant_id():
    tid = _seed_tenant()
    yield tid
    for col in ("tenants", "users", "technicians", "crews", "job_timers"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture
def admin(tenant_id):
    return _seed_user(tenant_id, "admin", "Admin P9")


@pytest.fixture
def manager(tenant_id):
    return _seed_user(tenant_id, "manager", "Manager P9")


@pytest.fixture
def tech(tenant_id):
    return _seed_user(tenant_id, "technician", "Tech P9")


@pytest.fixture
def three_members(tenant_id):
    return [
        _seed_user(tenant_id, "tech", "Miguel"),
        _seed_user(tenant_id, "tech", "Remington"),
        _seed_user(tenant_id, "tech", "Steven"),
    ]


# ── 1 ─ POST + GET round-trip with 3 members ──────────────────────
def test_create_crew_with_three_members_round_trips(admin, three_members):
    ids = [m["id"] for m in three_members]
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Alpha", "color": "#3B82F6", "tech_ids": ids},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["tech_ids"] == ids
    cid = created["id"]
    r = requests.get(f"{API}/crews", headers=_auth(admin["token"]), timeout=20)
    assert r.status_code == 200, r.text
    rows = {c["id"]: c for c in r.json()}
    assert cid in rows
    row = rows[cid]
    assert len(row.get("tech_ids") or []) == 3
    assert len(row.get("members") or []) == 3
    names = sorted(m["name"] for m in row["members"])
    assert names == ["Miguel", "Remington", "Steven"]


# ── 2 ─ Single-member crew is valid ───────────────────────────────
def test_create_crew_with_one_member(admin, three_members):
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Solo", "color": "#3B82F6",
              "tech_ids": [three_members[0]["id"]]},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tech_ids"] == [three_members[0]["id"]]


# ── 3 ─ Zero-member crew is valid (preserved behavior) ────────────
def test_create_crew_with_zero_members(admin):
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Empty", "color": "#3B82F6", "tech_ids": []},
        timeout=20,
    )
    # Phase 9 preserves pre-Phase-9 "empty array is allowed" semantics
    # — adding members later via PATCH / add_crew_member is the
    # expected flow for a brand-new crew.
    assert r.status_code == 200, r.text
    assert r.json()["tech_ids"] == []


# ── 4 ─ Grow from 2 → 5 overwrites correctly (no stale ids) ───────
def test_patch_grows_from_two_to_five_members(admin, three_members, tenant_id):
    # Seed two extras.
    extras = [
        _seed_user(tenant_id, "tech", "Dana"),
        _seed_user(tenant_id, "tech", "Olu"),
    ]
    two = [three_members[0]["id"], three_members[1]["id"]]
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Growers", "color": "#3B82F6", "tech_ids": two},
        timeout=20,
    )
    assert r.status_code == 200
    cid = r.json()["id"]
    five = two + [three_members[2]["id"], extras[0]["id"], extras[1]["id"]]
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(admin["token"]),
        json={"tech_ids": five}, timeout=20,
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["tech_ids"]) == sorted(five)
    # Verify the stored doc too.
    doc = _sync.crews.find_one({"id": cid}, {"_id": 0})
    assert sorted(doc["tech_ids"]) == sorted(five)


# ── 5 ─ Shrink from 5 → 2 drops the removed ids ───────────────────
def test_patch_shrinks_from_five_to_two_members(
    admin, three_members, tenant_id,
):
    extras = [
        _seed_user(tenant_id, "tech", "Dana"),
        _seed_user(tenant_id, "tech", "Olu"),
    ]
    five = [m["id"] for m in three_members] \
        + [extras[0]["id"], extras[1]["id"]]
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Shrinkers", "color": "#3B82F6", "tech_ids": five},
        timeout=20,
    )
    cid = r.json()["id"]
    kept = [three_members[0]["id"], three_members[1]["id"]]
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(admin["token"]),
        json={"tech_ids": kept}, timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tech_ids"] == kept
    doc = _sync.crews.find_one({"id": cid}, {"_id": 0})
    assert doc["tech_ids"] == kept
    # Dropped ids genuinely gone (not merged / shadow-persisted).
    for m in (three_members[2]["id"], extras[0]["id"], extras[1]["id"]):
        assert m not in doc["tech_ids"]


# ── 6 ─ Tenant isolation — foreign member id rejected (defense) ───
def test_patch_rejects_cross_tenant_member_id(admin, three_members, tenant_id):
    # Create a crew in tenant A.
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Iso", "color": "#3B82F6",
              "tech_ids": [three_members[0]["id"]]},
        timeout=20,
    )
    cid = r.json()["id"]
    # Mint a member in tenant B.
    tid_b = _seed_tenant()
    try:
        foreign = _seed_user(tid_b, "tech", "Foreigner")
        r = requests.patch(
            f"{API}/crews/{cid}", headers=_auth(admin["token"]),
            json={"tech_ids": [three_members[0]["id"], foreign["id"]]},
            timeout=20,
        )
        # Phase 9 BE defense should reject the cross-tenant id with 400.
        assert r.status_code == 400, r.text
        assert "tenant" in r.text.lower()
        # Original roster unchanged (atomic reject, no partial write).
        doc = _sync.crews.find_one({"id": cid}, {"_id": 0})
        assert doc["tech_ids"] == [three_members[0]["id"]]
    finally:
        for col in ("tenants", "users", "crews"):
            _sync[col].delete_many({"tenant_id": tid_b})


# ── 7 ─ Role gate: tech 403, admin 200 ──────────────────────────────
# Note: the backend ``require_admin`` dependency on PATCH /crews/{id}
# admits admin / super_admin / owner only — NOT manager.  Phase 9
# scope is explicitly bug-fix, not role-widening, so this test
# locks the EXISTING gate: tech + manager both 403, admin succeeds.
def test_role_gate_on_patch(admin, manager, tech, three_members):
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Gated", "color": "#3B82F6",
              "tech_ids": [three_members[0]["id"]]},
        timeout=20,
    )
    cid = r.json()["id"]
    body = {"tech_ids": [m["id"] for m in three_members]}

    # Tech cannot save a crew.
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(tech["token"]),
        json=body, timeout=20,
    )
    assert r.status_code == 403, r.text

    # Manager also 403 under the current ``require_admin`` policy
    # (Phase 9 does not widen the role surface — see /routers/ops.py
    # update_crew Depends(require_admin)).
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(manager["token"]),
        json=body, timeout=20,
    )
    assert r.status_code == 403, r.text

    # Admin always succeeds.
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(admin["token"]),
        json=body, timeout=20,
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["tech_ids"]) == sorted(body["tech_ids"])


# ── 7b ─ Defensive validation: non-array tech_ids → 400 ───────────
def test_patch_rejects_non_array_tech_ids(admin, three_members):
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Validator", "color": "#3B82F6",
              "tech_ids": [three_members[0]["id"]]},
        timeout=20,
    )
    cid = r.json()["id"]
    # Someone sends a bare string instead of an array — must be rejected.
    r = requests.patch(
        f"{API}/crews/{cid}", headers=_auth(admin["token"]),
        json={"tech_ids": three_members[0]["id"]}, timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "array" in r.text.lower()


# ── 8 ─ Phase 6 crew-timer attribution smoke ──────────────────────
#
# This phase MUST NOT regress the Phase 6 wiring that pipes
# ``crew_id`` through ``auto_start_timer_on_arrival``.  A crew with
# any number of members (incl. a trio) should still be addressable
# as the ``crew_id`` on an arrival event.  The GET endpoint remains
# the single canonical fetch so a downstream consumer looking up
# ``crew_id`` → members gets the full roster.
def test_phase6_crew_timer_attribution_still_works(admin, three_members):
    ids = [m["id"] for m in three_members]
    r = requests.post(
        f"{API}/crews", headers=_auth(admin["token"]),
        json={"name": "Phase6-smoke", "color": "#3B82F6", "tech_ids": ids},
        timeout=20,
    )
    assert r.status_code == 200
    cid = r.json()["id"]
    # Fetch via list GET — this is the same path Phase 6's
    # ``auto_start_timer_on_arrival`` and the schedule board use.
    r = requests.get(f"{API}/crews", headers=_auth(admin["token"]), timeout=20)
    rows = {c["id"]: c for c in r.json()}
    assert cid in rows
    assert len(rows[cid].get("tech_ids") or []) == 3
    assert len(rows[cid].get("members") or []) == 3
