"""Phase P26 · Feb-2026 — Coordinate fallback resolver.

Small stateless helper that centralizes the "job coord + customer
service-coord fallback" logic. Extracted from the four inline
implementations that lived in ``routers/jobs.py`` (K58 4-rung
ladder), ``routers/schedule.py`` (``site_lat/lat`` only — the
reported P26 bug), ``routers/dispatch_board.py`` (customer-only in
``jobs_fallback`` path), and ``routers/dispatch.py`` (internal
ranking ``_job_coords``).

Ground rules (per Phase P26 spec):

* NEVER mutates the job document. Serialization-time enrichment
  only — callers apply the resolved value on the response envelope.
* Accepts a **preloaded** ``customer_lookup`` dict (customer_id →
  customer doc) so a batched list endpoint issues ONE customer
  ``find`` for N jobs, not N. Cross-tenant safety is the caller's
  responsibility — pass only tenant-scoped customer docs.
* Returns ``(lat, lng, source)`` where ``source`` is one of
  ``"job"``, ``"customer"``, or ``None``. The tri-state source
  drives the ``coord_source`` audit field on the response so the
  FE can debug + future analytics can measure fallback frequency.

Why this exists (root cause):

Pre-P26 the P22 K15 300-row-cap removal made every scheduled job
visible on the schedule map, but the map was still dropping pins
because ~1500 preview jobs have ``jobs.lat = null`` even though
their linked customer has a populated ``customers.service_lat``.
The various map/emit paths handled the fallback inconsistently:

* ``GET /api/jobs`` (K58 ladder)              → falls back OK.
* ``GET /api/schedule/today`` (this fix)      → dropped pin.
* ``GET /api/dispatch/board`` jobs_fallback   → customer-first
                                                (ignored job's
                                                own coords).

Consolidating the logic here also lets Phase P27 (Workstream
tiles) reuse the same rule without dragging an inline block.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


# Public: mapping value used for the ``coord_source`` audit field
# on response payloads. Kept as a module-level constant so tests
# and callers stay in sync on the exact string.
COORD_SOURCE_JOB = "job"
COORD_SOURCE_CUSTOMER = "customer"


def _coerce_pair(lat: Any, lng: Any) -> Optional[Tuple[float, float]]:
    """Return ``(lat, lng)`` as floats iff BOTH are non-null,
    non-empty, and coerce cleanly to ``float``. Otherwise ``None``.

    Guards against three edge cases seen in preview data:
      1. ``None`` values (unset field on the doc).
      2. Empty strings ``""`` (legacy CSV import artifacts).
      3. Strings that look numeric but fail ``float()`` (rare —
         mangled paste-in from spreadsheets).
    """
    if lat is None or lng is None:
        return None
    if isinstance(lat, str) and not lat.strip():
        return None
    if isinstance(lng, str) and not lng.strip():
        return None
    try:
        return (float(lat), float(lng))
    except (TypeError, ValueError):
        return None


def resolve_job_coordinates(
    job: Dict[str, Any],
    customer_lookup: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Resolve a job's map coordinates with customer-service fallback.

    Priority (higher wins):

      1. Job's own coords — any of ``site_lat`` / ``lat`` /
         ``latitude`` paired with the matching ``lng`` /
         ``longitude`` field. First non-null pair wins so a job
         geocoded by the newer write path (``latitude`` /
         ``longitude``) is preferred over a stale ``lat`` / ``lng``.
         Returns ``source = "job"``.
      2. Linked customer's ``service_lat`` / ``service_lng`` — the
         pre-K58 baseline. Requires the customer to be present in
         ``customer_lookup``; a dangling FK (customer deleted or
         cross-tenant leak the caller filtered out) gracefully
         degrades to ``None``. Returns ``source = "customer"``.
      3. Neither present → ``(None, None, None)``.

    Never mutates ``job`` or ``customer_lookup``.
    """
    # Rung 1 — job's own coords. Try the three field-name variants
    # in priority order (newer geocoder writes ``latitude`` /
    # ``longitude``; older writes ``site_lat`` / ``site_lng``; the
    # flattest is ``lat`` / ``lng``). First hit wins.
    for lat_key, lng_key in (
        ("site_lat", "site_lng"),
        ("latitude", "longitude"),
        ("lat", "lng"),
    ):
        pair = _coerce_pair(job.get(lat_key), job.get(lng_key))
        if pair is not None:
            return (pair[0], pair[1], COORD_SOURCE_JOB)

    # Rung 2 — customer fallback. Caller controls tenant scope by
    # only inserting tenant-scoped customer docs into the lookup.
    cust_id = job.get("customer_id")
    if cust_id:
        cust = customer_lookup.get(cust_id)
        if cust:
            pair = _coerce_pair(
                cust.get("service_lat"), cust.get("service_lng"),
            )
            if pair is not None:
                return (pair[0], pair[1], COORD_SOURCE_CUSTOMER)

    # Rung 3 — no coords anywhere. Frontend drops the pin.
    return (None, None, None)


async def build_customer_coord_lookup(
    db,
    tenant_id: str,
    customer_ids,
) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch a tenant-scoped ``customers`` projection keyed by
    id, for a coord-fallback pass. Skips the round trip entirely
    when ``customer_ids`` is empty.

    Projection is minimal — ``id``, ``service_lat``, ``service_lng``
    — so a list endpoint that only needs coords doesn't pay for
    unrelated fields. Callers that ALSO need ``name``, ``notes``,
    etc. should hoist their own batch fetch rather than
    round-tripping twice.

    Tenant safety: the ``tenant_id`` filter is REQUIRED — passing a
    stale/attacker-controlled tenant_id here would leak coord data
    across tenants. Every caller MUST derive ``tenant_id`` from
    ``get_current_tenant`` (never from the request body).
    """
    ids = [cid for cid in (customer_ids or []) if cid]
    if not ids:
        return {}
    # Dedupe so a repeated ``customer_id`` (multiple jobs for the
    # same customer on the same day) doesn't inflate the ``$in``.
    unique_ids = list({cid for cid in ids})
    cursor = db.customers.find(
        {"tenant_id": tenant_id, "id": {"$in": unique_ids}},
        {"_id": 0, "id": 1, "service_lat": 1, "service_lng": 1},
    )
    rows = await cursor.to_list(len(unique_ids))
    return {r["id"]: r for r in rows if r.get("id")}
