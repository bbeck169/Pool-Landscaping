"""MR0 · Feb-2026 — Address masking for public MapRankings widget.

Rules
-----
Public display MUST NOT reveal the exact house number. Everything
below the street-number granularity is safe. Given a raw street like
``"1234 Main St"`` we strip the leading numeric run and return
``"Main St"``. If the leading token is not numeric (e.g. ``"PO Box
42"``) the string is preserved verbatim — the "42" here is a box
number, not a house number, and public suppression is not required.

Test coverage lives in ``test_public_checkins.py``.
"""
from __future__ import annotations

import re
from typing import Any, Dict

_LEADING_NUMERIC = re.compile(r"^\d[\dA-Za-z\-\/]*\s+")


def mask_street(street: str | None) -> str:
    """Return ``street`` with any leading numeric house-number stripped.

    Examples
    --------
    >>> mask_street("1234 Main St")
    'Main St'
    >>> mask_street("Main St")
    'Main St'
    >>> mask_street("1 Way")
    'Way'
    >>> mask_street("PO Box 42")
    'PO Box 42'
    >>> mask_street("")
    ''
    """
    if not street:
        return ""
    s = str(street).strip()
    if not s:
        return ""
    return _LEADING_NUMERIC.sub("", s).strip()


def mask_address(raw: Dict[str, Any] | None) -> Dict[str, str]:
    """Convert a raw ``{street, city, state, zip, country}`` dict into
    the public-safe ``{street_name, city, state}`` shape."""
    raw = raw or {}
    return {
        "street_name": mask_street(raw.get("street")),
        "city": (raw.get("city") or "").strip(),
        "state": (raw.get("state") or "").strip(),
    }


__all__ = ["mask_street", "mask_address"]
