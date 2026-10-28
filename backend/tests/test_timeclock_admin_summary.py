"""Feb-2026 · Phase 4-landscape · Admin aggregation on timeclock.

Harness mirrors ``test_landscape_timeclock_dept_both.py``: direct
Mongo seed + signed JWTs, live-curl against ``localhost:8001``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, date, timedelta
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


def _seed_user(tenant_id, role, *, department=None):
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@tcas.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"TCAS {role} {uid[-4:]}", "email": email,
        "department": department,
    })
    return {
        "id": uid, "email": email, "role": role,
        "department": department, "tenant_id": tenant_id,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_punch(tenant_id, user_id, *,
                punch_type, ts_utc,
                lat=33.5, lng=-112.1, job_id=None):
    pid = f"p-{uuid.uuid4().hex[:10]}"
    _db.timeclock_punches.insert_one({
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": punch_type,
        "timestamp": ts_utc.isoformat(),
        "lat": lat, "lng": lng, "accuracy_m": 10.0,
        "source": "web", "geo_denied": False, "job_id": job_id,
    })
    return pid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"tcas-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"TCAS {tid}", "slug": f"tcas-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    admin = _seed_user(tid, "admin")
    yield {"tid": tid, "admin": admin}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


def _this_week():
    today_d = date.today()
    monday = today_d - timedelta(days=today_d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def test_admin_default_range_returns_landscape_techs_only(ctx):
    tid = ctx["tid"]
    land = _seed_user(tid, "technician", department="landscaping")
    pool = _seed_user(tid, "technician", department="pool")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "range" in data and "techs" in data
    tech_ids = [t["user_id"] for t in data["techs"]]
    assert land["id"] in tech_ids
    assert pool["id"] not in tech_ids
    assert data["range"].get("start"), data["range"]
    assert data["range"].get("end"), data["range"]


def test_non_admin_forbidden(ctx):
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(tech["token"]), timeout=20,
    )
    assert r.status_code == 403, r.text


def test_other_tenant_tech_excluded(ctx):
    tid = ctx["tid"]
    other_tid = f"tcas-oth-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": other_tid, "name": "Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    other = _seed_user(other_tid, "technician", department="landscaping")
    try:
        r = requests.get(
            f"{API}/timeclock/admin-summary",
            headers=_auth(ctx["admin"]["token"]), timeout=20,
        )
        assert r.status_code == 200
        tech_ids = [t["user_id"] for t in r.json()["techs"]]
        assert other["id"] not in tech_ids
    finally:
        _db.users.delete_many({"tenant_id": other_tid})
        _db.tenants.delete_many({"id": other_tid})


def test_pool_dept_tech_excluded(ctx):
    tid = ctx["tid"]
    pool = _seed_user(tid, "technician", department="pool")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200
    tech_ids = [t["user_id"] for t in r.json()["techs"]]
    assert pool["id"] not in tech_ids


def test_range_filtering_excludes_out_of_range_punches(ctx):
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    monday, sunday = _this_week()
    midweek = datetime.combine(
        monday, datetime.min.time(), timezone.utc,
    ) + timedelta(days=2, hours=9)
    in_range = _seed_punch(
        tid, tech["id"], punch_type="in", ts_utc=midweek,
    )
    out_range = _seed_punch(
        tid, tech["id"], punch_type="in",
        ts_utc=midweek - timedelta(days=14),
    )
    r = requests.get(
        f"{API}/timeclock/admin-summary?start={monday.isoformat()}"
        f"&end={sunday.isoformat()}",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    row = next(t for t in r.json()["techs"] if t["user_id"] == tech["id"])
    punch_ids = [p["id"] for p in row["punches"]]
    assert in_range in punch_ids
    assert out_range not in punch_ids


def test_paired_in_out_duration(ctx):
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    monday, sunday = _this_week()
    t0 = datetime.combine(
        monday, datetime.min.time(), timezone.utc,
    ) + timedelta(days=1, hours=9)
    _seed_punch(tid, tech["id"], punch_type="in", ts_utc=t0)
    _seed_punch(
        tid, tech["id"], punch_type="out",
        ts_utc=t0 + timedelta(hours=2),
    )
    r = requests.get(
        f"{API}/timeclock/admin-summary?start={monday.isoformat()}"
        f"&end={sunday.isoformat()}",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    row = next(t for t in r.json()["techs"] if t["user_id"] == tech["id"])
    assert row["total_seconds"] == 7200
    assert row["status"] == "out"


def test_dangling_in_marks_status_in_and_no_time_counted(ctx):
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    monday, sunday = _this_week()
    t0 = datetime.combine(
        monday, datetime.min.time(), timezone.utc,
    ) + timedelta(days=1, hours=9)
    _seed_punch(tid, tech["id"], punch_type="in", ts_utc=t0)
    r = requests.get(
        f"{API}/timeclock/admin-summary?start={monday.isoformat()}"
        f"&end={sunday.isoformat()}",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    row = next(t for t in r.json()["techs"] if t["user_id"] == tech["id"])
    assert row["status"] == "in"
    assert row["total_seconds"] == 0
    assert row["last_punch"]["punch_type"] == "in"


# ─────────────────────────────────────────────────────────────────────
# Phase 31 · Hide designated landscape test accounts from the UI
# ─────────────────────────────────────────────────────────────────────
def _seed_user_with_email(tenant_id, email, *, department="landscaping"):
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": f"TCAS tech {uid[-4:]}", "email": email,
        "department": department, "active": True,
    })
    return {"id": uid, "email": email}


def test_phase31_hide_landscape_test_techs_from_admin_summary(ctx):
    """``luis@aquaterra.com`` is the retained landscape-tech hide-list
    account post-TC ruling-reversal. TC · C2 (Feb-2026) removed
    ``carlos@aquaterra.com`` from ``_AGGREGATION_HIDE_EMAILS`` per
    operator decision (the demo-preview punch suppression was
    accidentally hiding real landscape-tech punches from the admin
    team-aggregation view, operator-reported P0). The carlos assertion
    half of this case has moved to the new ``test_tc_admin_roster_
    dept_fallback.py::test_carlos_unhidden_surfaces_when_punches_
    exist`` case; this test now locks the surviving luis-still-hidden
    + non-hidden-tech-surfaces thesis.
    """
    tid = ctx["tid"]
    _seed_user_with_email(tid, "luis@aquaterra.com")
    other = _seed_user_with_email(tid, f"other-{uuid.uuid4().hex[:6]}@tcas.test")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_emails = {t.get("name") for t in r.json()["techs"]}
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert other["id"] in returned_ids, (
        "non-hidden landscape tech must still appear in admin_summary")
    # The luis hide must NOT surface — assert via the authoritative
    # users-collection scan so we're not fooled by a name collision.
    hidden_user_ids = [
        u["id"] for u in _db.users.find(
            {"tenant_id": tid, "email": "luis@aquaterra.com"},
            {"_id": 0, "id": 1},
        )
    ]
    assert len(hidden_user_ids) == 1, (
        "pre-flight: luis hide-list seed must land in the users collection")
    for uid in hidden_user_ids:
        assert uid not in returned_ids, (
            f"hide-list user {uid} leaked into admin_summary.techs")
    # Belt-and-suspenders.
    assert "luis@aquaterra.com" not in returned_emails


# TC · ruling-reversal · Phase 31 demo-noise suppression lifted per
# TC Feb-2026 — the carlos-hidden-even-with-punches thesis is now
# obsolete. The replacement thesis
# ("carlos surfaces when punches exist") lives in the new
# ``test_tc_admin_roster_dept_fallback.py`` suite. Kept as .skip
# so readers see the retired contract boundary explicitly.
@pytest.mark.skip(reason="TC · ruling-reversal · Phase 31 demo-noise suppression lifted per TC Feb-2026")
def test_phase31_hide_emails_do_not_appear_even_with_punches(ctx):
    """A hide-listed email with real punches on the current week must
    STILL be absent from the response. Guards against a regression
    where someone adds a punch-based filter upstream and forgets the
    user-level ``$nin``."""
    tid = ctx["tid"]
    carlos = _seed_user_with_email(tid, "carlos@aquaterra.com")
    monday, sunday = _this_week()
    t0 = datetime.combine(
        monday, datetime.min.time(), timezone.utc,
    ) + timedelta(days=1, hours=9)
    _seed_punch(tid, carlos["id"], punch_type="in", ts_utc=t0)
    _seed_punch(tid, carlos["id"], punch_type="out",
                 ts_utc=t0 + timedelta(hours=2))
    r = requests.get(
        f"{API}/timeclock/admin-summary?start={monday.isoformat()}"
        f"&end={sunday.isoformat()}",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert carlos["id"] not in returned_ids
