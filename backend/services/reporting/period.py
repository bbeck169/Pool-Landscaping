"""Phase R0 · Feb-2026 — Period normalization for the reporting suite.

Consumers pass ``period=mtd|qtd|ytd|last_30d|custom`` on the
``/api/reports/kpi/{metric_key}`` query string.  This module
canonicalizes the input into a single :class:`Period` dataclass
with two boundaries (``start`` / ``end`` inclusive-exclusive ISO
strings) plus the ``prior`` boundaries used for period-over-period
delta calculations.

Boundaries follow the ordinary business-analytics convention:

* MTD:   first day of the current month  → now.
  Prior: same-length window ending at start of MTD.
* QTD:   first day of the current quarter → now.
* YTD:   Jan 1 of the current year        → now.
* last_30d: now-30d → now.
* custom: caller-supplied ``start`` + ``end`` (ISO date).

All boundaries are computed against the caller's UTC clock.  The
Feb-2026 CRM stack does not yet honour per-tenant timezones for
reporting — deliberately deferred to a future R-phase so R0 lands
without that dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException


ALLOWED_PERIODS = ("mtd", "qtd", "ytd", "last_30d", "custom")


@dataclass(frozen=True)
class Period:
    key: str                  # "mtd" | "qtd" | "ytd" | "last_30d" | "custom"
    label: str                # human readable e.g. "Month to date"
    start: str                # ISO date, inclusive
    end: str                  # ISO date, exclusive
    prior_start: str          # ISO date, inclusive
    prior_end: str            # ISO date, exclusive

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "start": self.start, "end": self.end,
                "prior_start": self.prior_start, "prior_end": self.prior_end}


def _iso_date(d: date) -> str:
    return d.isoformat()


def _start_of_month(d: date) -> date:
    return d.replace(day=1)


def _start_of_quarter(d: date) -> date:
    q_month = ((d.month - 1) // 3) * 3 + 1
    return d.replace(month=q_month, day=1)


def _start_of_year(d: date) -> date:
    return d.replace(month=1, day=1)


def _prior_window(start: date, end: date) -> tuple[date, date]:
    """Return the same-length window ending exactly at ``start``.
    Half-open [prior_start, prior_end) is exactly the length of
    [start, end)."""
    delta = end - start
    return (start - delta, start)


def resolve_period(
    period_key: Optional[str] = "mtd",
    start: Optional[str] = None,
    end: Optional[str] = None,
    *,
    _today: Optional[date] = None,  # injectable for tests
) -> Period:
    key = (period_key or "mtd").lower()
    if key not in ALLOWED_PERIODS:
        raise HTTPException(400, f"Unsupported period '{period_key}'")

    today = _today or datetime.now(timezone.utc).date()
    end_boundary = today + timedelta(days=1)  # inclusive of today

    if key == "mtd":
        s = _start_of_month(today)
        e = end_boundary
        label = "Month to date"
    elif key == "qtd":
        s = _start_of_quarter(today)
        e = end_boundary
        label = "Quarter to date"
    elif key == "ytd":
        s = _start_of_year(today)
        e = end_boundary
        label = "Year to date"
    elif key == "last_30d":
        s = today - timedelta(days=29)
        e = end_boundary
        label = "Last 30 days"
    else:  # custom
        if not (start and end):
            raise HTTPException(400, "custom period requires start + end")
        try:
            s = date.fromisoformat(start)
            e = date.fromisoformat(end) + timedelta(days=1)  # end inclusive
        except ValueError as exc:
            raise HTTPException(400, f"Invalid custom range: {exc}") from exc
        if e <= s:
            raise HTTPException(400, "custom period end must be after start")
        label = f"{start} → {end}"

    prior_s, prior_e = _prior_window(s, e)
    return Period(
        key=key, label=label,
        start=_iso_date(s), end=_iso_date(e),
        prior_start=_iso_date(prior_s), prior_end=_iso_date(prior_e),
    )
