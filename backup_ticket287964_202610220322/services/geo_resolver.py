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

import logging
import time
from typing import Any, Dict, Optional, Tuple


# Public: mapping value used for the ``coord_source`` audit field
# on response payloads. Kept as a module-level constant so tests
# and callers stay in sync on the exact string.
COORD_SOURCE_JOB = "job"
COORD_SOURCE_PROPERTY = "property"
COORD_SOURCE_CUSTOMER = "customer"


# Phase A.5 · Feb-2026 — in-process TTL set used to dedupe the
# "pin dropped" WARNING log in ``resolve_job_coordinates``. A
# single scheduled job can resolve to ``None`` dozens of times a
# day (one per schedule-map poll); without dedup the log blows up.
# 24h TTL keyed by ``(tenant_id, job_id)``. In-process is fine —
# the log is operator-facing instrumentation, not a cross-service
# audit.
_PIN_DROP_LOG_TTL_S = 24 * 60 * 60
_pin_drop_log_last: Dict[Tuple[str, str], float] = {}
_logger = logging.getLogger(__name__)


def _log_pin_drop_if_fresh(
    tenant_id: Optional[str],
    job_id: Optional[str],
    job: Dict[str, Any],
    reason: str,
) -> None:
    """Emit a WARNING log for a dropped-pin resolution once per
    ``(tenant_id, job_id)`` in a rolling 24h window. Operator
    instrumentation only — never raises.
    """
    if not tenant_id or not job_id:
        return
    key = (tenant_id, job_id)
    now = time.time()
    last = _pin_drop_log_last.get(key)
    if last is not None and (now - last) < _PIN_DROP_LOG_TTL_S:
        return
    _pin_drop_log_last[key] = now
    # Opportunistic cleanup — prune stale entries when the set
    # grows unbounded so a long-lived process doesn't leak.
    if len(_pin_drop_log_last) > 10000:
        cutoff = now - _PIN_DROP_LOG_TTL_S
        for k in list(_pin_drop_log_last):
            if _pin_drop_log_last[k] < cutoff:
                _pin_drop_log_last.pop(k, None)
    _logger.warning(
        "[geo-resolver] pin dropped: "
        "tenant_id=%s job_id=%s property_id=%s customer_id=%s "
        "reason=%s",
        tenant_id, job_id,
        job.get("property_id"), job.get("customer_id"),
        reason,
    )


def _coerce_pair(lat: Any, lng: Any) -> Optional[Tuple[float, float]]:
    """Return ``(lat, lng)`` as floats iff BOTH are non-null,
    non-empty, and coerce cleanly to ``float``. Otherwise ``None``.

    Guards against three edge cases seen in preview data:
      1. ``None`` values (unset field on the doc).
      2. Empty strings ``""`` (legacy CSV import artifacts).
      3. Strings that look numeric but fail ``float()`` (rare —
         mangled paste-in from spreadsheets).

    Phase A.5 · Feb-2026 — ``(0, 0)`` is also treated as invalid.
    A February-2026 Mongo audit of the preview tenant surfaced a
    235-property cluster at a tenant-centroid where a legacy bulk
    geocode had written identical coords because the input
    addresses were under-specified. (0, 0) itself — the Gulf-of-
    Guinea landmark — would be an even more obvious bug. Both
    cases are now filtered here so the resolver returns ``None``
    instead of silently pinning jobs to a shared bad point. The
    ``coord_source`` wire enum (``"job" | "property" | "customer"
    | null``) does NOT grow — zero coords simply fall through to
    the next rung and ultimately drop the pin.
    """
    if lat is None or lng is None:
        return None
    if isinstance(lat, str) and not lat.strip():
        return None
    if isinstance(lng, str) and not lng.strip():
        return None
    try:
        flat = float(lat)
        flng = float(lng)
    except (TypeError, ValueError):
        return None
    # Phase A.5 — treat (0, 0) as invalid. Both axes must be zero
    # to filter; a legitimate equator- or prime-meridian-adjacent
    # coord (one axis zero, other non-zero) is kept.
    if flat == 0.0 and flng == 0.0:
        return None
    return (flat, flng)


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
    #
    # Phase A.5 · Feb-2026 — emit a dedup'd WARNING log so
    # operators can diagnose silent pin drops. Only fires when
    # the caller passed a non-empty ``customer_lookup`` (i.e. the
    # customer rung was actually attempted). ``routers/jobs.py``
    # calls this helper TWICE per job — once with ``{}`` to try
    # just the job rung, then again with the full ``cmap`` after
    # the inline property rung didn't fire. The log should only
    # emit on the SECOND call (the "I give up" call), so the
    # empty-lookup first call is skipped here.
    if customer_lookup:
        if cust_id:
            # Determine why the customer rung didn't win so the log
            # reason is actionable.
            cust = customer_lookup.get(cust_id)
            if cust is None:
                reason = "no_customer_in_lookup"
            else:
                raw_lat = cust.get("service_lat")
                raw_lng = cust.get("service_lng")
                if raw_lat is None or raw_lng is None:
                    reason = "no_property_coords_no_customer_coords"
                else:
                    # The only remaining path to None here is the
                    # Phase A.5 (0, 0) filter.
                    try:
                        if float(raw_lat) == 0.0 and float(raw_lng) == 0.0:
                            reason = "customer_zero_coords"
                        else:
                            reason = "no_property_coords_no_customer_coords"
                    except (TypeError, ValueError):
                        reason = "no_property_coords_no_customer_coords"
        else:
            reason = "no_property_coords_no_customer_id"
        _log_pin_drop_if_fresh(
            job.get("tenant_id"), job.get("id"), job, reason,
        )
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


