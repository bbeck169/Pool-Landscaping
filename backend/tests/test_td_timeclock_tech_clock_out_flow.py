"""TD-timeclock-tech-clock-out-flow · Feb-2026.

Contract tests for the LandscapingClockWidget pivot from
``/api/timeclock/*`` (``timeclock_punches``) onto
``/api/workforce/*`` (``time_entries``).  See ticket brief for the
write/read mismatch rationale.

Scope
    * ``POST /api/workforce/clock-in`` with ``job_id`` omitted or
      ``null`` persists a ``time_entries`` row shaped exactly like
      a job-attached shift except ``assigned_job_id`` / ``job_id``
      stay ``None`` and ``job_title`` is ``"General work"``.
    * ``POST /api/workforce/clock-in`` while another open shift
      exists → 400 ``already have an open shift``.
    * ``POST /api/workforce/clock-out`` closes the open entry,
      computes a positive ``duration_minutes`` and flips
      ``status`` to ``submitted``.
    * ``GET /api/workforce/open-shift`` returns the open row
      wrapped in ``{"entry": {...}}`` when one exists; returns
      ``{"entry": null}`` when none.
    * Tenant isolation — tech on tenant A cannot see tenant B's
      open shift via ``/open-shift``.  Second tenant + tech are
      self-seeded inline (sync pymongo + self-minted JWT, mirrors
      the ``test_account_correction_parity`` CARAC pattern) so the
      security-sensitive assertion runs green on every env without
      depending on an upstream ``tech@sunbelt.com`` seed.
    * ``/auth/me`` projects ``effective_department`` +
      ``show_time_clock`` for landscape techs (smoke so the FE
      widget visibility contract stays locked).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")

JWT_SECRET = (
    _BE_ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _mint_jwt(uid: str, email: str, tid: str, role: str = "technician") -> str:
    """Self-mint a JWT for a self-seeded user, bypassing /auth/login.

    Follows the ``test_account_correction_parity`` CARAC pattern:
    the token is signed with the same ``JWT_SECRET`` the server
    verifies against, so ``get_current_user`` + ``get_current_tenant``
    treat it as a real session.  Lets this test file self-seed a
    second-tenant landscape tech instead of depending on a
    ``tech@sunbelt.com`` seed that may not exist in every env.
    """
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tech_h():
    # ``landscaper@aquaterra.com`` is a seeded landscape tech
    # (``department = "landscaping"``) — matches the widget's
    # visibility contract.
    return {"Authorization": f"Bearer {_login('landscaper@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tenant_b(db):
    """Self-seed a second tenant + its own landscape tech so the
    tenant-isolation assertion runs in every environment.

    Yields a dict ``{tenant_id, user_id, headers}``.  Tears down at
    module scope to leave the DB in its original state.
    """
    tid = f"td-tc-tenantb-{uuid.uuid4().hex[:8]}"
    uid = f"u-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@td-timeclock-isolation.test"
    db.tenants.insert_one({
        "id": tid, "name": "TD-timeclock isolation tenant",
        "slug": tid, "active": True,
    })
    db.users.insert_one({
        "id": uid, "tenant_id": tid, "role": "technician",
        "name": "Isolation Tech", "email": email,
        "department": "landscaping", "active": True,
    })
    token = _mint_jwt(uid, email, tid, role="technician")
    yield {
        "tenant_id": tid, "user_id": uid, "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    # Teardown — remove everything we created so the test is
    # idempotent across reruns and leaves no residue.
    db.time_entries.delete_many({"tenant_id": tid})
    db.users.delete_many({"id": uid})
    db.tenants.delete_many({"id": tid})


@pytest.fixture(autouse=True)
def _cleanup_open(db):
    # Clean the landscaper's open shift before + after each test
    # so cases don't bleed into each other.  We ONLY touch open
    # (clock_out_at None) rows; completed historical rows stay.
    uid_rows = list(db.users.find(
        {"email": "landscaper@aquaterra.com"},
        {"id": 1, "_id": 0},
    ))
    uids = [r["id"] for r in uid_rows]
    if uids:
        db.time_entries.delete_many({"user_id": {"$in": uids},
                                     "clock_out_at": None})
    yield
    if uids:
        db.time_entries.delete_many({"user_id": {"$in": uids},
                                     "clock_out_at": None})


# ─── Clock-in with no job (bare "General work") ────────────────────
def test_clock_in_with_null_job_id_creates_general_work_entry(tech_h, db):
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={"job_id": None,
                                            "lat": 33.70, "lng": -112.22},
                      timeout=20)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["job_id"] is None
    assert row["job_title"] == "General work"
    assert row["customer_id"] is None
    assert row["clock_in_at"]
    assert row["clock_out_at"] is None
    assert row["status"] == "open"
    assert row["out_of_geofence"] is False  # no job to geofence against

    # Mongo row matches
    doc = db.time_entries.find_one({"id": row["id"]}, {"_id": 0})
    assert doc is not None
    assert doc["job_title"] == "General work"
    assert doc["job_id"] is None


def test_clock_in_body_without_job_id_key_at_all_is_accepted(tech_h):
    # Mobile clients that omit the key entirely (not just null) must
    # also succeed — Pydantic default handles this but we lock the
    # contract so it can't regress.
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={"lat": 33.70, "lng": -112.22},
                      timeout=20)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["job_id"] is None
    assert row["job_title"] == "General work"


def test_clock_in_without_lat_lng_is_accepted(tech_h):
    # Geo may be denied; the widget still submits a null-geo punch.
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={}, timeout=20)
    assert r.status_code == 200, r.text


# ─── Double-clock-in → 400 ─────────────────────────────────────────
def test_double_clock_in_returns_400(tech_h):
    r1 = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert r2.status_code == 400
    assert "open shift" in r2.text.lower()


# ─── open-shift probe ─────────────────────────────────────────────
def test_open_shift_returns_entry_when_clocked_in(tech_h):
    requests.post(f"{API}/workforce/clock-in",
                  headers=tech_h, json={}, timeout=20)
    r = requests.get(f"{API}/workforce/open-shift",
                     headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"] is not None
    assert body["entry"]["clock_out_at"] is None
    assert body["entry"]["job_title"] == "General work"


def test_open_shift_returns_null_when_not_clocked_in(tech_h):
    r = requests.get(f"{API}/workforce/open-shift",
                     headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"entry": None}


# ─── Clock-out closes entry + computes duration ───────────────────
def test_clock_out_closes_entry_and_computes_duration(tech_h, db):
    ci = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert ci.status_code == 200
    entry_id = ci.json()["id"]

    # Rewind clock_in_at by 90 minutes so duration > 0 even when
    # the test runs in <1s wall-clock.
    db.time_entries.update_one(
        {"id": entry_id},
        {"$set": {"clock_in_at": _iso_minutes_ago(90)}},
    )
    co = requests.post(f"{API}/workforce/clock-out",
                       headers=tech_h,
                       json={"entry_id": entry_id,
                             "lat": 33.70, "lng": -112.22},
                       timeout=20)
    assert co.status_code == 200, co.text
    row = co.json()
    assert row["clock_out_at"]
    assert row["duration_minutes"] >= 89.0, row
    assert row["status"] == "submitted"

    # And open-shift probe now returns null.
    probe = requests.get(f"{API}/workforce/open-shift",
                         headers=tech_h, timeout=20)
    assert probe.json() == {"entry": None}


def _iso_minutes_ago(n: int) -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


# ─── Tenant isolation ─────────────────────────────────────────────
def test_open_shift_is_tenant_scoped(tech_h, tenant_b, db):
    """A tech on tenant B must NOT see tenant A's open shift via
    ``/workforce/open-shift``, and vice versa.  Second tenant +
    tech are self-seeded inline so the assertion runs green on
    every env without depending on an upstream sunbelt seed.
    """
    # Aquaterra landscaper (tenant A) clocks in.
    ci_a = requests.post(f"{API}/workforce/clock-in",
                         headers=tech_h, json={}, timeout=20)
    assert ci_a.status_code == 200
    a_entry_id = ci_a.json()["id"]

    # Tenant B tech probes /open-shift and must see nothing — their
    # own open shift list is empty.
    r_b = requests.get(f"{API}/workforce/open-shift",
                       headers=tenant_b["headers"], timeout=20)
    assert r_b.status_code == 200
    assert r_b.json() == {"entry": None}

    # Reverse leak probe — tenant B's own clock-in must land in
    # tenant B's bucket and MUST NOT surface to tenant A.
    ci_b = requests.post(f"{API}/workforce/clock-in",
                         headers=tenant_b["headers"], json={},
                         timeout=20)
    assert ci_b.status_code == 200, ci_b.text
    b_entry_id = ci_b.json()["id"]
    assert b_entry_id != a_entry_id

    # Tenant A's open-shift probe still returns tenant A's row,
    # not tenant B's.
    r_a = requests.get(f"{API}/workforce/open-shift",
                       headers=tech_h, timeout=20)
    assert r_a.status_code == 200
    a_entry = r_a.json()["entry"]
    assert a_entry is not None
    assert a_entry["id"] == a_entry_id
    assert a_entry["tenant_id"] != tenant_b["tenant_id"]

    # DB-level receipt — tenant B's row carries tenant B's id so a
    # future denormalisation regression surfaces here too.
    b_doc = db.time_entries.find_one({"id": b_entry_id}, {"_id": 0})
    assert b_doc is not None
    assert b_doc["tenant_id"] == tenant_b["tenant_id"]
    assert b_doc["user_id"] == tenant_b["user_id"]


# ─── /auth/me projects department (visibility smoke) ──────────────
def test_auth_me_projects_effective_department_and_show_time_clock(tech_h):
    r = requests.get(f"{API}/auth/me", headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    # These two fields power the widget's visibility helper.
    assert "effective_department" in body
    assert "show_time_clock" in body
    assert body["show_time_clock"] is True
    assert (body["effective_department"] or "").lower() in (
        "landscaping", "landscape_tech", "landscaper", "both",
    )
