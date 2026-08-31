"""Phase D · Feb-2026 — Drift Alerting (daily digest).

Fires at 08:00 tenant-local time. When the F3 boot-check found
``dangling_refs_total > 0``, dispatches a Slack + email digest via
the same infra ``scorecard_digest.py`` already uses (httpx to a
webhook + Resend). Idempotent per (tenant_id, YYYY-MM-DD) via
``audit_events``. Every dispatch OR clean skip writes an audit row.

Non-goals: new comms providers, SMS, cross-tenant digests.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from config import db, logger  # noqa: F401
from services.scorecard_digest import (
    _default_resend_send, _default_slack_post, _mask_webhook,
)


AUDIT_EVENT_TYPE = "data_integrity_digest"
_SENTINEL_SUFFIX_FMT = "%Y-%m-%d"


# ═══════════════════════════════════════════════════════════════════
# Settings persistence (per tenant)
# ═══════════════════════════════════════════════════════════════════

async def get_settings(tenant_id: str) -> Dict[str, Any]:
    s = await db.drift_alert_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0},
    ) or {}
    return {
        "tenant_id": tenant_id,
        "enabled": bool(s.get("enabled", True)),
        "slack_webhook_url": s.get("slack_webhook_url") or "",
        "email_recipients": s.get("email_recipients") or [],
        "timezone": s.get("timezone") or "America/Phoenix",
    }


async def public_settings(tenant_id: str) -> Dict[str, Any]:
    s = await get_settings(tenant_id)
    s["slack_webhook_url_masked"] = _mask_webhook(s["slack_webhook_url"])
    s.pop("slack_webhook_url", None)
    return s


async def save_settings(
    tenant_id: str, patch: Dict[str, Any],
) -> Dict[str, Any]:
    current = await get_settings(tenant_id)
    for k in ("enabled", "slack_webhook_url",
              "email_recipients", "timezone"):
        if k in patch and patch[k] is not None:
            current[k] = patch[k]
    await db.drift_alert_settings.update_one(
        {"tenant_id": tenant_id},
        {"$set": current},
        upsert=True,
    )
    return await public_settings(tenant_id)


# ═══════════════════════════════════════════════════════════════════
# Formatters
# ═══════════════════════════════════════════════════════════════════

def _top_offending_collections(
    payload: Dict[str, Any], n: int = 3,
) -> List[Dict[str, Any]]:
    """Aggregate the F9 status payload's per-tenant break-down into
    top-N offending collections keyed by orphan class."""
    cs = payload.get("current_state") or {}
    by_class = cs.get("dangling_refs_by_class") or {}
    rows = sorted(
        [(k, int(v or 0)) for k, v in by_class.items() if v],
        key=lambda kv: -kv[1],
    )[:n]
    return [{"class": k, "count": v} for k, v in rows]


def build_slack_blocks(
    tenant_name: str, payload: Dict[str, Any],
    top: List[Dict[str, Any]], app_url: str,
) -> Dict[str, Any]:
    total = int((payload.get("current_state") or {})
                .get("dangling_refs_total") or 0)
    top_lines = "\n".join(
        f"• *{r['class']}* — {r['count']} orphan{'s' if r['count'] != 1 else ''}"
        for r in top
    ) or "• (breakdown unavailable)"
    return {"blocks": [
        {"type": "header", "text": {
            "type": "plain_text",
            "text": f"Data Integrity Drift · {tenant_name}",
        }},
        {"type": "section", "text": {
            "type": "mrkdwn",
            "text": (
                f"*{total} dangling ref{'s' if total != 1 else ''}* detected "
                f"in this morning's F3 boot check.\n\n"
                f"{top_lines}"
            ),
        }},
        {"type": "actions", "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": "Open Migrations Console"},
            "url": f"{app_url.rstrip('/')}/admin/migrations",
        }]},
    ]}


def build_email(
    tenant_name: str, payload: Dict[str, Any],
    top: List[Dict[str, Any]], app_url: str,
):
    total = int((payload.get("current_state") or {})
                .get("dangling_refs_total") or 0)
    subject = (f"[{tenant_name}] Data Integrity Drift Detected — "
               f"{total} dangling ref{'s' if total != 1 else ''}")
    rows_html = "".join(
        f"<li><b>{r['class']}</b> — {r['count']}</li>" for r in top
    ) or "<li>Breakdown unavailable</li>"
    rows_plain = "\n".join(
        f"  * {r['class']}: {r['count']}" for r in top
    ) or "  * Breakdown unavailable"
    html = (
        f"<div style='font-family:system-ui;color:#0F172A;padding:16px'>"
        f"<h2 style='color:#B91C1C;margin:0 0 8px 0'>"
        f"Data Integrity Drift</h2>"
        f"<p><b>{tenant_name}</b></p>"
        f"<p>{total} dangling ref{'s' if total != 1 else ''} detected "
        f"in this morning's F3 boot check.</p>"
        f"<ul>{rows_html}</ul>"
        f"<p><a href='{app_url.rstrip('/')}/admin/migrations' "
        f"style='color:#0284C7'>Open Migrations Console →</a></p>"
        f"</div>"
    )
    text = (
        f"Data Integrity Drift — {tenant_name}\n\n"
        f"{total} dangling ref(s) detected in this morning's F3 boot check.\n\n"
        f"Top offending classes:\n{rows_plain}\n\n"
        f"Open: {app_url.rstrip('/')}/admin/migrations\n"
    )
    return subject, html, text


# ═══════════════════════════════════════════════════════════════════
# Dedupe + audit
# ═══════════════════════════════════════════════════════════════════

async def _already_dispatched_today(
    tenant_id: str, date_str: str,
) -> bool:
    return bool(await db.audit_events.find_one(
        {"event_type": AUDIT_EVENT_TYPE,
         "tenant_id": tenant_id,
         "payload.date": date_str,
         "payload.dispatched": True},
        {"_id": 0, "id": 1},
    ))


async def _write_audit(
    *, tenant_id: str, date_str: str, dangling_total: int,
    dispatched: bool, reason: str, top: List[Dict[str, Any]],
    channels_notified: List[str], skipped: bool = False,
) -> str:
    aid = str(uuid.uuid4())
    await db.audit_events.insert_one({
        "id": aid,
        "event_type": AUDIT_EVENT_TYPE,
        "actor_user_id": "cron:drift_alerting",
        "tenant_id": tenant_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "tenant_id": tenant_id,
            "date": date_str,
            "dangling_refs_total": dangling_total,
            "dispatched": dispatched,
            "skipped": skipped,
            "reason": reason,
            "channels_notified": channels_notified,
            "top_collections": top,
        },
    })
    return aid


# ═══════════════════════════════════════════════════════════════════
# Core dispatch (used by cron + test-fire endpoint)
# ═══════════════════════════════════════════════════════════════════

async def _tenant_local_date(tenant_settings: Dict[str, Any]) -> str:
    tz_name = tenant_settings.get("timezone") or "America/Phoenix"
    now = datetime.now(timezone.utc)
    if ZoneInfo is not None:
        try:
            now = now.astimezone(ZoneInfo(tz_name))
        except Exception:                                    # noqa: BLE001
            pass
    return now.strftime(_SENTINEL_SUFFIX_FMT)


async def dispatch_for_tenant(
    tenant: Dict[str, Any],
    *, force: bool = False,
    slack_post=_default_slack_post,
    resend_send=_default_resend_send,
) -> Dict[str, Any]:
    """Run one dispatch cycle for a single tenant.

    * ``force=True`` bypasses the same-day dedupe AND the 08:00 gate
      (used by the manual test-fire endpoint).
    * Returns a structured result dict:
      ``{tenant_id, date, dangling_refs_total, dispatched, skipped,
         reason, channels_notified, top, audit_event_id, preview: {slack, email}}``.
    """
    tenant_id = tenant["id"]
    settings = await get_settings(tenant_id)
    date_str = await _tenant_local_date(settings)
    tenant_name = (tenant.get("name") or tenant.get("business_name")
                   or "Business")
    app_url = (tenant.get("primary_app_domain")
               or os.environ.get("APP_PUBLIC_URL")
               or "https://app.example.com")

    if not settings.get("enabled"):
        aid = await _write_audit(
            tenant_id=tenant_id, date_str=date_str, dangling_total=0,
            dispatched=False, skipped=True, reason="disabled",
            top=[], channels_notified=[],
        )
        return {"tenant_id": tenant_id, "date": date_str,
                "dispatched": False, "skipped": True,
                "reason": "disabled", "audit_event_id": aid}

    if not force and await _already_dispatched_today(tenant_id, date_str):
        aid = await _write_audit(
            tenant_id=tenant_id, date_str=date_str, dangling_total=0,
            dispatched=False, skipped=True,
            reason="already_dispatched_today",
            top=[], channels_notified=[],
        )
        return {"tenant_id": tenant_id, "date": date_str,
                "dispatched": False, "skipped": True,
                "reason": "already_dispatched_today",
                "audit_event_id": aid}

    # Read F3 status directly — no HTTP round-trip.
    from routers.data_repair import data_repair_status
    payload = await data_repair_status(
        user={"role": "super_admin", "id": "cron", "tenant_id": tenant_id},
    )
    total = int((payload.get("current_state") or {})
                .get("dangling_refs_total") or 0)
    top = _top_offending_collections(payload)

    if total == 0:
        aid = await _write_audit(
            tenant_id=tenant_id, date_str=date_str, dangling_total=0,
            dispatched=False, reason="clean",
            top=[], channels_notified=[],
        )
        return {"tenant_id": tenant_id, "date": date_str,
                "dangling_refs_total": 0,
                "dispatched": False, "reason": "clean",
                "audit_event_id": aid}

    slack_url = settings.get("slack_webhook_url") or ""
    email_to = settings.get("email_recipients") or []
    if not slack_url and not email_to:
        aid = await _write_audit(
            tenant_id=tenant_id, date_str=date_str, dangling_total=total,
            dispatched=False, reason="no_channels_configured",
            top=top, channels_notified=[],
        )
        return {"tenant_id": tenant_id, "date": date_str,
                "dangling_refs_total": total,
                "dispatched": False, "reason": "no_channels_configured",
                "audit_event_id": aid, "top": top}

    channels_notified: List[str] = []
    preview: Dict[str, Any] = {}
    if slack_url:
        blocks = build_slack_blocks(tenant_name, payload, top, app_url)
        r = await slack_post(slack_url, blocks)
        preview["slack"] = {"ok": bool(r.get("ok")),
                             "status": r.get("status"),
                             "error": r.get("error")}
        if r.get("ok"):
            channels_notified.append("slack")

    if email_to:
        subject, html, text = build_email(
            tenant_name, payload, top, app_url,
        )
        r = await resend_send(email_to, subject, html, text)
        preview["email"] = {"ok": bool(r.get("ok")),
                             "status": r.get("status"),
                             "error": r.get("error"),
                             "recipients": email_to,
                             "subject": subject}
        if r.get("ok"):
            channels_notified.append("email")

    aid = await _write_audit(
        tenant_id=tenant_id, date_str=date_str, dangling_total=total,
        dispatched=bool(channels_notified),
        reason=("sent" if channels_notified else "delivery_failed"),
        top=top, channels_notified=channels_notified,
    )
    return {"tenant_id": tenant_id, "date": date_str,
            "dangling_refs_total": total,
            "dispatched": bool(channels_notified),
            "reason": "sent" if channels_notified else "delivery_failed",
            "channels_notified": channels_notified,
            "top": top, "preview": preview,
            "audit_event_id": aid}


# ═══════════════════════════════════════════════════════════════════
# Cron entrypoint — one tick per hour, dispatches when it's 08:00
# in each tenant's local timezone.
# ═══════════════════════════════════════════════════════════════════

async def daily_data_integrity_digest_tick() -> Dict[str, Any]:
    """Register-me-hourly. For every enabled tenant, if local hour
    is 08 we dispatch.  Same-date dedupe protects against duplicate
    hourly ticks in the same hour window."""
    now_utc = datetime.now(timezone.utc)
    ran = 0
    skipped_wrong_hour = 0
    async for s in db.drift_alert_settings.find(
        {"enabled": True}, {"_id": 0},
    ):
        tid = s["tenant_id"]
        tz_name = s.get("timezone") or "America/Phoenix"
        local_hour = now_utc.hour
        if ZoneInfo is not None:
            try:
                local_hour = now_utc.astimezone(ZoneInfo(tz_name)).hour
            except Exception:                                # noqa: BLE001
                pass
        if local_hour != 8:
            skipped_wrong_hour += 1
            continue
        tenant = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
        if not tenant:
            continue
        tenant = {"id": tid, **tenant}
        try:
            await dispatch_for_tenant(tenant)
            ran += 1
        except Exception as exc:                             # noqa: BLE001
            logger.warning(
                "[drift-alerting] tenant %s failed: %s", tid, exc,
            )
    return {"tenants_run": ran, "skipped_wrong_hour": skipped_wrong_hour}
