"""Feb-2026 · ``GET /api/timeclock/mine-status`` — rollover shift +
day-boundary contract tests.

The spec called out an edge case where a landscape tech clocks in
at 22:00 on day N and stays clocked in past midnight into day
N+1.  Before the fix, ``mine-status`` only queried today's punches
so the day-N+1 probe returned ``clocked_in: false`` even though
the shift was still open.  Fix: extend the window back to
yesterday-00:00 and use the LATEST punch's type as the source of
truth.  These tests lock the new contract in-process against a
fake ``timeclock_punches`` collection so we don't need HTTP + JWT
plumbing for what is a pure query-shape contract.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from routers import timeclock_landscaping as tcl


# ─── Fake async cursor + fake collection ────────────────────────
class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs
    def sort(self, *_args, **_kwargs):
        # Punches are pre-sorted in the fixture — no-op the sort
        # so the router's ``.sort("timestamp", 1)`` call is safe.
        return self
    async def to_list(self, _cap: int) -> List[Dict[str, Any]]:
        return list(self._docs)


class _FakePunches:
    """Tiny in-memory ``timeclock_punches`` stand-in.  Supports the
    two calls ``mine_status`` makes: ``find(query, projection)`` +
    ``.sort(...).to_list(N)``.  Filtering honors ``tenant_id``,
    ``user_id``, and the ``timestamp: {$gte, $lte}`` window so we
    can prove the widened lookup actually admits yesterday rows."""
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def find(self, query: Dict[str, Any], _projection: Dict[str, Any] = None):
        tid = query.get("tenant_id")
        uid = query.get("user_id")
        ts_range = query.get("timestamp") or {}
        gte = ts_range.get("$gte")
        lte = ts_range.get("$lte")
        matched = [
            d for d in self._docs
            if d.get("tenant_id") == tid
            and d.get("user_id") == uid
            and (gte is None or d.get("timestamp") >= gte)
            and (lte is None or d.get("timestamp") <= lte)
        ]
        # Router sorts by timestamp ASC — pre-sort here.
        matched.sort(key=lambda d: d.get("timestamp", ""))
        return _FakeCursor(matched)


class _FakeDB:
    def __init__(self, punches: List[Dict[str, Any]]):
        self.timeclock_punches = _FakePunches(punches)


# ─── Fixtures ───────────────────────────────────────────────────
_TENANT = "t-1"
_USER = {"id": "u-luis", "tenant_id": _TENANT, "role": "technician",
         "department": "landscaping"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _iso(d: date, hh: int, mm: int = 0) -> str:
    return datetime(d.year, d.month, d.day, hh, mm,
                    tzinfo=timezone.utc).isoformat()


def _patch_db(monkeypatch, punches: List[Dict[str, Any]]):
    monkeypatch.setattr(tcl, "db", _FakeDB(punches))


# ─── Specs ──────────────────────────────────────────────────────
class TestMineStatusRollover:
    def test_rollover_shift_from_yesterday_still_reads_as_clocked_in(
        self, monkeypatch,
    ):
        """The primary spec case — a shift that started at 22:00
        yesterday and hasn't been clocked out MUST surface as
        ``clocked_in: true`` on today's probe."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        _patch_db(monkeypatch, [
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "in", "timestamp": _iso(yesterday, 22)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is True
        # ``punch_count`` still reflects TODAY's activity — the
        # yesterday-only punch doesn't inflate today's counter.
        assert result["punch_count"] == 0

    def test_yesterday_closed_out_and_today_empty_reads_as_clocked_out(
        self, monkeypatch,
    ):
        today = date.today()
        yesterday = today - timedelta(days=1)
        _patch_db(monkeypatch, [
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "in",  "timestamp": _iso(yesterday, 9)},
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "out", "timestamp": _iso(yesterday, 17)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is False

    def test_no_punches_at_all_reads_as_clocked_out(self, monkeypatch):
        _patch_db(monkeypatch, [])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is False
        assert result["punch_count"] == 0

    def test_today_out_after_a_yesterday_in_reads_as_clocked_out(
        self, monkeypatch,
    ):
        """The tech rolled the shift over then clocked out early
        this morning.  The LATEST punch (``out``) wins even though
        an earlier ``in`` sits in the window."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        _patch_db(monkeypatch, [
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "in",  "timestamp": _iso(yesterday, 22)},
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "out", "timestamp": _iso(today, 6)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is False
        # ``punch_count`` counts TODAY's ``out`` only.
        assert result["punch_count"] == 1

    def test_today_open_shift_reads_as_clocked_in(self, monkeypatch):
        """Baseline non-rollover case — a normal open shift that
        started this morning still fires correctly (regression
        guard for the pre-fix behaviour)."""
        today = date.today()
        _patch_db(monkeypatch, [
            {"tenant_id": _TENANT, "user_id": _USER["id"],
             "punch_type": "in", "timestamp": _iso(today, 9)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is True
        assert result["punch_count"] == 1

    def test_cross_tenant_leakage_guard(self, monkeypatch):
        """A different tenant's ``in`` punch MUST NOT leak into
        this tenant's status probe.  Guards the tenant-scoping
        clause in the query."""
        today = date.today()
        _patch_db(monkeypatch, [
            # Another tenant, same user id (rare edge) — still gated.
            {"tenant_id": "t-2", "user_id": _USER["id"],
             "punch_type": "in", "timestamp": _iso(today, 8)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is False

    def test_cross_user_leakage_guard(self, monkeypatch):
        today = date.today()
        _patch_db(monkeypatch, [
            {"tenant_id": _TENANT, "user_id": "u-someone-else",
             "punch_type": "in", "timestamp": _iso(today, 9)},
        ])
        result = _run(tcl.mine_status(user=_USER))
        assert result["clocked_in"] is False
