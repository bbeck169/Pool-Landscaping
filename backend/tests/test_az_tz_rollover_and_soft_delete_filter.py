"""Feb-2026 — ``timeclock_landscaping.py`` AZ-TZ UTC-rollover +
soft-delete fixes.

Two bugs resolved by one commit:

  1. **UTC-rollover on POST /timeclock/punch**.  Pre-fix the open-
     shift lookup scanned a TODAY-only UTC window, so an AZ-5 pm
     IN (= 00:00 UTC day N+1) could not be clocked OUT the next
     morning (also day N+1 UTC) because the IN was in the
     "yesterday" UTC bucket.  POST ``/punch`` would 409 with
     ``no_open_shift`` even though ``/mine-status`` (2-day scan)
     correctly reported ``clocked_in: true``.

  2. **Soft-delete leak across every reader**.  Pre-fix no
     reader filtered ``deleted_at``.  A tombstoned punch would
     still surface on ``/mine-status`` / ``/mine-today`` /
     ``/mine-summary`` / ``/admin-summary`` AND be picked up by
     the open-shift resolver inside POST ``/punch``.

Fix: POST ``/punch`` now resolves the open shift via the SAME
``_unified_events`` 2-day window ``/mine-status`` already uses
(DRY — same helper, no duplicated date math).  ``_unified_events``
carries a ``deleted_at: None`` filter (matches both missing-field
and explicit null — standard Mongo semantics) so every unified
reader AND the open-shift lookup exclude tombstones uniformly.

Harness mirrors ``test_tc_timeclock_unified_read.py`` + the
Ticket-2 schedule-mine-day suite from the prior sprint — direct
Mongo seed + signed JWTs, live-curl against ``localhost:8001``.
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


def _seed_landscape_tech(tenant_id):
    uid = f"ltech-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@az-fix.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": f"AZ-fix {uid[-4:]}", "email": email,
        "department": "landscaping",
        "technician_id": uid,
    })
    return {
        "id": uid, "email": email,
        "token": _tok(uid, email, "technician", tenant_id),
    }


def _seed_punch(tenant_id, user_id, *, punch_type, ts_utc,
                 deleted_at=None, job_id=None):
    pid = f"p-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": punch_type,
        "timestamp": ts_utc.isoformat(),
        "lat": 33.5, "lng": -112.1, "accuracy_m": 10.0,
        "source": "web", "geo_denied": False, "job_id": job_id,
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    _db.timeclock_punches.insert_one(doc)
    return pid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctx():
    tid = f"az-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"AZ-fix {tid}", "slug": f"az-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield {"tid": tid}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.time_entries.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


# ─────────────────────────────────────────────────────────────────
# Part 2 — AZ-TZ UTC-rollover: POST /punch finds yesterday's open IN
# ─────────────────────────────────────────────────────────────────
def test_punch_out_closes_shift_opened_yesterday_utc(ctx):
    """AZ-TZ scenario — tech punches IN at 5 pm AZ-local = 00:00
    UTC today, which was yesterday-UTC when the punch landed.
    Pre-fix the open-shift lookup scanned TODAY-only UTC and
    missed the IN; POST ``/punch`` with ``out`` 409'd on
    ``no_open_shift``.  Post-fix the 2-day unified window picks
    up yesterday's IN and the OUT closes it cleanly."""
    tech = _seed_landscape_tech(ctx["tid"])
    # Seed an IN punch that lands 1 hour before NOW's UTC-today
    # boundary — guaranteed to be in "yesterday" UTC relative to
    # a NOW within the first 23 hours of today UTC.
    now = datetime.now(timezone.utc)
    today_utc_start = datetime(
        now.year, now.month, now.day, tzinfo=timezone.utc,
    )
    in_ts = today_utc_start - timedelta(hours=1)  # yesterday UTC
    _seed_punch(ctx["tid"], tech["id"], punch_type="in", ts_utc=in_ts)

    # POST /punch with "out" — must find the yesterday-UTC IN.
    r = requests.post(
        f"{API}/timeclock/punch",
        headers=_auth(tech["token"]),
        json={
            "punch_type": "out", "lat": 33.5, "lng": -112.1,
            "accuracy_m": 10.0, "source": "web", "geo_denied": False,
        }, timeout=15,
    )
    assert r.status_code == 200, (
        f"POST /punch 'out' must close the yesterday-UTC IN; "
        f"got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    assert body["punch_type"] == "out"

    # /mine-today (2-day window) reflects the closed shift.
    r2 = requests.get(f"{API}/timeclock/mine-today",
                       headers=_auth(tech["token"]), timeout=15)
    assert r2.status_code == 200
    assert r2.json()["clocked_in"] is False, (
        f"/mine-today should reflect the closed shift; "
        f"got {r2.json()!r}"
    )


def test_punch_in_blocked_if_yesterday_shift_still_open(ctx):
    """Operator-named ``already_clocked_in`` guard also widens to
    the 2-day window.  A tech with an unclosed yesterday-UTC IN
    cannot double-punch IN today — must be ``409 already_clocked
    _in``."""
    tech = _seed_landscape_tech(ctx["tid"])
    now = datetime.now(timezone.utc)
    today_utc_start = datetime(
        now.year, now.month, now.day, tzinfo=timezone.utc,
    )
    _seed_punch(ctx["tid"], tech["id"], punch_type="in",
                ts_utc=today_utc_start - timedelta(hours=2))

    r = requests.post(
        f"{API}/timeclock/punch",
        headers=_auth(tech["token"]),
        json={"punch_type": "in", "lat": 33.5, "lng": -112.1,
              "accuracy_m": 10.0, "source": "web",
              "geo_denied": False},
        timeout=15,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_clocked_in"


# ─────────────────────────────────────────────────────────────────
# Part 1 — Soft-delete exclusion across every reader + POST /punch
# ─────────────────────────────────────────────────────────────────
def test_deleted_punch_hidden_from_mine_status(ctx):
    """A tombstoned IN punch must NOT register as the current
    open shift on ``/mine-status``."""
    tech = _seed_landscape_tech(ctx["tid"])
    now = datetime.now(timezone.utc)
    _seed_punch(ctx["tid"], tech["id"], punch_type="in",
                ts_utc=now - timedelta(hours=1),
                deleted_at=now.isoformat())  # soft-deleted

    r = requests.get(f"{API}/timeclock/mine-status",
                      headers=_auth(tech["token"]), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["clocked_in"] is False, (
        f"deleted punch must NOT flip clocked_in=True; "
        f"got {body!r}"
    )
    assert body["punch_count"] == 0


def test_deleted_punch_hidden_from_mine_today(ctx):
    """``/mine-today`` must omit tombstoned rows from both the
    ``punches`` list AND the ``seconds`` aggregate."""
    tech = _seed_landscape_tech(ctx["tid"])
    now = datetime.now(timezone.utc)
    # Soft-deleted IN + OUT pair earlier today.
    _seed_punch(ctx["tid"], tech["id"], punch_type="in",
                ts_utc=now - timedelta(hours=3),
                deleted_at=now.isoformat())
    _seed_punch(ctx["tid"], tech["id"], punch_type="out",
                ts_utc=now - timedelta(hours=2),
                deleted_at=now.isoformat())

    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_auth(tech["token"]), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["punches"] == [], (
        f"deleted punches must be filtered out; got {body!r}"
    )
    assert body["seconds"] == 0
    assert body["clocked_in"] is False


def test_deleted_punch_not_counted_as_open_shift_on_punch_post(ctx):
    """POST ``/punch`` with ``out`` must NOT treat a tombstoned
    IN as the matching open shift.  Must 409 on
    ``no_open_shift`` just like the no-punch case."""
    tech = _seed_landscape_tech(ctx["tid"])
    now = datetime.now(timezone.utc)
    _seed_punch(ctx["tid"], tech["id"], punch_type="in",
                ts_utc=now - timedelta(hours=1),
                deleted_at=now.isoformat())  # soft-deleted

    r = requests.post(
        f"{API}/timeclock/punch",
        headers=_auth(tech["token"]),
        json={"punch_type": "out", "lat": 33.5, "lng": -112.1,
              "accuracy_m": 10.0, "source": "web",
              "geo_denied": False},
        timeout=15,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "no_open_shift", (
        f"tombstoned IN must not count as open shift; "
        f"got {r.json()!r}"
    )


# ─────────────────────────────────────────────────────────────────
# Regression — non-deleted punches still appear + happy-path works
# ─────────────────────────────────────────────────────────────────
def test_regression_non_deleted_punches_still_appear(ctx):
    """A live (not-tombstoned) IN punch MUST still surface on
    ``/mine-status`` and ``/mine-today`` after the filter lands."""
    tech = _seed_landscape_tech(ctx["tid"])
    now = datetime.now(timezone.utc)
    _seed_punch(ctx["tid"], tech["id"], punch_type="in",
                ts_utc=now - timedelta(minutes=30))

    r = requests.get(f"{API}/timeclock/mine-status",
                      headers=_auth(tech["token"]), timeout=15)
    assert r.status_code == 200
    assert r.json()["clocked_in"] is True
    assert r.json()["punch_count"] == 1

    r2 = requests.get(f"{API}/timeclock/mine-today",
                       headers=_auth(tech["token"]), timeout=15)
    assert r2.status_code == 200
    assert r2.json()["clocked_in"] is True
    assert len(r2.json()["punches"]) == 1
