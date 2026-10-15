"""TD-52 · Feb-2026 — Form Builder palette expansion.

Four new field types shipped on the admin form definition:
    * ``signature``          — data URL submission value.
    * ``address_manual``     — composite nested dict value.
    * ``rating_stars``       — integer 1..5 with server-side sanity.
    * ``file_multi_upload``  — multi-file picker; multipart ingress.

Covers (15 cases):

Palette:
    1. All four types are members of ``_FIELD_TYPES``.
    2. None of the four appear in ``_LAYOUT_TYPES`` or
       ``_OPTIONS_REQUIRED_TYPES`` (they are value-carrying with
       no options list).
    3. ``FormField`` accepts a form definition for each new type
       and ``_validate_field_defs`` normalises it without error.
    4. Duplicate ``name`` detection still fires for the new types
       (regression gate — new types are NOT layout-exempt).
    5. ``_validate_field_defs`` does NOT require ``options`` on any
       new type.

Rating coercion:
    6. ``_coerce_rating_stars`` accepts ints in [1, 5].
    7. ``_coerce_rating_stars`` accepts numeric strings in [1, 5].
    8. ``_coerce_rating_stars`` returns None for out-of-range ints.
    9. ``_coerce_rating_stars`` returns None for non-numeric strings.
   10. ``_coerce_rating_stars`` returns None for bools (True/False).
   11. ``_coerce_rating_stars`` returns None for floats that aren't
       integers (3.5 → None).

Submit-time dispatcher:
   12. ``_validate_td52_field_values`` coerces numeric string rating
       into an int in the submission payload (``"4"`` → ``4``).
   13. ``_validate_td52_field_values`` raises 422 on an invalid
       rating value.
   14. ``_validate_td52_field_values`` IGNORES None / "" / missing
       rating values (no coercion, no raise — required-check runs
       separately upstream).
   15. ``_validate_td52_field_values`` leaves non-rating fields
       untouched (signature / address_manual / file_multi_upload).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers.marketing_forms import (
    FormField,
    _FIELD_TYPES,
    _LAYOUT_TYPES,
    _OPTIONS_REQUIRED_TYPES,
    _coerce_rating_stars,
    _validate_field_defs,
    _validate_td52_field_values,
)


# ──────────────────────────────────────────────────────────────────
# 1–5. Palette / schema
# ──────────────────────────────────────────────────────────────────
_NEW_TYPES = ("signature", "address_manual", "rating_stars",
              "file_multi_upload")


@pytest.mark.parametrize("t", _NEW_TYPES)
def test_new_field_type_is_in_palette(t):
    assert t in _FIELD_TYPES


@pytest.mark.parametrize("t", _NEW_TYPES)
def test_new_field_type_is_not_layout_nor_options_required(t):
    assert t not in _LAYOUT_TYPES, (
        f"{t} is a value-carrying field, not a layout marker"
    )
    assert t not in _OPTIONS_REQUIRED_TYPES, (
        f"{t} does not need an options list"
    )


@pytest.mark.parametrize("t", _NEW_TYPES)
def test_validate_field_defs_accepts_new_type(t):
    out = _validate_field_defs([
        FormField(name=f"n_{t}", label=f"Label for {t}", type=t),
    ])
    assert out[0]["type"] == t
    assert out[0]["name"] == f"n_{t}"
    # Normaliser must still auto-assign an id + order.
    assert out[0]["id"]
    assert out[0]["order"] == 0


def test_duplicate_name_still_rejected_for_new_type():
    with pytest.raises(HTTPException) as exc:
        _validate_field_defs([
            FormField(name="rating", label="Rate us", type="rating_stars"),
            FormField(name="rating", label="Rate again", type="rating_stars"),
        ])
    assert exc.value.status_code == 422
    assert "duplicate" in str(exc.value.detail).lower()


def test_new_types_do_not_need_options_list():
    # Each new type is accepted with ``options=None`` — no 422 from
    # the ``_OPTIONS_REQUIRED_TYPES`` branch.
    for t in _NEW_TYPES:
        out = _validate_field_defs([
            FormField(name=f"n_{t}", label=f"L {t}", type=t, options=None),
        ])
        assert out[0]["type"] == t


# ──────────────────────────────────────────────────────────────────
# 6–11. Rating coercion
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", [1, 2, 3, 4, 5])
def test_coerce_rating_stars_accepts_valid_ints(v):
    assert _coerce_rating_stars(v) == v


@pytest.mark.parametrize("v,expected", [
    ("1", 1), ("3", 3), ("5", 5), ("  4 ", 4),
])
def test_coerce_rating_stars_accepts_numeric_strings(v, expected):
    assert _coerce_rating_stars(v) == expected


@pytest.mark.parametrize("v", [0, 6, -1, 100, -100])
def test_coerce_rating_stars_rejects_out_of_range_ints(v):
    assert _coerce_rating_stars(v) is None


@pytest.mark.parametrize("v", ["abc", "3.5", "", "   ", "five"])
def test_coerce_rating_stars_rejects_non_numeric_strings(v):
    assert _coerce_rating_stars(v) is None


@pytest.mark.parametrize("v", [True, False])
def test_coerce_rating_stars_rejects_bools(v):
    """True/False must NOT silently become 1/0 — a boolean submission
    is a client bug (checkbox mis-wired to a rating field), not a
    valid rating."""
    assert _coerce_rating_stars(v) is None


@pytest.mark.parametrize("v", [3.5, 2.9, 1.01, float("nan")])
def test_coerce_rating_stars_rejects_non_integer_floats(v):
    assert _coerce_rating_stars(v) is None


# ──────────────────────────────────────────────────────────────────
# 12–15. Submit-time dispatcher gate
# ──────────────────────────────────────────────────────────────────
def _rating_field(name="rate") -> dict:
    return {"id": name, "name": name, "label": "Rate us",
            "type": "rating_stars", "required": False}


def test_validate_td52_field_values_coerces_numeric_string():
    payload = {"rate": "4"}
    _validate_td52_field_values([_rating_field()], payload)
    assert payload == {"rate": 4}


def test_validate_td52_field_values_422s_on_invalid_rating():
    payload = {"rate": "banana"}
    with pytest.raises(HTTPException) as exc:
        _validate_td52_field_values([_rating_field()], payload)
    assert exc.value.status_code == 422
    assert "rating_stars" in str(exc.value.detail)


def test_validate_td52_field_values_ignores_missing_or_blank():
    """Required-check runs separately; a missing / blank rating is
    silently passed through here."""
    for v in (None, "", "   "):
        payload = {"rate": v} if v is not None else {}
        _validate_td52_field_values([_rating_field()], payload)
        # No raise, no coercion → payload unchanged.
        assert payload == ({"rate": v} if v is not None else {})


def test_validate_td52_field_values_leaves_other_new_types_untouched():
    """signature / address_manual / file_multi_upload have loose
    submission shapes; the dispatcher must NOT raise or mutate
    their values."""
    payload = {
        "sig": "data:image/png;base64,iVBORw0KGgo=",
        "addr": {"line1": "1 Pool Rd", "city": "Phoenix",
                   "state": "AZ", "zip": "85001"},
        "docs": ["invoice.pdf", "photo.jpg"],
        "rate": 5,
    }
    fields = [
        {"id": "sig", "name": "sig", "label": "Sign", "type": "signature"},
        {"id": "addr", "name": "addr", "label": "Addr", "type": "address_manual"},
        {"id": "docs", "name": "docs", "label": "Docs", "type": "file_multi_upload"},
        _rating_field(),
    ]
    _validate_td52_field_values(fields, payload)
    # Rating stays int; other values unchanged.
    assert payload["sig"] == "data:image/png;base64,iVBORw0KGgo="
    assert payload["addr"]["city"] == "Phoenix"
    assert payload["docs"] == ["invoice.pdf", "photo.jpg"]
    assert payload["rate"] == 5
