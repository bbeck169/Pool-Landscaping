"""Phase P13 · Feb-2026 · P0 HOTFIX — Schedule timezone correctness.

Locks in the 4 backend acceptance points:

  1. A job whose ``scheduled_date`` string was mis-stamped in UTC
     (Phoenix-8pm-today → UTC-tomorrow) but whose ``scheduled_start``
     datetime IS the correct Phoenix-8pm today, must be returned when
     the client queries ``GET /api/jobs?scheduled_date=<today_in_phoenix>``.
  2. A job whose ``scheduled_date`` matches the requested day but has
     no ``scheduled_start`` still returns (regression net — the pure
     string branch keeps working).
  3. A job whose ``scheduled_start`` is 23:00 Phoenix on the PREVIOUS
     Phoenix day (so 06:00 UTC on today's date) is NOT returned when
     querying for today's Phoenix date.
  4. A tenant with NO ``timezone`` field defaults to Phoenix and
     returns the same union as an explicit-Phoenix tenant.

No freezegun involvement — the backend endpoint takes explicit
``scheduled_date`` / ``start`` / ``end`` params; there's no
``datetime.now`` today-derivation to freeze. The frontend is what
computes "today" and passes it in — we exercise the backend's
tenant-local-day → UTC-window union directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")

PHOENIX = ZoneInfo("America/Phoenix")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture
def _cleanup(dbc):
    bag: dict = {"jobs": [], "tenant_backup": None}
    yield bag
    for jid in bag["jobs"]:
        dbc.jobs.delete_one({"id": jid})
    if bag["tenant_backup"] is not None:
        tid, prev_tz = bag["tenant_backup"]
        if prev_tz is None:
            dbc.tenants.update_one(
                {"id": tid}, {"$unset": {"timezone": ""}},
            )
        else:
            dbc.tenants.update_one(
                {"id": tid}, {"$set": {"timezone": prev_tz}},
            )


def _phoenix_iso(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> str:
    """Return the UTC ISO string for a wall-clock Phoenix time.

    Mirrors what a well-behaved write path stamps into
    ``scheduled_start`` — an ISO string in UTC. Phoenix has NO DST
    so this is a plain -07:00 offset year-round.
    """
    local = datetime(y, mo, d, h, mi, 0, tzinfo=PHOENIX)
    return local.astimezone(timezone.utc).isoformat()


def _pick_id(rows, jid) -> bool:
    return any((r.get("id") == jid) for r in rows)


# ── 1) Phoenix-late-evening job with UTC-mis-stamped scheduled_date ──
def test_p13_evening_phoenix_job_returned_for_todays_phoenix_date(
    admin_h, dbc, _cleanup,
):
    """The canonical production regression — a job at 20:00 Phoenix
    'today' whose ``scheduled_date`` string was mis-stamped in UTC
    (== tomorrow's date). Must appear under today's Phoenix date
    filter."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    # Ensure the tenant is on Phoenix so the backend fold-in
    # computes the right UTC window regardless of prior seed state.
    prev = dbc.tenants.find_one({"id": tenant_id}, {"_id": 0, "timezone": 1})
    _cleanup["tenant_backup"] = (tenant_id, (prev or {}).get("timezone"))
    dbc.tenants.update_one({"id": tenant_id},
                            {"$set": {"timezone": "America/Phoenix"}})

    # 20:00 Phoenix on 2025-11-14 == 2025-11-15T03:00:00+00:00 in UTC.
    scheduled_start_utc = _phoenix_iso(2025, 11, 14, 20, 0)
    # The pre-P13 write bug stamped ``scheduled_date`` from the UTC
    # datetime — flipping to the NEXT day.
    mis_stamped_date = "2025-11-15"

    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p13 · phoenix-20:00 with utc-mis-stamped date",
        "customer_id": "p13-fake", "status": "scheduled",
        "scheduled_start": scheduled_start_utc,
        "scheduled_date": mis_stamped_date,
    })
    _cleanup["jobs"].append(jid)

    r = requests.get(
        f"{API}/jobs?scheduled_date=2025-11-14",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    rows = r.json()
    assert _pick_id(rows, jid), (
        "P13 regression: 20:00 Phoenix job with UTC-mis-stamped "
        "scheduled_date not returned under today's Phoenix date filter"
    )


# ── 2) Fast-path regression net — string branch still works ─────────
def test_p13_correctly_stamped_scheduled_date_still_returned(
    admin_h, dbc, _cleanup,
):
    """A job with a correct ``scheduled_date`` (matches the requested
    day) but NO ``scheduled_start`` still comes back — the union
    doesn't drop the fast string branch."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]

    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p13 · string-only, no scheduled_start",
        "status": "scheduled",
        "scheduled_date": "2025-11-14",
    })
    _cleanup["jobs"].append(jid)

    r = requests.get(
        f"{API}/jobs?scheduled_date=2025-11-14",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    assert _pick_id(r.json(), jid)


# ── 3) Previous-day Phoenix job must NOT bleed into today ───────────
def test_p13_previous_phoenix_day_job_not_in_todays_result(
    admin_h, dbc, _cleanup,
):
    """A job at 23:00 Phoenix on 2025-11-13 (= 06:00 UTC on
    2025-11-14) MUST NOT be returned when the client asks for the
    2025-11-14 Phoenix day. Would prove a mis-tightened union that
    accidentally includes UTC-day boundaries instead of Phoenix-day."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    prev = dbc.tenants.find_one({"id": tenant_id}, {"_id": 0, "timezone": 1})
    _cleanup["tenant_backup"] = (tenant_id, (prev or {}).get("timezone"))
    dbc.tenants.update_one({"id": tenant_id},
                            {"$set": {"timezone": "America/Phoenix"}})

    scheduled_start_utc = _phoenix_iso(2025, 11, 13, 23, 0)   # 06:00 UTC 2025-11-14
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p13 · 23:00 phoenix yesterday, 06:00 UTC today",
        "status": "scheduled",
        # Deliberately DON'T set scheduled_date to 2025-11-14 — we
        # want the ONLY reason it might match to be a mis-scoped
        # scheduled_start window. If the test flakes because
        # scheduled_date was left None, that's fine — the union
        # can only hit via scheduled_start; verify it's out-of-window.
        "scheduled_date": "2025-11-13",
        "scheduled_start": scheduled_start_utc,
    })
    _cleanup["jobs"].append(jid)

    r = requests.get(
        f"{API}/jobs?scheduled_date=2025-11-14",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    assert not _pick_id(r.json(), jid), (
        "P13 over-tighten: a 23:00-phoenix-YESTERDAY job leaked into "
        "TODAY's Phoenix result via a UTC-day-boundary mis-scope"
    )


# ── 4) Tenant without a ``timezone`` field defaults to Phoenix ──────
def test_p13_missing_tenant_timezone_defaults_to_phoenix(
    admin_h, dbc, _cleanup,
):
    """Fallback contract — a tenant with NO ``timezone`` field
    inherits ``America/Phoenix`` semantics and returns the same
    union as an explicit-Phoenix tenant."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    prev = dbc.tenants.find_one({"id": tenant_id}, {"_id": 0, "timezone": 1})
    _cleanup["tenant_backup"] = (tenant_id, (prev or {}).get("timezone"))
    # Strip the field entirely for the duration of this test.
    dbc.tenants.update_one({"id": tenant_id},
                            {"$unset": {"timezone": ""}})

    scheduled_start_utc = _phoenix_iso(2025, 11, 14, 20, 0)
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p13 · tz-less tenant · phoenix-20:00 fallback",
        "status": "scheduled",
        "scheduled_start": scheduled_start_utc,
        "scheduled_date": "2025-11-15",   # UTC-mis-stamped
    })
    _cleanup["jobs"].append(jid)

    r = requests.get(
        f"{API}/jobs?scheduled_date=2025-11-14",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    assert _pick_id(r.json(), jid), (
        "P13 fallback broken: a tenant with no ``timezone`` field did "
        "NOT default to America/Phoenix — the mis-stamped-date job "
        "wasn't returned under today's Phoenix filter"
    )
