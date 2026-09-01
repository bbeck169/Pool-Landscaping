"""Phase 52 · webhook scaffold + Phase 54 · full RingCentral integration.

Router mounts under `/api/ringcentral`. All 5 surfaces live here:
    · GET  /health                                (admin) — env booleans + subscription
    · POST /webhook                               (public) — validation echo + event dispatch
    · POST /subscription/register                  (admin) — create/refresh RC subscription
    · POST /ringout                                (admin/tech) — RingOut click-to-call
    · POST /sms/send                                (admin/tech) — outbound SMS
    · POST /contacts/sync                          (admin) — push customers → RC address book
    · GET  /events?limit=                          (admin) — recent metadata rows

All outbound routes are gated by `is_outbound_enabled()`. When the
runtime flag is off, they return `{"mocked": true,
"reason": "rc_outbound_disabled"}` so the UI can be exercised safely.

Credential values are NEVER echoed in logs, responses, or comments —
env-var names only.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from config import db, logger, APP_PUBLIC_URL
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from services.ringcentral_client import (
    get_rc_platform, reset_rc_platform, is_outbound_enabled, rc_health_env,
    is_live_events_enabled,
)
from services.notifications import emit as notify_emit

router = APIRouter(prefix="/ringcentral", tags=["ringcentral"])


_INDEXES_READY = False


async def _ensure_indexes() -> None:
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        await db.ringcentral_events.create_index("event_id", unique=True, sparse=True)
        await db.ringcentral_events.create_index("received_at")
        await db.call_logs.create_index([("customer_id", 1), ("started_at", -1)])
        await db.sms_messages.create_index([("customer_id", 1), ("sent_at", -1)])
        await db.voicemails.create_index([("matched_customer_id", 1), ("received_at", -1)])
        await db.faxes.create_index([("matched_customer_id", 1), ("received_at", -1)])
        _INDEXES_READY = True
    except Exception as e:
        logger.warning(f"ringcentral indexes: {e}")


def _webhook_url() -> str:
    base = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/api/ringcentral/webhook" if base else "/api/ringcentral/webhook"


async def _notify_admins(tenant_id: Optional[str], kind: str, title: str, body: str,
                          href: Optional[str] = None, source_ref: Optional[dict] = None,
                          customer_id: Optional[str] = None) -> None:
    """Fan out an inbound-comm notification to every admin/super_admin in a
    tenant. Silent no-op when tenant unknown (unmatched inbound with no
    default tenant configured)."""
    if not tenant_id:
        return
    try:
        admins = await db.users.find(
            {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        user_ids = [a["id"] for a in admins if a.get("id")]
        if not user_ids:
            return
        await notify_emit(user_ids, kind=kind, title=title, body=body,
                          href=href, source_ref=source_ref or {},
                          customer_id=customer_id, tenant_id=tenant_id,
                          audience="internal")
    except Exception as e:
        logger.warning(f"rc notif fan-out failed: {type(e).__name__}")


async def _default_tenant_id() -> Optional[str]:
    """Resolve the RC default tenant when a caller/message doesn't
    match a specific customer. Used to route ``*_unmatched`` bells to
    admins so unknown numbers don't silently vanish (Phase 55.1)."""
    slug = os.getenv("RC_DEFAULT_TENANT_SLUG") or ""
    if slug:
        t = await db.tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
        if t: return t.get("id")
    else:
        logger.warning("RC_DEFAULT_TENANT_SLUG unset — routing unmatched inbound bells to the 'aquaterra' demo tenant fallback")
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    return (t or {}).get("id")


def _normalize_phone(p: Optional[str]) -> str:
    if not p:
        return ""
    return "".join(ch for ch in str(p) if ch.isdigit())


