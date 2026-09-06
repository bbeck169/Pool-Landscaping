"""Phase K63.finalize · Feb-2026 — admin resend-notifications endpoint.

Fires the K63 lead-alert fan-out for a specific lead again,
bypassing the ``lead_notification_dispatches`` idempotency guard.
Intended for two scenarios:

  1. An admin added a new recipient to the tenant's Lead Alerts
     settings and wants the new person looped in on a recent lead.
  2. A previous dispatch failed and the admin wants to retry the
     send now that the underlying issue is resolved (e.g. Resend
     domain re-verified, RingCentral OAuth reissued).

Contract:
  * Role gate: admin, super_admin, owner (via ``require_admin``).
  * Tenant-scoped — the lead is looked up in the acting tenant's
    scope; a 404 is returned for cross-tenant probes.
  * Bypasses idempotency by clearing the matching rows in
    ``lead_notification_dispatches`` before invoking the
    dispatcher. The dispatcher's guard then treats every recipient
    as "never fired" and re-sends unconditionally.
  * Every resend writes an audit row
    (``event=lead_notification_resent``) with the actor id + a
    summary of what was dispatched, so the K63.polish "Last
    activity" chip + drill-down modal surface the retry cleanly.
  * Fire-and-forget — response includes the per-recipient status
    inferred from the queue counts; the actual adapter I/O runs
    in the returned BackgroundTasks queue.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin


router = APIRouter(tags=["admin"])


@router.post("/admin/leads/{lead_id}/resend-notifications")
async def resend_lead_notifications(
    lead_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    _admin: dict = Depends(require_admin),
):
    """Re-fire the K63 lead-alert fan-out for a single lead.

    ``_admin`` is only wired to enforce the role gate — the actor
    metadata comes from ``get_current_user`` so we can log who
    triggered the resend on the audit row.
    """
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "User has no tenant")

    lead = await db.leads.find_one(
        {"id": lead_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")

    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}

    # Clear the K63 idempotency rows for this lead so the
    # dispatcher's guard treats every recipient as "never fired".
    # Scoped tightly to the (tenant, lead) pair — never clears any
    # OTHER lead's dispatch history.
    wiped = await db.lead_notification_dispatches.delete_many(
        {"tenant_id": tenant_id, "lead_id": lead_id},
    )

    from services.lead_notifications import send_lead_alert_notifications

    counts = await send_lead_alert_notifications(
        lead=lead, tenant=tenant,
        background_tasks=background_tasks,
    )

    # Build the response now — the per-recipient status is
    # inferred from the queue counts. If the dispatcher suppressed
    # the send (muted contact) or the tenant has no recipients,
    # ``dispatched`` is empty.
    dispatched: list[dict] = []
    rich = list(tenant.get("lead_notification_recipients") or [])
    if rich:
        for r in rich:
            if not isinstance(r, dict):
                continue
            phone = (r.get("phone") or "").strip()
            email = (r.get("email") or "").strip()
            if phone and r.get("sms_opt_in"):
                dispatched.append({
                    "recipient": phone, "channel": "sms",
                    "status": "queued",
                })
            if email and r.get("email_opt_in"):
                dispatched.append({
                    "recipient": email, "channel": "email",
                    "status": "queued",
                })
    else:
        for p in tenant.get("lead_alert_sms_recipients") or []:
            if isinstance(p, str) and p.strip():
                dispatched.append({
                    "recipient": p.strip(), "channel": "sms",
                    "status": "queued",
                })
        for e in tenant.get("lead_alert_email_recipients") or []:
            if isinstance(e, str) and e.strip():
                dispatched.append({
                    "recipient": e.strip(), "channel": "email",
                    "status": "queued",
                })

    # Audit row — captured on the acting tenant, keyed to the lead
    # so the K63.polish drill-down modal can filter it in.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "lead_notification_resent",
            "lead_id": lead_id,
            "actor_id": user.get("id"),
            "actor_role": user.get("role"),
            "actor_email": user.get("email"),
            "idempotency_rows_cleared": wiped.deleted_count,
            "sms_queued": counts.get("sms_queued", 0),
            "email_queued": counts.get("email_queued", 0),
            "muted_suppressed_customer_id":
                counts.get("muted_suppressed_customer_id"),
            "created_at": now_iso(),
        })
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[k63.finalize] resend audit insert failed: {exc}")

    return {
        "ok": True,
        "lead_id": lead_id,
        "dispatched": dispatched,
        "sms_queued": counts.get("sms_queued", 0),
        "email_queued": counts.get("email_queued", 0),
        "idempotency_rows_cleared": wiped.deleted_count,
        "muted_suppressed_customer_id":
            counts.get("muted_suppressed_customer_id"),
    }
