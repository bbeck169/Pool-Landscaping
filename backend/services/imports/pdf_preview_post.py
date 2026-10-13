"""Feb-2026 · PDF Import Hub — preview post-processor.

Shared helper that runs AFTER ``pdf_mapper.map_extracted_to_quote_in``
has produced every :class:`MapperReport` for a batch, but BEFORE the
mapper_previews array is persisted on the ``db.import_batches`` doc.

Three defensive concerns live here (all three Feb-2026 PDF Import
Hub bugs flagged by user QA against the Joe Kail estimate fixture):

  * **Bug 1 — Document Type override.** When the operator picked an
    explicit Document Type on the FE dropdown (``hint_doc_kind`` is
    not None), the mapper's auto-detected ``doc_type`` must be
    overridden by that explicit choice.  The pre-fix behavior let
    the vision model's classifier win over the user's selection
    (hint was only a prompt nudge, not a hard override).  The
    original auto-detected value is retained on
    ``auto_detected_doc_type`` for forensics so the FE can surface a
    small "AI said: X" badge next to the pill.

  * **Bug 3 — Customer-name demotion.** When the mapper's
    ``quote_in.customer_name`` field looks like the document number
    (short digit-only string, matches the row's doc_number, or an
    "Invoice #123" style literal), null it and flag
    ``customer_extraction_confidence="low"``.  This routes the row
    through the existing pending-customer workflow (operator must
    manually set the customer before commit) rather than silently
    auto-creating a customer named "346".

  * **Bug 2 defensive — subtotal mismatch warn.** Non-blocking —
    emit a WARN log + stamp
    ``quote_in.line_total_subtotal_mismatch_cents`` when
    ``Σ line_item.line_total`` differs from ``quote_in.subtotal`` by
    more than $0.01.  The FE expand panel surfaces the mismatch as
    an amber warning so the operator notices before commit.

The pre-existing Invoice commit path (`fc1ee96e3`) continues to
work verbatim — this post-processor is additive and runs over
every mapper report in a batch regardless of doc_kind.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from .extraction_schema import MapperReport


logger = logging.getLogger("pdf_import_preview_post")


# ─── Bug 1 · hint_doc_kind → canonical ``quote_in.doc_type`` ─────
# Mapper uses the ``quote`` literal for an estimate (doc_kind=estimate)
# and ``invoice`` for an invoice.  Payment receipts have no
# ``quote_in`` so they're skipped.
_HINT_TO_QUOTE_DOC_TYPE = {
    "invoice":        "invoice",
    "estimate":       "quote",
    # ``payment`` + ``payment_receipt`` do not land on quote_in —
    # explicitly not mapped so the override no-ops for those.
}


# ─── Bug 3 · "customer_name is actually a doc number" detectors ──
# Short all-digit strings up to 6 chars; matches invoice numbers
# like "346", "4521", etc.  Longer digit sequences could be legit
# business names in rare cases — stay conservative.
_DIGIT_ONLY_RE = re.compile(r"^\s*\d{1,6}\s*$")
# "Invoice #123" / "INV-456" / "Est 789" / "Estimate # 42" style.
_DOC_NUMBER_LITERAL_RE = re.compile(
    r"^\s*(?:invoice|inv|est|estimate|#)\s*[-#]?\s*\d+\s*$",
    re.IGNORECASE,
)


def _looks_like_doc_number(
    customer_name: Optional[str],
    doc_number: Optional[str],
) -> bool:
    """Return True IFF ``customer_name`` looks like a document
    number rather than a real customer name."""
    if not isinstance(customer_name, str):
        return False
    name = customer_name.strip()
    if not name:
        return False
    if _DIGIT_ONLY_RE.match(name):
        return True
    if _DOC_NUMBER_LITERAL_RE.match(name):
        return True
    if doc_number:
        if name.lower() == str(doc_number).strip().lower():
            return True
    return False


def _apply_doc_type_override(
    mp: MapperReport,
    hint_doc_kind: Optional[str],
) -> None:
    """Bug 1 fix — force ``quote_in.doc_type`` to the user's
    explicit hint when provided; stash the auto-detected value in
    a sibling field for FE forensics."""
    qi = mp.quote_in
    if not qi:
        return
    auto = qi.get("doc_type")
    # Idempotency — if the post-processor has already run on this
    # report, ``auto_detected_doc_type`` is already stamped with
    # the true auto-detected value.  Preserve it rather than
    # overwriting with the (potentially already-overridden)
    # current ``doc_type``.
    if "auto_detected_doc_type" not in qi:
        qi["auto_detected_doc_type"] = auto
    if not hint_doc_kind:
        return
    forced = _HINT_TO_QUOTE_DOC_TYPE.get(hint_doc_kind)
    if forced is None or forced == qi["auto_detected_doc_type"]:
        return
    qi["doc_type"] = forced
    qi["doc_type_user_override"] = True
    logger.info(
        "[pdf-import] doc_type override — source_doc_index=%d "
        "auto=%s user_hint=%s forced=%s",
        getattr(mp, "source_doc_index", -1),
        qi["auto_detected_doc_type"], hint_doc_kind, forced,
    )


def _apply_customer_name_demotion(mp: MapperReport) -> None:
    """Bug 3 fix — if ``customer_name`` on the mapper's quote_in
    looks like a doc-number literal, null it and flag the row
    low-confidence so the FE can surface a warning + the operator
    can set the real customer before commit."""
    qi = mp.quote_in
    if not qi:
        return
    name = qi.get("customer_name")
    doc_number = qi.get("doc_number") or qi.get("invoice_number")
    if not _looks_like_doc_number(name, doc_number):
        return
    # Preserve the suspect value for operator diagnostics.
    qi["customer_name_suspect_value"] = name
    qi["customer_name"] = None
    qi["customer_extraction_confidence"] = "low"
    qi["customer_extraction_reason"] = (
        "name_matched_doc_number_pattern"
    )
    logger.warning(
        "[pdf-import] customer_name demoted to low-confidence — "
        "source_doc_index=%d suspect_value=%r doc_number=%r",
        getattr(mp, "source_doc_index", -1),
        name, doc_number,
    )


def _apply_line_total_subtotal_check(mp: MapperReport) -> None:
    """Bug 2 defensive — WARN if the mapper's line_total sum
    diverges from the stated subtotal by more than $0.01.  Stamps
    ``quote_in.line_total_subtotal_mismatch_cents`` so the FE expand
    panel can surface the amber warning next to the line-items
    table.  Non-blocking — commit proceeds either way."""
    qi = mp.quote_in
    if not qi:
        return
    line_items = qi.get("line_items") or []
    subtotal = qi.get("subtotal")
    if subtotal is None or not line_items:
        qi["line_total_subtotal_mismatch_cents"] = 0
        return
    try:
        sum_line_total = sum(
            float(li.get("line_total") or 0.0)
            for li in line_items
        )
        subtotal_f = float(subtotal)
    except (TypeError, ValueError):
        return
    delta_cents = int(round((sum_line_total - subtotal_f) * 100))
    qi["line_total_subtotal_mismatch_cents"] = delta_cents
    if abs(delta_cents) > 1:  # > $0.01
        logger.warning(
            "pdf_import.estimate.line_total_subtotal_mismatch "
            "source_doc_index=%d sum_line_total=%.2f subtotal=%.2f "
            "delta_cents=%d",
            getattr(mp, "source_doc_index", -1),
            sum_line_total, subtotal_f, delta_cents,
        )


def apply_preview_post_processing(
    mapper_previews: List[MapperReport],
    *,
    hint_doc_kind: Optional[str] = None,
) -> None:
    """Run every defensive post-processor over ``mapper_previews``
    in place.  Called by the import background task right before
    the previews are serialised onto the ``db.import_batches`` doc.

    Idempotent — safe to re-run on the same previews list (e.g. a
    retry path).  Preserves every existing field on ``quote_in``;
    only adds new sibling fields documented in the module header.
    """
    for mp in mapper_previews:
        if mp is None:
            continue
        _apply_doc_type_override(mp, hint_doc_kind)
        _apply_customer_name_demotion(mp)
        _apply_line_total_subtotal_check(mp)