def _normalize_phone_e164(value: Optional[str]) -> Optional[str]:
    """Phase 54.1 fix — coerce any US phone shape into `+1XXXXXXXXXX`.

    Handles: `4805550102`, `480-555-0102`, `(480) 555-0102`,
    `+14805550102`, `1-480-555-0102`. Returns None for values that
    aren't a valid US 10-digit number. Non-US E.164 (already starts
    with `+` and isn't 11 digits of `1XXXXXXXXXX`) is preserved."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if raw.startswith("+") and len(digits) >= 8:
        # Foreign or already-normalized E.164 — return the sanitized form.
        return f"+{digits}"
    return None


async def _match_customer_by_phone(tenant_id: Optional[str], phone: str) -> Optional[dict]:
    if not phone:
        return None
    # Phase 54.1 — compare on the normalized form so a webhook's
    # `+14805550102` matches a seeded `480-555-0102`. Because the
    # stored phones may contain arbitrary non-digit separators (dashes,
    # spaces, parens), we build a permissive regex from the last 10
    # digits: `4\D*8\D*0\D*...` so `480-555-0102` matches
    # `+14805550102` extracted digits.
    normalized = _normalize_phone_e164(phone)
    digits = _normalize_phone(phone)
    q: Dict[str, Any] = {}
    if tenant_id: q["tenant_id"] = tenant_id
    # Try exact string match first (fast path for phones stored
    # already in E.164 or the same shape as the incoming value).
    # Seeded customer docs may hold their phone number on EITHER the
    # scalar `phone` field OR the array `phones` field; check both.
    for candidate in (phone, normalized):
        if not candidate:
            continue
        q_exact = dict(q, **{"$or": [{"phones": candidate}, {"phone": candidate}]})
        match = await db.customers.find_one(q_exact, {"_id": 0})
        if match:
            return match
    # Fall back to a digit-agnostic regex over the last 10 digits.
    tail10 = digits[-10:] if len(digits) >= 10 else digits
    if len(tail10) >= 7:
        pattern = "".join(f"{d}\\D*" for d in tail10)
        # Anchor at end so `4805550102` doesn't spuriously hit
        # something like `1480555010200000000`.
        rgx = {"$regex": pattern + "$"}
        q_regex = dict(q, **{"$or": [{"phones": rgx}, {"phone": rgx}]})
        match = await db.customers.find_one(q_regex, {"_id": 0})
        if match:
            return match
    return None


# ═══════════════════════════ /health ══════════════════════════════════
@router.get("/health")
async def ringcentral_health(user: dict = Depends(require_admin)):
    env = rc_health_env()
    outbound = await is_outbound_enabled()
    sub = await db.ringcentral_subscriptions.find_one(
        {"active": True}, {"_id": 0, "subscription_id": 1, "expires_at": 1},
        sort=[("created_at", -1)],
    )
    # Phase 56.19 · RC-diagnostic — actually validate auth against RC,
    # not just env-var presence. Health returns 503 with the specific
    # error class + first 200 chars of RC's body when auth fails.
    # NEVER echoes the JWT or client secret.
    rc_auth_ok = None
    rc_auth_error = None
    if outbound:
        try:
            platform = get_rc_platform()
            # Cheap authenticated read — extension info. Confirms JWT
            # login succeeded (SDK caches the token internally).
            resp = platform.get("/restapi/v1.0/account/~/extension/~")
            _ = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
            rc_auth_ok = True
        except Exception as e:
            diag = _capture_rc_error(e)
            rc_auth_ok = False
            rc_auth_error = {
                "error_class": diag["error_class"],
                "error_snippet": diag["error_snippet"],
            }
    payload = {
        "configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_token_configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_url": _webhook_url(),
        **env,
        "outbound_enabled": outbound,
        "live_events_enabled": await is_live_events_enabled(),
        "active_subscription_id": (sub or {}).get("subscription_id"),
        "active_subscription_expires": (sub or {}).get("expires_at"),
        "rc_auth_ok": rc_auth_ok,
        "rc_auth_error": rc_auth_error,
    }
    if outbound and rc_auth_ok is False:
        # Return 503 so monitoring flags a real outage — not a "green"
        # env-var-only success like the pre-56.19 behavior.
        raise HTTPException(status_code=503, detail=payload)
    return payload


def _capture_rc_error(exc: Exception) -> dict:
    """Safely extract RC ApiException body for logs + client responses.

    Never echoes headers/credentials. Returns:
        {error_class: str, error_snippet: str}  (snippet ≤ 200 chars)
    """
    cls = type(exc).__name__
    snippet = ""
    # RC Python SDK: `exc.response` is the underlying HTTP response.
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            # `.text()` on some SDK versions returns str; on others a bytes-returning callable.
            text = resp.text() if callable(getattr(resp, "text", None)) else str(getattr(resp, "text", ""))
            if isinstance(text, (bytes, bytearray)):
                text = text.decode("utf-8", errors="replace")
            snippet = text[:200]
        except Exception:
            pass
    if not snippet:
        # Fall back to the exception message (still safe — no auth material).
        snippet = str(exc)[:200]
    return {"error_class": cls, "error_snippet": snippet}


# ═══════════════════════════ /webhook ═════════════════════════════════
@router.post("/webhook")
async def ringcentral_webhook(request: Request):
    """RC subscription validation + event receiver.

    Validation-Token flow: echo header + 200.
    Event flow: parse envelope, persist metadata to `ringcentral_events`,
    dispatch by event type. Raw payload is NEVER stored — handlers pull
    fresh full details via authenticated SDK where needed."""
    await _ensure_indexes()
    validation_token = request.headers.get("Validation-Token") or request.headers.get("validation-token")
    if validation_token:
        logger.info("ringcentral webhook validation request handled")
        return Response(
            content='{"received": true, "kind": "validation"}',
            media_type="application/json",
            headers={"Validation-Token": validation_token},
            status_code=200,
        )
    raw_body = await request.body()
    size = len(raw_body or b"")
    try:
        import json as _json
        payload: Dict[str, Any] = _json.loads(raw_body or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")

    # Phase 55.1 — verify the shared verification token. Every genuine
    # RC delivery repeats the token we set at subscription-create time
    # via the ``verificationToken`` field, echoed back on every event
    # as the ``Verification-Token`` header (RC docs). Missing/mismatched
    # header ⇒ 401.
    expected = os.getenv("RINGCENTRAL_WEBHOOK_TOKEN") or os.getenv("RC_WEBHOOK_TOKEN") or ""
    if expected:
        got = (request.headers.get("Verification-Token")
               or request.headers.get("verification-token")
               or request.headers.get("X-Verification-Token")
               or request.headers.get("x-rc-verification-token") or "")
        if got != expected:
            logger.warning("ringcentral webhook rejected: token mismatch")
            raise HTTPException(status_code=401, detail="invalid verification token")

    event_type = str(payload.get("event") or payload.get("eventType") or "")
    event_id = str(payload.get("uuid") or payload.get("eventId") or payload.get("id") or "") or None
    subscription_id = str(payload.get("subscriptionId") or "") or None

    try:
        await db.ringcentral_events.insert_one({
            "id": new_id(), "tenant_id": None,
            "event_type": event_type or "unknown",
            "event_id": event_id, "subscription_id": subscription_id,
            "received_at": now_iso(), "processed": False,
            "raw_payload_size_bytes": size,
        })
    except Exception as e:
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            return {"received": True, "duplicate": True, "type": event_type}
        logger.warning(f"ringcentral event insert failed: {type(e).__name__}")

    logger.info(f"ringcentral webhook event received: type={event_type} size={size}b")
    try:
        if "telephony" in event_type or "call" in event_type.lower():
            await _handle_telephony_event(payload)
        elif "SMS" in event_type or "sms" in event_type.lower():
            await _handle_sms_event(payload)
        elif "Fax" in event_type or "fax" in event_type.lower():
            await _handle_fax_event(payload)
        elif "VoiceMail" in event_type or "voicemail" in event_type.lower():
            await _handle_voicemail_event(payload)
        else:
            # Legacy shape (Phase 51 tests) — top-level `from/to/duration`.
            if payload.get("from") or payload.get("to") or payload.get("call"):
                await _handle_telephony_event(payload)
    except Exception as e:
        logger.warning(f"ringcentral handler {event_type} raised: {type(e).__name__}")
    return {"received": True, "type": event_type}


# ═══════════════════════ Event handlers ═══════════════════════════════
async def _handle_telephony_event(body: Dict[str, Any]) -> None:
    """Persist a sanitized call_log and, when caller is unknown, a lead.
    For Phase 54 telephony/sessions events the RC envelope carries a
    `body.sessionId` — we could hit `/telephony/sessions/{id}` for
    full detail, but we defer that pull until the OUT/END event so we
    have final duration + recording."""
    # Legacy shape (top-level from/to) OR nested {call:{...}}.
    call = body.get("call") if isinstance(body.get("call"), dict) else None
    if call:
        src = call
        f_raw, t_raw = src.get("from"), src.get("to")
        from_number = f_raw if isinstance(f_raw, str) else (f_raw or {}).get("phoneNumber", "")
        to_number = t_raw if isinstance(t_raw, str) else (t_raw or {}).get("phoneNumber", "")
        duration = src.get("duration") or 0
        recording_url = (src.get("recording_url")
                          or ((src.get("recording") or {}).get("contentUri")
                                if isinstance(src.get("recording"), dict) else None))
        direction = src.get("direction")
        session_id = src.get("session_id") or src.get("sessionId")
    elif body.get("from") or body.get("to"):
        from_number = (body.get("from") or {}).get("phoneNumber") or body.get("from_number") or ""
        to_number = (body.get("to") or {}).get("phoneNumber") or body.get("to_number") or ""
        duration = body.get("duration") or 0
        recording_url = (body.get("recording") or {}).get("contentUri") or body.get("recording_url")
        direction = body.get("direction")
        session_id = body.get("sessionId")
    else:
        # Phase 54 telephony/sessions envelope — pull details from RC.
        session_id = ((body.get("body") or {}).get("sessionId") if isinstance(body.get("body"), dict)
                       else body.get("sessionId"))
        detail = await _fetch_telephony_session_detail(session_id)
        if not detail:
            return
        from_number = detail.get("from_number", "")
        to_number = detail.get("to_number", "")
        duration = detail.get("duration_seconds") or 0
        recording_url = detail.get("recording_url")
        direction = detail.get("direction")
    if not (from_number or to_number):
        return
    match = await _match_customer_by_phone(None, from_number or to_number)
    # Phase 6B — fallback lead lookup when no customer matches. Kept
    # optional so a bad lookup doesn't drop the call log.
    matched_lead = None
    if not match:
        try:
            from routers.ringcentral_jwt import match_lead_by_phone
            matched_lead = await match_lead_by_phone(None, from_number or to_number)
        except Exception as _e:
            logger.warning(f"[phase6b] lead lookup skipped: {_e}")
    # Phase 6B · Feb 2026 — SSE broadcast dedup. RC sometimes emits
    # ``Proceeding`` + ``Setup`` + ``Answered`` events on the same
    # session_id within a couple seconds. Toasting three times for a
    # single call is noisy. Track session_ids we've already announced
    # for 60 seconds and skip repeat broadcasts.
    global _recent_broadcast_sessions
    try:
        _recent_broadcast_sessions
    except NameError:
        _recent_broadcast_sessions = {}
    import time as _tm
    _cutoff = _tm.monotonic() - 60.0
    _recent_broadcast_sessions = {
        k: v for k, v in _recent_broadcast_sessions.items() if v > _cutoff
    }
    already_broadcast = bool(session_id and session_id in _recent_broadcast_sessions)
    doc = {
        "id": new_id(),
        "session_id": session_id,
        "from_number": from_number, "to_number": to_number,
        "duration": duration, "recording_url": recording_url,
        "direction": direction,
        "customer_id": (match or {}).get("id"),
        "customer_name": (match or {}).get("name"),
        "lead_id": (matched_lead or {}).get("id"),
        "matched_entity": (
            "customer" if match else ("lead" if matched_lead else "unmatched")
        ),
        "tenant_id": (match or matched_lead or {}).get("tenant_id"),
        "started_at": now_iso(),
        "created_at": now_iso(),
    }
    await db.call_logs.insert_one(doc)
    # Phase 6B — compute open-invoice balance for customer matches and
    # publish an SSE event so admin/manager clients pop a toast.
    open_balance_usd = 0.0
    tenant_id_for_broadcast = (match or matched_lead or {}).get("tenant_id")
    if match and tenant_id_for_broadcast:
        try:
            from routers.ringcentral_jwt import compute_open_invoice_total
            open_balance_usd = await compute_open_invoice_total(
                tenant_id_for_broadcast, match["id"],
            )
        except Exception as _e:
            logger.warning(f"[phase6b] open balance calc failed: {_e}")
    if (direction or "").lower() != "outbound" and tenant_id_for_broadcast and not already_broadcast:
        try:
            from services.sse_broker import publish as _sse_publish
            await _sse_publish(tenant_id_for_broadcast, {
                "type": "call.inbound",
                "call_log_id": doc["id"],
                "session_id": session_id,
                "from_number": from_number,
                "to_number": to_number,
                "direction": direction,
                "duration": duration,
                "matched_entity": doc["matched_entity"],
                "customer_id": (match or {}).get("id"),
                "customer_name": (match or {}).get("name"),
                "lead_id": (matched_lead or {}).get("id"),
                "lead_name": (matched_lead or {}).get("name"),
                "open_invoice_total_usd": open_balance_usd,
                "started_at": doc["started_at"],
            })
            if session_id:
                _recent_broadcast_sessions[session_id] = _tm.monotonic()
        except Exception as _e:
            logger.warning(f"[phase6b] sse publish failed: {_e}")
    # Phase 55 — notify tenant admins on inbound call.
    if match and (direction or "").lower() != "outbound":
        await _notify_admins(
            tenant_id=(match or {}).get("tenant_id"),
            kind="rc_call_inbound",
            title=f"Inbound call · {(match or {}).get('name') or from_number}",
            body=f"{from_number} → {to_number} · {duration}s",
            href=f"/customers/{(match or {}).get('id')}" if match else None,
            customer_id=(match or {}).get("id"),
            source_ref={"kind": "call_log", "id": doc["id"], "session_id": session_id},
        )
    elif not match and (direction or "").lower() != "outbound" and from_number:
        # Phase 55.1 — surface unknown inbound calls to admins.
        await _notify_admins(
            tenant_id=await _default_tenant_id(),
            kind="rc_call_inbound_unmatched",
            title=f"New call from unknown number {from_number}",
            body=f"{from_number} → {to_number} · {duration}s",
            # Phase 56.19 · RC-diagnostic — link to the real notifications
            # inbox filtered on this kind (was the ghost route
            # /admin/unmatched-communications).
            href="/notifications?kind=rc_call_inbound_unmatched",
            source_ref={"kind": "call_log", "id": doc["id"], "session_id": session_id},
        )
    if not match and from_number:
        await db.unmatched_calls.insert_one({
            "id": new_id(), "phone": from_number,
            "session_id": session_id, "created_at": now_iso(),
            "resolved": False,
        })
        # Feb-2026 · Tag with a tenant so the ``new_lead`` sequence
        # trigger can scope. ``_default_tenant_id`` matches the
        # sibling ``_notify_admins`` call above — same webhook
        # ambient-tenant assumption.
        rc_tenant_id = await _default_tenant_id()
        rc_lead = {
            "id": new_id(), "tenant_id": rc_tenant_id,
            "source": "ringcentral-inbound",
            "phone": from_number,
            "name": f"Unknown caller {from_number[-4:]}",
            "created_at": now_iso(), "status": "new",
        }
        await db.leads.insert_one(rc_lead)
        # Fire the ``new_lead`` marketing-sequence trigger inline —
        # webhook path has no ``BackgroundTasks`` handle; a slow
        # sweep is acceptable at RC latency.
        try:
            from services.marketing.lead_triggers import (
                fire_new_lead_sequence_trigger,
            )
            await fire_new_lead_sequence_trigger(
                lead=rc_lead, tenant_id=rc_tenant_id,
            )
        except Exception:
            pass


async def _fetch_telephony_session_detail(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Best-effort pull of full session detail from RC. Returns None if
    outbound is disabled OR the SDK call fails — never raises so a bad
    fetch doesn't drop the webhook."""
    if not session_id:
        return None
    try:
        platform = get_rc_platform()
        resp = platform.get(f"/restapi/v1.0/account/~/telephony/sessions/{session_id}")
        data = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
        parties = (data or {}).get("parties") or []
        # Pick the primary party.
        p = parties[0] if parties else {}
        return {
            "from_number": ((p.get("from") or {}).get("phoneNumber") or ""),
            "to_number":   ((p.get("to") or {}).get("phoneNumber") or ""),
            "duration_seconds": p.get("duration") or 0,
            "direction": p.get("direction"),
            "recording_url": ((p.get("recordings") or [{}])[0].get("contentUri")
                                if p.get("recordings") else None),
        }
    except Exception as e:
        # Phase 56.19 · RC-diagnostic — capture RC error body safely so
        # webhook drops surface with a real reason (was: class name only).
        diag = _capture_rc_error(e)
        logger.warning(f"rc session detail fetch failed: {diag['error_class']} :: {diag['error_snippet']}")
        return None


