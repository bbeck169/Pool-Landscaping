"""TD-ai-phase1 · Oct-2026 — per-actor rate-limit for the
``POST /api/ai/draft-reply`` endpoint.

Minimal in-memory implementation keyed by ``(tenant_id, user_id,
feature)``. Process-local — a horizontal-scale deployment would want
a Redis + ``INCR + EXPIRE`` pair, but for v1 the preview + prod pods
run one backend container so a process-local map is sufficient.

Operator decision D6 locks the window at 10 seconds.
"""
from __future__ import annotations

import time
from typing import Dict, Tuple

# Operator decision D6 — 10 second cooldown between successive draft
# calls from the same actor.
DEFAULT_WINDOW_SECONDS = 10.0

# key = (tenant_id, user_id, feature) → monotonic timestamp of the
# last SUCCESSFUL call. Only successful calls occupy the slot; failed
# LLM calls do NOT consume the window (so an operator can retry
# immediately on error).
_last_call_at: Dict[Tuple[str, str, str], float] = {}


def check(
    *, tenant_id: str, user_id: str, feature: str = "draft-reply",
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    now: float | None = None,
) -> float:
    """Return 0.0 if the actor is allowed to call now; otherwise
    return ``retry_after_seconds`` > 0 as a float.

    No side effect — callers must call :func:`stamp` on the successful
    path to occupy the slot."""
    t_now = now if now is not None else time.monotonic()
    key = (tenant_id, user_id, feature)
    last = _last_call_at.get(key)
    if last is None:
        return 0.0
    delta = t_now - last
    if delta >= window_seconds:
        return 0.0
    return float(window_seconds - delta)


def stamp(
    *, tenant_id: str, user_id: str, feature: str = "draft-reply",
    now: float | None = None,
) -> None:
    """Record this call as the actor's most-recent successful draft."""
    t_now = now if now is not None else time.monotonic()
    _last_call_at[(tenant_id, user_id, feature)] = t_now


def _reset_for_tests() -> None:
    """Test-only — clear the in-memory map between pytest cases."""
    _last_call_at.clear()