# ═══════════════════════════════════════════════════════════════════
# TD-39 · Feb-2026 — Property-rung parity.
#
# ``routers/jobs.py`` ships the full 4-rung ladder (job → property →
# customer → None) with the property rung implemented INLINE between
# the two shared-helper calls. ``routers/schedule.py`` + ``routers/
# dispatch_board.py`` both bypass the property rung entirely — they
# call ``resolve_job_coordinates(job, cust_map)`` directly and have
# always skipped straight from job to customer. For a tenant whose
# properties are geocoded but whose customer billing-addresses are
# NOT, the schedule-map + dispatch-board drop pins that `/api/jobs`
# correctly plots. The fix lifts the inline rung into this shared
# module so all three endpoints share one source of truth, and
# ``jobs.py`` can collapse its inline block.
#
# Enum contract (DOES NOT GROW): ``"job" | "property" | "customer" |
# null`` — same values ``jobs.py`` has emitted since Phase 4. Callers
# that still hand in only a ``customer_lookup`` (no property
# lookup) can keep using ``resolve_job_coordinates`` unchanged; it
# emits the 3-rung ``"job" | "customer" | null`` subset.
# ═══════════════════════════════════════════════════════════════════


def _property_coord_pair(
    prop: Optional[Dict[str, Any]],
) -> Optional[Tuple[float, float]]:
    """Extract ``(lat, lng)`` from a property doc, matching the
    ``jobs.py`` inline rung's exact precedence:

      * ``latitude`` / ``longitude`` (newer geocoder write path)
      * fall back to ``lat`` / ``lng`` (flat schema shape)

    Honors ``_coerce_pair`` guards: ``None`` / empty-string / unparse-
    able / ``(0, 0)`` all resolve to ``None``.
    """
    if not prop:
        return None
    p_lat = prop.get("latitude")
    if p_lat is None:
        p_lat = prop.get("lat")
    p_lng = prop.get("longitude")
    if p_lng is None:
        p_lng = prop.get("lng")
    return _coerce_pair(p_lat, p_lng)


def resolve_job_coordinates_with_property(
    job: Dict[str, Any],
    customer_lookup: Dict[str, Dict[str, Any]],
    property_lookup: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Full 4-rung resolver. Priority (higher wins):

      1. Job's own coords (``site_lat/lng`` / ``latitude/longitude``
         / ``lat/lng`` — first non-null pair wins).
         Returns ``source = "job"``.
      2. Linked property's ``latitude`` / ``longitude`` (fallback
         ``lat`` / ``lng``). Only consulted when the job carries a
         ``property_id`` present in ``property_lookup``. Caller
         controls tenant scope by only inserting tenant-scoped
         property docs into the lookup (identical safety contract
         to the ``customer_lookup`` rung).
         Returns ``source = "property"``.
      3. Linked customer's ``service_lat`` / ``service_lng`` — the
         pre-K58 baseline.
         Returns ``source = "customer"``.
      4. Neither → ``(None, None, None)``.

    Never mutates ``job`` / ``customer_lookup`` / ``property_lookup``.
    Zero-coord ``(0, 0)`` on ANY rung is filtered via ``_coerce_pair``
    — the ladder falls through to the next rung instead of pinning
    the job at the Gulf-of-Guinea landmark. See TECH_DEBT.md · TD-39
    for the full root-cause story.
    """
    # Rung 1 — delegate to the shared helper with an empty customer
    # lookup so the helper tries ONLY the job's own coords (prevents
    # it from falling to the customer rung before we've attempted
    # the property rung).
    lat, lng, source = resolve_job_coordinates(job, {})
    if source is not None:
        return (lat, lng, source)

    # Rung 2 — property fallback.
    pid = job.get("property_id")
    if pid:
        prop = property_lookup.get(pid)
        pair = _property_coord_pair(prop)
        if pair is not None:
            return (pair[0], pair[1], COORD_SOURCE_PROPERTY)

    # Rung 3 — customer fallback. Re-enter the shared helper with
    # the full customer lookup so the pin-drop dedup WARNING logs
    # from ``resolve_job_coordinates`` continue to fire exactly once
    # per ``(tenant_id, job_id)`` 24h window on the "I give up" path.
    return resolve_job_coordinates(job, customer_lookup)


async def build_property_coord_lookup(
    db,
    tenant_id: str,
    property_ids,
) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch a tenant-scoped ``properties`` projection keyed by
    id, mirroring :func:`build_customer_coord_lookup`'s contract.

    Projection includes BOTH coordinate shape variants:

      * ``latitude`` / ``longitude`` — newer geocoder write path.
      * ``lat`` / ``lng``             — flat/legacy shape.

    Skips the round trip entirely when ``property_ids`` is empty.
    Dedupes IDs so N jobs sharing a property only cost one ``$in``
    slot. Tenant_id filter is REQUIRED to prevent cross-tenant coord
    leaks — same contract as the customer helper.
    """
    ids = [pid for pid in (property_ids or []) if pid]
    if not ids:
        return {}
    unique_ids = list({pid for pid in ids})
    cursor = db.properties.find(
        {"tenant_id": tenant_id, "id": {"$in": unique_ids}},
        # TD-schedule-address · Feb-2026 — projection extended with
        # ``address`` (sub-doc) + ``deleted_at`` so the shared
        # ``services.address_resolver.resolve_job_address_from_batches``
        # can run the FK-ladder compose off the same batch result
        # (no second ``properties`` round-trip for address lookup).
        {"_id": 0, "id": 1,
         "latitude": 1, "longitude": 1,
         "lat": 1, "lng": 1,
         "address": 1, "deleted_at": 1},
    )
    rows = await cursor.to_list(len(unique_ids))
    return {r["id"]: r for r in rows if r.get("id")}
