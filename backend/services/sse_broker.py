"""Phase 6B · Feb 2026 — In-memory SSE broker for RingCentral live events.

Per-tenant fan-out. Each subscriber gets its own asyncio.Queue; on
publish, we push a copy of the JSON payload to every live queue for
that tenant. Queues are unbounded but each event is a tiny dict, so
we cap subscribers per tenant at 32 and drop the oldest event when a
slow consumer would exceed 100 buffered events.

This broker is intentionally process-local. If we ever run more than
one backend replica, RingCentral webhooks land on the replica that
holds the RC subscription's TCP session so a single-replica broker is
still correct for now. Cross-replica fan-out would need Redis pub/sub
or Mongo change streams — deferred until we horizontally scale.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from config import logger

_MAX_SUBS_PER_TENANT = 32
_MAX_QUEUE_LEN = 100
_subscribers: Dict[str, List[asyncio.Queue]] = {}
_lock = asyncio.Lock()


async def subscribe(tenant_id: str) -> asyncio.Queue:
    async with _lock:
        subs = _subscribers.setdefault(tenant_id, [])
        if len(subs) >= _MAX_SUBS_PER_TENANT:
            # Boot the oldest to make room; this keeps a runaway UI from
            # exhausting the broker.
            evicted = subs.pop(0)
            try:
                evicted.put_nowait({"type": "evicted"})
            except Exception:
                pass
        q: asyncio.Queue = asyncio.Queue()
        subs.append(q)
    return q


async def unsubscribe(tenant_id: str, q: asyncio.Queue) -> None:
    async with _lock:
        subs = _subscribers.get(tenant_id) or []
        try:
            subs.remove(q)
        except ValueError:
            pass
        if not subs and tenant_id in _subscribers:
            _subscribers.pop(tenant_id, None)


async def publish(tenant_id: str, payload: Dict[str, Any]) -> int:
    """Broadcast to every live queue for a tenant. Returns delivered count."""
    delivered = 0
    async with _lock:
        subs = list(_subscribers.get(tenant_id) or [])
    for q in subs:
        try:
            if q.qsize() >= _MAX_QUEUE_LEN:
                # Drop the oldest event to keep the tail fresh.
                try:
                    q.get_nowait()
                except Exception:
                    pass
            q.put_nowait(payload)
            delivered += 1
        except Exception as e:
            logger.warning(f"[sse_broker] publish drop: {type(e).__name__}")
    logger.info(f"[sse_broker] publish tenant={tenant_id[:8]} type={payload.get('type')} delivered={delivered} subs={len(subs)}")
    return delivered


def subscriber_count(tenant_id: str) -> int:
    return len(_subscribers.get(tenant_id) or [])
