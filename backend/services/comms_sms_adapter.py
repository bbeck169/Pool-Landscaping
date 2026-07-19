"""Communications Subsystem · Phase 1 — SMS delivery adapter.

RingCentral OAU-153 remains unresolved for this preview, so we ship a
mock-first adapter gated by the ``SMS_MOCK_MODE`` env flag (default
``"1"``). While mocked, the adapter records the fully-rendered message
body in the ``communication_sends`` log with ``status="mocked"`` and
never touches the RingCentral SDK. When ``SMS_MOCK_MODE="0"`` it routes
to the same ``get_rc_platform()`` helper the notifications module
already uses.

Character/segment counts are computed against the GSM-7 vs. UCS-2 split:
plain ASCII / GSM-7 body → 160 chars/segment; anything above that (unicode
emoji, non-ASCII glyphs) → 70 chars/segment. Multipart concatenated SMS
loses ~7 chars/segment for header overhead — we account for that too.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from config import db, logger

# GSM-7 basic + extension table — anything not in this set forces UCS-2.
_GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = set("|^€{}[~]\\\\")


def _is_gsm7(body: str) -> bool:
    for ch in body:
        if ch not in _GSM7_BASIC and ch not in _GSM7_EXT:
            return False
    return True


def sms_length_stats(body: str) -> Dict[str, int]:
    """Return character count + segment count for the given SMS body."""
    body = body or ""
    if _is_gsm7(body):
        # GSM-7 extension chars count as 2.
        weighted = sum(2 if ch in _GSM7_EXT else 1 for ch in body)
        if weighted <= 160:
            segments = 1 if weighted else 0
        else:
            # 153-char concatenated segments.
            segments = (weighted + 152) // 153
        return {"character_count": weighted, "segment_count": segments}
    else:
        # UCS-2 — 70 per single segment, 67 per concatenated segment.
        n = len(body)
        if n <= 70:
            segments = 1 if n else 0
        else:
            segments = (n + 66) // 67
        return {"character_count": n, "segment_count": segments}


async def _is_opted_out(tenant_id: str, phone: str) -> bool:
    if not phone:
        return False
    row = await db.communication_opt_outs.find_one({
        "tenant_id": tenant_id,
        "contact_phone": phone,
        "channel": "sms",
    })
    return row is not None


async def send_sms(tenant_id: str, to_phone: str, body: str,
                    mms_url: Optional[str] = None) -> Dict[str, Any]:
    """Send an SMS (or log a mock). Never raises.

    Returns a dict with:
        - ``status``: ``sent`` | ``mocked`` | ``failed`` | ``skipped_opted_out``
        - ``provider_id``: RingCentral message id when real send succeeds; ``None`` otherwise
        - ``error``: exception summary on failed sends
        - ``character_count`` / ``segment_count``: metrics on the rendered body
    """
    stats = sms_length_stats(body)
    if not to_phone:
        return {"status": "failed", "error": "empty recipient phone", **stats}
    if await _is_opted_out(tenant_id, to_phone):
        return {"status": "skipped_opted_out", **stats}

    if os.environ.get("SMS_MOCK_MODE", "1") == "1":
        logger.info(
            f"comms_sms_adapter: MOCKED sms tenant={tenant_id} to={to_phone} "
            f"chars={stats['character_count']} segs={stats['segment_count']} "
            f"mms={'yes' if mms_url else 'no'} body={body!r}")
        return {"status": "mocked", "provider_id": None, **stats}

    # Real path — kept minimal because OAU-153 is not resolved for this pod.
    try:
        from services.ringcentral_client import get_rc_platform, is_outbound_enabled
        if not await is_outbound_enabled():
            return {"status": "failed", "error": "outbound disabled", **stats}
        platform = get_rc_platform()
        req = {
            "from": {"phoneNumber": os.environ.get("RC_FROM_NUMBER") or ""},
            "to": [{"phoneNumber": to_phone}],
            "text": body or "",
        }
        # MMS attachment support depends on RC endpoint; if a URL is given
        # we include it in the text body as a fallback so the message
        # still delivers even where the account can't accept MMS payloads.
        if mms_url:
            req["text"] = f"{req['text']}\n{mms_url}".strip()
        resp = platform.post("/restapi/v1.0/account/~/extension/~/sms", req)
        provider_id = None
        try:
            j = resp.json_dict() if hasattr(resp, "json_dict") else (resp.json() if hasattr(resp, "json") else None)
            if isinstance(j, dict):
                provider_id = j.get("id")
        except Exception:
            pass
        return {"status": "sent", "provider_id": provider_id, **stats}
    except Exception as e:
        logger.warning(f"comms_sms_adapter: rc send failed: {type(e).__name__}: {e}")
        return {"status": "failed", "error": f"{type(e).__name__}: {e}", **stats}
