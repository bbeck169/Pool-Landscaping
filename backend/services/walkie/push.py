"""Phase 51c · Feb 2026 — Walkie-Talkie Expo push fan-out.

Best-effort push to every recipient with a registered mobile device
token. Two-layer safety:

  1. ``WALKIE_PUSH_LIVE=1`` env flag — MUST be explicitly set for the
     helper to hit the Expo push API. Default is dry-run (logs the
     payload only, never opens a network connection). This keeps CI +
     local dev + preview environments silent by default and mirrors
     the Phase 49 ``LANA_SMS_LIVE`` gating pattern.
  2. ``EXPO_PUSH_ACCESS_TOKEN`` env — even with the LIVE flag set, if
     no Expo access token is configured the helper falls back to
     dry-run and logs ``expo-token-not-configured``.

Reuses the existing ``mobile_tokens`` collection from
``routers/mobile_push.py`` — no new collection, no duplicate
registration endpoint.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

EXPO_PUSH_ENDPOINT = "https://exp.host/--/api/v2/push/send"


def _channel_display(channel: dict[str, Any]) -> str:
    kind = channel.get("kind")
    if kind == "all_hands":
        return "All-Hands"
    if kind == "department":
        d = (channel.get("department") or "").capitalize()
        return f"{d} Team"
    return "Direct"


def _duration_label(duration_ms: int) -> str:
    secs = max(1, int(round(duration_ms / 1000)))
    return f"{secs}s"


async def fan_out_walkie_push(
    *,
    recipients: list[str],
    channel: dict[str, Any],
    sender: dict[str, Any],
    message_id: str,
    duration_ms: int,
) -> dict[str, Any]:
    """Send one Expo push per recipient device.

    Returns a summary dict useful for both the dry-run log and the
    live-mode assertion in the Phase 51c test suite:

    ``{"mode": "dry_run" | "live" | "skipped_no_recipients", ...}``
    """
    from config import db, logger  # local — keeps this module importable in tests

    if not recipients:
        return {"mode": "skipped_no_recipients", "recipients": 0}

    live = os.environ.get("WALKIE_PUSH_LIVE") == "1"
    access = os.environ.get("EXPO_PUSH_ACCESS_TOKEN") or ""
    sender_name = sender.get("name") or sender.get("email") or "Teammate"
    channel_label = _channel_display(channel)
    title = f"{sender_name} \u2192 {channel_label}"
    body = f"New walkie clip ({_duration_label(duration_ms)})"
    data = {"type": "walkie", "channel_id": channel.get("id"), "message_id": message_id}

    # Collect tokens for the resolved recipients (excluding sender —
    # already excluded by ``resolve_recipients`` upstream).
    rows = await db.mobile_tokens.find(
        {"user_id": {"$in": recipients}}, {"_id": 0}
    ).to_list(500)
    tokens = [r["token"] for r in rows if r.get("token")]

    if not tokens:
        logger.info(
            f"[walkie.push] no device tokens for {len(recipients)} recipient(s) "
            f"channel={channel.get('id')} msg={message_id}"
        )
        return {"mode": "dry_run", "reason": "no-tokens", "recipients": len(recipients), "tokens": 0}

    if not live or not access:
        reason = "flag-off" if not live else "expo-token-not-configured"
        logger.info(
            f"[walkie.push] DRY-RUN ({reason}) "
            f"channel={channel.get('id')} msg={message_id} "
            f"title={title!r} body={body!r} tokens={len(tokens)}"
        )
        return {
            "mode": "dry_run",
            "reason": reason,
            "recipients": len(recipients),
            "tokens": len(tokens),
            "title": title,
            "body": body,
        }

    # LIVE — post the payload to Expo push service.
    messages = [
        {"to": t, "title": title, "body": body, "data": data, "sound": "default"}
        for t in tokens
    ]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                EXPO_PUSH_ENDPOINT,
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
                json=messages,
            )
        logger.info(
            f"[walkie.push] LIVE sent {len(messages)} push(es) "
            f"status={r.status_code} channel={channel.get('id')} msg={message_id}"
        )
        return {"mode": "live", "recipients": len(recipients), "tokens": len(tokens), "status": r.status_code}
    except Exception as e:  # pragma: no cover — network path
        logger.warning(f"[walkie.push] LIVE send failed: {e}")
        return {"mode": "live_failed", "reason": str(e)[:120], "recipients": len(recipients), "tokens": len(tokens)}
