"""MTH-D · Feb-2026 — in-memory sliding-window rate limiter.

Preview endpoint only — plain per-process dict + monotonic
timestamps.  30 previews / 60 s per user by default.  Multi-worker
deployments should tighten this if we ever mount preview under
uvicorn --workers >1; for now the surface is admin-only and
low-volume so a single-process bucket is fine.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

DEFAULT_LIMIT = 30
DEFAULT_WINDOW_S = 60

_lock = threading.Lock()
_buckets: Dict[str, Deque[float]] = {}


def check_and_record(
    user_id: str,
    *, limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_S,
    now: float | None = None,
) -> Tuple[bool, int, int]:
    """Return ``(allowed, remaining, retry_after_s)``.

    * ``allowed=True`` on the first ``limit`` calls in any rolling
      ``window_seconds`` window.  A "consumed" call is recorded
      before the return, so the caller doesn't have to do a
      separate accounting step.
    * ``allowed=False`` when the window is full.  ``retry_after_s``
      is the number of seconds until the oldest recorded call
      exits the window.
    """
    if not user_id:
        # Unknown user — fail-open with a per-process fallback bucket.
        user_id = "__anon__"
    ts = now if now is not None else time.monotonic()
    horizon = ts - window_seconds
    with _lock:
        bucket = _buckets.get(user_id)
        if bucket is None:
            bucket = deque()
            _buckets[user_id] = bucket
        # Trim expired entries.
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
            _buckets.pop(user_id, None)


__all__ = ["check_and_record", "reset", "DEFAULT_LIMIT", "DEFAULT_WINDOW_S"]