async def _handle_sms_event(body: Dict[str, Any]) -> None:
    """Store inbound SMS or update delivery status of an outbound one."""
    inner = body.get("body") if isinstance(body.get("body"), dict) else body
    from_number = ((inner.get("from") or {}).get("phoneNumber") or inner.get("from_number") or "")
    to_list = inner.get("to") or []
    to_number = (to_list[0] or {}).get("phoneNumber") if to_list else inner.get("to_number") or ""
    msg = inner.get("subject") or inner.get("text") or inner.get("body") or ""
    rc_id = inner.get("id") or body.get("id")
    direction = "inbound" if from_number and to_number else "unknown"
    # RC emits both directions on the same event stream. Sniff the
    # ``direction`` field when it's present so outbound status updates
    # don't get mislabeled as inbound.
    rc_direction = (inner.get("direction") or "").lower()
    if rc_direction in ("outbound", "inbound"):
        direction = rc_direction
    match = await _match_customer_by_phone(None, from_number if direction == "inbound" else to_number)
    # Phase 7B · Feb 2026 — fallback lead lookup for unknown senders.
    matched_lead = None
    if direction == "inbound" and not match:
        try:
            from routers.ringcentral_jwt import match_lead_by_phone
            matched_lead = await match_lead_by_phone(None, from_number)
        except Exception as _e:
            logger.warning(f"[phase7b] SMS lead lookup skipped: {_e}")
    doc = {
        "id": new_id(),
        "tenant_id": (match or matched_lead or {}).get("tenant_id"),
        "customer_id": (match or {}).get("id"),
        "lead_id": (matched_lead or {}).get("id"),
        "direction": direction,
        "from_number": from_number, "to_number": to_number,
        "body": msg,
        "rc_message_id": rc_id,
        "delivery_status": inner.get("messageStatus") or ("received" if direction == "inbound" else "sent"),
        "sent_at": now_iso(),
    }
    await db.sms_messages.insert_one(doc)

    # Feb-2026 · Slice O — mirror outbound SMS status onto the
    # matching ``marketing_deliveries`` row so the communications-log
    # UI can show carrier delivery confirmation (SMS "read" isn't
    # achievable; only Delivered / Failed / Undelivered are surfaced).
    # We match by ``provider_response_id == rc_message_id`` — the
    # id we captured at send time.
    if direction == "outbound" and rc_id:
        raw_status = (inner.get("messageStatus")
                       or inner.get("message_status") or "").strip()
        # RC returns strings like "Delivered", "SendingFailed",
        # "DeliveryFailed", "Sent", "Queued". Normalize to a small
        # closed set the UI can pill-color.
        final_map = {
            "delivered": "delivered",
            "sendingfailed": "failed",
            "deliveryfailed": "failed",
            "failed": "failed",
            "undelivered": "undelivered",
        }
        s_low = raw_status.lower()
        sms_final = final_map.get(s_low)
        if sms_final:
            await db.marketing_deliveries.update_one(
                {"provider_response_id": rc_id, "channel": "sms"},
                {"$set": {
                    "sms_status_final": sms_final,
                    "sms_status_raw": raw_status,
                    "sms_status_at": now_iso(),
                    "provider_last_event_at": now_iso(),
                    "provider_status": sms_final,
                }},
            )
    # Phase 7B · Feb 2026 — also persist to ``sms_inbound`` per the
    # RC cutover contract. Kept separate from ``sms_messages`` (which
    # tracks BOTH directions) so consumers can subscribe to inbound
    # traffic alone via a simpler collection query.
    if direction == "inbound":
        try:
            await db.sms_inbound.insert_one({
                "id": new_id(),
                "tenant_id": doc["tenant_id"],
                "message_id": rc_id,
                "from_number": from_number,
                "to_number": to_number,
                "text": msg,
                "received_at": now_iso(),
                "matched_entity": (
                    "customer" if match
                    else ("lead" if matched_lead else "unmatched")
                ),
                "matched_customer_id": (match or {}).get("id"),
                "matched_lead_id": (matched_lead or {}).get("id"),
                "raw_event": inner,
            })
        except Exception as _e:
            logger.warning(f"[phase7b] sms_inbound insert failed: {_e}")
        # Phase 7B · STOP-keyword auto-suppress — this replaced the
        # Twilio ``/webhooks/twilio/inbound`` handler. When a customer
        # replies STOP / UNSUBSCRIBE / QUIT etc. we materialise a
        # ``marketing_suppressions`` row so our own campaign + drip
        # senders honor the opt-out even though RC has already stopped
        # the delivery on their side.
        try:
            keyword = (msg or "").strip().upper().split(None, 1)[0] \
                if (msg or "").strip() else ""
            if keyword in {"STOP", "STOPALL", "UNSUBSCRIBE",
                             "CANCEL", "END", "QUIT"} and from_number:
                # Resolve which tenant owns the ``to_number`` for cases
                # where we couldn't match sender to a customer.
                if not doc["tenant_id"] and to_number:
                    t_row = await db.tenants.find_one(
                        {"$or": [
                            {"rc_sms_from_number": to_number},
                            {"support_phone_number": to_number},
                        ]},
                        {"_id": 0, "id": 1},
                    )
                    if t_row:
                        doc["tenant_id"] = t_row["id"]
                supp_tenant = doc["tenant_id"]
                if supp_tenant:
                    existing = await db.marketing_suppressions.find_one({
                        "tenant_id": supp_tenant, "channel": "sms",
                        "address": from_number, "category": "all",
                        "deleted_at": None,
                    })
                    if not existing:
                        await db.marketing_suppressions.insert_one({
                            "id": new_id(),
                            "tenant_id": supp_tenant,
                            "channel": "sms", "address": from_number,
                            "reason": "stop_reply", "category": "all",
                            "customer_id": (match or {}).get("id"),
                            "created_at": now_iso(),
                            "created_by": "rc_inbound_sms",
                            "deleted_at": None,
                        })
        except Exception as _e:
            logger.warning(f"[phase7b] STOP-keyword handling failed: {_e}")
    # Phase K9 · Feb-2026 — Portal chat ↔ SMS bridge.  If the inbound
    # SMS carries a ``[T:xxxxxx]`` tag OR the from-number matches a
    # recent portal-chat notification, route it back to the thread
    # as a "Support" reply.  Runs BEFORE the notify-admins pass so
    # the admin-side notification already reflects any downstream
    # side effects (audit event, unread count bump).  Never raises.
    if direction == "inbound" and from_number:
        try:
            from services.portal_chat_sms_bridge import (
                route_inbound_admin_reply,
            )
            k9_result = await route_inbound_admin_reply(
                from_number=from_number, sms_text=msg,
            )
            if k9_result:
                logger.info(
                    "[k9] inbound SMS routed to portal chat thread=%s msg=%s",
                    k9_result["thread_id"], k9_result["message_id"],
                )
        except Exception as _k9e:
            logger.warning(f"[k9] inbound routing skipped: {_k9e}")

    # Phase 55 — notify admins on inbound SMS only.
    if direction == "inbound" and match:
        await _notify_admins(
            tenant_id=(match or {}).get("tenant_id"),
            kind="rc_sms_inbound",
            title=f"SMS · {(match or {}).get('name') or from_number}",
            body=msg,
            href=f"/customers/{(match or {}).get('id')}",
            customer_id=(match or {}).get("id"),
            source_ref={"kind": "sms_message", "id": doc["id"]},
        )
        # Feb-2026 Unified Notifications spec — also fire the
        # cross-channel ``inbound_customer_message`` category so admins
        # who have the RC-specific kind muted still get the unified
        # ping (default push=ON for admins).
        try:
            from services.notifications import (
                enqueue_for_tenant_admins as _emit_admins,
                enqueue_for_record_owner as _emit_owner,
            )
            tenant_id_final = (match or {}).get("tenant_id")
            # Prefer the customer's assigned tech (if any) for the
            # ``inbound_customer_message_assigned`` kind; falls back to
            # admins on the plain ``inbound_customer_message``.
            assigned_uid = (match or {}).get("assigned_user_id") \
                or (match or {}).get("default_technician_id")
            await _emit_admins(
                tenant_id_final, "inbound_customer_message",
                title=f"Customer message · {(match or {}).get('name') or from_number}",
                body=(msg or "")[:200],
                source_ref={"kind": "sms_message", "id": doc["id"]},
                href=f"/customers/{(match or {}).get('id')}",
                priority="high",
            )
            if assigned_uid:
                await _emit_owner(
                    tenant_id_final,
                    owner_user_id=assigned_uid,
                    kind="inbound_customer_message_assigned",
                    title=f"Customer message · {(match or {}).get('name') or from_number}",
                    body=(msg or "")[:200],
                    source_ref={"kind": "sms_message", "id": doc["id"]},
                    href=f"/customers/{(match or {}).get('id')}",
                    priority="high",
                    fallback_admins=False,
                )
        except Exception as _e:
            logger.warning(f"[rc] unified inbound_customer notify failed: {_e}")
    elif direction == "inbound" and from_number:
        # Phase 55.1 — surface SMS from unknown numbers to admins.
        await _notify_admins(
            tenant_id=await _default_tenant_id(),
            kind="rc_sms_inbound_unmatched",
            title=f"New SMS from unknown number {from_number}",
            body=(msg or "")[:100],
            # Phase 56.19 · RC-diagnostic — link to the notifications inbox
            # filtered on this kind.
            href="/notifications?kind=rc_sms_inbound_unmatched",
            source_ref={"kind": "sms_message", "id": doc["id"]},
        )


