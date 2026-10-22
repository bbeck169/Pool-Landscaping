"""Shared address-resolver — TD-schedule-address · Feb-2026.

Extracted from ``services.auto_visit_email`` (which pioneered the
FK-ladder resolve-at-read-time pattern on the auto-visit-email
path).  Both the auto-visit email render path AND the
``/api/schedule/today`` schedule-page response now resolve the
"current" job address live via the same FK ladder:

  1. ``job.property_id``                → ``db.properties.address``
  2. ``customer.primary_property_id``   → ``db.properties.address``
  3. ``customer.service_address`` / ``.address`` / ``.billing_address``
  4. ``job.address`` / ``job.site_address`` (text snapshot fallback)

The schedule endpoint already batch-fetches properties + customers
for coord resolution (`build_property_coord_lookup` +
`build_customer_coord_lookup`); the sync helper here reuses those
batches so address resolution is zero-extra-roundtrip.

Mirrors ``services.auto_visit_email._format_property_address`` so
the email path keeps identical compose semantics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


def format_property_address(prop: Mapping[str, Any]) -> str:
    """Compose ``"line1, city, STATE POSTAL"`` from a property doc.

    Returns an empty string when the property has no usable address
    fragments — the caller falls back to the next ladder rung.

    Must stay byte-identical to the auto-visit-email path's prior
    inlined ``_format_property_address`` to preserve the regression
    coverage locked by ``test_auto_visit_email_address.py``.
    """
    addr = prop.get("address")
    if not isinstance(addr, dict):
        return ""
    line1 = (addr.get("line1") or "").strip()
    line2 = (addr.get("line2") or "").strip()
    city = (addr.get("city") or "").strip()
    state = (addr.get("state") or "").strip()
    postal = (addr.get("postal_code") or "").strip()
    street = ", ".join(p for p in (line1, line2) if p)
    tail = " ".join(p for p in (state, postal) if p).strip()
    # Mirror the customer-side composition (see
    # ``routers.customers._mirror_address_to_primary_property``).
    parts: List[str] = []
    if street:
        parts.append(street)
    if city:
        parts.append(city)
    if tail:
        parts.append(tail)
    return ", ".join(parts)


def property_belongs_to_customer(
    prop: Mapping[str, Any], customer_id: Optional[str],
) -> bool:
    """True unless the property is provably owned by a DIFFERENT customer.

    Legacy property docs without ``customer_id`` (and callers without a
    customer to compare) are trusted, preserving prior behaviour.  Added
    for ticket 287964: a job / template whose ``property_id`` points at
    another customer's property must never drive the displayed address.
    """
    owner = prop.get("customer_id")
    if not owner or not customer_id:
        return True
    return owner == customer_id


def resolve_job_address_from_batches(
    job: Mapping[str, Any],
    cust_map: Dict[str, Dict[str, Any]],
    prop_map: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Synchronous FK-ladder resolve using already-batched maps.

    Returns the first non-empty address found down the ladder;
    final fallback is the job's snapshot (``job.address`` →
    ``job.site_address``).  Never raises.

    Expected input shape:

    * ``cust_map`` keyed by ``customer.id`` with (at minimum):
      ``primary_property_id`` + ``service_address`` + ``address`` +
      ``billing_address``.
    * ``prop_map`` keyed by ``property.id`` with (at minimum):
      ``address`` (sub-doc) + ``deleted_at`` (optional).

    Deleted / cross-tenant properties resolve via
    ``build_property_coord_lookup`` which already applies tenant
    scoping; ``deleted_at`` is honored here to avoid rendering a
    deleted property's address.
    """
    # Rung 1: job.property_id
    pid = job.get("property_id")
    cust_id = job.get("customer_id") or ""
    cust = cust_map.get(cust_id) or {}

    # Rung 2: customer.primary_property_id (only when rung 1 miss)
    if not pid:
        pid = cust.get("primary_property_id")

    # Ticket 287964: ignore a linked property owned by a different
    # customer and fall through to this customer's own primary property.
    def _usable(candidate_pid):
        p = prop_map.get(candidate_pid) or {}
        return (
            p and not p.get("deleted_at")
            and property_belongs_to_customer(p, cust_id)
        )

    if pid and not _usable(pid):
        pid = cust.get("primary_property_id") if pid != cust.get("primary_property_id") else None

    if pid and _usable(pid):
        composed = format_property_address(prop_map[pid])
        if composed:
            return composed

    # Rung 3: customer.service_address → .address → .billing_address
    for key in ("service_address", "address", "billing_address"):
        val = cust.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Rung 4: job snapshot fallback (previous behavior).
    snapshot = (job.get("address") or job.get("site_address") or "")
    if isinstance(snapshot, str) and snapshot.strip():
        return snapshot.strip()
    return ""


async def correct_cross_customer_job_addresses(
    db,
    tenant_id: str,
    docs: List[Dict[str, Any]],
    cust_map: Dict[str, Dict[str, Any]],
    prop_map: Dict[str, Dict[str, Any]],
) -> int:
    """Response-only fix for jobs linked to ANOTHER customer's property.

    Ticket 287998: ``GET /api/jobs`` (calendar / dispatch schedule) returned
    the stored ``job.address`` snapshot verbatim, so jobs whose
    ``property_id`` points at a different customer's property showed that
    customer's street (several cards with one address) and the Navigate
    button (which reads ``address``) routed there.  For every such job,
    swap in the job's OWN customer's address: first that customer's active
    property, else the shared FK-ladder fallback (customer address fields).

    Mutates ``docs`` in place (``address`` / ``property_label`` /
    ``property_address`` + ``address_corrected`` flag); never writes to the
    DB.  Jobs whose property belongs to the job's customer, has no owner
    recorded, or is absent from ``prop_map`` are left untouched.  Returns
    the number of jobs corrected.
    """
    bad_cids = set()
    for d in docs:
        pid = d.get("property_id")
        prop = prop_map.get(pid) if pid else None
        if prop and not property_belongs_to_customer(prop, d.get("customer_id")):
            bad_cids.add(d.get("customer_id"))
    if not bad_cids:
        return 0

    own_by_cust: Dict[str, Dict[str, Any]] = {}
    try:
        rows = await db.properties.find(
            {"tenant_id": tenant_id, "customer_id": {"$in": list(bad_cids)},
             "active": {"$ne": False}, "deleted_at": None},
            {"_id": 0, "id": 1, "customer_id": 1, "label": 1, "address": 1,
             "sort_order": 1},
        ).to_list(len(bad_cids) * 10)
        for r in sorted(rows, key=lambda x: x.get("sort_order") or 0):
            own_by_cust.setdefault(r.get("customer_id"), r)
    except Exception:  # non-fatal: fall back to the customer-address rungs
        own_by_cust = {}

    fixed = 0
    for d in docs:
        pid = d.get("property_id")
        prop = prop_map.get(pid) if pid else None
        if not prop or property_belongs_to_customer(prop, d.get("customer_id")):
            continue
        own = own_by_cust.get(d.get("customer_id"))
        addr = format_property_address(own) if own else ""
        if not addr:
            # Guarded ladder: skips the foreign property, then customer
            # address fields, then the (stale) job snapshot as last resort.
            addr = resolve_job_address_from_batches(d, cust_map, prop_map) or ""
        d["property_label"] = (own or {}).get("label") or None
        d["property_address"] = format_property_address(own) if own else None
        if addr:
            d["address"] = addr
        d["address_corrected"] = True
        fixed += 1
    return fixed
