"""TC · C1 (Feb-2026) — unified read across ``timeclock_punches`` +
``time_entries``.

Cashes in ``memory/TD-landscape-time-clock-unify-reads.md``: the four
``/api/timeclock/*`` read handlers (``admin-summary``, ``mine-today``,
``mine-summary``, ``mine-status``) must now return events from BOTH
collections, normalized to the same flat event shape so the FE
``pairPunches.js`` + the backend ``_sum_shifts`` stay byte-stable.

Harness mirrors ``test_timeclock_admin_summary.py``: direct Mongo seed +
signed JWTs, live-curl against ``localhost:8001``.
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
    email = f"{uid}@tcur.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"TCUR {role} {uid[-4:]}", "email": email,
        "department": department,
    })
    return {
        "id": uid, "email": email, "role": role,
        "department": department, "tenant_id": tenant_id,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_tc_punch(tenant_id, user_id, *, punch_type, ts_utc,
                     lat=33.5, lng=-112.1, source="web", job_id=None):
    """Seed into ``timeclock_punches`` (the page + mobile write path)."""
    pid = f"p-{uuid.uuid4().hex[:10]}"
    _db.timeclock_punches.insert_one({
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": punch_type,
        "timestamp": ts_utc.isoformat(),
        "lat": lat, "lng": lng, "accuracy_m": 10.0,
        "source": source, "geo_denied": False, "job_id": job_id,
    })
    return pid


def _seed_te_shift(tenant_id, user_id, *, clock_in, clock_out=None,
                    in_lat=33.5, in_lng=-112.1,
                    out_lat=33.5, out_lng=-112.1, job_id=None):
    """Seed into ``time_entries`` (the widget + per-job write path)."""
    eid = f"e-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": eid, "tenant_id": tenant_id, "user_id": user_id,
        "user_name": f"TCUR tech {user_id[-4:]}",
        "job_id": job_id, "job_title": "General work", "customer_id": None,
        "clock_in_at": clock_in.isoformat(),
        "clock_out_at": clock_out.isoformat() if clock_out else None,
        "clock_in_geo": {"lat": in_lat, "lng": in_lng, "accuracy": 10.0},
        "clock_out_geo": ({"lat": out_lat, "lng": out_lng}
                            if clock_out else None),
        "out_of_geofence": False, "photo_url": None, "breaks": [],
        "duration_minutes": (
            int((clock_out - clock_in).total_seconds() / 60)
            if clock_out else 0
        ),
        "mileage_miles": 0, "status": "closed" if clock_out else "open",
        "notes": "", "created_at": clock_in.isoformat(),
    }
    _db.time_entries.insert_one(doc)
    return eid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"tcur-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"TCUR {tid}", "slug": f"tcur-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    admin = _seed_user(tid, "admin")
    yield {"tid": tid, "admin": admin}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.time_entries.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


def _this_week():
    today_d = date.today()
    monday = today_d - timedelta(days=today_d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _today_at(hour, minute=0):
    return datetime.now(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )


# ───────────────────────────────────────────────────────────────────
# admin-summary — the operator-reported "No punches yet" bug surface
# ───────────────────────────────────────────────────────────────────
def test_widget_only_day_visible_on_admin_summary(ctx):
    """Widget writes land in ``time_entries`` only. Pre-TC: invisible on
    ``admin-summary`` (reads only ``timeclock_punches``). Post-TC:
    surfaces as paired IN+OUT events."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    in_at = _today_at(9, 0)
    out_at = _today_at(17, 30)
    _seed_te_shift(tid, tech["id"], clock_in=in_at, clock_out=out_at)
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    techs = {t["user_id"]: t for t in r.json()["techs"]}
    row = techs[tech["id"]]
    types = [p["punch_type"] for p in row["punches"]]
    assert types == ["in", "out"], row["punches"]
    assert all(p.get("source") == "time_entries" for p in row["punches"])
    expected_sec = int((out_at - in_at).total_seconds())
    assert row["total_seconds"] == expected_sec
    assert row["status"] == "out"


def test_page_only_day_visible_on_admin_summary(ctx):
    """Full-page web punches land in ``timeclock_punches``. Pre-TC
    already visible; the test locks that we didn't regress it."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    in_at = _today_at(8, 15)
    out_at = _today_at(16, 45)
    _seed_tc_punch(tid, tech["id"], punch_type="in",
                     ts_utc=in_at, source="web")
    _seed_tc_punch(tid, tech["id"], punch_type="out",
                     ts_utc=out_at, source="web")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    row = {t["user_id"]: t for t in r.json()["techs"]}[tech["id"]]
    types = [p["punch_type"] for p in row["punches"]]
    assert types == ["in", "out"], row["punches"]
    sources = {p.get("source") for p in row["punches"]}
    # Source tag preserves the pre-existing "web" / "mobile" value
    # from the row rather than overwriting with the collection tag.
    assert "web" in sources
    assert row["status"] == "out"


def test_mobile_only_day_visible_on_admin_summary(ctx):
    """Mobile writes land in ``timeclock_punches`` with source="mobile"."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    in_at = _today_at(7, 0)
    out_at = _today_at(15, 0)
    _seed_tc_punch(tid, tech["id"], punch_type="in",
                     ts_utc=in_at, source="mobile")
    _seed_tc_punch(tid, tech["id"], punch_type="out",
                     ts_utc=out_at, source="mobile")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    row = {t["user_id"]: t for t in r.json()["techs"]}[tech["id"]]
    sources = {p.get("source") for p in row["punches"]}
    assert "mobile" in sources
    assert row["total_seconds"] == int((out_at - in_at).total_seconds())


