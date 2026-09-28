"""SO-A · Feb-2026 — Schedule-optimizer rate limiter.

Reuses the MTH-D sliding-window pattern but with an isolated
per-process bucket store so a spike on the preview endpoint doesn't
starve the recommendation endpoint (and vice-versa).  Same
``check_and_record(user_id, limit=..., window_seconds=...)`` API
so tests can be near-identical.

Default: 10 recommendations per 60 s per user (per brief §6 —
generation is more expensive than a preview).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

DEFAULT_LIMIT = 10
DEFAULT_WINDOW_S = 60
NAMESPACE = "schedule_ai_recommendation"

_lock = threading.Lock()
_buckets: Dict[str, Deque[float]] = {}


def check_and_record(
    user_id: str,
    *, limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_S,
    now: float | None = None,
) -> Tuple[bool, int, int]:
    if not user_id:
        user_id = "__anon__"
    key = f"{NAMESPACE}:{user_id}"
    ts = now if now is not None else time.monotonic()
    horizon = ts - window_seconds
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = deque()
            _buckets[key] = bucket
        while bucket and bucket[0] < horizon:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(bucket[0] + window_seconds - ts))
            return False, 0, retry_after
        bucket.append(ts)
        remaining = max(0, limit - len(bucket))
        return True, remaining, 0


def reset(user_id: str | None = None) -> None:
    """Test hook — clear one user's bucket or all buckets."""
    with _lock:
        if user_id is None:
            _buckets.clear()
        else:
            _buckets.pop(f"{NAMESPACE}:{user_id}", None)


__all__ = ["check_and_record", "reset", "NAMESPACE",
            "DEFAULT_LIMIT", "DEFAULT_WINDOW_S"]
