"""Sprint 3d · Feb-2026 — Insert-and-shift day-route reorder tests.

Immovable-anchor semantics (user-confirmed Feb-2026):
    * Completed / cancelled / skipped jobs are ANCHORS.  Their
      ``route_index`` is frozen and cannot be touched by any reorder.
    * The full day is numbered 1..N absolute.  Anchors occupy their
      fixed slots; incomplete jobs shift among the remaining
      non-anchor slots.
    * An in-range ``new_position`` that lands on an anchor is
      REJECTED with ``409 slot_occupied_by_completed_job``.
    * Out-of-range values (``≤ 0`` or ``> N``) clamp to the nearest
      non-anchor slot.

Uses the codebase's canonical async test pattern:
    * ``run_test(coro_factory)`` from ``tests._f7_loop_fixture`` to
      rebind Motor to a fresh loop.
    * ``httpx.AsyncClient(transport=ASGITransport(app=server.app))``
      driven in-process.
    * Dependency overrides for ``get_current_user`` +
      ``get_current_tenant`` so we skip JWT plumbing.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


def _make_job(*, tenant_id: str, tech_user_id: str, date: str,
                idx: int, status: str = "scheduled") -> Dict[str, Any]:
    return {
        "id":                 f"job_{tenant_id[:4]}_{tech_user_id[:4]}_{idx}_{uuid.uuid4().hex[:6]}",
        "tenant_id":          tenant_id,
        "customer_id":        f"cust_{idx}",
        "tech_user_id":       tech_user_id,
        "assigned_to":        tech_user_id,
        "technician_id":      tech_user_id,
        "scheduled_date":     f"{date}T09:00:00+00:00",
        "route_index":        idx,
        "status":             status,
        "created_at":         datetime.now(timezone.utc).isoformat(),
        "updated_at":         datetime.now(timezone.utc).isoformat(),
        "deleted_at":         None,
    }


@pytest.fixture(scope="module")
def seeded(dbc):
    """Seed a 5-job day for a dedicated test tenant + tech.

    Layout (0-indexed ``route_index``):
        [j0 scheduled, j1 scheduled, j2 scheduled,
         j3 COMPLETED (anchor at slot #4),
         j4 scheduled]

    Non-anchor absolute slots (1-indexed): #1, #2, #3, #5.
    Anchor slot: #4 → j3.
    """
    tenant_id    = f"t_reorder_{uuid.uuid4().hex[:8]}"
    tech_a       = f"tech_a_{uuid.uuid4().hex[:8]}"
    tech_b       = f"tech_b_{uuid.uuid4().hex[:8]}"
    date         = "2026-02-14"
    other_tenant = f"t_other_{uuid.uuid4().hex[:8]}"

    dbc.tenants.insert_many([
        {"id": tenant_id, "slug": f"reorder-{tenant_id[:6]}",
         "name": "Reorder Test"},
        {"id": other_tenant, "slug": f"other-{other_tenant[:6]}",
         "name": "Other Tenant"},
    ])
    admin_user = {
        "id": f"u_admin_{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "role": "admin",
        "email": f"admin.{tenant_id[:6]}@test.local",
    }
    dbc.users.insert_one(admin_user)

    # 5 jobs for tech_a on `date`, one terminal-status at idx 3
    # (locked-in-place semantics — immovable anchor).
    jobs: List[Dict[str, Any]] = []
    for i in range(5):
        st = "completed" if i == 3 else "scheduled"
        jobs.append(_make_job(
            tenant_id=tenant_id, tech_user_id=tech_a, date=date,
            idx=i, status=st,
        ))
    # 1 job on tech_b same day — should never appear in tech_a reorders.
    jobs.append(_make_job(
        tenant_id=tenant_id, tech_user_id=tech_b, date=date,
        idx=0,
    ))
    # 1 job in OTHER tenant, same tech id — cross-tenant guard.
    jobs.append(_make_job(
        tenant_id=other_tenant, tech_user_id=tech_a, date=date,
        idx=0,
    ))
    dbc.jobs.insert_many(jobs)

    yield {
        "tenant_id":    tenant_id,
        "other_tenant": other_tenant,
        "tech_a":       tech_a,
        "tech_b":       tech_b,
        "date":         date,
        "admin_id":     admin_user["id"],
        "job_ids_a":    [j["id"] for j in jobs
                          if j["tenant_id"] == tenant_id
                          and j["tech_user_id"] == tech_a],
    }

    # Cleanup
    dbc.jobs.delete_many({"tenant_id": {"$in": [tenant_id, other_tenant]}})
    dbc.users.delete_many({"tenant_id": tenant_id})
    dbc.tenants.delete_many({"id": {"$in": [tenant_id, other_tenant]}})
    dbc.audit_logs.delete_many({"tenant_id": tenant_id})


def _install_overrides(user: Dict[str, Any]):
    from utils import get_current_user
    from routers.tenants import get_current_tenant
    app = _get_app()

    async def _fake_user():
        return dict(user)

    async def _fake_tenant():
        return {"id": user["tenant_id"], "name": "T-Reorder"}

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _reset_positions(dbc, seeded):
    """Reset the 5-job day back to route_index 0..4 with anchor at #4."""
    for i, jid in enumerate(seeded["job_ids_a"]):
        dbc.jobs.update_one(
            {"id": jid},
            {"$set": {"route_index": i,
                       "status": "completed" if i == 3 else "scheduled"}},
        )


def _post(user: Dict[str, Any], body: Dict[str, Any]) -> httpx.Response:
    """Fire the endpoint under a fresh loop-bound HTTP session."""
    clear = _install_overrides(user)
    try:
        holder: Dict[str, Any] = {}

        async def _go(_db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                          base_url="http://test") as ac:
                holder["r"] = await ac.post(
                    "/api/jobs/reorder-day-route", json=body,
                )
        run_test(_go)
        return holder["r"]
    finally:
        clear()


# ─── Movement math ────────────────────────────────────────────────
def test_move_forward_from_5_to_2(dbc, seeded):
    """Move j4 (slot #5) → #2. Anchor j3 stays at #4."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][4],
        "new_position":  2,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["changed"] is True
    assert body["n"] == 5
    ordered = [row["job_id"] for row in body["renumbered"]]
    # New absolute order: j0(#1), j4(#2), j1(#3), j3(#4 anchor), j2(#5).
    assert ordered == [
        seeded["job_ids_a"][0],
        seeded["job_ids_a"][4],
        seeded["job_ids_a"][1],
        seeded["job_ids_a"][3],
        seeded["job_ids_a"][2],
    ]
    assert [row["sequence_number"] for row in body["renumbered"]] == [1, 2, 3, 4, 5]
    assert [row["is_anchor"] for row in body["renumbered"]] == [False, False, False, True, False]
    # Confirm the anchor's route_index in Mongo is untouched (still 3).
    anchor = dbc.jobs.find_one({"id": seeded["job_ids_a"][3]})
    assert anchor["route_index"] == 3


def test_move_backward_from_2_to_5(dbc, seeded):
    """Move j1 (slot #2) → #5 — legal, skips the anchor at #4."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][1],
        "new_position":  5,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    ordered = [row["job_id"] for row in body["renumbered"]]
    # j0 stays at #1. j2 shifts left to #2. j4 shifts left to #3.
    # Anchor j3 stays at #4. j1 lands at #5.
    assert ordered == [
        seeded["job_ids_a"][0],
        seeded["job_ids_a"][2],
        seeded["job_ids_a"][4],
        seeded["job_ids_a"][3],
        seeded["job_ids_a"][1],
    ]
    assert body["new_position"] == 5


def test_anchor_collision_rejected_409(dbc, seeded):
    """Attempt to move an incomplete job onto the anchor slot #4."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][1],
        "new_position":  4,   # anchor slot
    })
    assert r.status_code == 409, r.text
    detail = r.json().get("detail")
    assert isinstance(detail, dict)
    assert detail["code"] == "slot_occupied_by_completed_job"
    assert detail["requested_position"] == 4
    assert detail["anchor_job_id"] == seeded["job_ids_a"][3]
    assert detail["n"] == 5
    assert 4 not in detail["free_positions"]
    # Nothing persisted — j1 stays at #2.
    j1 = dbc.jobs.find_one({"id": seeded["job_ids_a"][1]})
    assert j1["route_index"] == 1


def test_move_to_end_clamps_past_anchor(dbc, seeded):
    """Move j0 to position 99 — clamps to the largest free slot (#5)."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][0],
        "new_position":  99,
    })
    assert r.status_code == 200
    body = r.json()
    # Clamp lands on the largest non-anchor slot = #5.
    assert body["new_position"] == 5
    assert body["renumbered"][-1]["job_id"] == seeded["job_ids_a"][0]
    assert body["renumbered"][-1]["sequence_number"] == 5
    # Anchor untouched at #4.
    assert body["renumbered"][3]["is_anchor"] is True
    assert body["renumbered"][3]["job_id"] == seeded["job_ids_a"][3]


def test_clamp_to_start(dbc, seeded):
    """new_position=0 clamps to the smallest free slot (#1)."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][4],
        "new_position":  0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["new_position"] == 1
    assert body["renumbered"][0]["job_id"] == seeded["job_ids_a"][4]
    assert body["renumbered"][0]["sequence_number"] == 1


def test_same_position_noop(dbc, seeded):
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][0],
        "new_position":  1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is False
    assert body["affected_job_ids"] == []
    assert body["updated_count"] == 0


# ─── Terminal-status locking ──────────────────────────────────────
def test_terminal_job_cannot_be_reordered(dbc, seeded):
    """Attempt to move the anchor itself → 404."""
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][3],  # completed
        "new_position":  1,
    })
    assert r.status_code == 404, r.text


def test_terminal_job_route_index_unchanged_after_reorder(dbc, seeded):
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][4],
        "new_position":  1,
    })
    completed = dbc.jobs.find_one({"id": seeded["job_ids_a"][3]})
    assert completed["route_index"] == 3  # untouched


# ─── Cross-tenant / cross-tech isolation ──────────────────────────
def test_cross_tenant_isolation(dbc, seeded):
    _reset_positions(dbc, seeded)
    other_user = {"id": "u_other_admin", "role": "admin",
                    "tenant_id": seeded["other_tenant"]}
    r = _post(other_user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][0],
        "new_position":  3,
    })
    assert r.status_code == 404


# ─── RBAC ─────────────────────────────────────────────────────────
def test_non_admin_role_rejected(dbc, seeded):
    _reset_positions(dbc, seeded)
    tech = {"id": "u_tech", "role": "technician",
             "tenant_id": seeded["tenant_id"]}
    r = _post(tech, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][0],
        "new_position":  2,
    })
    assert r.status_code == 403


# ─── Bad input ────────────────────────────────────────────────────
def test_unknown_job_id_404(dbc, seeded):
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        "nonexistent",
        "new_position":  2,
    })
    assert r.status_code == 404


def test_unknown_tech_404(dbc, seeded):
    _reset_positions(dbc, seeded)
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": "no_such_tech",
        "job_id":        seeded["job_ids_a"][0],
        "new_position":  2,
    })
    assert r.status_code == 404


def test_bad_body_422(dbc, seeded):
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {"date": seeded["date"]})  # missing fields
    assert r.status_code == 422


# ─── Audit ────────────────────────────────────────────────────────
def test_audit_line_written(dbc, seeded):
    _reset_positions(dbc, seeded)
    dbc.audit_logs.delete_many(
        {"tenant_id": seeded["tenant_id"], "event": "job_route_reordered"},
    )
    user = {"id": seeded["admin_id"], "role": "admin",
             "tenant_id": seeded["tenant_id"]}
    r = _post(user, {
        "date":          seeded["date"],
        "technician_id": seeded["tech_a"],
        "job_id":        seeded["job_ids_a"][4],
        "new_position":  2,
    })
    assert r.status_code == 200
    audit = dbc.audit_logs.find_one(
        {"tenant_id": seeded["tenant_id"], "event": "job_route_reordered"},
    )
    assert audit is not None
    assert audit["actor_user_id"] == seeded["admin_id"]
    assert audit["job_id"] == seeded["job_ids_a"][4]
    assert audit["new_position"] == 2
    assert isinstance(audit.get("affected_job_ids"), list)
    assert len(audit["affected_job_ids"]) >= 2


# ─── Frontend uniqueness copy — dead-code guard ─────────────────
def test_uniqueness_validation_string_removed():
    src_path = Path(__file__).resolve().parents[2] / "frontend" / "src" \
                / "pages" / "schedule" / "NumberedReorder.jsx"
    text = src_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    live_message_lines = [
        ln for ln in lines
        if "message =" in ln and not ln.lstrip().startswith("//")
    ]
    joined = "\n".join(live_message_lines)
    assert "Job numbers must be unique" not in joined, (
        "uniqueness error copy leaked back into the live validate() "
        "code path"
    )
