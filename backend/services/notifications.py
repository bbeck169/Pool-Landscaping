"""Phase 55 · Unified notifications engine.

Single source of truth for emitting in-app / email / SMS alerts across the
entire CRM. Every event source (RingCentral SMS/call/voicemail/fax, system
events like autosave-conflict / dispatcher / cancel-cascade, tech notes,
customer portal messages, etc.) funnels through ``emit()``.

Design
======
* **Bell channel is authoritative.** When ``bell`` is enabled for the target
  user + kind, we always insert a row into ``db.notifications``. That's what
  the header bell counts. Realtime WS/SSE fan-out is best-effort.
* **Email channel is gated by ``RESEND_API_KEY``**. When the key is missing
  we log a mock row into ``email_delivery_log`` — same pattern as the
  Phase 50.G / 52.A digests. NEVER echo the key.
* **SMS channel is gated by ``RC_OUTBOUND_ENABLED``** (runtime tenant flag
  wins over env). When the flag is off we record a queued row in
  ``sms_messages`` so the thread UI reflects the intent without actually
  billing an RC send. NEVER flip the flag from this module.
* **Preferences.** Read per-user from ``db.notification_preferences``.
  ``get_user_prefs`` merges defaults for any unset kind so first-time users
  behave identically to seeded users.
* **Body truncation.** Every ``body`` is truncated to 500 chars server-side
  to keep the bell dropdown scannable and the DB rows bounded.
* **No push notifications yet** — TODO below. Foreground WS/SSE and
  Expo push (mobile_push router) already handle in-app fan-out.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from config import db, logger
from utils import new_id, now_iso

# ─── Kinds catalog ─────────────────────────────────────────────────────────
# Keep this list stable — the /settings/notifications UI renders one row per
# kind and persists per-channel toggles keyed by the kind string.
KIND_LABELS: dict[str, str] = {
    # RingCentral (Phase 54)
    "rc_sms_inbound":    "RingCentral · Inbound SMS",
    "rc_call_inbound":   "RingCentral · Inbound Call",
    "rc_voicemail":      "RingCentral · Voicemail",
    "rc_fax":            "RingCentral · Fax",
    # Jobs / dispatch
    "job_assigned":      "Job Assigned",
    "job_completed":     "Job Completed",
    "job_cancelled":     "Job Cancelled",
    "dispatch_alert":    "Dispatch Alert",
    "autosave_conflict": "Autosave Conflict",
    # Money
    "invoice_paid":      "Invoice Paid",
    "invoice_overdue":   "Invoice Overdue",
    "payment_received":  "Payment Received",
    "payment_refunded":  "Payment Refunded",
    # Communications
    "tech_message":      "Technician Message",
    "tech_note":         "Technician Note",
    "customer_message":  "Customer Portal Message",
    # Leads / marketing
    "lead_new":          "New Lead",
    # Meta
    "system_alert":      "System Alert",
}

DEFAULT_CHANNELS = {"bell": True, "email": False, "sms": False}
BODY_TRUNCATE = 500


def default_prefs() -> dict:
    """Fresh preference blob — bell ON, email/sms OFF for every kind."""
    return {k: dict(DEFAULT_CHANNELS) for k in KIND_LABELS}


async def get_user_prefs(tenant_id: str, user_id: str) -> dict:
    """Return the merged preference doc for a user. Never returns None."""
    doc = await db.notification_preferences.find_one(
        {"tenant_id": tenant_id, "user_id": user_id}, {"_id": 0}
    ) or {}
    stored = doc.get("channels") or {}
    merged = default_prefs()
    for kind, chans in stored.items():
        if isinstance(chans, dict):
            merged[kind] = {**merged.get(kind, dict(DEFAULT_CHANNELS)), **chans}
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "channels": merged,
        "updated_at": doc.get("updated_at"),
    }


async def set_user_prefs(tenant_id: str, user_id: str, channels: dict) -> dict:
    """Upsert. Silently drops kinds we don't recognize (schema guard)."""
    clean: dict[str, dict] = {}
    for kind, chans in (channels or {}).items():
        if kind not in KIND_LABELS:
            continue
        if not isinstance(chans, dict):
            continue
        clean[kind] = {
            "bell":  bool(chans.get("bell",  DEFAULT_CHANNELS["bell"])),
            "email": bool(chans.get("email", DEFAULT_CHANNELS["email"])),
            "sms":   bool(chans.get("sms",   DEFAULT_CHANNELS["sms"])),
        }
    now = now_iso()
    await db.notification_preferences.update_one(
        {"tenant_id": tenant_id, "user_id": user_id},
        {"$set": {"channels": clean, "updated_at": now, "tenant_id": tenant_id, "user_id": user_id}},
        upsert=True,
    )
    return await get_user_prefs(tenant_id, user_id)


