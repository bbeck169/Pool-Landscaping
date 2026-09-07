"""Phase K79 · Feb-2026 — Grouped customer-facing estimate view.

Aggregation helper that rolls up ``quote.line_items[]`` by their
``service_category_id`` for customer-facing surfaces (public email
link, portal, PDF).

Design rules:
    * Groups render in the order of first appearance in ``line_items[]``.
      Admins reorder line items to control the customer's reading order.
    * Lines missing ``service_category_id`` bucket into a single
      "Other" group at the tail.
    * The K71 ``long_description`` is INTERNAL-ONLY and must NEVER leak
      into a grouped row (contract locked by test).
    * Subtotal per group = sum(qty * unit_price) with 2dp rounding.
    * Currency preserved from the quote doc (falls back to "USD").
    * The doc-level tax / discount / total continue to be rendered
      by the surface — this helper only groups the LINE items.
    * Group descriptions come from
      ``quote.customer_group_descriptions[service_category_id]``.
      Missing keys yield no description (empty string is fine).

The helper is a pure function so it can be unit-tested without a DB
round-trip. Consumers pass in the pre-loaded service-category list.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


_OTHER_KEY = "__other__"
_OTHER_LABEL = "Other"


def _resolve_label(cat_id: str,
                   categories: List[Dict[str, Any]]) -> str:
    """Return the human label for a service_category_id.

    Falls back to the id itself if the category isn't in the list
    (defensive against a category deleted after the quote was written).
    """
    for c in categories:
        if c.get("id") == cat_id:
            return c.get("name") or cat_id
    return cat_id


def group_lines_for_customer(
    quote: Dict[str, Any],
    service_categories: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Roll up quote line items into customer-facing groups.

    Args:
        quote: full quote document (needs ``line_items`` and
            ``customer_group_descriptions``, plus optional ``currency``).
        service_categories: tenant-scoped list of service categories
            for label resolution. If None, labels fall back to the id.

    Returns:
        List of ``{category_id, label, description, subtotal, currency}``
        dicts, ordered by first appearance in ``line_items[]``. The
        "Other" bucket, if any, is appended last.
    """
    lines: List[Dict[str, Any]] = quote.get("line_items") or []
    descriptions: Dict[str, str] = (
        quote.get("customer_group_descriptions") or {}
    )
    currency = quote.get("currency") or "USD"
    cats = service_categories or []

    # Preserve first-appearance order without a helper OrderedDict —
    # a plain dict on 3.7+ is ordered by insertion.
    buckets: Dict[str, Dict[str, Any]] = {}
    for li in lines:
        raw_id = li.get("service_category_id")
        cat_id = raw_id if isinstance(raw_id, str) and raw_id.strip() else _OTHER_KEY

        qty = float(li.get("quantity") or 0)
        unit_price = float(li.get("unit_price") or 0)
        line_subtotal = qty * unit_price

        if cat_id not in buckets:
            label = (_OTHER_LABEL if cat_id == _OTHER_KEY
                     else _resolve_label(cat_id, cats))
            desc = descriptions.get(cat_id, "") if cat_id != _OTHER_KEY else ""
            buckets[cat_id] = {
                "category_id": None if cat_id == _OTHER_KEY else cat_id,
                "label": label,
                "description": (desc or "").strip(),
                "subtotal": 0.0,
                "currency": currency,
            }
        buckets[cat_id]["subtotal"] += line_subtotal

    # Round subtotals + push the "Other" bucket to the tail.
    result: List[Dict[str, Any]] = []
    other: Optional[Dict[str, Any]] = None
    for key, row in buckets.items():
        row["subtotal"] = round(row["subtotal"], 2)
        if key == _OTHER_KEY:
            other = row
        else:
            result.append(row)
    if other is not None:
        result.append(other)
    return result


def build_customer_view_payload(
    quote: Dict[str, Any],
    service_categories: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return the full customer-view payload for a quote.

    Includes the grouped rows PLUS the doc-level totals (subtotal,
    tax, discount, total) so a surface can render "grouped rows +
    standard totals footer" without a second call.

    NOTE: ``long_description`` is INTENTIONALLY absent — the grouped
    rows never expose per-line internal notes.
    """
    groups = group_lines_for_customer(quote, service_categories)
    tax = float(quote.get("tax") or 0)
    subtotal = float(quote.get("subtotal") or 0)
    discount = float(quote.get("discount_value") or quote.get("discount_amount") or 0)
    total = float(quote.get("total") or 0)
    amount_paid = float(quote.get("amount_paid") or 0)
    grouped_sum = round(sum(g["subtotal"] for g in groups), 2)
    return {
        "customer_group_display": bool(quote.get("customer_group_display")),
        "groups": groups,
        "grouped_subtotal": grouped_sum,
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "discount": round(discount, 2),
        "total": round(total, 2),
        "amount_paid": round(amount_paid, 2),
        "currency": quote.get("currency") or "USD",
    }


__all__ = [
    "group_lines_for_customer",
    "build_customer_view_payload",
]
