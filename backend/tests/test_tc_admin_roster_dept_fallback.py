"""TC · C2 (Feb-2026) — admin-summary roster uses the punch-gate's
two-source department resolution + hide-list cleanup.

Mirrors the harness shape of ``test_timeclock_admin_summary.py`` so
seed + JWT + live-curl mechanics stay consistent.

Four locked cases:
  1. Tech with ``users.department=None`` + ``technicians.department=
     "landscaping"`` surfaces in the admin roster.
  2. Tech with no dept in EITHER source does NOT surface.
  3. Carlos (now un-hidden post-TC ruling-reversal) surfaces when
     punches exist on the window.
  4. Luis (still-hidden) does NOT surface.
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


def _seed_user(tenant_id, role, *, email=None,
                users_department=None, technician_id=None):
    """Seed a user row with (optionally) empty ``users.department`` so
    the C2 fallback is exercised. ``technician_id`` is the FK that
    links back to ``db.technicians`` the same way the punch gate's
    resolver walks it (see ``_resolve_tech_department`` L58-91).
    """
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = email or f"{uid}@tcrdf.test"
    doc = {
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"TCRDF {role} {uid[-4:]}", "email": email,
        "department": users_department,
    }
    if technician_id:
        doc["technician_id"] = technician_id
    _db.users.insert_one(doc)
    return {
        "id": uid, "email": email, "role": role,
        "department": users_department,
        "technician_id": technician_id,
        "tenant_id": tenant_id,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_technician_row(tenant_id, *, department=None):
    """Seed a ``db.technicians`` row keyed by its own ``id`` so a
    ``users.technician_id`` FK can link to it."""
    tid = f"tech-{uuid.uuid4().hex[:8]}"
    _db.technicians.insert_one({
        "id": tid, "tenant_id": tenant_id,
        "name": f"TCRDF tech-row {tid[-4:]}",
        "department": department,
        "active": True,
    })
    return tid


def _seed_punch(tenant_id, user_id, *,
                punch_type, ts_utc,
                lat=33.5, lng=-112.1):
    pid = f"p-{uuid.uuid4().hex[:10]}"
    _db.timeclock_punches.insert_one({
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": punch_type,
        "timestamp": ts_utc.isoformat(),
        "lat": lat, "lng": lng, "accuracy_m": 10.0,
        "source": "web", "geo_denied": False, "job_id": None,
    })
    return pid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"tcrdf-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"TCRDF {tid}", "slug": f"tcrdf-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    admin = _seed_user(tid, "admin")
    yield {"tid": tid, "admin": admin}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.technicians.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


def _this_week():
    today_d = date.today()
    monday = today_d - timedelta(days=today_d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ───────────────────────────────────────────────────────────────────
# C2 · dept resolution via technicians fallback
# ───────────────────────────────────────────────────────────────────
def test_tech_with_dept_only_in_technicians_surfaces(ctx):
    """Pre-TC: tech with ``users.department=None`` AND
    ``technicians.department="landscaping"`` was silently dropped
    from the admin roster even though the punch gate let them in.
    Post-C2: the roster mirrors the punch gate's two-source
    resolution and the tech surfaces.
    """
    tid = ctx["tid"]
    tech_row_id = _seed_technician_row(tid, department="landscaping")
    tech = _seed_user(
        tid, "technician",
        users_department=None,       # pre-TC drop-out trigger
        technician_id=tech_row_id,   # FK that enables fallback
    )
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert tech["id"] in returned_ids, (
        "tech with users.department=None + technicians.department="
        "landscaping must surface via the C2 fallback"
    )


def test_tech_with_no_dept_in_either_source_does_not_surface(ctx):
    """A tech with no landscape dept on EITHER source stays out of
    the roster. Guards against the fallback over-admitting pool /
    unassigned techs."""
    tid = ctx["tid"]
    tech_row_id = _seed_technician_row(tid, department=None)
    tech = _seed_user(
        tid, "technician",
        users_department=None,
        technician_id=tech_row_id,
    )
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert tech["id"] not in returned_ids, (
        "tech with no dept in either source must NOT surface"
    )


def test_tech_with_pool_dept_in_technicians_does_not_surface(ctx):
    """A tech whose ``technicians.department`` resolves to a NON-
    landscape value stays out of the roster even though they're a
    technician role. Belt-and-braces on the fallback filter."""
    tid = ctx["tid"]
    tech_row_id = _seed_technician_row(tid, department="pool")
    tech = _seed_user(
        tid, "technician",
        users_department=None,
        technician_id=tech_row_id,
    )
    r = requests.get(
        f"{API}/timeclock/admin-summary",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert tech["id"] not in returned_ids, (
        "tech with technicians.department=pool must NOT surface"
    )


# ───────────────────────────────────────────────────────────────────
# C2 · hide-list cleanup (carlos un-hidden; luis retained)
# ───────────────────────────────────────────────────────────────────
def test_carlos_unhidden_surfaces_when_punches_exist(ctx):
    """TC · C2 ruling-reversal of Phase 31 — ``carlos@aquaterra.com``
    is no longer in ``_AGGREGATION_HIDE_EMAILS`` so his real punches
    now flow through to the admin team-aggregation view."""
    tid = ctx["tid"]
    carlos = _seed_user(
        tid, "technician",
        email="carlos@aquaterra.com",
        users_department="landscaping",
    )
    monday, sunday = _this_week()
    t0 = datetime.combine(monday, datetime.min.time(), timezone.utc)
    t0 += timedelta(days=1, hours=9)
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
    assert carlos["id"] in returned_ids, (
        "carlos must surface post-TC ruling-reversal"
    )
    row = {t["user_id"]: t for t in r.json()["techs"]}[carlos["id"]]
    assert row["total_seconds"] == 2 * 3600, row


def test_luis_still_hidden(ctx):
    """TC · C2 retained ``luis@aquaterra.com`` in
    ``_AGGREGATION_HIDE_EMAILS`` — no code reference outside the
    hide list + its lock test, preserve-until-proven."""
    tid = ctx["tid"]
    luis = _seed_user(
        tid, "technician",
        email="luis@aquaterra.com",
        users_department="landscaping",
    )
    monday, sunday = _this_week()
    t0 = datetime.combine(monday, datetime.min.time(), timezone.utc)
    t0 += timedelta(days=1, hours=9)
    _seed_punch(tid, luis["id"], punch_type="in", ts_utc=t0)
    _seed_punch(tid, luis["id"], punch_type="out",
                 ts_utc=t0 + timedelta(hours=2))
    r = requests.get(
        f"{API}/timeclock/admin-summary?start={monday.isoformat()}"
        f"&end={sunday.isoformat()}",
        headers=_auth(ctx["admin"]["token"]), timeout=20,
    )
    assert r.status_code == 200, r.text
    returned_ids = {t["user_id"] for t in r.json()["techs"]}
    assert luis["id"] not in returned_ids, (
        "luis must stay hidden per C2 preserve-until-proven ruling"
    )
