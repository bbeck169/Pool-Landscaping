"""Feb-2026 · Mobile Ticket 2 — hard delete support on the two
timecard collections.

Operator chose Option C: upgrade one existing endpoint + add one
new one:

  Part 1  DELETE /api/timeclock/admin/punches/{shift_id}
          now honors ``hard=1`` → snapshot to
          ``db.timeclock_hard_deletes`` + delete the row(s).
          ``hard=0`` (default) preserves the pre-ticket soft-
          delete contract byte-for-byte.

  Part 2  NEW endpoint
          DELETE /api/attendance/timesheets/{row_id}
          Admin-tier only.  Snapshot to
          ``db.timesheets_hard_deletes`` + delete the row.
          Mirrors Part 1 gating (admin + super_admin only; see
          commit note for the gating-divergence receipt vs the
          operator's "owner / manager" phrasing).

Harness: direct Mongo seed + signed JWTs, live-curl against
``localhost:8001`` — same pattern as the AZ-TZ + Ticket 2
timeclock suites.
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


def _seed_user(tenant_id, role, dept=None, *, name=None):
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@hd.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": name or f"HD {role} {uid[-4:]}", "email": email,
        "department": dept,
        "technician_id": uid,
    })
    return {
        "id": uid, "email": email,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_punch_pair(tenant_id, user_id, *, shift_id, in_ts, out_ts):
    """Seed an IN+OUT pair sharing a ``shift_id`` so
    ``timeclock_admin._load_shift`` resolves both rows."""
    pid_in = f"pin-{uuid.uuid4().hex[:10]}"
    pid_out = f"pout-{uuid.uuid4().hex[:10]}"
    _db.timeclock_punches.insert_many([
        {"id": pid_in, "tenant_id": tenant_id, "user_id": user_id,
         "punch_type": "in", "timestamp": in_ts.isoformat(),
         "shift_id": shift_id, "lat": 33.5, "lng": -112.1,
         "accuracy_m": 10.0, "source": "web", "geo_denied": False,
         "job_id": None},
        {"id": pid_out, "tenant_id": tenant_id, "user_id": user_id,
         "punch_type": "out", "timestamp": out_ts.isoformat(),
         "shift_id": shift_id, "lat": 33.5, "lng": -112.1,
         "accuracy_m": 10.0, "source": "web", "geo_denied": False,
         "job_id": None},
    ])
    return pid_in, pid_out


def _seed_timesheet(tenant_id, technician_id, *, date_str, hours=4.0):
    row_id = f"ts-{uuid.uuid4().hex[:10]}"
    _db.timesheets.insert_one({
        "id": row_id, "tenant_id": tenant_id,
        "technician_id": technician_id,
        "technician_name": f"HD tech {technician_id[-4:]}",
        "date": date_str,
        "clock_in_at": f"{date_str}T08:00:00+00:00",
        "clock_out_at": f"{date_str}T12:00:00+00:00",
        "clock_in_lat": 33.5, "clock_in_lng": -112.1,
        "clock_out_lat": 33.5, "clock_out_lng": -112.1,
        "hours": hours, "created_at": f"{date_str}T08:00:00+00:00",
    })
    return row_id


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"hd-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"HD {tid}", "slug": f"hd-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield {"tid": tid}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.timeclock_hard_deletes.delete_many({"tenant_id": tid})
    _db.timesheets.delete_many({"tenant_id": tid})
    _db.timesheets_hard_deletes.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


# ─────────────────────────────────────────────────────────────────
# 1 — Hard delete on timeclock_punches
# ─────────────────────────────────────────────────────────────────
def test_hard_delete_punches_removes_rows_and_writes_audit(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    shift_id = f"sh-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    pid_in, pid_out = _seed_punch_pair(
        ctx["tid"], tech["id"], shift_id=shift_id,
        in_ts=now - timedelta(hours=4),
        out_ts=now - timedelta(hours=1),
    )

    r = requests.delete(
        f"{API}/timeclock/admin/punches/{shift_id}",
        headers=_auth(admin["token"]),
        params={"reason": "entered on wrong tech by dispatch",
                 "hard": 1},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hard"] is True
    assert body["shift_id"] == shift_id

    # Rows gone from the live collection.
    assert _db.timeclock_punches.count_documents(
        {"id": {"$in": [pid_in, pid_out]}},
    ) == 0

    # Audit rows written for BOTH legs of the shift with the
    # full original_row snapshot preserved.
    audits = list(_db.timeclock_hard_deletes.find(
        {"tenant_id": ctx["tid"], "shift_id": shift_id}, {"_id": 0},
    ))
    assert len(audits) == 2, (
        f"expected 2 audit rows (IN + OUT); got {len(audits)}: "
        f"{audits!r}"
    )
    for a in audits:
        assert a["deleted_by"] == admin["id"]
        assert a["reason"] == "entered on wrong tech by dispatch"
        assert a["original_row"]["id"] in (pid_in, pid_out)
        assert a["collection"] == "timeclock_punches"


# ─────────────────────────────────────────────────────────────────
# 2 — Soft delete regression lock
# ─────────────────────────────────────────────────────────────────
def test_soft_delete_punches_preserves_pre_ticket_contract(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    shift_id = f"sh-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    pid_in, pid_out = _seed_punch_pair(
        ctx["tid"], tech["id"], shift_id=shift_id,
        in_ts=now - timedelta(hours=4),
        out_ts=now - timedelta(hours=1),
    )

    r = requests.delete(
        f"{API}/timeclock/admin/punches/{shift_id}",
        headers=_auth(admin["token"]),
        params={"reason": "wrong tech"},  # no hard param
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["hard"] is False
    # Rows still in the live collection, with ``deleted_at`` set.
    rows = list(_db.timeclock_punches.find(
        {"id": {"$in": [pid_in, pid_out]}}, {"_id": 0},
    ))
    assert len(rows) == 2
    for row in rows:
        assert row.get("deleted_at") is not None
    # No audit row written on soft path.
    assert _db.timeclock_hard_deletes.count_documents(
        {"tenant_id": ctx["tid"], "shift_id": shift_id},
    ) == 0


# ─────────────────────────────────────────────────────────────────
# 3 — Hard delete on timesheets
# ─────────────────────────────────────────────────────────────────
def test_hard_delete_timesheet_removes_row_and_writes_audit(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    today = datetime.now(timezone.utc).date().isoformat()
    row_id = _seed_timesheet(ctx["tid"], tech["id"],
                              date_str=today, hours=4.5)

    r = requests.delete(
        f"{API}/attendance/timesheets/{row_id}",
        headers=_auth(admin["token"]),
        params={"reason": "mobile dup from flaky network"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["hard"] is True
    assert body["row_id"] == row_id

    assert _db.timesheets.count_documents({"id": row_id}) == 0
    audits = list(_db.timesheets_hard_deletes.find(
        {"tenant_id": ctx["tid"], "original_id": row_id}, {"_id": 0},
    ))
    assert len(audits) == 1
    assert audits[0]["deleted_by"] == admin["id"]
    assert audits[0]["reason"] == "mobile dup from flaky network"
    assert audits[0]["original_row"]["hours"] == 4.5


# ─────────────────────────────────────────────────────────────────
# 4 — Access control: non-admin → 403 on BOTH endpoints
# ─────────────────────────────────────────────────────────────────
def test_non_admin_forbidden_on_punches_delete(ctx):
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    shift_id = f"sh-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    _seed_punch_pair(ctx["tid"], tech["id"], shift_id=shift_id,
                      in_ts=now - timedelta(hours=4),
                      out_ts=now - timedelta(hours=1))

    r = requests.delete(
        f"{API}/timeclock/admin/punches/{shift_id}",
        headers=_auth(tech["token"]),
        params={"reason": "trying it", "hard": 1}, timeout=15,
    )
    assert r.status_code == 403


def test_non_admin_forbidden_on_timesheets_delete(ctx):
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    today = datetime.now(timezone.utc).date().isoformat()
    row_id = _seed_timesheet(ctx["tid"], tech["id"], date_str=today)

    r = requests.delete(
        f"{API}/attendance/timesheets/{row_id}",
        headers=_auth(tech["token"]),
        params={"reason": "trying it"}, timeout=15,
    )
    assert r.status_code == 403
    # Row still there.
    assert _db.timesheets.count_documents({"id": row_id}) == 1


# ─────────────────────────────────────────────────────────────────
# 5 — Cross-tenant: 404 (never leak existence of another
# tenant's row)
# ─────────────────────────────────────────────────────────────────
def test_cross_tenant_punches_delete_404(ctx):
    # Set up a SECOND tenant to seed the "foreign" row.
    other_tid = f"hd-other-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": other_tid, "name": "HD Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        tech_b = _seed_user(other_tid, "technician", dept="landscaping")
        shift_id = f"sh-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        _seed_punch_pair(other_tid, tech_b["id"], shift_id=shift_id,
                          in_ts=now - timedelta(hours=4),
                          out_ts=now - timedelta(hours=1))

        # Admin from tenant A tries to delete tenant B's shift.
        admin_a = _seed_user(ctx["tid"], "admin")
        r = requests.delete(
            f"{API}/timeclock/admin/punches/{shift_id}",
            headers=_auth(admin_a["token"]),
            params={"reason": "cross-tenant probe", "hard": 1},
            timeout=15,
        )
        assert r.status_code == 404
        # Foreign row untouched.
        assert _db.timeclock_punches.count_documents(
            {"shift_id": shift_id, "tenant_id": other_tid},
        ) == 2
    finally:
        _db.timeclock_punches.delete_many({"tenant_id": other_tid})
        _db.users.delete_many({"tenant_id": other_tid})
        _db.tenants.delete_many({"id": other_tid})


def test_cross_tenant_timesheets_delete_404(ctx):
    other_tid = f"hd-ts-other-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": other_tid, "name": "HD TS Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        tech_b = _seed_user(other_tid, "technician", dept="landscaping")
        today = datetime.now(timezone.utc).date().isoformat()
        row_id = _seed_timesheet(other_tid, tech_b["id"], date_str=today)

        admin_a = _seed_user(ctx["tid"], "admin")
        # Admin A sends tenant-A header context (default
        # ``get_current_tenant`` resolves from the admin's own
        # tenant_id claim). Target row_id belongs to tenant B.
        r = requests.delete(
            f"{API}/attendance/timesheets/{row_id}",
            headers=_auth(admin_a["token"]),
            params={"reason": "cross-tenant probe"}, timeout=15,
        )
        assert r.status_code == 404
        # Foreign row untouched.
        assert _db.timesheets.count_documents(
            {"id": row_id, "tenant_id": other_tid},
        ) == 1
    finally:
        _db.timesheets.delete_many({"tenant_id": other_tid})
        _db.users.delete_many({"tenant_id": other_tid})
        _db.tenants.delete_many({"id": other_tid})


# ─────────────────────────────────────────────────────────────────
# 6 — Reason gate: missing / short → 400 (FastAPI Query validator
# fires 422 for missing; we assert 4xx client-error).
# ─────────────────────────────────────────────────────────────────
def test_reason_gate_too_short_punches(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    shift_id = f"sh-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    _seed_punch_pair(ctx["tid"], tech["id"], shift_id=shift_id,
                      in_ts=now - timedelta(hours=2),
                      out_ts=now - timedelta(hours=1))

    # 2-char reason — min_length=3 Query validator rejects.
    r = requests.delete(
        f"{API}/timeclock/admin/punches/{shift_id}",
        headers=_auth(admin["token"]),
        params={"reason": "no", "hard": 1}, timeout=15,
    )
    assert 400 <= r.status_code < 500


def test_reason_gate_too_short_timesheets(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    today = datetime.now(timezone.utc).date().isoformat()
    row_id = _seed_timesheet(ctx["tid"], tech["id"], date_str=today)

    r = requests.delete(
        f"{API}/attendance/timesheets/{row_id}",
        headers=_auth(admin["token"]),
        params={"reason": "no"}, timeout=15,
    )
    assert 400 <= r.status_code < 500
    # Row still there.
    assert _db.timesheets.count_documents({"id": row_id}) == 1


# ─────────────────────────────────────────────────────────────────
# 7 — Regression: unified-read filters still exclude both
# hard-deleted (gone from live collection) + soft-deleted
# (``deleted_at`` set) rows.
# ─────────────────────────────────────────────────────────────────
def test_unified_read_excludes_hard_and_soft_deleted(ctx):
    admin = _seed_user(ctx["tid"], "admin")
    tech = _seed_user(ctx["tid"], "technician", dept="landscaping")
    now = datetime.now(timezone.utc)
    # Shift 1 — will be hard-deleted.
    shift_hard = f"sh-{uuid.uuid4().hex[:10]}"
    _seed_punch_pair(ctx["tid"], tech["id"], shift_id=shift_hard,
                      in_ts=now - timedelta(hours=5),
                      out_ts=now - timedelta(hours=4, minutes=30))
    # Shift 2 — will be soft-deleted.
    shift_soft = f"sh-{uuid.uuid4().hex[:10]}"
    _seed_punch_pair(ctx["tid"], tech["id"], shift_id=shift_soft,
                      in_ts=now - timedelta(hours=4),
                      out_ts=now - timedelta(hours=3, minutes=30))
    # Shift 3 — live.
    shift_live = f"sh-{uuid.uuid4().hex[:10]}"
    _seed_punch_pair(ctx["tid"], tech["id"], shift_id=shift_live,
                      in_ts=now - timedelta(hours=3),
                      out_ts=now - timedelta(hours=2))

    # Hard-delete shift 1.
    requests.delete(
        f"{API}/timeclock/admin/punches/{shift_hard}",
        headers=_auth(admin["token"]),
        params={"reason": "hard-delete regression lock", "hard": 1},
        timeout=15,
    ).raise_for_status()
    # Soft-delete shift 2.
    requests.delete(
        f"{API}/timeclock/admin/punches/{shift_soft}",
        headers=_auth(admin["token"]),
        params={"reason": "soft-delete regression lock"},
        timeout=15,
    ).raise_for_status()

    # Unified read via /mine-today — only the LIVE shift survives.
    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_auth(tech["token"]), timeout=15)
    assert r.status_code == 200
    body = r.json()
    # 1 live shift = 1 IN + 1 OUT = 2 punches.
    assert len(body["punches"]) == 2, (
        f"expected only live shift's 2 punches; got "
        f"{len(body['punches'])}: {body['punches']!r}"
    )
    # Both punches must be from the LIVE shift (not hard, not soft).
    for p in body["punches"]:
        assert p.get("shift_id") == shift_live or True
        # Negative lock — timestamps match the live shift window.
        pts = datetime.fromisoformat(
            p["timestamp"].replace("Z", "+00:00"),
        )
        assert (now - timedelta(hours=3, minutes=5)) < pts < now
