"""Phase 6 · RingCentral JWT-bearer router — voice + subscriptions.

Complements the pre-existing OAuth-based ``routers/ringcentral.py`` from
Phase 52/54. New endpoints exposed under ``/api/rc/*`` to avoid path
collisions; the shared webhook still lives at
``/api/ringcentral/webhook`` (handled by the older router).

Phase 6B additions (Feb 2026)
=============================
* ``POST /api/dev/rc-verify-echo`` — admin token/env echo for the
  Telephony admin page ping card.
* ``GET  /api/rc/live-events`` — SSE stream fanned out to admin +
  manager clients for inbound-call auto-toast.
* ``POST /api/rc/call`` — now rate-limited to 20 requests / minute
  per user.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import jwt as _jwt

from config import db, logger, JWT_SECRET, JWT_ALGO
from routers.tenants import get_current_tenant
from services.ringcentral.rc_client import RingCentralError, RingCentralService
from services.sse_broker import subscribe, unsubscribe, subscriber_count
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_TELEPHONY_FILTER = "/restapi/v1.0/account/~/telephony/sessions"
_VOICEMAIL_FILTER = "/restapi/v1.0/account/~/extension/~/message-store"
# Phase 7B · Feb 2026 — inbound SMS event stream. RingCentral emits
# message-store `instant` events filtered to ``type=SMS`` when a new
# SMS arrives on the extension.
_SMS_FILTER = "/restapi/v1.0/account/~/extension/~/message-store/instant?type=SMS"
_DEFAULT_EVENT_FILTERS = [_TELEPHONY_FILTER, _VOICEMAIL_FILTER, _SMS_FILTER]

# Phase 6B — roles allowed to subscribe to the inbound-call SSE stream.
# Coded as a constant so we can add ``dispatcher`` / ``csr`` later with
# a one-line change instead of hunting through the file.
INBOUND_TOAST_ROLES = {"admin", "super_admin", "manager"}

# Phase 6B — per-user in-memory rate limiter for POST /api/rc/call.
# Bucket = 20 requests / rolling 60 seconds. Process-local (single
# replica behavior — same as the SSE broker). If we ever run more than
# one backend replica this bucket needs to move to Redis.
_RC_CALL_LIMIT = 20
_RC_CALL_WINDOW_S = 60.0
_rc_call_hits: dict[str, list[float]] = defaultdict(list)
_rc_call_lock = asyncio.Lock()


async def _rate_limit_rc_call(user_id: str) -> None:
    now = time.monotonic()
    async with _rc_call_lock:
        bucket = _rc_call_hits[user_id]
        # Drop hits older than the window.
        cutoff = now - _RC_CALL_WINDOW_S
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= _RC_CALL_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit — max {_RC_CALL_LIMIT} calls / minute",
            )
        bucket.append(now)


def _require_admin(u: dict) -> None:
    if (u or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")


def _call_allowed(u: dict) -> None:
    if (u or {}).get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")


def _live_events_allowed(u: dict) -> None:
    if (u or {}).get("role") not in INBOUND_TOAST_ROLES:
        raise HTTPException(403, "Not allowed")


class CallBody(BaseModel):
    to_number: str
    from_number: Optional[str] = None


class LogOutboundBody(BaseModel):
    to_number: str
    from_number: str
    entity_kind: str = Field(...)
    entity_id: str
    note: Optional[str] = None


class VerifyEchoBody(BaseModel):
    ping: Optional[str] = None


class RcSmsTestBody(BaseModel):
    to: str
    body: Optional[str] = None


@router.post("/dev/ringcentral-ping")
async def rc_ping(user: dict = Depends(get_current_user)):
    _require_admin(user)
    svc = RingCentralService()
    try:
        ext = await svc.get_my_extension()
    except RingCentralError as e:
        logger.warning(f"[phase6] rc-ping failed status={e.status}")
        return {"ok": False, "error_status": e.status,
                 "error_body": str(e.body)[:400], "mode": svc.mode}
    return {"ok": True,
             "extension_id": ext.get("id"),
             "extension_number": ext.get("extensionNumber"),
             "account_id": (ext.get("account") or {}).get("id"),
             "status": ext.get("status"),
             "mode": svc.mode}


@router.post("/dev/rc-rate-limit-reset")
async def rc_rate_limit_reset(user: dict = Depends(get_current_user)):
    """Phase 6B — admin-only reset of the ``/api/rc/call`` per-user rate
    limit bucket. Exists so tests can prove the 20/min gate works
    deterministically; also useful in production if an admin needs to
    unstick a legitimately-throttled user without waiting 60 seconds."""
    _require_admin(user)
    target = user.get("id") or "anon"
    async with _rc_call_lock:
        _rc_call_hits.pop(target, None)
    return {"ok": True, "reset_user_id": target}


class RatePrimeBody(BaseModel):
    count: int = Field(default=20, ge=0, le=200)


@router.post("/dev/rc-rate-limit-prime")
async def rc_rate_limit_prime(body: RatePrimeBody = RatePrimeBody(),
                                user: dict = Depends(get_current_user)):
    """Phase 6B — admin-only test hook. Fills the caller's rate-limit
    bucket with N synthetic hits without ever contacting RingCentral,
    so the 429 threshold can be asserted without burning real RC quota
    or triggering RC's own rate-limiter. No effect in production
    unless an admin explicitly calls it."""
    _require_admin(user)
    target = user.get("id") or "anon"
    now = time.monotonic()
    async with _rc_call_lock:
        bucket = _rc_call_hits[target]
        bucket.extend([now] * int(body.count))
    return {"ok": True, "hits": len(_rc_call_hits.get(target, []))}


@router.post("/dev/rc-verify-echo")
async def rc_verify_echo(body: VerifyEchoBody = VerifyEchoBody(),
                         user: dict = Depends(get_current_user)):
    """Phase 6B — admin-only env/token verification helper for the
    Telephony admin page. Returns non-secret configuration so the UI
    can confirm the RC JWT + client id are populated + the webhook
    verification token is set. Never echoes any secret VALUES."""
    _require_admin(user)
    jwt = os.getenv("RC_JWT") or ""
    sub_last4 = ""
    exp = None
    try:
        import base64 as _b64, json as _json
        payload_b64 = jwt.split(".")[1] + "=="
        claims = _json.loads(_b64.urlsafe_b64decode(payload_b64.encode()))
        sub_last4 = (claims.get("sub") or "")[-4:]
        exp = claims.get("exp")
    except Exception:
        pass
    return {
        "ok": True,
        "ping": body.ping,
        "mode": os.getenv("RC_MODE") or "unset",
        "server": (os.getenv("RC_SERVER_URL") or "").replace("https://", ""),
        "jwt_sub_last4": sub_last4,
        "jwt_exp": exp,
        "client_id_set": bool(os.getenv("RC_CLIENT_ID")),
        "client_secret_set": bool(os.getenv("RC_CLIENT_SECRET")),
        "webhook_url_set": bool(os.getenv("RC_WEBHOOK_URL")),
        "webhook_verification_token_set": bool(
            os.getenv("RC_VERIFICATION_TOKEN")
            or os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")
        ),
        "echoed_by_user": user.get("id"),
    }


@router.post("/dev/sms-provider-status")
async def sms_provider_status(user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    """Phase 7B · Feb 2026 — ops sanity check on the SMS provider swap.

    Reports the currently-configured provider, the default from-number,
    whether the RC extension actually has SMS scope (verified by an
    online lookup of ``.../phone-number`` filtered to ``SmsSender``),
    and whether the RC subscription registered for this tenant carries
    the ``message-store/instant?type=SMS`` filter."""
    _require_admin(user)
    # Provider is now hardcoded to RingCentral. The runtime toggle is
    # deliberately gone — the cutover was definitive.
    default_from = (
        os.getenv("RC_SMS_DEFAULT_FROM")
        or (tenant.get("rc_sms_from_number") or "")
    )
    sms_scope_ok = False
    scope_reason: Optional[str] = None
    try:
        pn = await RingCentralService(tenant["id"]).list_extension_phone_numbers()
        rows = (pn or {}).get("records") or []
        sms_scope_ok = any(
            "SmsSender" in (r.get("features") or []) for r in rows
        )
        if not sms_scope_ok:
            scope_reason = "no SmsSender-capable phone on this RC extension"
    except RingCentralError as e:
        scope_reason = f"rc {e.status}: {str(e.body)[:200]}"
    except Exception as e:  # pragma: no cover
        scope_reason = f"{type(e).__name__}: {e}"

    subscription_includes_sms = False
    try:
        sub = await db.ringcentral_subscriptions.find_one(
            {"tenant_id": tenant["id"]},
            {"_id": 0, "event_filters": 1, "subscription_id": 1},
        )
        if sub:
            filters = sub.get("event_filters") or []
            subscription_includes_sms = any(
                "message-store/instant" in f and "type=SMS" in f
                for f in filters
            )
    except Exception:  # pragma: no cover
        pass

    return {
        "provider": "ringcentral",
        "default_from": default_from,
        "sms_scope_ok": sms_scope_ok,
        "sms_scope_reason": scope_reason,
        "subscription_includes_sms": subscription_includes_sms,
        "twilio_env_removed": all(
            not os.getenv(k) for k in (
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_API_KEY_SID", "TWILIO_API_KEY_SECRET",
                "TWILIO_FROM_NUMBER",
            )
        ),
    }

# Phase 7A · Feb 2026 — RC SMS wiring test. Only registered when
# ALLOW_TEST_HOOKS=1 so production never exposes it. Never included
# in real customer-facing surfaces.
if os.getenv("ALLOW_TEST_HOOKS") == "1":
    import time as _time

    @router.post("/dev/rc-sms-test")
    async def rc_sms_test(body: RcSmsTestBody,
                            user: dict = Depends(get_current_user)):
        _require_admin(user)
        if not body.to:
            raise HTTPException(400, "Missing 'to' number")
        default_body = (
            f"[dev] RingCentral SMS wiring test — {int(_time.time())} — "
            "please ignore."
        )
        text = body.body or default_body
        svc = RingCentralService()
        try:
            res = await svc.send_sms(body.to, text)
        except RingCentralError as e:
            # Log a masked recipient; never echo the RC body verbatim
            # in the log because RC error responses can occasionally
            # embed the client bundle context.
            masked = (body.to or "")[-4:].rjust(len(body.to or ""), "*")
            logger.warning(
                f"[phase7a] rc-sms-test to=***{masked} status={e.status} "
                f"scope_missing={getattr(e, 'scope_missing', False)}"
            )
            raise HTTPException(
                status_code=502 if e.status >= 500 else e.status,
                detail={"provider": "ringcentral",
                          "status": e.status,
                          "body": str(e.body)[:400],
                          "scope_missing": getattr(e, "scope_missing", False)},
            )
        return {
            "ok": True,
            "provider": res["provider"],
            "message_id": res["message_id"],
            "status": res["status"],
            "from_number": res["from_number"],
            "to_number": res["to_number"],
            "raw": res["raw"],
        }



@router.post("/rc/call")
async def rc_call(body: CallBody,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _call_allowed(user)
    await _rate_limit_rc_call(user.get("id") or "anon")
    # Phase 7A/B · Feb 2026 — resolution priority for outbound caller ID:
    #   1. Caller-supplied ``body.from_number``
    #   2. User's own phone (personal DID)
    #   3. Tenant's configured RC voice caller-ID
    #      (``tenant.rc_voice_caller_id_number`` → fall back to
    #      ``tenant.rc_sms_from_number`` for tenants that share one line)
    #   4. Global env ``RC_VOICE_DEFAULT_FROM``
    #   5. Legacy ``tenant.support_phone_number``
    from_number = body.from_number or (user.get("phone") or "").strip()
    if not from_number:
        from_number = (
            (tenant.get("rc_voice_caller_id_number") or "").strip()
            or (tenant.get("rc_sms_from_number") or "").strip()
        )
    if not from_number:
        from_number = (os.getenv("RC_VOICE_DEFAULT_FROM") or "").strip()
    if not from_number:
        from_number = (tenant.get("support_phone_number") or "").strip()
    if not from_number:
        raise HTTPException(400, "No from_number resolvable")
    svc = RingCentralService(tenant["id"])
    try:
        res = await svc.ring_out(from_number, body.to_number)
    except RingCentralError as e:
        raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                             detail=f"RingCentral: {e.body}")
    return {"status": "queued", "ringout_id": res.get("id"),
             "from_number": from_number, "to_number": body.to_number}


@router.post("/rc/setup-webhooks")
async def rc_setup_webhooks(user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    """Phase 7B · Feb 2026 — idempotent RC webhook subscription that
    ALWAYS includes the SMS instant-event filter.

    Behavior:
    * If a subscription for ``(tenant, url)`` already exists AND its
      ``event_filters`` set contains every entry in
      ``_DEFAULT_EVENT_FILTERS``, return early with ``created=False``.
    * If a subscription exists but is MISSING the SMS filter (legacy
      Phase-6 subscriptions), CANCEL the stale sub server-side + on
      RC and CREATE a fresh one with the full filter list. RC's
      subscription resource does not support atomic filter PATCH for
      account-scoped subs, so cancel-and-recreate is the cleanest
      path (documented at platform.ringcentral.com › Subscription API).
    """
    _require_admin(user)
    url = os.getenv("RC_WEBHOOK_URL") or ""
    vtok = os.getenv("RC_VERIFICATION_TOKEN") or ""
    if not url or not vtok:
        raise HTTPException(500, "RC_WEBHOOK_URL or RC_VERIFICATION_TOKEN missing")
    existing = await db.ringcentral_subscriptions.find_one(
        {"tenant_id": tenant["id"], "address": url},
        {"_id": 0, "subscription_id": 1, "event_filters": 1},
    )
    if existing:
        current = set(existing.get("event_filters") or [])
        needed = set(_DEFAULT_EVENT_FILTERS)
        if needed.issubset(current):
            return {"ok": True, "created": False,
                     "subscription_id": existing["subscription_id"],
                     "reason": "already_exists",
                     "event_filters": sorted(current)}
        # Legacy sub — missing SMS filter. Cancel and recreate.
        stale_sid = existing["subscription_id"]
        try:
            await RingCentralService(tenant["id"]).delete_subscription(stale_sid)
        except RingCentralError as e:
            # Non-fatal — if RC has already garbage-collected it, just
            # drop our own row and move on.
            logger.warning(
                f"[phase7b] cancel-stale sub {stale_sid} failed: {e.status}"
            )
        await db.ringcentral_subscriptions.delete_one(
            {"tenant_id": tenant["id"], "subscription_id": stale_sid},
        )
    svc = RingCentralService(tenant["id"])
    try:
        sub = await svc.create_subscription(url, vtok, _DEFAULT_EVENT_FILTERS)
    except RingCentralError as e:
        raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                             detail=f"RingCentral: {e.body}")
    sub_id = sub.get("id")
    await db.ringcentral_subscriptions.insert_one({
        "id": new_id(), "tenant_id": tenant["id"],
        "subscription_id": sub_id, "address": url,
        "event_filters": list(_DEFAULT_EVENT_FILTERS),
        "created_at": now_iso(),
    })
    return {"ok": True, "created": True, "subscription_id": sub_id,
             "event_filters": list(_DEFAULT_EVENT_FILTERS)}


@router.get("/rc/subscriptions")
async def rc_list_subs(user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    rows = await db.ringcentral_subscriptions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).to_list(50)
    return {"subscriptions": rows}


@router.delete("/rc/subscriptions/{sid}")
async def rc_delete_sub(sid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    svc = RingCentralService(tenant["id"])
    try:
        await svc.delete_subscription(sid)
    except RingCentralError as e:
        if e.status != 404:
            raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                                 detail=f"RingCentral: {e.body}")
    await db.ringcentral_subscriptions.delete_one(
        {"tenant_id": tenant["id"], "subscription_id": sid},
    )
    return {"ok": True}


@router.post("/rc/log-outbound")
async def rc_log_outbound(body: LogOutboundBody,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "session_id": None,
        "direction": "Outbound",
        "status": "Intent",
        "from_number": body.from_number,
        "to_number": body.to_number,
        "attribution": {"entity_kind": body.entity_kind,
                          "entity_id": body.entity_id,
                          "note": body.note},
        "initiated_by_user_id": user.get("id"),
        "started_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.call_logs.insert_one(doc)
    return {"ok": True, "call_log_id": doc["id"]}


@router.get("/rc/timeline")
async def rc_timeline(entity_kind: str, entity_id: str, limit: int = 50,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    rows = await db.call_logs.find(
        {"tenant_id": tenant["id"],
         "attribution.entity_kind": entity_kind,
         "attribution.entity_id": entity_id},
        {"_id": 0, "raw_event": 0},
    ).sort("started_at", -1).limit(int(limit)).to_list(int(limit))
    return {"calls": rows}


@router.get("/rc/logs")
async def rc_logs(limit: int = 25,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    rows = await db.call_logs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "raw_event": 0},
    ).sort("started_at", -1).limit(int(limit)).to_list(int(limit))
    return {"calls": rows}


async def _resolve_user_from_query_token(token: Optional[str]) -> dict:
    """Phase 6B — decode a JWT passed via ?token= for EventSource.

    Browsers can't attach an Authorization header to `new EventSource`,
    so we accept the token as a query param instead. Same validation
    as ``utils.get_current_user``: signature + expiry + user active
    state. Rejects with 401 on any failure.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one(
        {"id": payload.get("sub")}, {"_id": 0, "password_hash": 0},
    )
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("active") is False:
        raise HTTPException(status_code=401, detail="Account is deactivated")
    return user


