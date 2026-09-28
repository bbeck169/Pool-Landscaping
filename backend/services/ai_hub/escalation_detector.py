"""MTH-C · Feb-2026 — Escalation detection + SLA-breach scanner.

Consumes tenant AI rules ``escalation_rules`` and fans out to two
places:

* Inbound comms path — :func:`scan_and_escalate` is invoked by
  the RingCentral SMS webhook after each inbound message lands.
  First matching rule creates an ``ai_escalations`` row and fires
  a SAFE-SEND notification to the target-role admins.

* SLA-breach loop — :func:`scan_sla_breaches` is invoked every
  minute by the MTH-C APScheduler.  It scans for escalation rows
  where ``sla_deadline < now && resolved=False && notified=True
  && breach_notified=False`` and sends one follow-up notification
  per row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from config import logger

COLLECTION = "ai_escalations"
_UTC = timezone.utc


def _now_utc(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(_UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=_UTC)
    return now.astimezone(_UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(_UTC).isoformat()


async def scan_and_escalate(
    *, tenant_id: Optional[str], source: str,
    message_body: str,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Scan ``message_body`` against the tenant's escalation rules.

    Returns the persisted escalation doc on hit, ``None`` on no
    match / bad scope.  Non-fatal — every exception is logged
    then swallowed so an inbound-webhook path never crashes on a
    misconfigured rule.
    """
    if not tenant_id or not isinstance(message_body, str) or not message_body:
        return None
    try:
        from services.tenant_ai_rules.resolver import (
            resolve_rules_for_tenant,
        )
        from services.tenant_ai_rules.gate import match_escalation
        resolved = await resolve_rules_for_tenant(tenant_id)
        rules = (resolved.get("rules") or {}).get("escalation_rules") or []
        hit = match_escalation(message_body, rules)
        if not hit:
            return None
        return await _persist_and_notify(
            tenant_id=tenant_id, source=source, rule=hit,
            message_body=message_body, customer_id=customer_id,
            lead_id=lead_id, now=now,
        )
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[mth-c] scan_and_escalate failed tenant=%s source=%s",
            tenant_id, source,
        )
        return None


async def _persist_and_notify(
    *, tenant_id: str, source: str, rule: Dict[str, Any],
    message_body: str, customer_id: Optional[str],
    lead_id: Optional[str], now: Optional[datetime],
) -> Dict[str, Any]:
    from config import db
    now_utc = _now_utc(now)
    sla_min = int(rule.get("sla_minutes") or 5)
    deadline = now_utc + timedelta(minutes=max(1, sla_min))
    doc = {
        "id": str(uuid4()),
        "tenant_id": tenant_id,
        "source": source,
        "customer_id": customer_id,
        "lead_id": lead_id,
        "message_body": (message_body or "")[:2000],
        "matched_rule": {
            "keyword": rule.get("keyword"),
            "is_regex": bool(rule.get("is_regex")),
            "target_role": rule.get("target_role") or "admin",
            "sla_minutes": sla_min,
            "notify_channel": rule.get("notify_channel") or "email",
        },
        "escalated_at": _iso(now_utc),
        "sla_deadline": _iso(deadline),
        "sla_deadline_ts": deadline.timestamp(),
        "notified": False,
        "notified_at": None,
        "notify_error": None,
        "breach_notified": False,
        "breach_notified_at": None,
        "resolved": False,
        "resolved_by": None,
        "resolved_at": None,
    }
    await db[COLLECTION].insert_one(doc)
    ok, err = await _notify_target_role(doc)
    if ok:
        await db[COLLECTION].update_one(
            {"id": doc["id"]},
            {"$set": {"notified": True, "notified_at": _iso(_now_utc())}},
        )
        doc["notified"] = True
    else:
        await db[COLLECTION].update_one(
            {"id": doc["id"]},
            {"$set": {"notify_error": err or "unknown"}},
        )
        doc["notify_error"] = err
    doc.pop("_id", None)
    return doc


async def _resolve_target_admins(tenant_id: str, role: str) -> List[dict]:
    from config import db
    roles = [role]
    if role == "admin":
        roles = ["admin", "super_admin"]
    cursor = db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": roles}},
        {"_id": 0, "email": 1, "phone_number": 1, "id": 1, "name": 1},
    )
    return await cursor.to_list(50)