async def _handle_fax_event(body: Dict[str, Any]) -> None:
    inner = body.get("body") if isinstance(body.get("body"), dict) else body
    from_number = ((inner.get("from") or {}).get("phoneNumber") or "")
    rc_id = inner.get("id") or body.get("id")
    attachment_url = None
    try:
        attachments = inner.get("attachments") or []
        if attachments:
            attachment_url = attachments[0].get("uri")
    except Exception:
        pass
    match = await _match_customer_by_phone(None, from_number)
    doc = {
        "id": new_id(),
        "tenant_id": (match or {}).get("tenant_id"),
        "matched_customer_id": (match or {}).get("id"),
        "from_number": from_number,
        "attachment_url": attachment_url,
        "rc_message_id": rc_id,
        "received_at": now_iso(),
    }
    if match:
        await db.faxes.insert_one(doc)
        await _notify_admins(
            tenant_id=(match or {}).get("tenant_id"),
            kind="rc_fax",
            title=f"Fax · {(match or {}).get('name') or from_number}",
            body=f"From {from_number}" + (" · attachment attached" if attachment_url else ""),
            href=f"/customers/{(match or {}).get('id')}",
            customer_id=(match or {}).get("id"),
            source_ref={"kind": "fax", "id": doc["id"]},
        )
    else:
        await db.unmatched_faxes.insert_one(doc)
        if from_number:
            await _notify_admins(
                tenant_id=await _default_tenant_id(),
                kind="rc_fax_unmatched",
                title=f"New fax from unknown number {from_number}",
                body=(f"From {from_number}" + (" · attachment attached" if attachment_url else ""))[:100],
                # Phase 56.19 · RC-diagnostic — link to the notifications
                # inbox filtered on this kind.
                href="/notifications?kind=rc_fax_unmatched",
                source_ref={"kind": "fax", "id": doc["id"]},
            )


