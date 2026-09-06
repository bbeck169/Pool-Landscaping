"""Phase R0 · Feb-2026 — Cache layer for the reporting suite.

R0 ships an in-memory ``cachetools.TTLCache`` gated by a stable
compound key. The interface (``get``, ``set``, ``clear_tenant``)
is intentionally the same shape a Redis-backed adapter would
expose so we can swap the backend later without touching any
call-sites.

Contract:

* Every cache key MUST include ``tenant_id`` — enforced by the
  :py:meth:`ReportCache.make_key` helper (returns a hashable str).
* TTL is 60 seconds by default; long enough to absorb rapid
  re-renders of the same dashboard tile, short enough that
  data-freshness expectations are met without an explicit
  invalidation path.
* ``clear_tenant`` deletes every entry that begins with the
  tenant prefix — used by write-side hooks that want to force
  the next read to be uncached.
"""
from __future__ import annotations

from typing import Any, Optional

from cachetools import TTLCache


_DEFAULT_TTL = 60          # seconds
_DEFAULT_MAX = 512         # entries per process


class ReportCache:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL, max_entries: int = _DEFAULT_MAX):
        self._cache: TTLCache = TTLCache(maxsize=max_entries, ttl=ttl_seconds)

    # ── Key discipline ────────────────────────────────────────────
    @staticmethod
    def make_key(tenant_id: str, *parts: str) -> str:
        if not tenant_id:
            raise ValueError("cache key requires tenant_id")
        cleaned = [str(p) for p in parts if p is not None]
        return "|".join(["t", tenant_id, *cleaned])

    # ── Backend surface (mirror Redis semantics) ──────────────────
    def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def clear_tenant(self, tenant_id: str) -> int:
        if not tenant_id:
            return 0
        prefix = f"t|{tenant_id}|"
        matches = [k for k in list(self._cache.keys()) if k.startswith(prefix)]
        for k in matches:
            del self._cache[k]
        return len(matches)

    def clear(self) -> None:
        self._cache.clear()


# Module-level singleton — call-sites reach for the same instance
# so cache hits work across requests.
report_cache = ReportCache()
