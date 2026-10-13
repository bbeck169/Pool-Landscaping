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
    # RingCentral unmatched (Phase 55.1 — inbound from unknown numbers)
    "rc_sms_inbound_unmatched":  "RingCentral · Inbound SMS (unknown number)",
    "rc_call_inbound_unmatched": "RingCentral · Inbound Call (unknown number)",
    "rc_voicemail_unmatched":    "RingCentral · Voicemail (unknown number)",
    "rc_fax_unmatched":          "RingCentral · Fax (unknown number)",
    # Jobs / dispatch
    "job_assigned":       "Job Assigned",
    "job_completed":      "Job Completed",
    "job_cancelled":      "Job Cancelled",
    "job_status_change":  "Job Status Change",
    "dispatch_alert":     "Dispatch Alert",
    "autosave_conflict":  "Autosave Conflict",
    # Money
    "invoice_paid":       "Invoice Paid",
    "invoice_overdue":    "Invoice Overdue",
    "payment_received":   "Payment Received",
    "payment_failed":     "Payment Failed",
    "payment_refunded":   "Payment Refunded",
    # Communications
    "tech_message":       "Technician Message",
    "tech_note":          "Technician Note",
    "customer_message":   "Customer Portal Message",
    # TODO(HL-inbox): When the HighLevel Conversation Inbox phase lands,
    # its inbound handlers (FB DM / IG DM / WhatsApp / Google Business
    # Messages) MUST also fire ``inbound_customer_message`` so the
    # unified category stays authoritative across every channel. Reuse
    # ``enqueue_for_tenant_admins`` + the ``_assigned`` variant when a
    # deal/owner is resolvable.
    "inbound_customer_message":          "Inbound Customer Message",
    "inbound_customer_message_assigned": "Inbound Customer Message (assigned to you)",
    # Team messaging (Phase 56)
    "chat_dm":                    "Team Chat · DM to you",
    "chat_dm_to_admin":           "Team Chat · DM to an admin",
    "chat_mention_in_channel":    "Team Chat · You were @mentioned",
    "chat_message_in_channel":    "Team Chat · New channel message",
    # Leads / marketing
    "lead_new":                   "New Lead (legacy)",
    "new_lead":                   "New Lead",
    "customer_created":           "Customer Created",
    "subscriber_confirmed":       "Marketing Subscriber Confirmed",
    "marketing_import_complete":  "Marketing Import Complete",
    # Reviews
    "review_received":            "Review Received",
    "review_low_star":            "Low-star Review (≤3★)",
    # Deals
    "deal_created":               "Deal Created",
    "deal_won":                   "Deal Won",
    "deal_lost":                  "Deal Lost",
    # Automation / system
    "automation_error":           "Automation Error",
    "system_alert":               "System Alert",
    # Directories (Phase D1 — Feb 2026)
    "directory_status_change":    "Directory · Submission Status Change",
    # Marketing M2 (Feb 2026)
    "marketing_campaign_sent":    "Marketing Campaign · Sent",
    # Customer Detail Additions (Feb 2026)
    "customer.vip_flagged":       "Customer · VIP Flagged",
    "task_assigned":              "Task Assigned to You",
    # Multi-Property MP1 (Feb 2026)
    "property.created":           "Property · Added",
    "property.deleted":           "Property · Removed",
    # Phase 18 · Inventory (Feb 2026)
    "inventory_low_stock":        "Inventory · Low Stock",
    # Feb-2026 · Optimize Route (tech→admin approval flow).
    "route_optimization_request": "Route Optimization · Request",
    # Feb-2026 · MARCO · Sub-phase E — proactive todo reminder.
    "marco_todo_due":             "MARCO · Todo Due Soon",
}

# NB: two new channels added — ``push`` (Expo mobile push) + ``in_app`` alias
# for ``bell``. Existing rows persisted under the legacy 3-key shape merge
# forward cleanly because ``get_user_prefs`` layers stored values on top of
# ``DEFAULT_CHANNELS``.
DEFAULT_CHANNELS = {"bell": True, "email": False, "sms": False, "push": False}
BODY_TRUNCATE = 500

# Categories that ship push=on for admins/super_admins by default. Everything
# else stays push=off; admins can flip individually. Bell stays on for all
# so the in-app inbox is exhaustive.
_ADMIN_PUSH_DEFAULT_ON = {
    "review_received", "review_low_star",
    "chat_dm_to_admin",
    "inbound_customer_message",
    "new_lead",
    "inventory_low_stock",  # Phase 18 · Feb 2026
}
# Non-admin techs / sales default: chat DMs to them, own mentions,
# customer messages tied to their assigned work. Everything else off.
_NONADMIN_PUSH_DEFAULT_ON = {
    "chat_dm",
    "chat_mention_in_channel",
    "inbound_customer_message_assigned",
    "job_status_change",
    # Feb-2026 Customer Detail Additions — assignee should be pinged
    # when a task lands in their queue.
    "task_assigned",
}