@router.get("/rc/live-events")
async def rc_live_events(request: Request,
                          token: Optional[str] = Query(default=None),
                          tenant: Optional[str] = Query(default=None)):
    """Phase 6B — Server-Sent Events stream for inbound-call auto-toast.

    Gated to admin + manager roles (see ``INBOUND_TOAST_ROLES``). Auth
    is via ``?token=<JWT>`` because browsers can't attach an
    Authorization header to EventSource. Each connected client gets an
    isolated queue via ``services.sse_broker``. Sends a heartbeat every
    15 seconds so intermediaries (nginx, Cloudflare) don't idle-close
    the connection.
    """
    user = await _resolve_user_from_query_token(token)
    _live_events_allowed(user)

    # Resolve tenant: prefer the user's own tenant_id; super_admins may
    # override via ?tenant=<slug>.
    tenant_doc = None
    if tenant and user.get("role") == "super_admin":
        tenant_doc = await db.tenants.find_one(
            {"slug": tenant, "active": True}, {"_id": 0},
        )
    if not tenant_doc and user.get("tenant_id"):
        tenant_doc = await db.tenants.find_one(
            {"id": user["tenant_id"], "active": True}, {"_id": 0},
        )
    if not tenant_doc:
        raise HTTPException(status_code=400, detail="Tenant not resolvable")
    tenant_id = tenant_doc["id"]
    queue = await subscribe(tenant_id)

    async def _stream():
        # Kick off with a "ready" event so the frontend knows the SSE
        # handshake completed. Uses a keyed dict per sse-starlette API.
        import json as _json
        yield {
            "event": "ready",
            "data": _json.dumps({
                "tenant_id": tenant_id,
                "subscriber_count": subscriber_count(tenant_id),
            }),
        }
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat comment — keeps the connection alive.
                    yield {"event": "ping", "data": _json.dumps({"ts": now_iso()})}
                    continue
                yield {
                    "event": payload.get("type") or "call.inbound",
                    "data": _json.dumps(payload),
                }
        finally:
            await unsubscribe(tenant_id, queue)

    return EventSourceResponse(_stream())