# ─── Emit ──────────────────────────────────────────────────────────────────
async def emit(
    user_ids: Iterable[str],
    kind: str,
    title: str,
    body: str,
    source_ref: Optional[dict] = None,
    href: Optional[str] = None,
    priority: str = "normal",
    customer_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> list[str]:
    """Fan out a notification to a list of user IDs, honoring per-user prefs.

    Returns the list of created notification IDs (bell-channel rows).

    Arguments
    ---------
    user_ids   : list/tuple of user ids OR a single id string
    kind       : one of ``KIND_LABELS`` — silently accepts unknown kinds so
                 callers don't crash if a new kind is added mid-migration.
    title      : short header shown in the bell dropdown
    body       : body text, truncated to 500 chars
    source_ref : arbitrary dict linking back to the source doc, e.g.
                 ``{"kind":"invoice","id":"..."}``
    href       : deep-link URL for the "Open" button on the row (relative)
    priority   : "low" | "normal" | "high" — surfaced to the UI
    customer_id: opt-in customer scoping for portal reads
    tenant_id  : if omitted we resolve from the target user's tenant_id
    """
    if isinstance(user_ids, str):
        user_ids = [user_ids]
    user_ids = [uid for uid in (user_ids or []) if uid]
    if not user_ids:
        return []

    title = (title or "")[:200]
    body = (body or "")[:BODY_TRUNCATE]
    label = KIND_LABELS.get(kind, kind)
    created: list[str] = []

    for uid in user_ids:
        # Tenant fallback lookup — some emitters (e.g. RC webhook) may not
        # have tenant context.
        t_id = tenant_id
        if not t_id:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "tenant_id": 1}) or {}
            t_id = u.get("tenant_id")

        prefs = (await get_user_prefs(t_id, uid))["channels"].get(kind, dict(DEFAULT_CHANNELS))

        if prefs.get("bell", True):
            nid = new_id()
            doc = {
                "id": nid,
                "tenant_id": t_id,
                "user_id": uid,
                "customer_id": customer_id,
                "kind": kind,
                "label": label,
                "title": title,
                "body": body,
                "href": href,
                "priority": priority,
                "source_ref": source_ref or {},
                "read": False,
                "created_at": now_iso(),
            }
            await db.notifications.insert_one(doc)
            created.append(nid)
            # Realtime fan-out — best effort.
            try:
                from routers.realtime import bus
                await bus.broadcast(uid, {"type": "notification",
                                            "payload": {k: doc[k] for k in
                                                        ("id", "title", "body", "kind",
                                                         "href", "priority", "created_at")}})
            except Exception:
                pass
            # Expo mobile push — best effort. Respects registered devices.
            try:
                from routers.mobile_push import send_push_to_user
                await send_push_to_user(uid, title, body,
                                        data={"notification_id": nid, "kind": kind, "href": href})
            except Exception:
                pass

        if prefs.get("email", False):
            await _dispatch_email(t_id, uid, title, body, kind, href)

        if prefs.get("sms", False):
            await _dispatch_sms(t_id, uid, f"{title}: {body}"[:320], kind)

    return created


# ─── Email dispatch (mocks when RESEND_API_KEY missing) ───────────────────
async def _dispatch_email(tenant_id: Optional[str], user_id: str, subject: str,
                          body: str, kind: str, href: Optional[str]) -> None:
    from utils import now_iso as _n
    resend_key = os.environ.get("RESEND_API_KEY")
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1, "name": 1}) or {}
    to_addr = u.get("email")
    if not to_addr:
        return
    if not resend_key:
        await db.email_delivery_log.insert_one({
            "id": new_id(),
            "kind": f"notification:{kind}",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "to": to_addr,
            "subject": subject,
            "body": body,
            "href": href,
            "mocked": True,
            "reason": "resend_key_missing",
            "created_at": _n(),
        })
        return
    try:
        import resend  # type: ignore
        resend.api_key = resend_key
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
            "to": [to_addr],
            "subject": subject,
            "html": f"<p>{body}</p>" + (f'<p><a href="{href}">Open</a></p>' if href else ""),
        })
        await db.email_delivery_log.insert_one({
            "id": new_id(),
            "kind": f"notification:{kind}",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "to": to_addr,
            "subject": subject,
            "mocked": False,
            "created_at": _n(),
        })
    except Exception as e:
        logger.warning(f"notif email dispatch failed: {type(e).__name__}")


# ─── SMS dispatch (honors RC_OUTBOUND_ENABLED) ─────────────────────────────
async def _dispatch_sms(tenant_id: Optional[str], user_id: str, body: str, kind: str) -> None:
    """Send an SMS via RingCentral when outbound is enabled, else queue a
    mocked row so the audit trail exists."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "phone": 1}) or {}
    to = u.get("phone")
    if not to:
        return
    try:
        from services.ringcentral_client import is_outbound_enabled, get_rc_platform
    except Exception:
        is_outbound_enabled = None  # type: ignore
    enabled = False
    try:
        enabled = bool(is_outbound_enabled and await is_outbound_enabled())
    except Exception:
        enabled = False
    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": None,
        "direction": "outbound",
        "from_number": os.environ.get("RC_FROM_NUMBER") or None,
        "to_number": to,
        "body": body,
        "rc_message_id": None,
        "delivery_status": "sent" if enabled else "mocked",
        "sent_at": now_iso(),
        "kind": f"notification:{kind}",
    }
    if enabled:
        try:
            platform = get_rc_platform()
            platform.post("/restapi/v1.0/account/~/extension/~/sms",
                          {"from": {"phoneNumber": row["from_number"]},
                           "to": [{"phoneNumber": to}],
                           "text": body})
        except Exception as e:
            logger.warning(f"notif sms send failed: {type(e).__name__}")
            row["delivery_status"] = "failed"
    await db.sms_messages.insert_one(row)


# TODO(push): OS-level push (APNs/FCM via Expo push service is already wired
# through routers.mobile_push.send_push_to_user; a browser Push API endpoint
# is deferred to a follow-up phase — see HANDOFF.md).
