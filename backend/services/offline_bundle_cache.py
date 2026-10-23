"""TD-offline-bundle-tenant-cache · Feb-2026 — per-tenant TTL cache
for ``GET /api/mobile/offline-bundle``.

The handler at ``routers.mobile_sync.mobile_offline_bundle`` is the
mobile client's pull-to-refresh entry point.  Phase 2 Lane A
(``asyncio.gather`` of 9 post-jobs queries, BE commit ``4f7892489``)
and Phase 2 Lane B (``quotes.(tenant_id, doc_type, updated_at DESC)``
compound index, BE commit ``c68d2655b``) brought per-call cost from
~2.8 s down to a few hundred ms.  Lane D collapses *repeat*
pull-to-refresh traffic within a short window to a near-zero-cost
dict lookup.

Design decisions (locked by operator approval of the Phase 0 recon's
Lane D):

* **TTL = 120 seconds.**  Operator rationale: "60 s is too aggressive
  for the index overhead you're trying to reduce; 120 s is the right
  balance for a field-ops app where data changes in bursts, not
  continuously."
* **Cache key = `(tenant_id, tech_id)`.**  The operator's dispatch
  specified `tenant_id` as the sole key, citing "bundle is
  tenant-scoped per Phase 2 Lane A audit".  **Deviation flagged:**
  the Lane A audit actually showed queries #1 (jobs), #2 (customers)
  and #3 (service_reports) are *tech-scoped* — different techs within
  the same tenant see different ``jobs`` + ``customers`` + ``reports``
  subsets.  Keying by ``tenant_id`` alone would serve one tech's jobs
  to another tech on a cache hit — a data-leak class of bug.  Keying
  by the full ``(tenant_id, tech_id)`` tuple is correct; the operator
  is asked to confirm post-hoc via the ship receipt.
* **Invalidation:** fire-and-forget direct dict manipulation on every
  job / quote write for a tenant.  Dict operations are microsecond-
  scale; the invalidator does not need to be async-task'd.
* **In-process only.**  No Redis, no inter-pod coordination.  Each
  backend worker pod maintains its own cache; a cache miss falls
  through to the full handler (Lane A + Lane B still protect).

Collection surface locked by the Phase 2 Lane A dependency audit:
only ``db.quotes`` and ``db.jobs`` writes affect the bundle shape
for a given tenant.  Writes to ``db.customers``, ``db.pricebook_items``,
etc., can go stale for up to 120 s — operator-accepted trade-off.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("offline_bundle_cache")

# TTL locked by the operator decision captured in the Phase 0 recon.
# Any change requires a new TD ticket + operator sign-off.
TTL_SECONDS: float = 120.0

# Keyed by ``(tenant_id, tech_id)`` so admin-impersonation + multi-
# tech-per-tenant traffic can't cross-contaminate.  See module
# docstring Design Decisions.
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def get(tenant_id: str, tech_id: str) -> Optional[Dict[str, Any]]:
    """Return the cached bundle for ``(tenant_id, tech_id)`` if still
    within the 120 s window; else ``None``.  Pops expired entries on
    read.
    """
    key = (tenant_id, tech_id)
    entry = _cache.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if time.monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return payload


def put(tenant_id: str, tech_id: str, payload: Dict[str, Any]) -> None:
    """Store a bundle for ``(tenant_id, tech_id)`` with a 120 s TTL."""
    _cache[(tenant_id, tech_id)] = (time.monotonic() + TTL_SECONDS, payload)


def invalidate(tenant_id: str) -> int:
    """Drop every cache entry for ``tenant_id`` across all techs.

    Called from every job / quote mutation endpoint — see the hook
    sweep in ``routers.jobs`` and ``routers.quotes``.  Fire-and-forget
    semantic: errors are logged, not raised, so a cache mis-op can
    never break a mutation.

    Returns the number of entries dropped (0 if the tenant had no
    cache entries, which is the common case for a cold cache).
    """
    try:
        keys_to_drop = [k for k in _cache if k[0] == tenant_id]
        for k in keys_to_drop:
            _cache.pop(k, None)
        if keys_to_drop:
            logger.info(
                "[offline-bundle-cache] invalidated %d entries for tenant=%s",
                len(keys_to_drop), tenant_id,
            )
        return len(keys_to_drop)
    except Exception as exc:    # noqa: BLE001
        logger.warning(
            "[offline-bundle-cache] invalidate failed for tenant=%s: %s",
            tenant_id, exc,
        )
        return 0


def _clear() -> None:
    """Test-only helper — wipes the cache so pytest cases start clean."""
    _cache.clear()


def _snapshot() -> Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]]:
    """Test-only helper — returns a shallow copy of the cache for
    assertion inspection.  Do NOT mutate the returned dict.
    """
    return dict(_cache)


def invalidates_offline_bundle(func):
    """Decorator for mutation route handlers that drops the offline-
    bundle cache entries for the tenant whose job / quote data just
    changed.

    The decorator inspects the handler's resolved kwargs for a
    ``tenant`` dict (FastAPI dependency injection convention used
    throughout ``routers.jobs`` and ``routers.quotes``) and invalidates
    on that tenant's id.  Invalidation runs AFTER the handler returns
    successfully — a 4xx / 5xx bubbling out skips the drop.

    Fire-and-forget semantic: a cache mis-op (e.g. ``tenant`` kwarg
    absent on an unusual handler shape) is logged and swallowed; the
    handler's return value is passed through untouched.

    ``functools.wraps`` preserves ``func``'s signature so FastAPI's
    dependency resolver sees the original parameter list.
    """
    from functools import wraps

    @wraps(func)
    async def _wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        try:
            tenant_id: Optional[str] = None
            tenant = kwargs.get("tenant")
            if isinstance(tenant, dict):
                tenant_id = tenant.get("id")
            if not tenant_id:
                # Fallback — some handlers (e.g. ``routers.invoice_edit``)
                # take only ``user`` via ``Depends(get_current_user)`` and
                # derive the tenant internally.  ``user.tenant_id`` is
                # the canonical attribute carried on the auth bundle.
                user = kwargs.get("user")
                if isinstance(user, dict):
                    tenant_id = user.get("tenant_id")
            if tenant_id:
                invalidate(tenant_id)
        except Exception as exc:    # noqa: BLE001
            logger.warning(
                "[offline-bundle-cache] decorator invalidate failed "
                "on %s: %s", getattr(func, "__name__", "<fn>"), exc,
            )
        return result

    return _wrapper