async def _handle_voicemail_event(body: Dict[str, Any]) -> None:
    inner = body.get("body") if isinstance(body.get("body"), dict) else body
    from_number = ((inner.get("from") or {}).get("phoneNumber") or "")
    rc_id = inner.get("id") or body.get("id")
    duration = inner.get("duration") or 0
    audio_url = None
    transcription_text = None
    try:
        atts = inner.get("attachments") or []
        for a in atts:
            if a.get("type") == "AudioRecording":
                audio_url = a.get("uri")
            elif a.get("type") == "AudioTranscription":
                transcription_text = a.get("text") or a.get("uri")
    except Exception:
        pass
    match = await _match_customer_by_phone(None, from_number)
    doc = {
        "id": new_id(),
        "tenant_id": (match or {}).get("tenant_id"),
        "matched_customer_id": (match or {}).get("id"),
        "caller_number": from_number,
        "duration": duration,
        "transcription_text": transcription_text,
        "audio_url": audio_url,
        "rc_message_id": rc_id,
        "received_at": now_iso(),
    }
    await db.voicemails.insert_one(doc)
    # Phase 55 — notify admins on new voicemail (matched only; unmatched
    # voicemails still land in db.voicemails without customer scope).
    if match:
        await _notify_admins(
            tenant_id=(match or {}).get("tenant_id"),
            kind="rc_voicemail",
            title=f"Voicemail · {(match or {}).get('name') or from_number}",
            body=(transcription_text or f"{duration}s voicemail from {from_number}")[:500],
            href=f"/customers/{(match or {}).get('id')}",
            customer_id=(match or {}).get("id"),
            source_ref={"kind": "voicemail", "id": doc["id"]},
        )
    elif from_number:
        # Phase 55.1 — surface voicemails from unknown numbers to admins.
        await _notify_admins(
            tenant_id=await _default_tenant_id(),
            kind="rc_voicemail_unmatched",
            title=f"New voicemail from unknown number {from_number}",
            body=(transcription_text or f"{duration}s voicemail from {from_number}")[:100],
            # Phase 56.19 · RC-diagnostic — link to the notifications inbox
            # filtered on this kind.
            href="/notifications?kind=rc_voicemail_unmatched",
            source_ref={"kind": "voicemail", "id": doc["id"]},
        )


