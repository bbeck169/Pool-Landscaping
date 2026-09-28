"""PDF-FIX-C · Feb-2026 — deep-extraction schema + prompt hardening.

Locks the extractor's contract additions shipped with
PDF-FIX-C:

  1. ``tax_rate: Optional[float]`` added to
     ``ExtractedDocument`` — captured verbatim as a
     percentage float (6.25 == 6.25%, not 0.0625).
  2. Deserializer accepts line items with EITHER
     ``item_name`` OR non-empty ``description`` (the new
     prompt allows ``description=null`` when only a SKU is on
     the invoice line). Both-empty items still drop —
     matches PDF-FIX-B FE fallback.
  3. Deserializer coerces ``description=null`` to ``""`` at
     the ``ExtractedLineItem`` boundary so the schema's
     ``description: str`` constraint is satisfied without
     rejecting SKU-only rows.
  4. ``line_total`` extracted verbatim from the PDF's line-
     item column (unchanged from schema — extractor prompt
     hardened to instruct the LLM not to compute it from
     ``qty × price``).
  5. Soft totals-consistency check —
     ``|subtotal + tax_total - grand_total| > $0.01`` logs a
     ``[pdf_extract.consistency] subtotal_tax_mismatch`` warning
     but never rejects the document.
  6. ``EXTRACTOR_PROMPT_VERSION = "v2_deep_extraction"``
     module-level constant, stamped in the extract-start log
     line for A/B measurement across prompt revisions.
  7. Backwards compat — old-schema extraction responses that
     lack ``subtotal`` / ``tax_total`` / ``tax_rate`` /
     ``item_name`` still parse gracefully (all Optional; no
     migration needed).

All tests are unit-level against ``_ensure_document`` — no DB
required, no PDF byte scaffolding. The extract-start log
stamp is verified via a source-inspect check rather than a
full extract() invocation to keep the test file hermetic.

Integration guard: the real-vision extraction tests live
under ``pytest -m integration`` in
``test_task_h1_pdf_import.py`` and remain the sole opt-in
LLM smoke — PDF-FIX-C does not add new integration paths.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List

import pytest


def _make_raw_doc(**overrides: Any) -> Dict[str, Any]:
    """Minimal raw extraction dict — mirrors what
    ``_call_vision_model`` would return for one document.
    """
    base: Dict[str, Any] = {
        "doc_kind": "invoice",
        "source_page_range": [1, 1],
        "customer_name": "Test Customer",
        "doc_number": "INV-C-0001",
        "doc_date": "2026-02-01",
        "line_items": [
            {
                "item_name": "SKU-1",
                "description": "Chlorine tabs",
                "cost_rate": 25.0,
                "qty": 4.0,
                "line_total": 100.0,
                "confidence": 1.0,
            },
        ],
        "subtotal": 100.00,
        "tax_total": 0.00,
        "tax_rate": None,
        "grand_total": 100.00,
        "amount_paid": None,
        "total_due": 100.00,
    }
    base.update(overrides)
    return base


def _call_ensure(raw: Dict[str, Any]):
    """Import + invoke ``_ensure_document`` on a raw dict."""
    from services.imports.pdf_invoice_extractor import _ensure_document
    warnings: List[str] = []
    doc = _ensure_document(raw, warnings, doc_position_hint=1)
    return doc, warnings


# ══════════════════════════════════════════════════════════════
# Acceptance cases (9) — from PDF-FIX-C dispatch brief.
# ══════════════════════════════════════════════════════════════

def test_a_new_totals_fields_populate_on_extracted_document():
    """(a) Mock extractor response with subtotal, grand_total,
    tax_total, tax_rate → all fields present on
    ``ExtractedDocument``.
    """
    raw = _make_raw_doc(
        subtotal=400.00, tax_total=25.00, tax_rate=6.25,
        grand_total=425.00, total_due=425.00,
    )
    doc, _ = _call_ensure(raw)
    assert doc.subtotal == 400.00
    assert doc.tax_total == 25.00
    assert doc.tax_rate == 6.25
    assert doc.grand_total == 425.00


def test_b_line_item_with_both_name_and_description_captured_separately():
    """(b) Line item with both name + description →
    ``ExtractedLineItem`` captures both as separate fields.
    """
    raw = _make_raw_doc(line_items=[{
        "item_name": "SKU-CL4LB",
        "description": "Chlorine 4-lb tablets — bulk",
        "qty": 1.0, "cost_rate": 42.0, "line_total": 42.0,
        "confidence": 1.0,
    }])
    doc, _ = _call_ensure(raw)
    assert len(doc.line_items) == 1
    li = doc.line_items[0]
    assert li.item_name == "SKU-CL4LB"
    assert li.description == "Chlorine 4-lb tablets — bulk"


def test_c_line_item_with_only_item_name_captured_description_empty():
    """(c) Line item with only ``item_name`` (description is
    ``null`` per new prompt) → captured; deserializer coerces
    description to ``""`` (empty string) to satisfy the
    ``ExtractedLineItem.description: str`` schema constraint
    without dropping the row.
    """
    raw = _make_raw_doc(line_items=[{
        "item_name": "SKU-NAMEONLY",
        "description": None,
        "qty": 3.0, "cost_rate": 15.0, "line_total": 45.0,
    }])
    doc, _ = _call_ensure(raw)
    assert len(doc.line_items) == 1, (
        "SKU-only line item MUST NOT be dropped by the "
        "deserializer's filter"
    )
    li = doc.line_items[0]
    assert li.item_name == "SKU-NAMEONLY"
    assert li.description == "", (
        "null description should coerce to '' at the schema "
        "boundary — never None on ExtractedLineItem"
    )


def test_d_line_item_with_only_description_captured_item_name_null():
    """(d) Line item with only ``description`` (no
    ``item_name``) → captured; ``item_name`` remains None
    (Optional).
    """
    raw = _make_raw_doc(line_items=[{
        "item_name": None,
        "description": "Weekly pool service — 3/12",
        "qty": 1.0, "cost_rate": 120.0, "line_total": 120.0,
    }])
    doc, _ = _call_ensure(raw)
    assert len(doc.line_items) == 1
    li = doc.line_items[0]
    assert li.item_name is None
    assert li.description == "Weekly pool service — 3/12"


def test_e_line_total_captured_verbatim_not_recomputed():
    """(e) Line item with ``line_total = 100.00`` from PDF →
    captured verbatim on ``ExtractedLineItem.line_total``.
    The extractor's deserializer does NOT overwrite this via
    ``qty × cost_rate`` — the PDF's printed total may reflect
    discounts / rounding the extractor cannot see.
    """
    raw = _make_raw_doc(line_items=[{
        "item_name": "SKU-1",
        "description": "Discounted item",
        "qty": 5.0,
        "cost_rate": 20.0,       # implied line_total via math = 100.00
        "line_total": 89.99,     # ACTUAL printed line_total (post-discount)
    }])
    doc, _ = _call_ensure(raw)
    assert doc.line_items[0].line_total == 89.99, (
        "line_total must be preserved verbatim from the "
        "extractor payload, not recomputed as qty × cost_rate"
    )


def test_f_totals_consistency_within_penny_no_warning(caplog):
    """(f) subtotal=400 + tax=25 == grand=425 → no
    ``[pdf_extract.consistency]`` warning.
    """
    raw = _make_raw_doc(
        subtotal=400.00, tax_total=25.00, grand_total=425.00,
    )
    with caplog.at_level(logging.WARNING,
                            logger="imports.pdf_invoice_extractor"):
        _call_ensure(raw)
    consistency_hits = [
        r for r in caplog.records
        if "[pdf_extract.consistency]" in r.getMessage()
    ]
    assert consistency_hits == [], (
        f"expected NO consistency warning; got: "
        f"{[r.getMessage() for r in consistency_hits]}"
    )


def test_g_totals_consistency_mismatch_logs_warning_with_delta(caplog):
    """(g) subtotal=400 + tax=25 != grand=430 → warning
    logged with ``subtotal_tax_mismatch`` code + $5.00 delta.
    """
    raw = _make_raw_doc(
        subtotal=400.00, tax_total=25.00, grand_total=430.00,
    )
    with caplog.at_level(logging.WARNING,
                            logger="imports.pdf_invoice_extractor"):
        _call_ensure(raw)
    consistency_hits = [
        r for r in caplog.records
        if "[pdf_extract.consistency]" in r.getMessage()
        and "subtotal_tax_mismatch" in r.getMessage()
    ]
    assert len(consistency_hits) == 1, (
        f"expected exactly one consistency warning; got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    msg = consistency_hits[0].getMessage()
    # delta = computed(425) - grand(430) = -5.00
    assert "delta=-5.00" in msg, msg


def test_g2_totals_consistency_penny_edge_still_silent(caplog):
    """(g-edge) Exactly $0.01 delta → no warning (threshold
    is ``> 0.01``, not ``>= 0.01``).
    """
    raw = _make_raw_doc(
        subtotal=100.00, tax_total=0.00, grand_total=100.01,
    )
    with caplog.at_level(logging.WARNING,
                            logger="imports.pdf_invoice_extractor"):
        _call_ensure(raw)
    consistency_hits = [
        r for r in caplog.records
        if "[pdf_extract.consistency]" in r.getMessage()
    ]
    assert consistency_hits == []


def test_h_prompt_version_constant_and_extract_start_log_reference():
    """(h) ``EXTRACTOR_PROMPT_VERSION`` constant is defined
    and stamped in the ``extract()`` start-line log — verified
    via source-inspection to keep this test hermetic (no PDF
    byte scaffolding, no vision-call mock).
    """
    from services.imports import pdf_invoice_extractor as mod
    # PDF-MIRROR · Feb-2026 — prompt bumped to v3_pdf_mirror after
    # the CHEM-LOCK / PDF-FIX-D cut. Whenever the extractor prompt's
    # semantic contract changes (new required fields, altered
    # rules), bump this constant AND update this pin.
    assert mod.EXTRACTOR_PROMPT_VERSION == "v3_pdf_mirror"

    # Source-level check that extract() actually references
    # the constant in its start-line log — catches accidental
    # regressions where the constant is defined but never used.
    src = inspect.getsource(mod.extract)
    assert "EXTRACTOR_PROMPT_VERSION" in src, (
        "extract() must reference EXTRACTOR_PROMPT_VERSION "
        "in its start-line log for A/B measurement"
    )
    assert "[pdf_extract.start]" in src, (
        "extract() must emit a [pdf_extract.start] log line "
        "at the top of the run"
    )


def test_i_backwards_compat_old_schema_response_still_parses():
    """(i) Extractor response that pre-dates PDF-FIX-C (no
    ``tax_rate``, no ``item_name`` on line items) parses
    without error. All new fields default to their None
    values on the resulting ``ExtractedDocument``.
    """
    raw = {
        "doc_kind": "invoice",
        "source_page_range": [1, 1],
        "customer_name": "Legacy Customer",
        "doc_number": "INV-LEGACY-001",
        "doc_date": "2026-01-15",
        "line_items": [
            {
                "description": "Legacy line item (no item_name)",
                "qty": 1.0,
                "cost_rate": 50.0,
                "line_total": 50.0,
            },
        ],
        "subtotal": 50.00,
        "tax_total": None,
        "grand_total": 50.00,
        # NO tax_rate field at all (pre-C schema).
    }
    doc, warnings = _call_ensure(raw)
    assert doc.tax_rate is None, (
        "missing tax_rate on the raw payload should coerce to "
        "None on ExtractedDocument (Optional[float])"
    )
    assert len(doc.line_items) == 1
    assert doc.line_items[0].item_name is None
    assert doc.line_items[0].description == "Legacy line item (no item_name)"
    # No consistency-check warning since tax_total is None
    # (nothing to reconcile).
    consistency_hits = [
        w for w in warnings if "consistency" in w.lower()
    ]
    assert consistency_hits == []


def test_prompt_template_advertises_all_new_fields():
    """Bonus — the extractor's user-prompt template exposes
    ``tax_rate`` and clarifies the item_name / description
    separation to the LLM. Guards a silent prompt regression
    where the schema field exists but the LLM never sees it.
    """
    from services.imports.pdf_invoice_extractor import (
        _EXTRACTION_USER_TMPL,
    )
    assert '"tax_rate"' in _EXTRACTION_USER_TMPL
    assert '"line_total"' in _EXTRACTION_USER_TMPL
    assert "leave" in _EXTRACTION_USER_TMPL.lower() and "null" in _EXTRACTION_USER_TMPL.lower(), (
        "prompt must instruct the LLM that description can be null"
    )
    assert "verbatim" in _EXTRACTION_USER_TMPL.lower(), (
        "prompt must instruct the LLM to extract line_total verbatim"
    )
