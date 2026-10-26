"""Ticket LL · Feb-2026 — hourly soft-cap for ``POST /api/ai/rewrite``.

The operator spec locks a 20-call per-user per-hour soft cap on the
rewrite endpoint.  The existing ``services.ai.draft_rate_limit``
module is a cooldown-timestamp map (one key → one monotonic
timestamp), which can't express a per-window counter — so LL
ships a sibling module here, matching the single-concern pattern
of ``services.ai.draft_cache`` + ``services.ai.draft_rate_limit``.

In-memory, process-local, keyed by ``(tenant_id, user_id,
hour_bucket)``.  A horizontal-scale deployment would want Redis
``INCR + EXPIRE``, but for v1 the preview + prod pods run one
backend container so the dict is sufficient.

Only STAMPED (successful) calls occupy the slot — a failed LLM
call does NOT consume quota, matching the ``draft_rate_limit``
contract.  A tiny ``_reset_for_tests`` hook mirrors the sibling.
"""
from __future__ import annotations

import time
from typing import Dict, Tuple


# Operator decision — 20 successful rewrites per user per hour.
DEFAULT_HOURLY_CAP = 20

# key = (tenant_id, user_id, hour_bucket) → count of successful calls
# in that bucket.  ``hour_bucket`` is the ``int(epoch_seconds // 3600)``
# so the counter rolls over on the hour boundary without a sweep.
_counts: Dict[Tuple[str, str, int], int] = {}


def _hour_bucket(now: float | None = None) -> int:
    t_now = now if now is not None else time.time()
    return int(t_now // 3600)


def check(
    *, tenant_id: str, user_id: str,
    cap: int = DEFAULT_HOURLY_CAP,
    now: float | None = None,
) -> Tuple[bool, float]:
    """Return ``(allowed, retry_after_seconds)``.

    * ``allowed=True`` means the caller is under the hourly cap and
      MAY proceed with the LLM call; after a successful call the
      caller MUST call :func:`stamp` to occupy the slot.
    * ``allowed=False`` means the caller is at the cap; the
      ``retry_after_seconds`` is the whole-second count-down until
      the start of the next hour bucket.
    """
    t_now = now if now is not None else time.time()
    bucket = _hour_bucket(t_now)
    key = (tenant_id, user_id, bucket)
    current = _counts.get(key, 0)
    if current < cap:
        return True, 0.0
    # At or over the cap — compute seconds until the next bucket.
    next_bucket_start = (bucket + 1) * 3600
    retry = max(1.0, next_bucket_start - t_now)
    return False, float(retry)


def stamp(
    *, tenant_id: str, user_id: str,
    now: float | None = None,
) -> None:
    """Record one successful rewrite in the current hour bucket.
    Idempotent-equivalent — multiple stamps on the same monotonic
    tick are each counted (matches the per-call-consumes-one-slot
    contract)."""
    t_now = now if now is not None else time.time()
    bucket = _hour_bucket(t_now)
    key = (tenant_id, user_id, bucket)
    _counts[key] = _counts.get(key, 0) + 1


def _reset_for_tests() -> None:
    """Test-only — clear the in-memory map between pytest cases."""
    _counts.clear()
