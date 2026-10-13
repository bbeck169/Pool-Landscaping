"""P1 · Feb-2026 — Branch 1 mileage calculator fix + backfill tests.

Pins the behaviour of:

  1. ``routers.workforce._entry_mileage_miles`` — now reads from
     ``db.gps_pings`` (``captured_at``, ``lat``, ``lon``) instead
     of the legacy ``db.location_pings`` (``ts``, ``lat``, ``lng``).
     Preserves the ``len(pings) < 2`` sentinel + max_speed +
     min_hop filters.
  2. ``routers.admin_mileage_backfill.backfill_recompute`` —
     dry-run no-write, writes-on-live, idempotent, tenant-scoped,
     audit row written.

Pure-helper + mock-DB coverage.  No live Mongo required.
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


# ═════════════════════════════════════════════════════════════
# Mock DB
# ═════════════════════════════════════════════════════════════

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, field, direction=1):
        self._rows.sort(
            key=lambda r: r.get(field) or "",
            reverse=(direction == -1),
        )
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
        self.inserted = []
        self.updates = []

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _match(r, query):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        self.rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id") or "m"})()

    async def update_one(self, query, update):
        for r in self.rows:
            if _match(r, query):
                for k, v in (update.get("$set") or {}).items():
                    r[k] = v
                self.updates.append({"q": query, "u": update})
                return type("U", (), {"matched_count": 1,
                                        "modified_count": 1})()
        return type("U", (), {"matched_count": 0,
                                "modified_count": 0})()


def _match(row, query):
    for key, val in query.items():
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$gte" in val:
                if not (row.get(key) is not None
                        and row.get(key) >= val["$gte"]):
                    return False
            if "$lte" in val:
                if not (row.get(key) is not None
                        and row.get(key) <= val["$lte"]):
                    return False
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, gps_pings=None, location_pings=None,
                 time_entries=None, audit_logs=None):
        self.gps_pings = _MockCollection(gps_pings)
        self.location_pings = _MockCollection(location_pings)
        self.time_entries = _MockCollection(time_entries)
        self.audit_logs = _MockCollection(audit_logs)


# ═════════════════════════════════════════════════════════════
# §1 · _entry_mileage_miles — Branch 1 fix behaviour
# ═════════════════════════════════════════════════════════════

_DEFAULT_SETTINGS = {
    "mileage_max_speed_mph": 80,
    "mileage_min_hop_m": 25,
}


async def test_calculator_reads_from_gps_pings_not_location_pings(
    monkeypatch,
):
    """Only ``gps_pings`` is consulted — a drive-tracking payload
    in ``location_pings`` is now IGNORED (the broken legacy
    source), while an equivalent payload in ``gps_pings`` yields
    a positive mileage."""
    from routers import workforce

    # Two gps_pings 200m apart → should produce ~0.124 mi after
    # the min_hop filter (200m > 25m) and max_speed filter
    # (200m / 60s = 3.33 m/s → 7.5 mph << 80 mph).
    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:00:00+00:00",
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:01:00+00:00",
         "lat": 33.6018, "lon": -112.0000},  # ~200m north
    ]
    # Equivalent payload in location_pings — now ignored.
    loc = [
        {"tenant_id": "t", "user_id": "u",
         "ts": "2026-10-01T10:00:00+00:00",
         "lat": 33.9000, "lng": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "ts": "2026-10-01T10:01:00+00:00",
         "lat": 34.0000, "lng": -112.0000},  # ~11km north — if
                                               # the calc still
                                               # read this coll
                                               # we'd see ~7 mi.
    ]
    db = _MockDB(gps_pings=gps, location_pings=loc)
    monkeypatch.setattr(workforce, "db", db)

    miles = await workforce._entry_mileage_miles(
        "t", "e1", "u",
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T23:59:59+00:00",
        _DEFAULT_SETTINGS,
    )
    # Expect ~0.12 mi from the gps_pings payload, NOT ~7 mi
    # from the (ignored) location_pings payload.
    assert 0.1 < miles < 0.2, (
        f"expected ~0.12 mi from gps_pings; got {miles}"
    )


async def test_calculator_returns_zero_when_fewer_than_two_gps_pings(
    monkeypatch,
):
    from routers import workforce
    db = _MockDB(gps_pings=[
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:00:00+00:00",
         "lat": 33.6, "lon": -112.0},
    ])
    monkeypatch.setattr(workforce, "db", db)
    miles = await workforce._entry_mileage_miles(
        "t", "e1", "u",
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T23:59:59+00:00",
        _DEFAULT_SETTINGS,
    )
    assert miles == 0.0


async def test_calculator_filters_tiny_jitter_hops(monkeypatch):
    """Hops shorter than ``mileage_min_hop_m`` are ignored."""
    from routers import workforce
    # Two pings ~5m apart (sub-25m) → filtered out → 0 mi.
    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:00:00+00:00",
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:01:00+00:00",
         "lat": 33.60004, "lon": -112.0000},  # ~4m north
    ]
    db = _MockDB(gps_pings=gps)
    monkeypatch.setattr(workforce, "db", db)
    miles = await workforce._entry_mileage_miles(
        "t", "e1", "u",
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T23:59:59+00:00",
        _DEFAULT_SETTINGS,
    )
    assert miles == 0.0


async def test_calculator_discards_super_fast_outliers(monkeypatch):
    """Hops that imply speed > max_speed_mph are discarded
    (likely GPS teleport glitches)."""
    from routers import workforce
    # Two pings 1 km apart in 1 second → ~2236 mph → discarded.
    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:00:00+00:00",
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": "2026-10-01T10:00:01+00:00",
         "lat": 33.6090, "lon": -112.0000},  # ~1 km in 1s
    ]
    db = _MockDB(gps_pings=gps)
    monkeypatch.setattr(workforce, "db", db)
    miles = await workforce._entry_mileage_miles(
        "t", "e1", "u",
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T23:59:59+00:00",
        _DEFAULT_SETTINGS,
    )
    assert miles == 0.0


async def test_calculator_respects_tenant_scope(monkeypatch):
    """Pings for another tenant must NOT contribute to this
    tenant's mileage."""
    from routers import workforce
    gps = [
        {"tenant_id": "t-OTHER", "user_id": "u",
         "captured_at": "2026-10-01T10:00:00+00:00",
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t-OTHER", "user_id": "u",
         "captured_at": "2026-10-01T10:01:00+00:00",
         "lat": 33.6018, "lon": -112.0000},
    ]
    db = _MockDB(gps_pings=gps)
    monkeypatch.setattr(workforce, "db", db)
    miles = await workforce._entry_mileage_miles(
        "t", "e1", "u",
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T23:59:59+00:00",
        _DEFAULT_SETTINGS,
    )
    assert miles == 0.0


