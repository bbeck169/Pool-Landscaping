"""FLEET-A · Fleet-membership CRUD tests.

Covers:
  * POST /api/fleet/membership/{tech_id} — enable + disable, first
    time creates a row, subsequent calls update it.
  * Audit log emitted for each transition (enable / disable).
  * GET /api/fleet/membership — server-joined roster where techs
    with no membership row default to ``in_fleet=False``.
  * Cross-tenant isolation — enabling a tech in t2 does NOT show up
    when a t1 admin lists membership.
  * RBAC — technician forbidden, admin allowed, super_admin allowed.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

from backend.tests._fleet_helpers import _DB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    fake.users.rows = [
        {"id": "u1", "tenant_id": "t1", "email": "a@t1", "name": "Alice",
         "role": "technician"},
        {"id": "u2", "tenant_id": "t1", "email": "b@t1", "name": "Bob",
         "role": "technician"},
        {"id": "u3", "tenant_id": "t2", "email": "c@t2", "name": "Carol",
         "role": "technician"},
        # Admin — must NOT surface on membership roster.
        {"id": "adm1", "tenant_id": "t1", "email": "admin@t1",
         "name": "Admin", "role": "admin"},
    ]
    for mod_name in ["routers.fleet"]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    return fake


def _admin(uid="adm1"):
    return {"id": uid, "role": "admin", "email": "admin@t1"}


def _super(uid="super1"):
    return {"id": uid, "role": "super_admin", "email": "s@t1"}


def _body(in_fleet, notes=None):
    from routers.fleet import MembershipBody
    return MembershipBody(in_fleet=in_fleet, notes=notes)


# ─── RBAC ───────────────────────────────────────────────────────────

def test_set_membership_forbidden_for_technician(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.set_membership(
            tech_user_id="u1", body=_body(True),
            user={"id": "u1", "role": "technician", "email": "t@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403


def test_list_membership_forbidden_for_technician(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.list_membership(
            user={"id": "u1", "role": "technician", "email": "t@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403


def test_set_membership_ok_for_super_admin(fake_db):
    from routers import fleet
    res = run(fleet.set_membership(
        tech_user_id="u1", body=_body(True, "GPS phone"),
        user=_super(), tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert res["membership"]["in_fleet"] is True


# ─── Enable / disable ───────────────────────────────────────────────

def test_enable_membership_creates_row(fake_db):
    from routers import fleet
    res = run(fleet.set_membership(
        tech_user_id="u1", body=_body(True, "primary rig"),
        user=_admin(), tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert res["membership"]["in_fleet"] is True
    row = fake_db.fleet_membership.rows[0]
    assert row["tech_user_id"] == "u1"
    assert row["tenant_id"] == "t1"
    assert row["enabled_by"] == "adm1"
    assert row["enabled_by_email"] == "admin@t1"
    assert row["enabled_at"]
    assert row["notes"] == "primary rig"


def test_disable_membership_updates_existing_row(fake_db):
    from routers import fleet
    # Enable first.
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True),
        user=_admin(), tenant={"id": "t1"},
    ))
    # Disable — same row updated.
    res = run(fleet.set_membership(
        tech_user_id="u1", body=_body(False, "on leave"),
        user=_admin(), tenant={"id": "t1"},
    ))
    assert res["membership"]["in_fleet"] is False
    assert res["membership"]["notes"] == "on leave"
    assert res["membership"]["disabled_by_email"] == "admin@t1"
    # Only one row for this (tenant, tech).
    matches = [r for r in fake_db.fleet_membership.rows
               if r["tech_user_id"] == "u1"]
    assert len(matches) == 1


def test_membership_writes_audit_log_on_enable(fake_db):
    from routers import fleet
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True),
        user=_admin(), tenant={"id": "t1"},
    ))
    events = [r for r in fake_db.audit_logs.rows
              if r.get("event", "").startswith("fleet.membership")]
    assert events
    assert events[-1]["event"] == "fleet.membership.enabled"
    assert events[-1]["actor_email"] == "admin@t1"
    assert events[-1]["target_user_id"] == "u1"


def test_membership_writes_audit_log_on_disable(fake_db):
    from routers import fleet
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True),
        user=_admin(), tenant={"id": "t1"},
    ))
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(False),
        user=_admin(), tenant={"id": "t1"},
    ))
    events = [r for r in fake_db.audit_logs.rows
              if r.get("event", "").startswith("fleet.membership")]
    assert events[-1]["event"] == "fleet.membership.disabled"


# ─── Roster (GET /membership) ───────────────────────────────────────

def test_list_membership_defaults_tech_to_out(fake_db):
    from routers import fleet
    res = run(fleet.list_membership(
        user=_admin(), tenant={"id": "t1"},
    ))
    assert res["count"] == 2                                   # u1 + u2
    for row in res["items"]:
        assert row["in_fleet"] is False


def test_list_membership_reflects_enabled_row(fake_db):
    from routers import fleet
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True, "primary"),
        user=_admin(), tenant={"id": "t1"},
    ))
    res = run(fleet.list_membership(
        user=_admin(), tenant={"id": "t1"},
    ))
    row_u1 = next(r for r in res["items"] if r["tech_user_id"] == "u1")
    row_u2 = next(r for r in res["items"] if r["tech_user_id"] == "u2")
    assert row_u1["in_fleet"] is True
    assert row_u1["notes"] == "primary"
    assert row_u1["enabled_by_email"] == "admin@t1"
    assert row_u2["in_fleet"] is False


def test_list_membership_cross_tenant_isolation(fake_db):
    from routers import fleet
    # Enable a t2 tech.
    run(fleet.set_membership(
        tech_user_id="u3", body=_body(True),
        user={"id": "adm-t2", "role": "admin", "email": "admin@t2"},
        tenant={"id": "t2"},
    ))
    # List for t1 — u3 must not appear.
    res = run(fleet.list_membership(
        user=_admin(), tenant={"id": "t1"},
    ))
    ids = {r["tech_user_id"] for r in res["items"]}
    assert ids == {"u1", "u2"}


def test_list_membership_excludes_non_tech_roles(fake_db):
    from routers import fleet
    res = run(fleet.list_membership(
        user=_admin(), tenant={"id": "t1"},
    ))
    ids = {r["tech_user_id"] for r in res["items"]}
    # Admin (adm1) is NOT a technician; must not appear.
    assert "adm1" not in ids


def test_disabled_tech_cannot_be_reenabled_without_new_audit(fake_db):
    """Every state flip produces its own audit event — enable →
    disable → re-enable must yield 3 events."""
    from routers import fleet
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True),
        user=_admin(), tenant={"id": "t1"},
    ))
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(False),
        user=_admin(), tenant={"id": "t1"},
    ))
    run(fleet.set_membership(
        tech_user_id="u1", body=_body(True, "back"),
        user=_admin(), tenant={"id": "t1"},
    ))
    events = [r for r in fake_db.audit_logs.rows
              if r.get("event", "").startswith("fleet.membership")]
    assert len(events) == 3
    assert [e["event"] for e in events] == [
        "fleet.membership.enabled",
        "fleet.membership.disabled",
        "fleet.membership.enabled",
    ]
