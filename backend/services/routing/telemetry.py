"""Feb-2026 · UX Polish Batch B — Routing cost telemetry buffer.

In-memory ring buffer that records each Google Routes API v2 call
originated by :mod:`services.google_maps.directions` (the two public
entrypoints :func:`optimize_route` and :func:`compute_route_no_optimize`).
Callers pass the resolved tenant id, whether the request went out
with ``TRAFFIC_AWARE`` or ``TRAFFIC_UNAWARE`` routing preference, and
the waypoint count that the routes API was billed for.

Design decisions:

* **In-memory ring buffer** — chosen over log-tail parsing or a new
  Mongo collection to keep the storage story cheap (zero schema
  drift, zero disk IO, zero migration). The tradeoff is that pod
  restarts flush the buffer; that's acceptable for a "current
  window telemetry" surface — accuracy across restarts is a P3
  future dispatch, not this MVP.
* **Cap at 20 000 entries** — ~2.5 MB RSS max at 8 fields × 128 B
  each. At ~1 optimize call per admin action, this covers roughly
  a month of operator activity for a mid-sized tenant.
* **Simple filter-and-sum aggregation** — no time-bucketing, no
  moving-average smoothing. Callers pass a ``window_days`` and we
  filter by ``at`` epoch. Keeps the reader endpoint deterministic.
* **Cost model** — the ``TRAFFIC_AWARE`` SKU is billed at ~2× the
  base ``TRAFFIC_UNAWARE`` rate (source: Google Routes API v2
  pricing tiers, "Basic" vs "Advanced"). The base rate used here
  is a placeholder ``$0.005`` per request; admins can override via
  ``ROUTING_BILL_BASE_USD`` env if they want their real billing tier
  reflected in the tile. This module intentionally does NOT try to
  read the real invoice — that's Google Cloud Console territory.

Public API:

    record_routing_call(tenant_id, *, traffic_aware, waypoint_count,
                        op)
        Append a single call to the ring. Safe to call from within
        an async coroutine; the buffer is guarded by a simple
        threading lock so concurrent optimize calls don't tear.

    summarize(tenant_id, *, window_days) -> dict
        Aggregate the buffer for the given tenant + window. Never
        raises — returns zeros for tenants with no telemetry.

See /app/memory/FEATURE_SEND_TO_CUSTOMER_AND_COST_TELEMETRY.md § 2.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional


# ─── Config knobs ────────────────────────────────────────────────────

_MAX_ENTRIES = 20_000

try:
    _BASE_USD = float(os.environ.get("ROUTING_BILL_BASE_USD") or 0.005)
except Exception:
    _BASE_USD = 0.005

# Multiplier applied to the ``TRAFFIC_AWARE`` calls. Sourced from
# Google Routes API v2 pricing (Basic → Advanced tier). Kept as a
# module-level constant so tests can monkey-patch.
_TRAFFIC_AWARE_MULT = 2.0


# ─── Buffer state ────────────────────────────────────────────────────

_lock = threading.Lock()
# Each entry: {"tenant_id", "at" (epoch sec), "traffic_aware" (bool),
#              "waypoint_count" (int), "op" (str)}
_buf: Deque[Dict] = deque(maxlen=_MAX_ENTRIES)


# ─── Public API ──────────────────────────────────────────────────────

def record_routing_call(
    tenant_id: Optional[str],
    *,
    traffic_aware: bool,
    waypoint_count: int,
    op: str,
) -> None:
    """Append a single routing telemetry entry.

    ``tenant_id`` may be ``None`` for untenanted platform-internal
    calls; those are recorded with the sentinel ``"-"`` so the
    global counters stay honest but per-tenant aggregation excludes
    them.
    """
    entry = {
        "tenant_id": tenant_id or "-",
        "at": time.time(),
        "traffic_aware": bool(traffic_aware),
        "waypoint_count": max(0, int(waypoint_count or 0)),
        "op": op or "optimize",
    }
    with _lock:
        _buf.append(entry)


def summarize(tenant_id: str, *, window_days: int = 30) -> Dict:
    """Aggregate the buffer for one tenant + rolling window.

    Response shape mirrors the endpoint contract in
    :mod:`routers.routing_cost_telemetry`. Never raises — a tenant
    with zero calls yields ``total_calls == 0`` and both cost
    estimates at ``0.0``.
    """
    cutoff = time.time() - max(1, int(window_days)) * 86_400.0
    total = 0
    aware = 0
    unaware = 0
    waypoints = 0
    aware_calls = 0
    unaware_calls = 0
    with _lock:
        # deque iteration is a snapshot per Python semantics — safe
        # under the lock; we hold it for a tight loop only.
        for e in _buf:
            if e["tenant_id"] != tenant_id:
                continue
            if e["at"] < cutoff:
                continue
            total += 1
            waypoints += e["waypoint_count"]
            if e["traffic_aware"]:
                aware += 1
                aware_calls += 1
            else:
                unaware += 1
                unaware_calls += 1
    est_aware = round(aware_calls * _BASE_USD * _TRAFFIC_AWARE_MULT, 4)
    est_baseline = round(unaware_calls * _BASE_USD, 4)
    return {
        "window_days": int(window_days),
        "tenant_id": tenant_id,
        "total_calls": total,
        "traffic_aware_calls": aware,
        "traffic_unaware_calls": unaware,
        "waypoints_billed": waypoints,
        "est_traffic_aware_cost_usd": est_aware,
        "est_baseline_cost_usd": est_baseline,
    }


def _reset_for_tests() -> None:
    """Test-only helper. Not exported."""
    with _lock:
        _buf.clear()


__all__ = ["record_routing_call", "summarize"]
