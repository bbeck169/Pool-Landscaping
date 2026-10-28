"""G1 · Feb-2026 (WW follow-up) — ``PATCH /api/jobs/{jid}/service-
report`` is the 5th completed-job write path. The 4 shipped WW
flip-sites (``PUT /jobs/{jid}/field-report``, ``PATCH /jobs/{jid}``,
``POST /jobs/{jid}/photos``, ``DELETE /jobs/{jid}/photos/{pid}``)
missed it, so mobile ``checklist.tsx`` saves (chemistry / notes /
checklist / photos round-tripping through the service-report
autosave) didn't light the "Edited after completion" badge. G1
teaches the PATCH to flip ``jobs.edited_after_completion`` and
write a matching ``db.job_edits`` row, mirroring the shipped
sibling pattern at ``jobs.py:7695-7725`` 1:1.

Six locked cases per operator spec:
  1. Completed job + checklist patch → denorm flips,
     ``closed_job_checklist_toggle`` audit row with
     checklist_items diff.
  2. Completed job + chemistry patch → denorm flips,
     ``closed_job_edit`` audit row (per operator D1 pick (b)
     for WW mobile broader-unlock).
  3. Open job patch → NO flip, NO audit row (negative lock).
  4. Idempotent — second flip is a no-op; discriminator correct
     per field class.
  5. Admin 409 on mobile checklist post-submit still 409s (G2
     scope — do NOT accidentally fix).
  6. Round-trip with the shipped 4 WW flip-sites — if a sibling
     site flips first, this PATCH sees ``edited_after_completion``
     already True and the new row is still written with the
     correct discriminator.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_db = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id, email, role, tenant_id):
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _seed_user(tenant_id, role, *, department="pool", email=None):
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = email or f"{uid}@g1.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"G1 {role} {uid[-4:]}", "email": email,
        "department": department,
    })
    return {
        "id": uid, "email": email, "role": role,
        "tenant_id": tenant_id,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_job(tenant_id, tech_id, *, status, with_checklist=True):
    jid = f"g1-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": f"g1-cust-{uuid.uuid4().hex[:6]}",
        "technician_id": tech_id,
        "status": status,
        "notes": "pre-g1",
        "photos": [],
        "service_type": "pool-weekly",
    }
    if status == "completed":
        doc["completed_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()
    if with_checklist:
        doc["checklist"] = [
            {"id": "c0", "label": "Skim surface", "done": False},
            {"id": "c1", "label": "Vacuum floor", "done": False},
        ]
    _db.jobs.insert_one(doc)
    return jid


def _seed_service_report(tenant_id, jid, tech_id):
    """GET /service-report bootstraps the row if missing; prefer a
    direct seed so tests stay deterministic + offline-safe."""
    rid = f"sr-{uuid.uuid4().hex[:10]}"
    _db.service_reports.insert_one({
        "id": rid, "tenant_id": tenant_id,
        "job_id": jid, "tech_id": tech_id,
        "chemical_readings": [], "chemicals_added": [],
        "checklist_items": [], "photos": [],
        "notes": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return rid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"g1-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"G1 {tid}", "slug": tid,
        "active": True, "widget_allowed_domains": [],
    })
    tech = _seed_user(tid, "technician", department="pool")
    admin = _seed_user(tid, "admin", department=None)
    yield {"tid": tid, "tech": tech, "admin": admin}
    _db.job_edits.delete_many({"tenant_id": tid})
    _db.service_reports.delete_many({"tenant_id": tid})
    _db.jobs.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


# ───────────────────────────────────────────────────────────────────
# Case 1 · completed + checklist → flip + closed_job_checklist_toggle
# ───────────────────────────────────────────────────────────────────
def test_completed_job_checklist_patch_flips_denorm_and_writes_toggle_audit(ctx):
    jid = _seed_job(ctx["tid"], ctx["tech"]["id"], status="completed")
    _seed_service_report(ctx["tid"], jid, ctx["tech"]["id"])
    new_cl = [{"id": "c0", "label": "Skim", "done": True}]
    r = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"checklist_items": new_cl}, timeout=20,
    )
    assert r.status_code == 200, r.text
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert job["edited_after_completion"] is True
    row = _db.job_edits.find_one(
        {"job_id": jid, "event": "closed_job_checklist_toggle"},
        {"_id": 0},
    )
    assert row is not None, "closed_job_checklist_toggle audit missing"
    assert row["edited_by"] == ctx["tech"]["id"]
    assert row["edited_by_role"] == "technician"
    assert row["source"] == "web"
    assert "checklist_items" in row["changes"]
    assert row["changes"]["checklist_items"]["after"] == new_cl


# ───────────────────────────────────────────────────────────────────
# Case 2 · completed + chemistry → flip + closed_job_edit (mobile
#   broader-unlock per operator D1 pick (b) for WW mobile)
# ───────────────────────────────────────────────────────────────────
def test_completed_job_chemistry_patch_flips_denorm_and_writes_edit_audit(ctx):
    jid = _seed_job(ctx["tid"], ctx["tech"]["id"], status="completed")
    _seed_service_report(ctx["tid"], jid, ctx["tech"]["id"])
    new_readings = [{"key": "chlorine", "value_ppm": 2.4}]
    r = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"chemical_readings": new_readings}, timeout=20,
    )
    assert r.status_code == 200, r.text
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert job["edited_after_completion"] is True
    row = _db.job_edits.find_one(
        {"job_id": jid, "event": "closed_job_edit"}, {"_id": 0},
    )
    assert row is not None, (
        "closed_job_edit audit missing for chemistry patch on completed job"
    )
    assert "chemical_readings" in row["changes"]
    # Belt-and-braces — the toggle discriminator must NOT fire for a
    # chemistry-only payload.
    toggle = _db.job_edits.find_one(
        {"job_id": jid, "event": "closed_job_checklist_toggle"},
    )
    assert toggle is None


# ───────────────────────────────────────────────────────────────────
# Case 3 · open job → no flip, no audit row (negative lock)
# ───────────────────────────────────────────────────────────────────
def test_open_job_patch_does_not_flip_or_audit(ctx):
    jid = _seed_job(ctx["tid"], ctx["tech"]["id"], status="scheduled")
    _seed_service_report(ctx["tid"], jid, ctx["tech"]["id"])
    r = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"notes": "open-job note bump"}, timeout=20,
    )
    assert r.status_code == 200, r.text
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert not job.get("edited_after_completion"), (
        "open-job PATCH must NOT flip edited_after_completion"
    )
    row = _db.job_edits.find_one({"job_id": jid}, {"_id": 0})
    assert row is None, "open-job PATCH must NOT write a job_edits audit row"


# ───────────────────────────────────────────────────────────────────
# Case 4 · idempotent — 2nd flip is no-op; discriminator per field
# ───────────────────────────────────────────────────────────────────
def test_second_flip_is_noop_and_discriminator_switches_per_field(ctx):
    jid = _seed_job(ctx["tid"], ctx["tech"]["id"], status="completed")
    _seed_service_report(ctx["tid"], jid, ctx["tech"]["id"])
    # 1st PATCH — chemistry → closed_job_edit, flip denorm.
    r1 = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"chemical_readings": [{"key": "ph", "value_ppm": 7.2}]},
        timeout=20,
    )
    assert r1.status_code == 200, r1.text
    # 2nd PATCH — checklist → closed_job_checklist_toggle, flip is no-op.
    r2 = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"checklist_items": [
            {"id": "c0", "label": "Skim", "done": True},
        ]}, timeout=20,
    )
    assert r2.status_code == 200, r2.text
    # Denorm remains True (no backwards flip).
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert job["edited_after_completion"] is True
    # Exactly ONE closed_job_edit row + ONE closed_job_checklist_toggle row.
    edits = list(_db.job_edits.find(
        {"job_id": jid, "event": "closed_job_edit"}, {"_id": 0},
    ))
    toggles = list(_db.job_edits.find(
        {"job_id": jid, "event": "closed_job_checklist_toggle"}, {"_id": 0},
    ))
    assert len(edits) == 1
    assert len(toggles) == 1


# ───────────────────────────────────────────────────────────────────
# Case 5 · G2 scope lock — admin 409 on post-submit SR still 409s
# ───────────────────────────────────────────────────────────────────
def test_admin_post_submit_patch_still_409s_g2_scope(ctx):
    """G1 must NOT accidentally re-open the admin 409 that G2 owns.
    When ``rep.submitted_at`` is truthy AND the actor is admin, the
    PATCH must still 409 with the SR-already-submitted message."""
    jid = _seed_job(ctx["tid"], ctx["admin"]["id"], status="completed")
    rid = _seed_service_report(ctx["tid"], jid, ctx["admin"]["id"])
    _db.service_reports.update_one(
        {"id": rid},
        {"$set": {"submitted_at": datetime.now(timezone.utc).isoformat()}},
    )
    r = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["admin"]["token"]),
        json={"notes": "admin trying to edit post-submit"},
        timeout=20,
    )
    assert r.status_code == 409, (
        f"G2 scope regression — expected 409, got {r.status_code}: {r.text}"
    )
    # And the denorm must NOT have flipped on the 409 path.
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert not job.get("edited_after_completion")
    row = _db.job_edits.find_one({"job_id": jid}, {"_id": 0})
    assert row is None


# ───────────────────────────────────────────────────────────────────
# Case 6 · cross-site round-trip — denorm pre-flipped by sibling
# ───────────────────────────────────────────────────────────────────
def test_cross_site_roundtrip_preserves_flip_and_writes_g1_audit(ctx):
    """If a sibling WW flip-site (e.g. POST /jobs/{jid}/photos) has
    already flipped ``edited_after_completion`` to True on this job,
    the G1 PATCH must still write its own ``job_edits`` row with the
    correct discriminator — the ``$ne: True`` idempotency filter on
    the denorm must NOT suppress the audit insert."""
    jid = _seed_job(ctx["tid"], ctx["tech"]["id"], status="completed")
    _seed_service_report(ctx["tid"], jid, ctx["tech"]["id"])
    # Simulate a sibling flip-site landing first.
    _db.jobs.update_one(
        {"id": jid},
        {"$set": {"edited_after_completion": True}},
    )
    # G1 PATCH fires second.
    r = requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers=_auth(ctx["tech"]["token"]),
        json={"notes": "later edit via service-report autosave"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    # Denorm still True (no regression).
    job = _db.jobs.find_one({"id": jid}, {"_id": 0, "edited_after_completion": 1})
    assert job["edited_after_completion"] is True
    # G1 audit row still written.
    row = _db.job_edits.find_one(
        {"job_id": jid, "event": "closed_job_edit"}, {"_id": 0},
    )
    assert row is not None, (
        "G1 audit row must still be written when the denorm is already True"
    )
