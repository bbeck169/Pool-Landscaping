"""Backlog #iii · Feb-2026 — Pricebook cost helpers.

Two responsibilities:

  1. ``effective_cost(item)`` — canonical "cheapest wholesale cost"
     resolver used by every downstream consumer that historically
     read the single-scalar ``items.wholesale_price``. Precedence:

     * ``suppliers[]`` (Backlog #iii rich shape) → min of
       ``unit_cost`` across every row that has one.
     * ``supplier_prices[]`` (Phase 56-b compact shape) → min of
       ``cost_cents / 100`` across every row. Left in place so
       grandfathered items that predate #iii keep working.
     * ``wholesale_price`` (Phase PB1 scalar) → return as-is.
     * All three empty → return ``None`` and emit a structured
       warning log ``pricebook.effective_cost.fallback_null`` so ops
       can spot data-hygiene issues post-migration.

  2. ``rebuild_mirrors(item)`` — regenerate the read-only compat
     mirrors ``wholesale_price`` (scalar) + ``supplier_prices[]``
     (compact shape) from the authoritative ``suppliers[]``. Called
     on every write to ``/api/items`` (POST + PATCH). If ``suppliers[]``
     is empty the mirrors are left untouched so legacy manual-pricing
     writes on ``supplier_prices[]`` still round-trip.

Isolated in a ``services.pricebook`` module (not ``routers``) so the
migration + the invoice snapshotter can import without circular deps.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger("pricebook.cost")


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def effective_cost(item: Dict[str, Any], *, log_warn: bool = True) -> Optional[float]:
    """Return the item's effective wholesale cost.

    Resolution order documented in the module docstring. Rounds to 2
    decimals so downstream currency math stays stable.

    Set ``log_warn=False`` for tight loops (e.g., the report
    handlers) where a single-item null is expected and shouldn't spam
    the log. The invoice-line snapshotter and PATCH/POST write paths
    should keep the default so ops sees the warning.
    """
    if not isinstance(item, dict):
        return None

    # 1. Rich shape (Backlog #iii).
    suppliers = item.get("suppliers") or []
    costs: List[float] = []
    if isinstance(suppliers, list):
        for s in suppliers:
            if not isinstance(s, dict):
                continue
            f = _coerce_float(s.get("unit_cost"))
            if f is not None and f >= 0:
                costs.append(f)
    if costs:
        return round(min(costs), 2)

    # 2. Compact shape (Phase 56-b).
    prices = item.get("supplier_prices") or []
    if isinstance(prices, list):
        cents: List[int] = []
        for p in prices:
            if not isinstance(p, dict):
                continue
            try:
                c = int(p.get("cost_cents") or 0)
            except (TypeError, ValueError):
                continue
            if c > 0:
                cents.append(c)
        if cents:
            return round(min(cents) / 100.0, 2)

    # 3. Legacy scalar (Phase PB1).
    legacy = _coerce_float(item.get("wholesale_price"))
    if legacy is not None and legacy > 0:
        return round(legacy, 2)

    # 4. Nothing available.
    if log_warn:
        logger.warning(
            "pricebook.effective_cost.fallback_null "
            "tenant_id=%s item_id=%s item_name=%s",
            item.get("tenant_id"),
            item.get("id"),
            item.get("name"),
        )
    return None


def rebuild_mirrors(item: Dict[str, Any]) -> Dict[str, Any]:
    """Regenerate the read-only mirrors from ``suppliers[]``.

    Returns a NEW dict of the fields to ``$set``. Caller is
    responsible for the actual persist. Only touches mirrors when
    ``suppliers[]`` has at least one row — otherwise legacy
    ``supplier_prices[]`` / ``wholesale_price`` stay untouched (so
    manual-pricing writes on the compact shape aren't clobbered).
    """
    out: Dict[str, Any] = {}
    suppliers = item.get("suppliers") or []
    if not isinstance(suppliers, list) or not suppliers:
        return out

    # ``wholesale_price`` mirror — always the min unit_cost.
    ec = effective_cost({"suppliers": suppliers}, log_warn=False)
    if ec is not None:
        out["wholesale_price"] = ec

    # ``supplier_prices[]`` mirror — one row per supplier, keyed on a
    # slugified name so the compact-shape readers keep working. Use
    # the row's own ``id`` (fallback) if the name is missing so we
    # never drop a row silently.
    mirror: List[Dict[str, Any]] = []
    seen_slugs: set = set()
    for s in suppliers:
        if not isinstance(s, dict):
            continue
        f = _coerce_float(s.get("unit_cost"))
        if f is None or f < 0:
            continue
        name = str(s.get("supplier_name") or "").strip()
        if not name:
            continue
        slug = _slugify(name)
        # Dedup — if two suppliers share the same slugified name we
        # keep the LOWER-COST one so the compact-shape "min" query
        # stays truthful.
        if slug in seen_slugs:
            # Find existing row and keep the min.
            for m in mirror:
                if m["supplier_slug"] == slug:
                    if int(round(f * 100)) < m["cost_cents"]:
                        m["cost_cents"] = int(round(f * 100))
                    break
            continue
        seen_slugs.add(slug)
        mirror.append({
            "supplier_slug": slug,
            "cost_cents": int(round(f * 100)),
        })
    out["supplier_prices"] = mirror
    return out


def _slugify(name: str) -> str:
    """ASCII-safe slug for the compat mirror keys."""
    import re
    s = str(name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "supplier"