def default_prefs(role: str | None = None) -> dict:
    """Fresh preference blob keyed by kind.

    Bell stays ON for every kind (the in-app inbox is always exhaustive
    — the toggle only controls whether push/email/sms fire, not whether
    the notification is recorded). Push defaults are role-scoped per
    the Feb-2026 unified-notifications spec.
    """
    is_admin = (role or "").lower() in ("admin", "super_admin")
    on_set = _ADMIN_PUSH_DEFAULT_ON if is_admin else _NONADMIN_PUSH_DEFAULT_ON
    out: dict[str, dict] = {}
    for k in KIND_LABELS:
        row = dict(DEFAULT_CHANNELS)
        if k in on_set:
            row["push"] = True
        out[k] = row
    return out


DEFAULT_QUIET_HOURS = {
    "enabled": False,
    "start_time": "22:00",
    "end_time":   "07:00",
    "timezone":   "UTC",
}


def _minutes_of_day_utc() -> int:
    from datetime import datetime, timezone as _tz
    now = datetime.now(_tz.utc)
    return now.hour * 60 + now.minute


def _hhmm_to_min(s: str | None) -> int | None:
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        return int(h) * 60 + int(m[:2])
    except Exception:
        return None


def is_in_quiet_hours(prefs: dict) -> bool:
    """Return True when 'now' falls in the user's configured quiet window.

    Timezone-aware conversion is intentionally naive here: we treat both
    the current instant and the window in UTC, which is correct for the
    tenant defaults today and matches the seed data. A follow-up will
    honor user tz explicitly once every user carries a resolved tz.
    """
    qh = (prefs or {}).get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False
    start = _hhmm_to_min(qh.get("start_time"))
    end = _hhmm_to_min(qh.get("end_time"))
    if start is None or end is None:
        return False
    now = _minutes_of_day_utc()
    if start == end:
        return False
    if start < end:
        return start <= now < end
    # Wraps midnight, e.g. 22:00–07:00.
    return now >= start or now < end


async def _resolve_user_role(user_id: str) -> str | None:
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1}) or {}
    return u.get("role")


async def get_user_prefs(tenant_id: str, user_id: str,
                            role: str | None = None) -> dict:
    """Return the merged preference doc for a user. Never returns None.

    When the doc is missing OR present without stored channels, the
    role-aware defaults from ``default_prefs(role)`` seed the response
    so first-read on an admin user surfaces the correct push defaults.
    """
    doc = await db.notification_preferences.find_one(
        {"tenant_id": tenant_id, "user_id": user_id}, {"_id": 0}
    ) or {}
    if role is None:
        role = doc.get("role") or await _resolve_user_role(user_id)
    stored = doc.get("channels") or {}
    merged = default_prefs(role)
    for kind, chans in stored.items():
        if isinstance(chans, dict):
            merged[kind] = {**merged.get(kind, dict(DEFAULT_CHANNELS)), **chans}
    quiet = {**DEFAULT_QUIET_HOURS, **(doc.get("quiet_hours") or {})}
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "channels": merged,
        "quiet_hours": quiet,
        "updated_at": doc.get("updated_at"),
    }


async def set_user_prefs(tenant_id: str, user_id: str,
                            channels: dict,
                            quiet_hours: dict | None = None) -> dict:
    """Upsert. Silently drops kinds we don't recognize (schema guard).

    ``quiet_hours`` is optional; when omitted the previously-stored
    block is preserved.
    """
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
            "push":  bool(chans.get("push",  DEFAULT_CHANNELS["push"])),
        }
    now = now_iso()
    update: dict = {"channels": clean, "updated_at": now,
                     "tenant_id": tenant_id, "user_id": user_id}
    if quiet_hours is not None:
        qh = {**DEFAULT_QUIET_HOURS, **(quiet_hours or {})}
        # Only persist the recognised keys.
        update["quiet_hours"] = {
            "enabled":    bool(qh.get("enabled", False)),
            "start_time": str(qh.get("start_time") or "22:00")[:5],
            "end_time":   str(qh.get("end_time")   or "07:00")[:5],
            "timezone":   str(qh.get("timezone")   or "UTC")[:64],
        }
    await db.notification_preferences.update_one(
        {"tenant_id": tenant_id, "user_id": user_id},
        {"$set": update},
        upsert=True,
    )
    return await get_user_prefs(tenant_id, user_id)


