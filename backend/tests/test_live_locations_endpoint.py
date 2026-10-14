"""P1 Phase 3 · Feb-2026 — Live technician GPS pins pytest suite.

Covers ``routers.workforce_live_locations``:

  * ``classify_staleness`` boundaries (live / recent / stale /
    excluded).
  * Negative age_seconds (clock-skew) → ``live``.
  * ``_age_seconds`` ISO parsing + garbage input defensiveness.
  * End-to-end endpoint: tenant isolation, 2h cutoff, missing
    ping-doc graceful skip, empty-tenant, techs vs admins
    filtered, soft-deleted users excluded.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
for _k in ("MONGO_URL", "DB_NAME"):
    if _k not in os.environ and _BE.get(_k):
        os.environ[_k] = _BE[_k]


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ─── §1 · classify_staleness boundaries ──────────────────────────

def test_classify_staleness_live_bucket():
    from routers.workforce_live_locations import classify_staleness
    assert classify_staleness(0) == "live"
    assert classify_staleness(60) == "live"
    assert classify_staleness(120) == "live"  # inclusive boundary


def test_classify_staleness_recent_bucket():
    from routers.workforce_live_locations import classify_staleness
    assert classify_staleness(121) == "recent"
    assert classify_staleness(300) == "recent"
    assert classify_staleness(600) == "recent"  # inclusive


def test_classify_staleness_stale_bucket():
    from routers.workforce_live_locations import classify_staleness
    assert classify_staleness(601) == "stale"
    assert classify_staleness(3600) == "stale"
    assert classify_staleness(7200) == "stale"  # 2 hr inclusive


def test_classify_staleness_excluded_beyond_2h():
    from routers.workforce_live_locations import classify_staleness
    assert classify_staleness(7201) is None
    assert classify_staleness(86400) is None


def test_classify_staleness_negative_treated_as_live():
    """Clock-skew (ping stamped in the future) still renders as a
    live pin — hiding would make the map worse during local
    time-sync drift."""
    from routers.workforce_live_locations import classify_staleness
    assert classify_staleness(-5) == "live"


# ─── §2 · _age_seconds defensiveness ─────────────────────────────

def test_age_seconds_handles_iso_with_offset():
    from routers.workforce_live_locations import _age_seconds
    now = datetime(2026, 10, 15, 18, 22, 45, tzinfo=timezone.utc)
    age = _age_seconds("2026-10-15T18:22:00+00:00", now)
    assert age == 45


def test_age_seconds_handles_zulu():
    from routers.workforce_live_locations import _age_seconds
    now = datetime(2026, 10, 15, 18, 22, 45, tzinfo=timezone.utc)
    age = _age_seconds("2026-10-15T18:22:00Z", now)
    assert age == 45


def test_age_seconds_garbage_returns_beyond_stale():
    from routers.workforce_live_locations import (
        _age_seconds, STALENESS_STALE_MAX_S,
    )
    now = datetime.now(timezone.utc)
    assert _age_seconds(None, now) > STALENESS_STALE_MAX_S
    assert _age_seconds("", now) > STALENESS_STALE_MAX_S
    assert _age_seconds("not-a-date", now) > STALENESS_STALE_MAX_S


# ─── §3 · End-to-end endpoint — mock DB ──────────────────────────

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, field_or_list, direction=1):
        if isinstance(field_or_list, list):
            for field, dir_ in reversed(field_or_list):
                self._rows.sort(key=lambda r, f=field: r.get(f) or "",
                                reverse=(dir_ == -1))
        else:
            self._rows.sort(key=lambda r: r.get(field_or_list) or "",
                            reverse=(direction == -1))
        return self

    async def to_list(self, length=None):
        return list(self._rows[:length] if length else self._rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])

    async def find_one(self, query, projection=None, sort=None):
        matches = [r for r in self.rows if _match(r, query)]
        if sort:
            for field, dir_ in reversed(sort):
                matches.sort(key=lambda r, f=field: r.get(f) or "",
                             reverse=(dir_ == -1))
        return dict(matches[0]) if matches else None


def _match(row, query):
    for key, val in query.items():
        if key == "$or":
            if not any(_match(row, sub) for sub in val):
                return False
            continue
        if key == "$and":
            if not all(_match(row, sub) for sub in val):
                return False
            continue
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$gte" in val:
                if not (row.get(key) is not None
                        and row.get(key) >= val["$gte"]):
                    return False
            if "$exists" in val:
                exists = key in row
                if exists != val["$exists"]:
                    return False
                continue
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, users=None, gps_pings=None):
        self.users = _MockCollection(users)
        self.gps_pings = _MockCollection(gps_pings)


def _iso_ago(seconds):
    return (datetime.now(timezone.utc)
            - timedelta(seconds=seconds)).isoformat()


async def test_endpoint_returns_only_recent_pings(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[
            {"id": "u1", "tenant_id": "t", "role": "technician",
             "name": "Steven Martinez"},
        ],
        gps_pings=[
            {"user_id": "u1", "tenant_id": "t",
             "captured_at": _iso_ago(60),
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert len(out["pings"]) == 1
    p = out["pings"][0]
    assert p["user_name"] == "Steven Martinez"
    assert p["staleness"] == "live"
    assert p["lat"] == 33.6
    assert p["lon"] == -112.0


async def test_endpoint_excludes_pings_older_than_2h(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[{"id": "u1", "tenant_id": "t", "role": "technician"}],
        gps_pings=[
            {"user_id": "u1", "tenant_id": "t",
             "captured_at": _iso_ago(7300),  # > 2h
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert out["pings"] == []


async def test_endpoint_tenant_isolation(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[
            {"id": "u-mine", "tenant_id": "t", "role": "technician"},
            {"id": "u-other", "tenant_id": "t-OTHER",
             "role": "technician"},
        ],
        gps_pings=[
            {"user_id": "u-mine", "tenant_id": "t",
             "captured_at": _iso_ago(60),
             "lat": 33.6, "lon": -112.0},
            {"user_id": "u-other", "tenant_id": "t-OTHER",
             "captured_at": _iso_ago(60),
             "lat": 33.0, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert len(out["pings"]) == 1
    assert out["pings"][0]["user_id"] == "u-mine"


async def test_endpoint_skips_users_with_no_ping_doc(monkeypatch):
    """Technician in the roster with zero pings in the window
    must be skipped (not surfaced as an empty row)."""
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[
            {"id": "u1", "tenant_id": "t", "role": "technician"},
            {"id": "u2", "tenant_id": "t", "role": "worker"},
        ],
        gps_pings=[
            {"user_id": "u1", "tenant_id": "t",
             "captured_at": _iso_ago(90),
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert [p["user_id"] for p in out["pings"]] == ["u1"]


async def test_endpoint_excludes_admins_and_customers(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[
            {"id": "a1", "tenant_id": "t", "role": "admin"},
            {"id": "c1", "tenant_id": "t", "role": "customer"},
        ],
        gps_pings=[
            {"user_id": "a1", "tenant_id": "t",
             "captured_at": _iso_ago(60),
             "lat": 33.6, "lon": -112.0},
            {"user_id": "c1", "tenant_id": "t",
             "captured_at": _iso_ago(60),
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert out["pings"] == []


async def test_endpoint_soft_deleted_user_excluded(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[
            {"id": "u1", "tenant_id": "t", "role": "technician",
             "deleted_at": "2026-01-01T00:00:00+00:00"},
        ],
        gps_pings=[
            {"user_id": "u1", "tenant_id": "t",
             "captured_at": _iso_ago(60),
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert out["pings"] == []


async def test_endpoint_empty_tenant_returns_empty_list(monkeypatch):
    from routers import workforce_live_locations as mod
    db = _MockDB(users=[], gps_pings=[])
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert out["pings"] == []
    assert "server_time" in out


async def test_endpoint_response_shape_matches_contract(monkeypatch):
    """Lock the keys the FE depends on so a schema drift fails
    the test before shipping."""
    from routers import workforce_live_locations as mod
    db = _MockDB(
        users=[{"id": "u1", "tenant_id": "t", "role": "technician",
                "name": "Steven Martinez"}],
        gps_pings=[
            {"user_id": "u1", "tenant_id": "t",
             "captured_at": _iso_ago(45),
             "lat": 33.6, "lon": -112.0},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    out = await mod.live_locations(
        _user={"id": "a", "role": "admin"},
        tenant={"id": "t"},
    )
    assert set(out.keys()) == {"pings", "server_time"}
    p = out["pings"][0]
    for k in ("user_id", "user_name", "lat", "lon",
                "captured_at", "age_seconds", "staleness"):
        assert k in p, f"missing contract key: {k}"
