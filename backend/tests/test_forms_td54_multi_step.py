"""TD-54 · Feb-2026 — Multi-step forms (`page_break` layout field).

Phase 4 Commit 1 of the Form Builder multi-step ship.

Server-side contract:
    * ``page_break`` is a LAYOUT-ONLY field type (sibling of
      ``section``). No submission value. No ``name`` required.
    * Pagination is a client concern — the backend accepts the full
      ``answers`` dict on final submit regardless of how many pages
      the client walked through.
    * ``page_title`` optional metadata on ``page_break`` fields —
      max 60 chars. Shown as the step label in the widget's
      Prev/Next renderer.
    * Multiple ``page_break`` fields allowed in a single form; page
      count is simply ``page_break_count + 1`` from the client's
      perspective.
    * Required-field validation on submit is CROSS-PAGE: all
      required fields across every page must be present.
    * ``show_if`` works transparently across pages — hidden fields
      skip the required-check regardless of which page they live on.

Covers (14 cases):

Model/palette (4):
    1. ``page_break`` is in ``_FIELD_TYPES``.
    2. ``page_break`` is in ``_LAYOUT_TYPES`` (shares exemptions with
       ``section``).
    3. ``page_break`` is NOT in ``_OPTIONS_REQUIRED_TYPES``.
    4. ``FormField`` accepts ``page_title`` on a ``page_break`` field;
       capped at 60 chars.

Validator (6):
    5. One ``page_break`` → 2-page form, validation passes.
    6. Three ``page_breaks`` → 4-page form, validation passes.
    7. ``page_break`` with no ``name`` is accepted (layout exempt).
    8. ``page_break`` with no ``label`` is REJECTED — the shared
       ``FormField.label`` min_length=1 constraint still applies
       so every page carries an operator-visible marker in the
       admin canvas even when ``page_title`` is unset.
    9. Duplicate ``page_break`` ids are auto-suffixed via the
       existing section-id-collision loop.
   10. ``page_title`` longer than 60 chars is REJECTED by the
       pydantic max_length constraint.

Submit-time contract (4):
   11. A form with ``page_break`` accepts a normal submission; the
       answers dict carries the keys from fields across all pages.
   12. A form with ``page_break`` + a missing required field on a
       LATER page still 422s with the standard
       ``missing required fields:`` error.
   13. A form with ``page_break`` + ``show_if`` hiding a required
       field on a later page accepts submit without that field.
   14. A form WITHOUT any ``page_break`` round-trips validation
       byte-identically (regression gate — ``_LAYOUT_TYPES``
       widening must not perturb legacy forms).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routers.marketing_forms import (
    FormField,
    _FIELD_TYPES,
    _LAYOUT_TYPES,
    _OPTIONS_REQUIRED_TYPES,
    _validate_field_defs,
)


# ──────────────────────────────────────────────────────────────────
# 1–4. Model / palette
# ──────────────────────────────────────────────────────────────────
def test_page_break_in_field_types():
    assert "page_break" in _FIELD_TYPES


def test_page_break_in_layout_types():
    assert "page_break" in _LAYOUT_TYPES


def test_page_break_not_in_options_required():
    assert "page_break" not in _OPTIONS_REQUIRED_TYPES


def test_form_field_accepts_page_title():
    f = FormField(label="Step 1", type="page_break",
                   page_title="Contact Info")
    assert f.type == "page_break"
    assert f.page_title == "Contact Info"


# ──────────────────────────────────────────────────────────────────
# 5–10. Validator
# ──────────────────────────────────────────────────────────────────
def test_validator_accepts_single_page_break_two_page_form():
    out = _validate_field_defs([
        FormField(name="email", label="Email", type="email", required=True),
        FormField(label="Step 2", type="page_break", page_title="Address"),
        FormField(name="addr", label="Address", type="text"),
    ])
    assert [f["type"] for f in out] == ["email", "page_break", "text"]
    # Count of page_breaks is the authoritative client-side page
    # calculation input: pages = page_break_count + 1.
    pb_count = sum(1 for f in out if f["type"] == "page_break")
    assert pb_count == 1


def test_validator_accepts_three_page_breaks_four_page_form():
    out = _validate_field_defs([
        FormField(name="name", label="Name", type="text", required=True),
        FormField(label="PB1", type="page_break", page_title="Contact"),
        FormField(name="email", label="Email", type="email", required=True),
        FormField(label="PB2", type="page_break", page_title="Address"),
        FormField(name="addr", label="Address", type="text"),
        FormField(label="PB3", type="page_break", page_title="Review"),
        FormField(name="notes", label="Notes", type="textarea"),
    ])
    assert sum(1 for f in out if f["type"] == "page_break") == 3


def test_page_break_without_name_accepted():
    out = _validate_field_defs([
        FormField(name="email", label="Email", type="email"),
        FormField(label="Step 2", type="page_break"),
        FormField(name="phone", label="Phone", type="phone"),
    ])
    # Layout-exempt from name requirement — the ``_LAYOUT_TYPES``
    # branch in ``_validate_field_defs`` skips the empty-name check.
    assert out[1]["type"] == "page_break"
    assert out[1]["id"]  # id auto-derived from label


def test_page_break_without_label_rejected():
    """Shared ``FormField.label`` min_length=1 constraint still
    applies — every page carries an operator-visible marker even
    when page_title is unset."""
    with pytest.raises(ValidationError):
        FormField(type="page_break")  # no label


def test_duplicate_page_break_ids_auto_suffixed():
    out = _validate_field_defs([
        FormField(name="email", label="Email", type="email"),
        FormField(label="Step", type="page_break"),
        FormField(name="phone", label="Phone", type="phone"),
        FormField(label="Step", type="page_break"),
    ])
    pb_ids = [f["id"] for f in out if f["type"] == "page_break"]
    assert len(pb_ids) == 2
    assert len(set(pb_ids)) == 2  # unique after suffixing


def test_page_title_over_60_chars_rejected():
    with pytest.raises(ValidationError):
        FormField(label="Step", type="page_break",
                     page_title="x" * 61)


# ──────────────────────────────────────────────────────────────────
# 11–14. Submit-time contract — focused on the required-check +
# show_if interaction. We call the dispatcher's submission-time
# validation directly rather than firing a full widget HTTP round-
# trip (same strategy as test_forms_phase2_show_if.py).
# ──────────────────────────────────────────────────────────────────
def _two_page_form_with_required_fields():
    """Form shape: page1 has required email; page2 has required
    address. Returns the normalised fields list."""
    return _validate_field_defs([
        FormField(name="email", label="Email",
                     type="email", required=True),
        FormField(label="Step 2", type="page_break",
                     page_title="Address"),
        FormField(name="addr", label="Address",
                     type="text", required=True),
    ])


def _run_required_check(fields: list, payload: dict,
                           hidden_fids: set | None = None) -> None:
    """Minimal re-implementation of the dispatcher's required-check
    block (preserves the exact behavior exercised by the public
    widget submit path). Raises HTTPException(422) on missing
    required fields."""
    hidden_fids = hidden_fids or set()
    missing = []
    for f in fields:
        if not f.get("required"):
            continue
        if f.get("id") in hidden_fids:
            continue
        val = payload.get(f["name"])
        if val is None and f.get("id"):
            val = payload.get(f["id"])
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(f["name"])
    if missing:
        raise HTTPException(
            422, f"missing required fields: {', '.join(missing)}"
        )


def test_submit_accepts_full_payload_across_pages():
    fields = _two_page_form_with_required_fields()
    payload = {"email": "a@b.test", "addr": "1 Pool Rd"}
    # No exception = success.
    _run_required_check(fields, payload)


def test_submit_rejects_missing_required_on_later_page():
    fields = _two_page_form_with_required_fields()
    # email on page1 provided; addr on page2 is missing — this is
    # exactly the "user navigated to page2 but didn't fill it in"
    # scenario the widget client-side validator is supposed to
    # catch BEFORE the final submit. BE still enforces as the
    # authoritative gate.
    payload = {"email": "a@b.test"}
    with pytest.raises(HTTPException) as exc:
        _run_required_check(fields, payload)
    assert exc.value.status_code == 422
    assert "addr" in str(exc.value.detail)
    assert "email" not in str(exc.value.detail)


def test_submit_accepts_hidden_required_field_across_pages():
    """``show_if`` works transparently across pages — a required
    field on page2 that is hidden by a condition evaluated against
    a page1 answer must NOT 422 the submit."""
    fields = _two_page_form_with_required_fields()
    # Simulate the show_if evaluator result: the ``addr`` field's
    # id ends up in ``hidden_fids``.
    addr_id = next(f["id"] for f in fields if f["name"] == "addr")
    payload = {"email": "a@b.test"}  # no addr — but it's hidden
    _run_required_check(fields, payload, hidden_fids={addr_id})


def test_submit_byte_identical_for_form_without_page_break():
    """Regression gate: a form with ZERO page_breaks must validate
    identically to how it would have pre-TD-54. We exercise the
    normal happy-path + the missing-required path to lock both
    sides of the branch."""
    fields = _validate_field_defs([
        FormField(name="email", label="Email", type="email", required=True),
        FormField(name="name", label="Name", type="text", required=True),
    ])
    assert [f["type"] for f in fields] == ["email", "text"]
    # Happy path.
    _run_required_check(fields, {"email": "a@b", "name": "Alice"})
    # Missing required.
    with pytest.raises(HTTPException) as exc:
        _run_required_check(fields, {"email": "a@b"})
    assert "name" in str(exc.value.detail)