# ═══════════════════════ /subscription/register ═════════════════════
class SubRegisterBody(BaseModel):
    address: Optional[str] = None  # override webhook URL for testing


@router.post("/subscription/register")
async def register_subscription(
    body: SubRegisterBody = SubRegisterBody(),
    user: dict = Depends(require_admin),
):
    """Create or refresh the RingCentral webhook subscription pointing at
    this pod's `/api/ringcentral/webhook`. Requires JWT auth + outbound
    flag off is OK — subscription creation is a control-plane call, not
    a billed outbound call. Idempotent: previous ACTIVE rows are marked
    inactive so `/health` returns the newest."""
    if not (os.getenv("RC_CLIENT_ID") and os.getenv("RC_JWT")):
        raise HTTPException(400, "rc credentials missing")
    address = body.address or _webhook_url()
    event_filters = [
        "/restapi/v1.0/account/~/extension/~/telephony/sessions",
        "/restapi/v1.0/account/~/extension/~/message-store/instant?type=SMS",
        "/restapi/v1.0/account/~/extension/~/message-store/instant?type=Fax",
        "/restapi/v1.0/account/~/extension/~/message-store/instant?type=VoiceMail",
    ]
    payload = {
        "eventFilters": event_filters,
        "deliveryMode": {"transportType": "WebHook", "address": address},
        "expiresIn": 604800,  # 7 days — RC hard cap
    }
    try:
        platform = get_rc_platform()
        resp = platform.post("/restapi/v1.0/subscription", payload)
        sub = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
    except Exception as e:
        # Phase 56.19 · RC-diagnostic — capture RC error body safely.
        diag = _capture_rc_error(e)
        logger.warning(f"rc subscription register failed: {diag['error_class']} :: {diag['error_snippet']}")
        raise HTTPException(502, detail={
            "error": "ringcentral_subscription_failed",
            "error_class": diag["error_class"],
            "error_snippet": diag["error_snippet"],
        })
    # Deactivate any prior active row(s).
    await db.ringcentral_subscriptions.update_many(
        {"active": True}, {"$set": {"active": False}},
    )
    doc = {
        "id": new_id(),
        "subscription_id": sub.get("id"),
        "status": sub.get("status"),
        "address": address,
        "event_filters": event_filters,
        "expires_at": sub.get("expirationTime"),
        "active": True,
        "created_at": now_iso(),
        "created_by": user["id"],
    }
    await db.ringcentral_subscriptions.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ═══════════════════════ /ringout (outbound call) ═══════════════════
