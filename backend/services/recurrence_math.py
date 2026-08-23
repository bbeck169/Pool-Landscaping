"""Feb-2026 · P47 — shared month-advancing math for recurrence cadences
that step by whole months (monthly / quarterly / semi_annual).

Kept intentionally tiny so both ``routers/recurring_jobs.py::_next_after``
and ``routers/jobs.py::jobs_recurrence_preview`` can import the same
helper and stay in lock-step on month-length clamping.

Clamp rule (matches the existing monthly branch):
    Jan 31 + quarterly  → Apr 30   (Apr has 30 days)
    Feb 29 + semi-annual → Aug 29   (Aug has 31 days, day unchanged)
    Feb 29 + semi-annual, one more year → Feb 28  (non-leap clamp)
"""
from __future__ import annotations

import calendar
from datetime import date


# Advance N months, clamping day_of_month to the target month's last day.
# Callers pass the intended ``day_of_month`` explicitly rather than
# reading it off the anchor so the walker can preserve the template's
# "Nth" no matter what month-length trimming happened on the previous
# step.
def advance_months(anchor: date, months: int, dom: int) -> date:
    total = (anchor.year * 12) + (anchor.month - 1) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    last_day = calendar.monthrange(y, m)[1]
    picked = min(dom, last_day)
    return date(y, m, picked)


# Cadences whose step is a whole number of months. Public map so
# validators and walkers can look up the month-step without magic
# numbers.
MONTH_STEP = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
}