# ═════════════════════════════════════════════════════════════
# §2 · backfill_recompute endpoint — dry-run + live-write
# ═════════════════════════════════════════════════════════════

async def test_backfill_dry_run_writes_no_rows(monkeypatch):
    """``dry_run=True`` must not update ``time_entries``.  Response
    still surfaces the computed delta via ``changes_sample``."""
    from routers import admin_mileage_backfill as mod
    from routers import workforce

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()
    start = (now - timedelta(hours=3)).isoformat()
    end = (now - timedelta(hours=1)).isoformat()

    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": start,
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": end,
         "lat": 33.6018, "lon": -112.0000},
    ]
    entries = [
        {"id": "e1", "tenant_id": "t", "user_id": "u",
         "clock_in_at": start, "clock_out_at": end,
         "mileage_miles": 0.0, "status": "submitted"},
    ]
    db = _MockDB(gps_pings=gps, time_entries=entries)
    monkeypatch.setattr(mod, "db", db)
    monkeypatch.setattr(workforce, "db", db)

    out = await mod.backfill_recompute(
        days=7, dry_run=True,
        admin={"id": "admin-1"},
        tenant={"id": "t", "settings": {}},
    )
    assert out["dry_run"] is True
    assert out["processed"] == 1
    assert out["updated"] == 1  # would-update
    assert out["unchanged"] == 0
    assert out["errors"] == 0
    assert len(out["changes_sample"]) == 1
    # No writes to time_entries.
    assert db.time_entries.updates == []
    # Audit row still written (dry-run signalled in summary).
    assert len(db.audit_logs.inserted) == 1
    assert db.audit_logs.inserted[0]["action"] == (
        "mileage.backfill_recomputed")


