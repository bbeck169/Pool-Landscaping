"""TD-ai-phase1 · Oct-2026 — short-TTL in-memory cache for
``POST /api/ai/draft-reply`` responses.

Keyed by ``(tenant_id, recipient_id, prompt_hash)``. TTL default = 60s.
Mongo-backed cache is overkill for v1; revisit only if horizontal
scale makes same-prompt duplication a measurable cost. Mitigates:

  * Operator double-click on the "AI draft" button.
  * Hard-refresh retries that hit the endpoint before FE state settles.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Tuple

DEFAULT_TTL_SECONDS = 60.0

# key = (tenant_id, recipient_id, prompt_hash) → (expires_at, response)
_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}


def compute_prompt_hash(system_prompt: str, user_prompt: str) -> str:
    """Deterministic hash over the final strings sent to the LLM. Used
    for both cache lookup AND audit-log entries (so the audit row
    retains the hash even after the cache row expires)."""
    h = hashlib.sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_prompt.encode("utf-8"))
    return h.hexdigest()


def get(
    *, tenant_id: str, recipient_id: str, prompt_hash: str,
    now: float | None = None,
) -> Optional[Dict[str, Any]]:
    """Return the cached response dict if a non-expired entry exists,
    else None. Expired entries are evicted on access."""
    t_now = now if now is not None else time.monotonic()
    key = (tenant_id, recipient_id, prompt_hash)
    row = _cache.get(key)
    if row is None:
        return None
    expires_at, resp = row
    if t_now >= expires_at:
        _cache.pop(key, None)
        return None
    return resp


def put(
    *, tenant_id: str, recipient_id: str, prompt_hash: str,
    response: Dict[str, Any], ttl_seconds: float = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> None:
    """Store a response under the given key for ``ttl_seconds``."""
    t_now = now if now is not None else time.monotonic()
    key = (tenant_id, recipient_id, prompt_hash)
    _cache[key] = (t_now + ttl_seconds, response)


def _reset_for_tests() -> None:
    """Test-only — clear the in-memory cache between pytest cases."""
    _cache.clear()