def test_mixed_source_day_pairs_correctly(ctx):
    """Tech clocks IN via widget (``time_entries``) at 09:00 and
    clocks OUT via page (``timeclock_punches``) at 17:00 — the
    merged event stream must pair across sources."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    in_at = _today_at(9, 0)
    out_at = _today_at(17, 0)
    # Widget IN (open shift in time_entries — clock_out_at None).
    _seed_te_shift(tid, tech["id"], clock_in=in_at, clock_out=None)
    # Page OUT (orphan-looking in timeclock_punches alone — but the
    # unified stream pairs it with the widget IN).
    _seed_tc_punch(tid, tech["id"], punch_type="out",
                     ts_utc=out_at, source="web")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    row = {t["user_id"]: t for t in r.json()["techs"]}[tech["id"]]
    types = [p["punch_type"] for p in row["punches"]]
    assert types == ["in", "out"]
    # The widget IN's time_entries source + the page OUT's web source
    # both survive the merge.
    sources = [p.get("source") for p in row["punches"]]
    assert sources[0] == "time_entries"
    assert sources[1] == "web"
    # Pairing holds — ``_sum_shifts`` matches the IN to the OUT.
    assert row["total_seconds"] == int((out_at - in_at).total_seconds())


def test_tenant_isolation_across_both_collections(ctx):
    """A punch in a different tenant must not leak into this
    tenant's admin-summary, in either collection."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    other_tid = f"tcur-other-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": other_tid, "name": "OTHER",
                             "slug": other_tid, "active": True})
    other_uid = f"other-{uuid.uuid4().hex[:6]}"
    _db.users.insert_one({"id": other_uid, "tenant_id": other_tid,
                          "role": "technician",
                          "department": "landscaping",
                          "email": f"{other_uid}@tcur-other.test",
                          "name": "OTHER tech"})
    # Seed one punch per source in the other tenant.
    _seed_tc_punch(other_tid, other_uid, punch_type="in",
                     ts_utc=_today_at(9, 0))
    _seed_te_shift(other_tid, other_uid, clock_in=_today_at(10, 0),
                     clock_out=_today_at(16, 0))
    try:
        # Seed one time_entries shift on the primary tenant so the
        # response has a non-empty baseline to compare against.
        _seed_te_shift(tid, tech["id"], clock_in=_today_at(8, 0),
                         clock_out=_today_at(12, 0))
        r = requests.get(
            f"{API}/timeclock/admin-summary",
            headers=_auth(ctx["admin"]["token"]), timeout=20,
        )
        assert r.status_code == 200, r.text
        tech_ids = [t["user_id"] for t in r.json()["techs"]]
        assert other_uid not in tech_ids
    finally:
        _db.timeclock_punches.delete_many({"tenant_id": other_tid})
        _db.time_entries.delete_many({"tenant_id": other_tid})
        _db.users.delete_many({"tenant_id": other_tid})
        _db.tenants.delete_many({"id": other_tid})


def test_orphan_out_in_timeclock_punches_logged_and_dropped(ctx):
    """An OUT event with no preceding IN (data-quality issue) must
    not crash the handler and must not contribute to total_seconds.
    Match the FE ``pairPunches.js:84`` precedent."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    # ONLY an OUT — no matching IN.
    _seed_tc_punch(tid, tech["id"], punch_type="out",
                     ts_utc=_today_at(17, 0), source="web")
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    row = {t["user_id"]: t for t in r.json()["techs"]}[tech["id"]]
    # OUT still appears in the flat punches list (admin can see the
    # data-quality issue) but doesn't close any shift.
    assert any(p["punch_type"] == "out" for p in row["punches"])
    assert row["total_seconds"] == 0


# ───────────────────────────────────────────────────────────────────
# mine-today / mine-status — open-shift detection across both sources
# ───────────────────────────────────────────────────────────────────
def test_mine_today_open_shift_from_time_entries(ctx):
    """A widget-opened shift (open in ``time_entries``, no
    ``clock_out_at``) must surface as ``clocked_in: true`` on
    ``/mine-today``."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    _seed_te_shift(tid, tech["id"], clock_in=_today_at(8, 0),
                     clock_out=None)  # open shift
    r = requests.get(
        f"{API}/timeclock/mine-today",
        headers=_auth(tech["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["clocked_in"] is True
    assert len(data["punches"]) >= 1
    assert data["punches"][0]["punch_type"] == "in"


def test_mine_status_open_shift_from_time_entries(ctx):
    """Mirror of the above for the lightweight ``/mine-status`` probe."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    _seed_te_shift(tid, tech["id"], clock_in=_today_at(9, 30),
                     clock_out=None)
    r = requests.get(
        f"{API}/timeclock/mine-status",
        headers=_auth(tech["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["clocked_in"] is True
    assert data["punch_count"] >= 1


def test_mine_summary_unions_both_collections(ctx):
    """A tech with one widget shift + one page shift on the same day
    sees total_seconds == both durations summed."""
    tid = ctx["tid"]
    tech = _seed_user(tid, "technician", department="landscaping")
    # Widget shift 08:00-10:00 (2 h)
    _seed_te_shift(tid, tech["id"], clock_in=_today_at(8, 0),
                     clock_out=_today_at(10, 0))
    # Page shift 13:00-15:30 (2.5 h)
    _seed_tc_punch(tid, tech["id"], punch_type="in",
                     ts_utc=_today_at(13, 0), source="web")
    _seed_tc_punch(tid, tech["id"], punch_type="out",
                     ts_utc=_today_at(15, 30), source="web")
    monday, sunday = _this_week()
    r = requests.get(
        f"{API}/timeclock/mine-summary"
        f"?start={monday.isoformat()}&end={sunday.isoformat()}",
        headers=_auth(tech["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # 2 h + 2.5 h = 16200 s.
    assert data["total_seconds"] == 16200, data