class RingOutBody(BaseModel):
    customer_id: Optional[str] = None
    phone_number: str
    from_number: Optional[str] = None


@router.post("/ringout")
async def ringout(body: RingOutBody,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "not allowed")
    # Phase 54.1 — normalize destination to E.164 before send + storage.
    dest = _normalize_phone_e164(body.phone_number) or body.phone_number
    if not await is_outbound_enabled():
        return {"mocked": True, "reason": "rc_outbound_disabled",
                 "phone_number": dest}
    from_num = _normalize_phone_e164(body.from_number or os.getenv("RC_FROM_NUMBER") or "") \
                 or (body.from_number or os.getenv("RC_FROM_NUMBER") or "")
    if not from_num:
        raise HTTPException(400, "RC_FROM_NUMBER unset and no from_number provided")
    # Feb-2026 · Comms whitelist gate (P0 safety directive).
    try:
        from services.comms.gate import is_comm_allowed
        allowed = await is_comm_allowed(
            recipient_identifier={"customer_id": body.customer_id,
                                     "phone": dest},
            comm_type="voice",
            tenant_id=tenant["id"],
            provider="ringcentral",
            trigger_action="ringout",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"rc ringout gate errored — failing closed: {e}")
        allowed = False
    if not allowed:
        return {"mocked": True, "reason": "suppressed_not_demo",
                 "phone_number": dest}
    try:
        platform = get_rc_platform()
        resp = platform.post(
            "/restapi/v1.0/account/~/extension/~/ring-out",
            {"from": {"phoneNumber": from_num},
             "to":   {"phoneNumber": dest},
             "playPrompt": False},
        )
        rc = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
    except Exception as e:
        logger.warning(f"rc ringout failed: {type(e).__name__}")
        raise HTTPException(502, "ringcentral ring-out failed")
    await db.call_logs.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "from_number": from_num,
        "to_number": dest,
        "direction": "outbound",
        "initiated_by_user_id": user["id"],
        "rc_ringout_id": rc.get("id"),
        "status": rc.get("status", {}).get("callStatus") if isinstance(rc.get("status"), dict) else None,
        "started_at": now_iso(),
        "created_at": now_iso(),
    })
    return {"mocked": False, "rc_ringout_id": rc.get("id"), "status": rc.get("status")}


# ═══════════════════════ /sms/send (outbound SMS) ═══════════════════
class SmsSendBody(BaseModel):
    customer_id: Optional[str] = None
    phone_number: str
    message: str