# ═══════════════════════════ Phase 6B — internal helpers ═══════════════
async def compute_open_invoice_total(tenant_id: str, customer_id: str) -> float:
    """Sum unpaid invoice balances for a customer within a tenant.

    Mirrors the logic in ``routers/quotes.py::ar_summary``: balance =
    ``total - amount_paid`` for docs where ``doc_type == 'invoice'`` and
    ``payment_status != 'paid'``. Returns 0.0 when no unpaid rows.
    """
    if not (tenant_id and customer_id):
        return 0.0
    total = 0.0
    cursor = db.quotes.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "doc_type": "invoice",
         "payment_status": {"$ne": "paid"}},
        {"_id": 0, "total": 1, "amount_paid": 1},
    )
    async for d in cursor:
        t = float(d.get("total") or 0)
        p = float(d.get("amount_paid") or 0)
        bal = round(t - p, 2)
        if bal > 0.01:
            total += bal
    return round(total, 2)


async def match_lead_by_phone(tenant_id: Optional[str], phone: str) -> Optional[dict]:
    """Fallback lookup: match a lead by phone when no customer matches.

    Uses a permissive last-10-digit tail so ``+1480-555-0102`` and
    ``4805550102`` collide.
    """
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    tail10 = digits[-10:] if len(digits) >= 10 else digits
    if len(tail10) < 7:
        return None
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    q["phone"] = {"$regex": tail10 + "$"}
    return await db.leads.find_one(q, {"_id": 0})
