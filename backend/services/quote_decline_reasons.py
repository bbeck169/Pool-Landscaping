"""PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026.

Canonical list of customer-facing "decline reason" categories.
The customer portal (``frontend/src/components/EstimateView.jsx``)
requires the customer to pick one of these categories AND provide
a 10-500 char free-text explanation when declining a quote.

Keep this list IN SYNC with the frontend display-label map at
``frontend/src/pages/portal/quoteDeclineReasons.js``.
"""
from __future__ import annotations

from typing import Any

# ─── Enum (stored values · snake_case) ─────────────────────────────
# Any change here MUST land simultaneously in
# ``frontend/src/pages/portal/quoteDeclineReasons.js`` (display-label
# map).  The backend only validates against this list; the frontend
# owns the human-readable labels.
DECLINE_REASON_CATEGORIES = [
    "too_expensive",
    "going_with_another_provider",
    "timing_not_right",
    "changed_my_mind",
    "scope_not_what_expected",
    "other",
]

# Validation bounds for the free-text explanation.  Both ends
# enforced server-side; the frontend mirrors them for live UX.
DECLINE_REASON_TEXT_MIN_LEN = 10
DECLINE_REASON_TEXT_MAX_LEN = 500


def is_valid_category(value: Any) -> bool:
    """Return True iff ``value`` is a non-empty string that matches
    one of the canonical categories (case-sensitive, snake_case)."""
    return isinstance(value, str) and value in DECLINE_REASON_CATEGORIES
