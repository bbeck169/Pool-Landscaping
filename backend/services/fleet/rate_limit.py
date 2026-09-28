"""FLEET-A · in-memory per-tech ping rate limiter.

1 ping every 5 seconds per tech, tenant-scoped. Sliding-window,
memory-only — a scheduler-restart clears the state and that's fine
(a legitimate tech ping resumes cleanly after 5s).

Uses ``fastapi.HTTPException`` from the caller side; this module
just exposes a check function.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Tuple

_WINDOW_SEC = 5.0
_MAX_PINGS_PER_WINDOW = 1

# Key: (tenant_id, tech_user_id) → deque of timestamps (seconds).
_HISTORY: dict[Tuple[str, str], Deque[float]] = defaultdict(deque)


def check_and_stamp(tenant_id: str, tech_user_id: str) -> bool:
    """Return True if the ping should be allowed, else False.

    Also records the ping timestamp when allowed so the next call
    is properly gated.
    """
    now = time.monotonic()
    key = (tenant_id, tech_user_id)
    q = _HISTORY[key]
    # Drop timestamps outside the window.
    while q and (now - q[0]) > _WINDOW_SEC:
        q.popleft()
    if len(q) >= _MAX_PINGS_PER_WINDOW:
        return False
    q.append(now)
    return True


def reset() -> None:
    """Test hook — clear every recorded stamp."""
    _HISTORY.clear()