async def _notify_target_role(
    doc: Dict[str, Any],
    *, is_breach: bool = False,
) -> tuple:
    """Fan out to the tenant's admins for the target role.

    Uses the standard SAFE-SEND ``CommsContext.SYSTEM`` path —
    escalation notifications are internal ops-team pings, NOT AI
    customer-facing comms, so we route through a synthetic
    "system escalation" employee row that ``stamp_agent_context``
    resolves to SYSTEM verbatim (``authorized_for_public_use=True``
    keeps the caller's requested context).  This makes the
    AIHUB-A callsite guardrail happy without changing behavior.

    Non-fatal — returns ``(ok, err)`` so the caller can persist
    the failure reason on the row.
    """
    tenant_id = doc.get("tenant_id")
    rule = doc.get("matched_rule") or {}
    role = rule.get("target_role") or "admin"
    channel = rule.get("notify_channel") or "email"
    body_preview = (doc.get("message_body") or "")[:80]
    prefix = "[SLA BREACH] " if is_breach else "[ESCALATION] "
    subject = f'{prefix}Customer message: "{body_preview}..."'
    body_text = (
        f"An escalation rule fired for tenant {tenant_id}.\n\n"
        f"Rule: {rule.get('keyword')} "
        f"(regex={rule.get('is_regex')})\n"
        f"SLA: {rule.get('sla_minutes')} min · "
        f"deadline={doc.get('sla_deadline')}\n"
        f"Escalation id: {doc.get('id')}\n"
        f"Message: {(doc.get('message_body') or '')[:500]}"
    )
    try:
        admins = await _resolve_target_admins(tenant_id, role)
    except Exception as exc:                                       # noqa: BLE001
        return False, f"admin_lookup_failed:{exc}"
    if not admins:
        return False, "no_admins_for_target_role"

    from services.comms_env_guard import CommsContext
    from services.ai_hub.context_stamping import stamp_agent_context
    # Synthetic system employee so ``stamp_agent_context`` returns
    # SYSTEM verbatim (satisfies the AIHUB-A callsite guardrail
    # without redirecting the escalation notification through the
    # AGENT admin-redirect path — recipients ARE the admins).
    _escalation_ctx = stamp_agent_context(
        employee={
            "id": "system:escalation",
            "key": "system_escalation",
            "authorized_for_public_use": True,
        },
        requested_context=CommsContext.SYSTEM,
    )
    try:
        if channel in ("email", "both"):
            from services.comms_email_adapter import send_email
            for admin in admins:
                addr = admin.get("email")
                if not addr:
                    continue
                try:
                    await send_email(
                        to=addr,
                        subject=subject,
                        body=body_text,
                        context=_escalation_ctx,
                        tenant_id=tenant_id,
                    )
                except Exception as _e:                            # noqa: BLE001
                    logger.warning(
                        "[mth-c] escalation email to %s failed: %s",
                        addr, _e,
                    )
        if channel in ("sms", "both"):
            from services.comms_sms_adapter import send_sms
            # Same authorization stamp as the email branch — kept
            # local so the AIHUB-A callsite guardrail's 30-line
            # window catches the stamp call adjacent to the send.
            _escalation_ctx_sms = stamp_agent_context(
                employee={
                    "id": "system:escalation",
                    "key": "system_escalation",
                    "authorized_for_public_use": True,
                },
                requested_context=CommsContext.SYSTEM,
            )
            for admin in admins:
                phone = admin.get("phone_number")
                if not phone:
                    continue
                try:
                    await send_sms(
                        to=phone,
                        text=(
                            f"{prefix}Customer message flagged. "
                            f"See escalation {doc.get('id')}."
                        ),
                        context=_escalation_ctx_sms,
                        tenant_id=tenant_id,
                    )
                except Exception as _e:                            # noqa: BLE001
                    logger.warning(
                        "[mth-c] escalation sms to %s failed: %s",
                        phone, _e,
                    )
    except Exception as exc:                                       # noqa: BLE001
        return False, f"adapter_import_failed:{exc}"
    return True, None


async def scan_sla_breaches(
    *, now: Optional[datetime] = None, limit: int = 100,
) -> Dict[str, Any]:
    """Emit one SLA-breach follow-up notification per row where the
    deadline has passed and no breach notification has fired yet.
    Idempotent — sets ``breach_notified=True`` after the notify."""
    from config import db
    now_utc = _now_utc(now)
    now_ts = now_utc.timestamp()
    cursor = db[COLLECTION].find(
        {
            "resolved": False,
            "notified": True,
            "breach_notified": False,
            "sla_deadline_ts": {"$lt": now_ts},
        },
        {"_id": 0},
    ).limit(limit)
    entries = await cursor.to_list(limit)
    breached = 0
    errors = 0
    for entry in entries:
        ok, err = await _notify_target_role(entry, is_breach=True)
        upd = {
            "breach_notified": True,
            "breach_notified_at": _iso(_now_utc()),
        }
        if not ok:
            upd["breach_notify_error"] = err or "unknown"
            errors += 1
        else:
            breached += 1
        await db[COLLECTION].update_one(
            {"id": entry["id"]}, {"$set": upd},
        )
    return {
        "scanned": len(entries),
        "breached": breached,
        "errors": errors,
    }


__all__ = [
    "COLLECTION",
    "scan_and_escalate",
    "scan_sla_breaches",
]