# ─── Admin helpers ─────────────────────────────────────────────────────
async def enqueue_for_tenant_admins(tenant_id: str, kind: str, title: str,
                                       body: str,
                                       source_ref: Optional[dict] = None,
                                       href: Optional[str] = None,
                                       priority: str = "normal") -> list[str]:
    """Fire the given kind to every admin / super_admin in the tenant.

    No-op (returns []) when the tenant has no admin accounts — never
    raises so caller sites can drop this in without guards.
    """
    user_ids: list[str] = []
    async for u in db.users.find(
        {"tenant_id": tenant_id,
          "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "id": 1},
    ):
        if u.get("id"):
            user_ids.append(u["id"])
    return await emit(user_ids, kind, title, body,
                        source_ref=source_ref, href=href,
                        priority=priority, tenant_id=tenant_id)


async def enqueue_for_record_owner(tenant_id: str,
                                      owner_user_id: Optional[str],
                                      kind: str, title: str, body: str,
                                      source_ref: Optional[dict] = None,
                                      href: Optional[str] = None,
                                      priority: str = "normal",
                                      fallback_admins: bool = True) -> list[str]:
    """Emit to the owner of a record; falls back to tenant admins.

    Owner resolution is the caller's responsibility — pass the resolved
    ``owner_user_id`` or None. When None and fallback_admins is True the
    notification fans out to admins so tenant-wide visibility is kept.
    """
    if owner_user_id:
        return await emit([owner_user_id], kind, title, body,
                            source_ref=source_ref, href=href,
                            priority=priority, tenant_id=tenant_id)
    if fallback_admins:
        return await enqueue_for_tenant_admins(
            tenant_id, kind, title, body,
            source_ref=source_ref, href=href, priority=priority)
    return []


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
    audience: str = "internal",
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

        prefs_doc = await get_user_prefs(t_id, uid)
        prefs = prefs_doc["channels"].get(kind, dict(DEFAULT_CHANNELS))
        quiet = is_in_quiet_hours(prefs_doc)

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
                "audience": "portal" if audience == "portal" else "internal",
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

        # Expo mobile push — gated on the ``push`` channel toggle AND
        # not-in-quiet-hours. In-app row above is written independently
        # so users always have a browsable inbox of muted events.
        if prefs.get("push", False) and not quiet:
            try:
                from routers.mobile_push import send_push_to_user
                await send_push_to_user(uid, title, body,
                                        data={"kind": kind, "href": href,
                                              "source_ref": source_ref or {}})
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
    # WINGMAN-ESCALATION-EMAIL-FIX · Feb-2026 — pre-ship, this
    # dispatcher emitted ``<a href="{href}">Open</a>`` with the
    # ``href`` kwarg as a RELATIVE path (e.g. ``/communication/<cid>``
    # from ``routers/customer_ai.py``).  Mail clients with no base
    # URL in context fell back to ``file:///communication/<cid>``.
    # Fix: normalise the href through the shared absolute-URL
    # helper so missing-env misconfigs log loudly instead of
    # silently emitting a broken link.
    from services.email_urls import absolute_portal_url
    absolute_href = absolute_portal_url(
        href, template_name=f"admin_notification_fanout:{kind}",
    )
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
        # Feb-2026 · Comms whitelist gate (P0 safety directive).
        try:
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier={"user_id": user_id, "email": to_addr},
                comm_type="email",
                tenant_id=tenant_id,
                provider="resend",
                trigger_action=f"notification:{kind}",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"notif email gate errored — failing closed: {e}")
            allowed = False
        if not allowed:
            await db.email_delivery_log.insert_one({
                "id": new_id(),
                "kind": f"notification:{kind}",
                "tenant_id": tenant_id,
                "user_id": user_id,
                "to": to_addr,
                "subject": subject,
                "mocked": True,
                "reason": "suppressed_not_demo",
                "created_at": _n(),
            })
            return
        import resend  # type: ignore
        resend.api_key = resend_key
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
            "to": [to_addr],
            "subject": subject,
            "html": f"<p>{body}</p>" + (
                f'<p><a href="{absolute_href}">Open</a></p>'
                if absolute_href else ""
            ),
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
        # Feb-2026 · Comms whitelist gate (P0 safety directive).
        try:
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier={"user_id": user_id, "phone": to},
                comm_type="sms",
                tenant_id=tenant_id,
                provider="ringcentral",
                trigger_action=f"notification:{kind}",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"notif sms gate errored — failing closed: {e}")
            allowed = False
        if not allowed:
            row["delivery_status"] = "suppressed_not_demo"
        else:
            try:
                # safe-send: allowlist because legacy internal notification SMS gated by services.comms.gate.is_comm_allowed above; SAFE-SEND-D migration pending
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


