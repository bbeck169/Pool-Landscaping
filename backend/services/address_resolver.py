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
    cust = cust_map.get(job.get("customer_id") or "") or {}

    # Rung 2: customer.primary_property_id (only when rung 1 miss)
    if not pid:
        pid = cust.get("primary_property_id")

    if pid:
        prop = prop_map.get(pid) or {}
        if prop and not prop.get("deleted_at"):
            composed = format_property_address(prop)
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
