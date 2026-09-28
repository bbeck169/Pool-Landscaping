"""MTH-A · Feb-2026 — 30-sec in-process TTL cache for resolved rules.

Deliberately simple: a module-level ``dict`` keyed by ``tenant_id``
plus a monotonic ``time.time()`` timestamp.  No Redis in MTH-A.

Cache invalidation contract:

* :func:`invalidate` — one tenant (any tenant-scoped save).
* :func:`invalidate_all` — every tenant (platform-default save).

Callers hit the cache through
:func:`services.tenant_ai_rules.resolver.resolve_rules_for_tenant`.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any, Dict, Optional


TTL_SECONDS: int = 30

_lock = threading.Lock()
_CACHE: Dict[str, Dict[str, Any]] = {}


def get(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return a fresh cache entry (deep-copied) or ``None`` when the
    entry is missing / expired.  Fresh copies keep mutators in the
    router / gate from silently poisoning the cached payload.
    """
    with _lock:
        entry = _CACHE.get(tenant_id)
        if not entry:
            return None
        if (time.time() - entry["ts"]) > TTL_SECONDS:
            _CACHE.pop(tenant_id, None)
            return None
        return copy.deepcopy(entry["value"])


def set(tenant_id: str, value: Dict[str, Any]) -> None:            # noqa: A001
    """Cache ``value`` for ``tenant_id`` (deep-copied to detach the
    caller's mutable payload from the cached one)."""
    with _lock:
        _CACHE[tenant_id] = {
            "ts": time.time(),
            "value": copy.deepcopy(value),
        }


def invalidate(tenant_id: str) -> None:
    with _lock:
        _CACHE.pop(tenant_id, None)


def invalidate_all() -> None:
    with _lock:
        _CACHE.clear()


def size() -> int:
    """Test helper — number of cached tenants."""
    with _lock:
        return len(_CACHE)


def _debug_snapshot() -> Dict[str, Any]:
    """Test helper — read-only view (no deep copies) of the internal
    state.  Never invoked by production code."""
    with _lock:
        return {k: dict(v) for k, v in _CACHE.items()}