# ─── Muted-notification digest (opt-in nightly rollup) ─────────────────

async def build_muted_digest(tenant_id: str, hours_back: int = 24) -> list[dict]:
    """Per-user roll-ups of the last N hours of notifications for which
    the user has ``push`` OFF.

    Returned shape::
      [{"user_id": ..., "email": ..., "rows_by_kind": {kind: [rows]},
        "total_muted": int}, ...]
    """
    from datetime import datetime, timedelta, timezone as _tz
    cutoff = (datetime.now(_tz.utc) - timedelta(hours=hours_back)).isoformat()
    rows: list[dict] = []
    async for n in db.notifications.find(
        {"tenant_id": tenant_id, "created_at": {"$gte": cutoff},
          "audience": {"$in": ["internal", None]}},
        {"_id": 0},
    ):
        rows.append(n)
    if not rows:
        return []
    by_user: dict[str, list[dict]] = {}
    for r in rows:
        uid = r.get("user_id")
        if not uid or uid == "*":
            continue
        by_user.setdefault(uid, []).append(r)
    out: list[dict] = []
    for uid, urows in by_user.items():
        prefs = await get_user_prefs(tenant_id, uid)
        muted: dict[str, list[dict]] = {}
        for r in urows:
            kind = r.get("kind") or "system_alert"
            row_prefs = (prefs.get("channels") or {}).get(kind) or {}
            if not row_prefs.get("push", False):
                muted.setdefault(kind, []).append(r)
        if not muted:
            continue
        u = await db.users.find_one(
            {"id": uid}, {"_id": 0, "email": 1, "name": 1}) or {}
        out.append({
            "user_id": uid,
            "email": u.get("email") or "",
            "name": u.get("name") or "",
            "rows_by_kind": muted,
            "total_muted": sum(len(v) for v in muted.values()),
        })
    return out


async def enqueue_muted_digest_email(tenant_id: str,
                                        entry: dict) -> Optional[str]:
    """Write a queued email row for one user's digest."""
    if not entry.get("email") or not entry.get("rows_by_kind"):
        return None
    lines: list[str] = []
    for kind, items in entry["rows_by_kind"].items():
        label = KIND_LABELS.get(kind, kind)
        lines.append(f"<h3 style='margin:16px 0 4px 0'>{label} · {len(items)}</h3>")
        for it in items[:8]:
            title = (it.get("title") or "")[:120]
            body = (it.get("body") or "")[:160]
            lines.append(
                f"<div style='padding:6px 0;border-bottom:1px solid #eee'>"
                f"<b>{title}</b><br/><span style='color:#555'>{body}</span></div>"
            )
        if len(items) > 8:
            lines.append(f"<div style='color:#888;padding:4px 0'>… and {len(items) - 8} more</div>")
    html = (
        f"<div style='font-family:sans-serif;max-width:600px;margin:auto'>"
        f"<h2>Your muted-notification digest</h2>"
        f"<p style='color:#555'>Here are the notifications you had push-muted "
        f"in the last 24 hours. Adjust preferences any time in Settings → "
        f"Notifications.</p>{''.join(lines)}</div>"
    )
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "kind": "email",
        "channel": "email",
        "recipient_id": entry["user_id"],
        "recipient_address": entry["email"],
        "template_code": "system.muted_notification_digest",
        "subject": f"Your muted-notification digest · {entry['total_muted']} events",
        "body_html": html,
        "status": "queued",
        "queued_at": now_iso(),
        "context_meta": {"digest_kind_counts": {k: len(v) for k, v in entry["rows_by_kind"].items()}},
    }
    await db.communication_sends.insert_one(doc)
    return doc["id"]


async def run_muted_digest_sweep() -> dict:
    """Sweep every tenant with ``notification_digest_enabled=True`` and
    write digest email rows for each user with muted events."""
    total_written = 0
    per_tenant: dict[str, int] = {}
    async for t in db.tenants.find(
        {"notification_digest_enabled": True, "active": {"$ne": False}},
        {"_id": 0, "id": 1},
    ):
        tid = t.get("id")
        if not tid:
            continue
        digest = await build_muted_digest(tid, hours_back=24)
        written = 0
        for entry in digest:
            sid = await enqueue_muted_digest_email(tid, entry)
            if sid:
                written += 1
        if written:
            per_tenant[tid] = written
            total_written += written
    return {"emails_written": total_written, "per_tenant": per_tenant}
