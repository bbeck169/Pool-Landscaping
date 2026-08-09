"""Phase 52.1a · Feb-2026 — Walkie live-session event hooks.

Phase 52.1a lands the WebSocket signaling surface. This module is
where downstream slices (Phase 52.1b/c) will bolt the auto-record
fan-out that turns the just-ended live session into a 24h clip in the
walkie storage. Kept as a no-op stub in the 52.1a slice so the
signaling router can already invoke the hook without a circular
import — subsequent phases just replace the body of
``on_session_ended``.

Contract
--------
``on_session_ended(*, session_id: str, reason: str) -> None`` is
awaited by ``routers.walkie_signaling`` when the last peer leaves a
room. Errors raised here are swallowed by the caller (best-effort)
so signaling cleanup always completes.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("walkie.live.events")


async def on_session_ended(*, session_id: str, reason: str) -> None:
    """No-op in Phase 52.1a.  Phase 52.1b/c will wire the auto-record
    clip creation here (reads ``walkie_live_sessions`` for participant
    roster, pulls the recording buffer stashed by clients, mints a
    ``walkie_messages`` row + file). Kept explicitly async so the
    downstream implementation stays wire-compatible."""
    logger.debug(
        "[walkie.live.events] on_session_ended session=%s reason=%s (52.1a stub)",
        session_id,
        reason,
    )
