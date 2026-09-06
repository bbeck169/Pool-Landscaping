"""Phase R0.1 · Feb-2026 — shared invoice-revenue query helpers.

Both ``revenue_by_customer`` and ``revenue_by_city`` need the same
``quotes``/invoices filter shape:

* ``lens="invoiced"`` — sum ``total`` on every non-deleted quote
  whose ``created_at`` (fallback for the absent ``issued_date``
  field on Feb-2026 quotes) is in the period.
* ``lens="collected"`` — sum ``total`` on quotes with
  ``payment_status="paid"`` whose ``paid_at`` (fallback
  ``created_at``) is in the period.

Both lenses respect the tenant guard + soft-delete guard baked
into :class:`AggregationEngine._scope`.

Filters:

* ``service_type`` — matches customers whose top-level
  ``service_type`` equals the supplied value (customers own the
  service tier, invoices don't).
* ``tech_id`` — matches customers whose ``assigned_tech_ids``
  array contains the supplied technician id.

Both filters resolve into a customer-id whitelist that gets
$in-clamped onto the invoice pipeline. Empty whitelist returns
zero rows without hitting the invoices collection.
"""
from __future__ import annotations

from typing import Optional

from ..aggregation import AggregationEngine
from ..paid_date import build_paid_window_filter


def build_lens_filter(lens: str, start: str, end: str) -> dict:
    """Return the shared invoice filter for a lens + window.

    R1 · Feb-2026 — the ``collected`` branch now delegates to the
    shared ``build_paid_window_filter`` helper so R0.1's
    Revenue-by-Customer / Revenue-by-City metrics reconcile with
    R0's ``revenue_total`` and R1's P&L / cashflow / unpaid
    metrics byte-for-byte. Semantic equivalence preserved: the
    helper's cascade (``paid_at → paid_date → created_at``) is a
    strict superset of the previous local logic.
    """
    if lens == "collected":
        return {"$and": [
            {"payment_status": "paid"},
            build_paid_window_filter(start, end),
        ]}
    # Default: invoiced.
    return {"created_at": {"$gte": start, "$lt": end}}


async def resolve_customer_whitelist(
    engine: AggregationEngine,
    service_type: Optional[str],
    tech_id: Optional[str],
) -> Optional[list[str]]:
    """Return a list of matching customer ids, or ``None`` when
    neither filter is active. An empty list means "no matches" —
    the caller should short-circuit to a zero-row response."""
    if not service_type and not tech_id:
        return None
    cust_filter: dict = {}
    if service_type:
        cust_filter["service_type"] = service_type
    if tech_id:
        cust_filter["assigned_tech_ids"] = tech_id
    ids: list[str] = []
    async for row in engine.db.customers.find(
        engine._scope(cust_filter),
        {"_id": 0, "id": 1},
    ):
        cid = row.get("id")
        if cid:
            ids.append(cid)
    return ids


def parse_city(address: str | None) -> str:
    """Best-effort city extraction from the flat ``address`` string
    used by the Feb-2026 customer schema (e.g. "12 Vistancia Blvd,
    Peoria, AZ" → "Peoria"). Returns ``"(unknown)"`` when the
    address is missing or unparseable — never drops rows."""
    if not address or not isinstance(address, str):
        return "(unknown)"
    parts = [p.strip() for p in address.split(",") if p.strip()]
    # Common shapes:
    #   "line1, City, ST"          → parts[-2]
    #   "line1, City, ST 85383"    → parts[-2]
    #   "City, ST"                 → parts[-2]
    #   "line1, City"              → parts[-1]
    if len(parts) >= 3:
        return parts[-2]
    if len(parts) == 2:
        # Ambiguous — could be "City, ST" or "line1, City".
        second = parts[1]
        if len(second.split()) <= 2 and any(ch.isalpha() for ch in second):
            # If the second piece is 1-2 tokens starting with a letter
            # we lean toward "City, ST"; take the FIRST part as the
            # city. But if it also looks like a state (2 upper), we
            # instead take the FIRST as the city.
            if len(second) == 2 and second.isupper():
                return parts[0]
            return parts[0]
        return parts[0]
    return parts[0] if parts else "(unknown)"