@router.post("/sms/send")
async def sms_send(body: SmsSendBody,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "not allowed")
    if not body.message.strip():
        raise HTTPException(422, "empty message")
    # Phase 54.1 — normalize destination to E.164 before send + storage.
    dest = _normalize_phone_e164(body.phone_number) or body.phone_number
    if not await is_outbound_enabled():
        # Still persist the intent so the UI thread shows the queued row.
        await db.sms_messages.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": body.customer_id, "direction": "outbound",
            "from_number": os.getenv("RC_FROM_NUMBER") or "",
            "to_number": dest, "body": body.message,
            "delivery_status": "mocked",
            "initiated_by_user_id": user["id"], "sent_at": now_iso(),
        })
        return {"mocked": True, "reason": "rc_outbound_disabled"}
    from_num = _normalize_phone_e164(os.getenv("RC_FROM_NUMBER") or "") or (os.getenv("RC_FROM_NUMBER") or "")
    try:
        platform = get_rc_platform()
        resp = platform.post(
            "/restapi/v1.0/account/~/extension/~/sms",
            {"from": {"phoneNumber": from_num},
             "to":   [{"phoneNumber": dest}],
             "text": body.message},
        )
        rc = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
    except Exception as e:
        # Phase 56.19 · RC-diagnostic — capture the actual RC error body
        # (never echo credentials, only class + first 200 chars of body).
        diag = _capture_rc_error(e)
        logger.warning(f"rc sms send failed: {diag['error_class']} :: {diag['error_snippet']}")
        raise HTTPException(502, detail={
            "error": "ringcentral_sms_send_failed",
            "error_class": diag["error_class"],
            "error_snippet": diag["error_snippet"],
        })
    await db.sms_messages.insert_one({
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": body.customer_id, "direction": "outbound",
        "from_number": from_num,
        "to_number": dest, "body": body.message,
        "rc_message_id": rc.get("id"),
        "delivery_status": rc.get("messageStatus") or "sent",
        "initiated_by_user_id": user["id"], "sent_at": now_iso(),
    })
    return {"mocked": False, "rc_message_id": rc.get("id"),
             "delivery_status": rc.get("messageStatus")}


# ═══════════════════════ /contacts/sync ═════════════════════════════
@router.post("/contacts/sync")
async def contacts_sync(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Push Pool & Landscaping customers → RC personal address book. Idempotent
    by phone-number match (RC allows dup names, we dedup ourselves)."""
    if not await is_outbound_enabled():
        return {"mocked": True, "reason": "rc_outbound_disabled"}
    cursor = db.customers.find(
        {"tenant_id": tenant["id"], "phones": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "phones": 1, "email": 1, "address": 1},
    )
    pushed, skipped, failed = 0, 0, 0
    platform = get_rc_platform()
    for c in await cursor.to_list(500):
        phones = c.get("phones") or []
        if not phones:
            skipped += 1
            continue
        payload = {
            "firstName": (c.get("name") or "").split(" ")[0][:20],
            "lastName": " ".join((c.get("name") or "").split(" ")[1:])[:20] or ".",
            "email": c.get("email"),
            "businessPhone": phones[0],
        }
        try:
            platform.post("/restapi/v1.0/account/~/extension/~/address-book/contact", payload)
            pushed += 1
        except Exception:
            failed += 1
    return {"mocked": False, "pushed": pushed, "skipped": skipped, "failed": failed}


# ═══════════════════════ /events (recent metadata) ══════════════════
@router.get("/events")
async def recent_events(limit: int = 20, user: dict = Depends(require_admin)):
    rows = await db.ringcentral_events.find({}, {"_id": 0}).sort("received_at", -1).to_list(limit)
    return {"items": rows, "count": len(rows)}


# ═══════════════════════ /settings/outbound (toggle) ════════════════
class OutboundToggleBody(BaseModel):
    enabled: bool


@router.post("/settings/outbound")
async def set_outbound_flag(body: OutboundToggleBody,
                              user: dict = Depends(require_admin)):
    await db.rc_settings.update_one(
        {"key": "outbound_enabled"},
        {"$set": {"key": "outbound_enabled", "value": bool(body.enabled),
                    "updated_at": now_iso(), "updated_by": user["id"]}},
        upsert=True,
    )
    return {"outbound_enabled": bool(body.enabled)}


# ═══════════════════════ /settings/live-events (toggle) ═════════════
# Feb-2026 · Console-noise cleanup — default OFF. When disabled the
# client hook skips opening the SSE EventSource entirely, so tenants
# without RingCentral configured never see reconnect churn in the
# browser console.
class LiveEventsToggleBody(BaseModel):
    enabled: bool


@router.post("/settings/live-events")
async def set_live_events_flag(body: LiveEventsToggleBody,
                                user: dict = Depends(require_admin)):
    await db.rc_settings.update_one(
        {"key": "live_events_enabled"},
        {"$set": {"key": "live_events_enabled", "value": bool(body.enabled),
                    "updated_at": now_iso(), "updated_by": user["id"]}},
        upsert=True,
    )
    return {"live_events_enabled": bool(body.enabled)}


# ═══════════════════════ /simulate-inbound (test-only) ══════════════
class SimulateBody(BaseModel):
    event_type: str = "telephony.session"
    from_number: str = "+14805551234"
    to_number: str = "+16028870000"
    message: Optional[str] = None


@router.post("/simulate-inbound")
async def simulate_inbound(body: SimulateBody,
                            user: dict = Depends(require_admin)):
    """Admin test-only — invokes the internal handlers with a fake
    payload. No live RC round-trip. Never billable."""
    fake = {
        "event": body.event_type,
        "eventType": body.event_type,
        "uuid": new_id(),
        "subscriptionId": "sim",
        "call": {"from": body.from_number, "to": body.to_number,
                  "duration": 12, "direction": "inbound"},
        "body": {"from": {"phoneNumber": body.from_number},
                  "to": [{"phoneNumber": body.to_number}],
                  "subject": body.message or "Simulated inbound message"},
    }
    if body.event_type.lower().find("sms") >= 0:
        await _handle_sms_event(fake)
    elif body.event_type.lower().find("fax") >= 0:
        await _handle_fax_event(fake)
    elif body.event_type.lower().find("voicemail") >= 0:
        await _handle_voicemail_event(fake)
    else:
        await _handle_telephony_event(fake)
    return {"simulated": True, "event_type": body.event_type}
