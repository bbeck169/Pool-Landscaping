"""Feb-2026 · PDF Import Hub — preview post-processor pytests.

Covers ``services/imports/pdf_preview_post.apply_preview_post_
processing`` + its three defensive concerns:

  * Bug 1 — doc_type override honoured; auto-detected value stashed.
  * Bug 1 inverse — no hint → classifier output preserved.
  * Bug 2 — subtotal/line_total mismatch stamped + WARN log fires.
  * Bug 3 — digit-only / doc-number-literal / name == doc_number
    customer_name values demoted to low-confidence.
  * Bug 3 fallback — real customer names pass through untouched.

Fixture:
  ``backend/tests/fixtures/pdf_import/joe_kail_estimates.pdf`` is
  committed alongside this test as a regression reproducer for the
  operator to re-run end-to-end after deploy.  The post-processor
  logic itself is covered via synthetic ``MapperReport`` instances
  so the test suite does not require vision-model credits.
"""
from __future__ import annotations

import logging
import pathlib

import pytest

from services.imports.extraction_schema import MapperReport
from services.imports.pdf_preview_post import (
    apply_preview_post_processing,
    _looks_like_doc_number,
)


# ─── Factory ─────────────────────────────────────────────────────
def _mr(
    *,
    source_doc_index: int = 0,
    doc_kind: str = "estimate",
    quote_in: dict | None = None,
) -> MapperReport:
    """Build a minimal MapperReport for post-processor exercise."""
    return MapperReport(
        source_doc_index=source_doc_index,
        doc_kind=doc_kind,
        mapped_target="quote_in",
        quote_in=quote_in or {
            "customer_name": "Alice Example",
            "doc_type": "quote",
            "doc_number": "346",
            "line_items": [],
            "subtotal": None,
        },
        customer_resolution="pending",
    )