async def test_backfill_live_writes_mileage_and_stamps_provenance(
    monkeypatch,
):
    from routers import admin_mileage_backfill as mod
    from routers import workforce

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=3)).isoformat()
    end = (now - timedelta(hours=1)).isoformat()

    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": start,
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": end,
         "lat": 33.6018, "lon": -112.0000},
    ]
    entries = [
        {"id": "e1", "tenant_id": "t", "user_id": "u",
         "clock_in_at": start, "clock_out_at": end,
         "mileage_miles": 0.0, "status": "submitted"},
    ]
    db = _MockDB(gps_pings=gps, time_entries=entries)
    monkeypatch.setattr(mod, "db", db)
    monkeypatch.setattr(workforce, "db", db)

    out = await mod.backfill_recompute(
        days=7, dry_run=False,
        admin={"id": "admin-1"},
        tenant={"id": "t", "settings": {}},
    )
    assert out["updated"] == 1
    assert len(db.time_entries.updates) == 1
    stored = db.time_entries.rows[0]
    assert stored["mileage_miles"] > 0.1
    assert stored["mileage_recomputed_by"] == "admin-1"
    assert "mileage_recomputed_at" in stored


async def test_backfill_is_tenant_scoped(monkeypatch):
    """Running against tenant ``t`` must NOT update tenant
    ``t-OTHER`` even if that row would benefit from a
    recompute."""
    from routers import admin_mileage_backfill as mod
    from routers import workforce

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=3)).isoformat()
    end = (now - timedelta(hours=1)).isoformat()

    gps = [
        {"tenant_id": "t-OTHER", "user_id": "u",
         "captured_at": start,
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t-OTHER", "user_id": "u",
         "captured_at": end,
         "lat": 33.6018, "lon": -112.0000},
    ]
    entries = [
        {"id": "e-other", "tenant_id": "t-OTHER", "user_id": "u",
         "clock_in_at": start, "clock_out_at": end,
         "mileage_miles": 0.0, "status": "submitted"},
    ]
    db = _MockDB(gps_pings=gps, time_entries=entries)
    monkeypatch.setattr(mod, "db", db)
    monkeypatch.setattr(workforce, "db", db)

    out = await mod.backfill_recompute(
        days=7, dry_run=False,
        admin={"id": "admin-1"},
        tenant={"id": "t", "settings": {}},
    )
    assert out["processed"] == 0
    assert out["updated"] == 0
    # The other tenant's row stays at 0.0.
    assert db.time_entries.rows[0]["mileage_miles"] == 0.0


async def test_backfill_idempotent_on_repeat_run(monkeypatch):
    """A second run against the same window produces
    ``unchanged == processed`` because the recompute is
    deterministic."""
    from routers import admin_mileage_backfill as mod
    from routers import workforce

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=3)).isoformat()
    end = (now - timedelta(hours=1)).isoformat()

    gps = [
        {"tenant_id": "t", "user_id": "u",
         "captured_at": start,
         "lat": 33.6000, "lon": -112.0000},
        {"tenant_id": "t", "user_id": "u",
         "captured_at": end,
         "lat": 33.6018, "lon": -112.0000},
    ]
    entries = [
        {"id": "e1", "tenant_id": "t", "user_id": "u",
         "clock_in_at": start, "clock_out_at": end,
         "mileage_miles": 0.0, "status": "submitted"},
    ]
    db = _MockDB(gps_pings=gps, time_entries=entries)
    monkeypatch.setattr(mod, "db", db)
    monkeypatch.setattr(workforce, "db", db)

    first = await mod.backfill_recompute(
        days=7, dry_run=False,
        admin={"id": "a"}, tenant={"id": "t", "settings": {}})
    assert first["updated"] == 1
    second = await mod.backfill_recompute(
        days=7, dry_run=False,
        admin={"id": "a"}, tenant={"id": "t", "settings": {}})
    assert second["updated"] == 0
    assert second["unchanged"] == 1


async def test_backfill_ignores_open_shifts(monkeypatch):
    """Shifts without a ``clock_out_at`` must NOT be touched —
    the calculator is only valid for closed shifts."""
    from routers import admin_mileage_backfill as mod
    from routers import workforce

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=3)).isoformat()

    db = _MockDB(
        gps_pings=[],
        time_entries=[
            {"id": "e-open", "tenant_id": "t", "user_id": "u",
             "clock_in_at": start, "clock_out_at": None,
             "mileage_miles": 0.0, "status": "open"},
        ],
    )
    monkeypatch.setattr(mod, "db", db)
    monkeypatch.setattr(workforce, "db", db)
    out = await mod.backfill_recompute(
        days=7, dry_run=False,
        admin={"id": "a"}, tenant={"id": "t", "settings": {}})
    assert out["processed"] == 0
    assert out["updated"] == 0
