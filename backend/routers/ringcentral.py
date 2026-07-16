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
    tenant. Silent no-op when tenant unknown (unmatched inbound)."""
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
                          customer_id=customer_id, tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"rc notif fan-out failed: {type(e).__name__}")


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
    return {
        "configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_token_configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_url": _webhook_url(),
        **env,
        "outbound_enabled": outbound,
        "active_subscription_id": (sub or {}).get("subscription_id"),
        "active_subscription_expires": (sub or {}).get("expires_at"),
    }


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

    # TODO(phase 55) — verify HMAC against RINGCENTRAL_WEBHOOK_TOKEN.
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
    doc = {
        "id": new_id(),
        "session_id": session_id,
        "from_number": from_number, "to_number": to_number,
        "duration": duration, "recording_url": recording_url,
        "direction": direction,
        "customer_id": (match or {}).get("id"),
        "customer_name": (match or {}).get("name"),
        "tenant_id": (match or {}).get("tenant_id"),
        "started_at": now_iso(),
        "created_at": now_iso(),
    }
    await db.call_logs.insert_one(doc)
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
    if not match and from_number:
        await db.unmatched_calls.insert_one({
            "id": new_id(), "phone": from_number,
            "session_id": session_id, "created_at": now_iso(),
            "resolved": False,
        })
        await db.leads.insert_one({
            "id": new_id(), "source": "ringcentral-inbound",
            "phone": from_number,
            "name": f"Unknown caller {from_number[-4:]}",
            "created_at": now_iso(), "status": "new",
        })


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
        logger.warning(f"rc session detail fetch failed: {type(e).__name__}")
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
    match = await _match_customer_by_phone(None, from_number if direction == "inbound" else to_number)
    doc = {
        "id": new_id(),
        "tenant_id": (match or {}).get("tenant_id"),
        "customer_id": (match or {}).get("id"),
        "direction": direction,
        "from_number": from_number, "to_number": to_number,
        "body": msg,
        "rc_message_id": rc_id,
        "delivery_status": inner.get("messageStatus") or ("received" if direction == "inbound" else "sent"),
        "sent_at": now_iso(),
    }
    await db.sms_messages.insert_one(doc)
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
        # Never surface the exception detail — may contain auth material.
        logger.warning(f"rc subscription register failed: {type(e).__name__}")
        raise HTTPException(502, "ringcentral subscription request failed")
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
        logger.warning(f"rc sms send failed: {type(e).__name__}")
        raise HTTPException(502, "ringcentral sms send failed")
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
    """Push AquaTerra customers → RC personal address book. Idempotent
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
