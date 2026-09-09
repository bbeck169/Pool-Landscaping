"""Feb-2026 · Phase A · Customer per-line-item decline — server-truth
totals recomputation.

Rules (locked by the human):
  1. Line items with ``customer_status == 'declined'`` are excluded from
     the *adjusted* subtotal. All other line items count.
  2. Percent discounts (``discount_type == 'percent'``) are recomputed
     off the reduced subtotal. Fixed-amount discounts stay fixed.
  3. Tax is recomputed off the reduced-and-discounted subtotal so the
     line-item decline propagates through to the final adjusted total.
  4. The doc's top-level status is NEVER auto-transitioned when all
     lines are declined — the customer must explicitly hit top-level
     Decline. This helper only computes numbers; it never mutates
     ``status`` / ``decision``.
  5. When there are no declined line items, the ``adjusted_*`` fields
     match the ``original_*`` fields exactly. Callers can therefore
     compare the two blocks to render a "no adjustment" state or the
     strike-through summary without additional logic.

The output shape is stable; ``recompute_customer_adjusted_totals``
returns a dict that callers merge onto the quote document under new
top-level fields:

    {
      "original_subtotal", "original_discount_value",
      "original_tax", "original_total",
      "adjusted_subtotal", "adjusted_discount_value",
      "adjusted_tax", "adjusted_total",
      "has_declined_lines",
      "declined_line_count",
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _line_total(li: Dict[str, Any]) -> float:
    """Compute a single line item's contribution to the subtotal.

    Uses ``quantity * unit_price`` first (matches the invoice-edit
    +/quotes/quotes.py math). Falls back to ``li['total']`` when the
    line was persisted from the AI estimator (which stores ``total``
    directly).
    """
    qty = li.get("quantity")
    if qty is None:
        qty = li.get("qty_hr")
    price = li.get("unit_price")
    if qty is not None and price is not None:
        try:
            return float(qty) * float(price)
        except (TypeError, ValueError):
            pass
    # AI-estimator rows sometimes only carry a computed ``total``.
    try:
        return float(li.get("total") or 0)
    except (TypeError, ValueError):
        return 0.0


def _compute_block(line_items: List[Dict[str, Any]],
                    tax_rate: float,
                    discount_amount: float,
                    discount_type: Optional[str]) -> Dict[str, float]:
    """Server-authoritative subtotal → discount → tax → total math.

    Mirrors ``routers/invoice_edit.py::_compute_totals`` so the two
    surfaces produce identical numbers when fed the same rows.
    """
    subtotal = sum(_line_total(li) for li in (line_items or []))
    if discount_type == "percent":
        discount_value = subtotal * (float(discount_amount or 0) / 100.0)
    else:
        discount_value = float(discount_amount or 0)
    discounted_subtotal = max(subtotal - discount_value, 0.0)
    tax = round(discounted_subtotal * (float(tax_rate or 0) / 100.0), 2)
    total = round(discounted_subtotal + tax, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount_value": round(discount_value, 2),
        "tax": tax,
        "total": total,
    }


def recompute_customer_adjusted_totals(quote: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the ``original_*`` + ``adjusted_*`` totals block.

    ``quote`` is the raw ``db.quotes`` document dict — the helper reads
    ``line_items``, ``tax_rate``, ``discount_amount`` and
    ``discount_type`` off it. It does NOT mutate the passed dict.

    Returns a dict with 10 numeric + counter fields; callers merge this
    onto the doc via ``db.quotes.update_one`` after any per-line
    decline / undecline.
    """
    line_items = list(quote.get("line_items") or [])
    tax_rate = float(quote.get("tax_rate") or 0)
    discount_amount = float(quote.get("discount_amount") or 0)
    discount_type = quote.get("discount_type") or "fixed"

    original = _compute_block(line_items, tax_rate,
                                discount_amount, discount_type)

    active = [li for li in line_items
              if (li.get("customer_status") or "pending") != "declined"]
    declined_count = len(line_items) - len(active)

    if declined_count == 0:
        # No customer decline signal → adjusted block mirrors original.
        adjusted = dict(original)
    else:
        adjusted = _compute_block(active, tax_rate,
                                    discount_amount, discount_type)

    return {
        "original_subtotal": original["subtotal"],
        "original_discount_value": original["discount_value"],
        "original_tax": original["tax"],
        "original_total": original["total"],
        "adjusted_subtotal": adjusted["subtotal"],
        "adjusted_discount_value": adjusted["discount_value"],
        "adjusted_tax": adjusted["tax"],
        "adjusted_total": adjusted["total"],
        "has_declined_lines": declined_count > 0,
        "declined_line_count": declined_count,
    }