# ─── Bug 1 · explicit hint overrides classifier output ───────────
def test_bug1_explicit_hint_overrides_auto_detected_doc_type():
    # Classifier picked ``invoice``; operator chose Estimate.
    report = _mr(quote_in={
        "customer_name": "Alice", "doc_type": "invoice",
        "doc_number": "INV-1", "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind="estimate")
    qi = report.quote_in
    assert qi["doc_type"] == "quote"            # forced
    assert qi["auto_detected_doc_type"] == "invoice"
    assert qi["doc_type_user_override"] is True


# ─── Bug 1 inverse · no hint → classifier wins ───────────────────
def test_bug1_no_hint_preserves_classifier_output():
    report = _mr(quote_in={
        "customer_name": "Alice", "doc_type": "invoice",
        "doc_number": "INV-1", "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind=None)
    qi = report.quote_in
    assert qi["doc_type"] == "invoice"           # unchanged
    assert qi["auto_detected_doc_type"] == "invoice"
    # No override flag when the hint wasn't exercised.
    assert "doc_type_user_override" not in qi


def test_bug1_hint_matches_classifier_no_override_flag():
    report = _mr(quote_in={
        "customer_name": "Alice", "doc_type": "quote",
        "doc_number": "EST-1", "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind="estimate")
    qi = report.quote_in
    assert qi["doc_type"] == "quote"
    assert qi["auto_detected_doc_type"] == "quote"
    assert "doc_type_user_override" not in qi


# ─── Bug 3 · digit-only name demoted to low-confidence ───────────
@pytest.mark.parametrize("suspect_name", [
    "346",       # Joe Kail case · digit-only (the actual user bug).
    " 42 ",      # whitespace-wrapped digit-only.
    "4521",      # longer digit-only up to 6 chars.
])
def test_bug3_digit_only_customer_name_demoted(suspect_name, caplog):
    report = _mr(quote_in={
        "customer_name": suspect_name,
        "doc_type": "quote", "doc_number": "346",
        "line_items": [], "subtotal": None,
    })
    with caplog.at_level(logging.WARNING,
                         logger="pdf_import_preview_post"):
        apply_preview_post_processing([report], hint_doc_kind=None)
    qi = report.quote_in
    assert qi["customer_name"] is None
    assert qi["customer_extraction_confidence"] == "low"
    assert qi["customer_extraction_reason"] == (
        "name_matched_doc_number_pattern"
    )
    assert qi["customer_name_suspect_value"] == suspect_name
    assert any(
        "customer_name demoted" in rec.getMessage()
        for rec in caplog.records
    )


# ─── Bug 3 · doc-number literal patterns ─────────────────────────
@pytest.mark.parametrize("suspect_name", [
    "Invoice #123",
    "INV-456",
    "Est 789",
    "Estimate # 42",
    "#999",
    "estimate 100",
])
def test_bug3_doc_number_literal_names_demoted(suspect_name):
    report = _mr(quote_in={
        "customer_name": suspect_name,
        "doc_type": "quote", "doc_number": None,
        "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind=None)
    assert report.quote_in["customer_name"] is None
    assert report.quote_in["customer_extraction_confidence"] == "low"


# ─── Bug 3 · name == doc_number literal match ────────────────────
def test_bug3_customer_name_equals_doc_number_demoted():
    report = _mr(quote_in={
        "customer_name": "INV-5812",
        "doc_type": "invoice", "doc_number": "inv-5812",
        "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind=None)
    assert report.quote_in["customer_name"] is None
    assert report.quote_in["customer_extraction_confidence"] == "low"


# ─── Bug 3 · real customer names pass through untouched ──────────
@pytest.mark.parametrize("legit_name", [
    "Joe Kail",
    "Alice Example",
    "Smith & Sons Pools LLC",
    "O'Brien Pool Service",
    "123 Pool Street Inc",   # starts with digits but has suffix.
    "Barnes 42",             # digit suffix in a surname-style name.
])
def test_bug3_real_customer_names_pass_through(legit_name):
    report = _mr(quote_in={
        "customer_name": legit_name,
        "doc_type": "quote", "doc_number": "346",
        "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind=None)
    assert report.quote_in["customer_name"] == legit_name
    assert "customer_extraction_confidence" not in report.quote_in


# ─── Bug 2 · subtotal mismatch stamped + WARN ────────────────────
def test_bug2_subtotal_mismatch_stamped_and_warned(caplog):
    report = _mr(quote_in={
        "customer_name": "Alice", "doc_type": "quote",
        "doc_number": "E-1",
        "line_items": [
            {"description": "A", "line_total": 10.00},
            {"description": "B", "line_total": 15.00},
        ],
        "subtotal": 30.00,  # expected 25 → delta -500 cents
    })
    with caplog.at_level(logging.WARNING,
                         logger="pdf_import_preview_post"):
        apply_preview_post_processing([report], hint_doc_kind=None)
    qi = report.quote_in
    assert qi["line_total_subtotal_mismatch_cents"] == -500
    assert any(
        "line_total_subtotal_mismatch" in rec.getMessage()
        for rec in caplog.records
    )


def test_bug2_subtotal_match_no_warn_stamps_zero(caplog):
    report = _mr(quote_in={
        "customer_name": "Alice", "doc_type": "quote",
        "doc_number": "E-1",
        "line_items": [
            {"description": "A", "line_total": 10.00},
            {"description": "B", "line_total": 15.00},
        ],
        "subtotal": 25.00,
    })
    with caplog.at_level(logging.WARNING,
                         logger="pdf_import_preview_post"):
        apply_preview_post_processing([report], hint_doc_kind=None)
    qi = report.quote_in
    assert qi["line_total_subtotal_mismatch_cents"] == 0
    assert not any(
        "line_total_subtotal_mismatch" in rec.getMessage()
        for rec in caplog.records
    )


# ─── Idempotency · re-run leaves state unchanged ─────────────────
def test_post_processor_is_idempotent():
    report = _mr(quote_in={
        "customer_name": "346", "doc_type": "invoice",
        "doc_number": "346", "line_items": [], "subtotal": None,
    })
    apply_preview_post_processing([report], hint_doc_kind="estimate")
    first_snapshot = dict(report.quote_in)
    apply_preview_post_processing([report], hint_doc_kind="estimate")
    second_snapshot = dict(report.quote_in)
    assert first_snapshot == second_snapshot


# ─── Fixture reproducer file is present and non-empty ────────────
def test_joe_kail_fixture_pdf_committed_for_regression():
    """The Joe Kail PDF is committed to this suite so operators can
    re-run the end-to-end import post-deploy and verify the three
    bug fixes against the actual reproducer file. The post-processor
    logic itself is covered via synthetic ``MapperReport`` instances
    in the cases above so the regression test suite does not depend
    on vision-model credits."""
    fx = pathlib.Path(
        "/app/backend/tests/fixtures/pdf_import/"
        "joe_kail_estimates.pdf",
    )
    assert fx.exists(), "fixture PDF must be committed"
    assert fx.stat().st_size > 10_000, (
        "fixture PDF looks truncated — expected ≈115 KB"
    )
    # Starts with the PDF magic number.
    assert fx.read_bytes()[:4] == b"%PDF"


# ─── Helper · _looks_like_doc_number unit tests ──────────────────
@pytest.mark.parametrize("name,doc_number,expected", [
    ("346", "346", True),
    ("346", None, True),
    ("  42  ", None, True),
    ("Invoice #5", None, True),
    ("Joe Kail", "346", False),
    ("Smith & Sons LLC", None, False),
    (None, "346", False),
    ("", "346", False),
    ("1234567890", None, False),  # too long to be a doc number.
    ("Alpha346", "346", False),   # name happens to contain the number.
])
def test_looks_like_doc_number_detector(name, doc_number, expected):
    assert _looks_like_doc_number(name, doc_number) is expected
