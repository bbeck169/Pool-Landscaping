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

SAFE-SEND-A · Feb-2026 — mandatory ``context`` kwarg-only param
on ``send_sms``.  Redirects AGENT + TEST to the tenant admin
BEFORE any other gate fires.  See ``services.comms_env_guard``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from config import db, logger
from services.comms_env_guard import (
    CommsContext, RedirectTargetMissing,
    get_redirect_targets, should_redirect_to_admin,
)
from services.comms_send_log import format_exc, record_attempt

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
                    mms_url: Optional[str] = None,
                    *,
                    context: "CommsContext",
                    ) -> Dict[str, Any]:
    """Send an SMS (or log a mock). Never raises.

    Returns a dict with:
        - ``status``: ``sent`` | ``mocked`` | ``failed`` | ``skipped_opted_out`` | ``deferred``
        - ``provider_id``: RingCentral message id when real send succeeds; ``None`` otherwise
        - ``error``: exception summary on failed sends
        - ``character_count`` / ``segment_count``: metrics on the rendered body

    SAFE-SEND-A · Feb-2026 — the ``context`` kwarg is
    MANDATORY (no default).  Callers stamp one of
    ``CommsContext.{SYSTEM, AGENT, TEST}``.  AGENT / TEST get
    redirected to the tenant admin via
    ``get_redirect_targets`` BEFORE any opt-out, quiet-hours,
    BYO, or RingCentral gate fires.  SYSTEM passes through
    untouched.  Missing context → ``TypeError`` at call time.

    Ticket NN · Feb-2026 — adapter-level HTML strip safety net.
    Reuses Ticket JJ's ``services.text.html_to_plain.html_to_plain``
    helper (preserves ``\\n`` for ``<br>`` / ``</p>``, decodes
    entities, keeps list bullets) BEFORE any gate fires.  Catches
    the case where a template with inline HTML was authored on
    the email surface and a caller mistakenly reused the raw body
    for an SMS dispatch.  Idempotent on already-plain bodies.
    Merge-tag resolution still happens UPSTREAM at the call site
    (``services.marketing.merge_tags.render_template``) because
    the adapter has no customer / tenant ctx — this strip is a
    last-line safety net, not a resolver.
    """
    # Ticket NN · Feb-2026 — HTML strip safety net.  Runs BEFORE
    # the redirect gate so the MARCO-TEST prefix is appended to a
    # cleaned body (not an HTML-tagged body).
    if body:
        from services.text.html_to_plain import html_to_plain as _nn_strip
        body = _nn_strip(body)
    # SAFE-SEND-A · redirect FIRST — runs before opt-out check so
    # a customer's opt-out never suppresses an admin-directed
    # test / agent sample.
    _original_to = to_phone
    _redirected = False
    if should_redirect_to_admin(context):
        try:
            tenant_doc = await db.tenants.find_one(
                {"id": tenant_id}, {"_id": 0, "settings": 1},
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            tenant_doc = None
            logger.warning(
                "safe_send.tenant_lookup_failed tenant=%s err=%s",
                tenant_id, exc,
            )
        try:
            targets = await get_redirect_targets(
                tenant_settings=(tenant_doc or {}).get("settings") or {},
                tenant_id=tenant_id,
                channel="sms",
                db=db,
            )
        except RedirectTargetMissing as exc:
            logger.warning(
                "safe_send.redirect_target_missing context=%s tenant=%s "
                "original_to=%s err=%s — SKIPPING send",
                context.value, tenant_id, to_phone, exc,
            )
            # SAFE-SEND-A.1 · audit-parity — write the skip row so
            # ``comms_send_log`` reflects that a send was ATTEMPTED
            # and suppressed by the redirect gate.  Match the email
            # side's provider_status contract when it eventually
            # gets this branch — the string doubles as the response
            # envelope's ``status`` field (parity by construction).
            record_attempt(
                "sms", ok=False, tenant_id=tenant_id,
                recipient=None,                       # never sent
                provider="ringcentral",
                provider_status="skipped_no_redirect_target",
                was_mock=False, routed_via="safe_send_gate",
                error=str(exc),
                context=context.value,
                intended_recipient=_original_to,
                redirected=True,
            )
            return {
                "status": "skipped_no_redirect_target",
                "safe_send_context": context.value,
                "original_to": to_phone,
                "error": str(exc),
                **sms_length_stats(body),
            }
        to_phone = targets.phone or to_phone
        body = f"[MARCO TEST] {body or ''}".strip()
        _redirected = True
        logger.info(
            "safe_send.redirected channel=sms context=%s tenant=%s "
            "original_to=%s redirected_to=%s",
            context.value, tenant_id, _original_to, to_phone,
        )
    else:
        logger.debug(
            "safe_send.passthrough channel=sms context=%s tenant=%s to=%s",
            context.value, tenant_id, to_phone,
        )

    stats = sms_length_stats(body)
    if not to_phone:
        record_attempt(
            "sms", ok=False, tenant_id=tenant_id,
            recipient=to_phone,
            provider="ringcentral",
            provider_status="failed_empty_recipient",
            was_mock=False, routed_via="pre_gate",
            error="empty recipient phone",
            context=context.value,
            intended_recipient=_original_to,
            redirected=_redirected,
        )
        return {"status": "failed", "error": "empty recipient phone", **stats}
    if await _is_opted_out(tenant_id, to_phone):
        record_attempt(
            "sms", ok=False, tenant_id=tenant_id,
            recipient=to_phone,
            provider="ringcentral",
            provider_status="skipped_opted_out",
            was_mock=False, routed_via="opt_out_gate",
            context=context.value,
            intended_recipient=_original_to,
            redirected=_redirected,
        )
        return {"status": "skipped_opted_out", **stats}

    # Feb-2026 · P34 — Automation quiet-hours gate. See the mirror
    # comment in ``comms_email_adapter.send_email``.
    try:
        from services.quiet_hours import (
            is_within_send_window as _p34_ok,
            defer_send as _p34_defer,
        )
        from services.quiet_hours_context import is_bypassing as _p34_bypass
        if not _p34_bypass() and not await _p34_ok(tenant_id):
            deferred_id = await _p34_defer(
                tenant_id, "sms",
                {"to_phone": to_phone, "body": body, "mms_url": mms_url},
            )
            return {"status": "deferred", "deferred_id": deferred_id,
                     "provider_id": None, **stats}
    except Exception as _e34:
        logger.warning("[p34] quiet-hours gate errored — failing open: %s",
                          _e34)

    # Phase I1.7.e · chunk 1 · Feb-2026 — tenant-BYO first hop.
    # Route through the tenant's configured SMS provider when one is
    # saved. Cap-exceeded (HTTP 429) responses are normalized to
    # ``status="cap_exceeded"`` for the caller to interpret. See the
    # mirror comment in ``comms_email_adapter.send_email``.
    try:
        from services.messaging.byo_passthrough import (
            try_dispatch_sms_tenant_byo,
        )
        _byo = await try_dispatch_sms_tenant_byo(
            tenant_id=tenant_id, to=to_phone, body=body,
            media_urls=[mms_url] if mms_url else None,
        )
    except Exception as _byo_exc:  # noqa: BLE001
        logger.warning(
            "comms_sms_adapter: BYO probe raised — falling through: %s",
            _byo_exc,
        )
        _byo = None
    if _byo is not None:
        # Merge SMS length stats into the envelope so downstream
        # ledger rows still get character_count / segment_count.
        return {**_byo, **stats}

    # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit
    # for the platform (non-BYO) path. Runs AFTER opt-out + BYO probe
    # so both gates still fire; only the RC HTTP call is skipped.
    from services.messaging.testmode import (
        is_messaging_testmode, mock_sms_envelope,
    )
    if is_messaging_testmode():
        return mock_sms_envelope(
            tenant_id=tenant_id, to=to_phone, body=body,
            routed_via="platform_testmode_mock",
            length_stats=stats,
        )

    if os.environ.get("SMS_MOCK_MODE", "1") == "1":
        logger.info(
            f"comms_sms_adapter: MOCKED sms tenant={tenant_id} to={to_phone} "
            f"chars={stats['character_count']} segs={stats['segment_count']} "
            f"mms={'yes' if mms_url else 'no'} body={body!r}")
        record_attempt(
            "sms", ok=True, tenant_id=tenant_id,
            recipient=to_phone,
            provider="ringcentral",
            provider_status="mocked",
            was_mock=True, routed_via="sms_mock_mode",
            context=context.value,
            intended_recipient=_original_to,
            redirected=_redirected,
        )
        return {"status": "mocked", "provider_id": None, **stats}

    # Real path — kept minimal because OAU-153 is not resolved for this pod.
    try:
        from services.ringcentral_client import get_rc_platform, is_outbound_enabled
        if not await is_outbound_enabled():
            record_attempt(
                "sms", ok=False, tenant_id=tenant_id,
                recipient=to_phone,
                provider="ringcentral",
                provider_status="outbound_disabled",
                was_mock=False, routed_via="platform_ringcentral",
                error="outbound disabled",
                context=context.value,
                intended_recipient=_original_to,
                redirected=_redirected,
            )
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
        record_attempt(
            "sms", ok=True, tenant_id=tenant_id,
            recipient=to_phone,
            provider="ringcentral",
            provider_status="sent",
            provider_response_id=provider_id,
            was_mock=False, routed_via="platform_ringcentral",
            context=context.value,
            intended_recipient=_original_to,
            redirected=_redirected,
        )
        return {"status": "sent", "provider_id": provider_id, **stats}
    except Exception as e:
        logger.warning(f"comms_sms_adapter: rc send failed: {type(e).__name__}: {e}")
        record_attempt(
            "sms", ok=False, tenant_id=tenant_id,
            recipient=to_phone,
            provider="ringcentral",
            provider_status="failed",
            was_mock=False, routed_via="platform_ringcentral",
            context=context.value,
            intended_recipient=_original_to,
            redirected=_redirected,
            **format_exc(e),
        )
        return {"status": "failed", "error": f"{type(e).__name__}: {e}", **stats}
