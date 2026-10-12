"""Feb-2026 · regression · `_next_occurrences` + `end_date=None`.

Infinite-recurrence (introduced in prior-session commit ``8e42a1b7f``)
depends on the walker treating a null ``end_date`` as "no cap — use
``horizon_end`` as the sole stop". This file pins that behavior so
future refactors don't silently regress to "zero occurrences when
end_date is None".

Pure direct-call tests — no Mongo, no HTTP. Matches the style of
``test_recurring_cron_cursor_fix.py``.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from routers.recurring_jobs import _next_occurrences


# ─── 1 · null end_date emits through the full horizon ───────────────
def test_next_occurrences_null_end_date_emits_through_full_horizon():
    """A weekly template with end_date=None and a 90-day horizon
    must emit ~13 Monday occurrences (one per week), not short-circuit
    to zero.
    """
    anchor = date(2026, 1, 5)  # Monday
    horizon = anchor + timedelta(days=90)
    tpl = {
        "frequency": "weekly",
        "day_of_week": 0,              # Monday
        "start_date": anchor.isoformat(),
        "end_date": None,              # <-- the unbounded path
        "allow_sunday": False,
        "interval_days": 7,
        "is_active": True,
    }

    occs = _next_occurrences(tpl, anchor, horizon, max_count=200)

    # 90 days / 7 ≈ 12.85 Mondays — the walker emits every Monday
    # from the anchor through the horizon inclusive on either end
    # as the ruleset allows.
    assert len(occs) >= 12, (
        f"expected ≥12 weekly Mondays, got {len(occs)}: {occs}")
    # Every emitted date must be ≤ horizon_end.
    assert all(d <= horizon for d in occs), (
        f"walker emitted past horizon: {occs}")
    # Every emitted date must be the configured day_of_week (Monday).
    assert all(d.weekday() == 0 for d in occs), (
        f"non-Monday leaked through: {occs}")


# ─── 2 · horizon_end is the SOLE cap when end_date is None ──────────
def test_next_occurrences_horizon_end_is_sole_cap_when_end_date_null():
    """Pin the specific contract: shrink the horizon → the number of
    emitted occurrences strictly shrinks in lockstep. If end_date=None
    were silently applied as a cap, the two horizons would yield the
    same count.
    """
    anchor = date(2026, 2, 2)  # Monday
    tpl = {
        "frequency": "weekly",
        "day_of_week": 0,
        "start_date": anchor.isoformat(),
        "end_date": None,
        "allow_sunday": False,
        "interval_days": 7,
        "is_active": True,
    }

    short = _next_occurrences(
        tpl, anchor, anchor + timedelta(days=14), max_count=200)
    long = _next_occurrences(
        tpl, anchor, anchor + timedelta(days=60), max_count=200)

    # ~2 Mondays in 14 days vs ~8-9 in 60 days.
    assert len(long) > len(short), (
        f"horizon_end must be the sole cap for null end_date — "
        f"short={len(short)} long={len(long)}")
    assert len(short) <= 3  # inclusive-of-anchor-week sanity
    assert len(long) >= 7


# ─── 3 · bounded end_date wins over horizon when end_date < horizon ─
def test_next_occurrences_end_date_caps_before_horizon_when_bounded():
    """Complement to tests 1-2: when end_date IS set and is earlier
    than horizon_end, the walker respects end_date (hard_stop =
    min(horizon_end, end_date)). This proves the `if end_date else
    horizon_end` branch at line 313 is live — not dead code masked
    by the null path.
    """
    anchor = date(2026, 3, 2)  # Monday
    tpl = {
        "frequency": "weekly",
        "day_of_week": 0,
        "start_date": anchor.isoformat(),
        "end_date": (anchor + timedelta(days=20)).isoformat(),
        "allow_sunday": False,
        "interval_days": 7,
        "is_active": True,
    }

    occs = _next_occurrences(
        tpl, anchor, anchor + timedelta(days=90), max_count=200)

    # 20-day window from Monday → inclusive Mondays:
    # anchor, anchor+7, anchor+14 → 3 occurrences; anchor+21 falls
    # past end_date and must NOT be emitted.
    assert len(occs) == 3, (
        f"expected 3 Mondays within end_date cap, got {len(occs)}: {occs}")
    assert all(
        d <= (anchor + timedelta(days=20)) for d in occs), (
            f"walker emitted past bounded end_date: {occs}")
