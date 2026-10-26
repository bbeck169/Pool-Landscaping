"""Ticket 291808 · short-lived single-flight cache for duplicate scans.

The Customers list page fires ``GET /customers/duplicates`` and
``GET /customers/merge-candidates`` on load.  Both run an all-pairs
name comparison over the tenant's customers (~2M pairs at 2K
customers, 30-50s of pure-Python CPU).  Without sharing, every page
load / reload / abandoned request starts another full scan and they
stack up behind each other.

This module gives both endpoints:

  * a TTL cache per ``(kind, tenant_id)`` so repeat page loads are
    instant, and
  * single-flight: concurrent callers for the same key await ONE scan
    instead of each starting their own.  The scan is shielded, so a
    client disconnect / timeout does not cancel it and the next
    caller still gets the finished result.

``invalidate_tenant`` is called after a merge so the merged rows
disappear from the Duplicates panel straight away.  The cache is
per-process: with several replicas another pod may serve a result up
to ``_TTL_SECONDS`` old after a merge on a different pod.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

_TTL_SECONDS = 120.0

_Key = Tuple[str, str]

_results: Dict[_Key, Tuple[float, Any]] = {}
_inflight: Dict[_Key, "asyncio.Task[Any]"] = {}
_generation: Dict[str, int] = {}


async def cached_scan(
    kind: str,
    tenant_id: str,
    compute: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached result for ``(kind, tenant_id)`` or run
    ``compute`` once and share it with every concurrent caller."""
    key: _Key = (kind, tenant_id)
    hit = _results.get(key)
    if hit is not None and time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_run(key, compute))
        _inflight[key] = task
    return await asyncio.shield(task)


async def _run(key: _Key, compute: Callable[[], Awaitable[Any]]) -> Any:
    me = asyncio.current_task()
    gen = _generation.get(key[1], 0)
    try:
        value = await compute()
        # A merge that finished while we were scanning bumps the
        # generation: hand the (possibly stale) value to the callers
        # already waiting, but do not cache it.
        if _generation.get(key[1], 0) == gen:
            _results[key] = (time.monotonic(), value)
        return value
    finally:
        if _inflight.get(key) is me:
            _inflight.pop(key, None)


def invalidate_tenant(tenant_id: str) -> None:
    """Drop every cached / in-flight duplicate scan for the tenant."""
    _generation[tenant_id] = _generation.get(tenant_id, 0) + 1
    for key in [k for k in _results if k[1] == tenant_id]:
        _results.pop(key, None)
    for key in [k for k in _inflight if k[1] == tenant_id]:
        _inflight.pop(key, None)


__all__ = ["cached_scan", "invalidate_tenant"]
