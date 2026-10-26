"""Ticket KK · Feb-2026 — Bulk SMS to a selected list of customers.

``POST /customers/bulk-sms`` accepts
``{customer_ids: [str], message?: str, template_id?: str}`` and fires an
SMS to every selected customer on the caller's tenant. Replaces the
unbounded free-text/filter-driven ``/mass-messaging/send`` flow for the
"operator picks N rows in the Customers list → sends them a text"
use case the Customers page bulk action bar needs.

Scope decisions (locked in the KK pre-audit receipt):

* **No confirm-token round-trip.** The Mass Text modal lives in the
  Customers list bulk action bar: the operator has already picked the
  concrete recipient ids by clicking checkboxes, and the modal gates
  Send behind a destructive-styled "Send to N customers?" dialog. A
  two-step preview → confirm-token flow (as in
  ``routers/mass_messaging.py``) exists to defend audience-signature
  drift on filter-driven broadcasts; it adds no safety on a list of
  explicit ids. The server stays the security boundary via admin-
  only RBAC + K72 safety guards + per-tenant rate limit.

* **Reuses mass_messaging primitives verbatim.** The K72 CI block +
  real-tenant-non-prod block, ``_enforce_rate_limit``,
  ``_is_suppressed``, admin-owned deny-list strip, ``_log_delivery``
  and ``_classify_provider_status`` are imported from
  ``routers.mass_messaging`` so a KK broadcast lands in the same
  ``mass_messaging_batches`` audit collection and shares the 5-min
  per-tenant rate-limit window as a mass_messaging broadcast.

* **Hard audience cap at 5000 recipients** — same as mass_messaging.

Response envelope is synchronous counts (resolved vs skipped vs
queued); the actual provider fanout runs in a BackgroundTask the same
way mass_messaging does.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant
from routers.mass_messaging import (
    _ADMIN_ROLES,
    _AUDIENCE_CAP,
    _classify_provider_status,
    _enforce_rate_limit,
    _is_suppressed,
    _load_template,
    _log_delivery,
)


router = APIRouter()


# ── Pydantic bodies ───────────────────────────────────────────────
class BulkSmsIn(BaseModel):
    customer_ids: List[str] = Field(..., min_length=1, max_length=_AUDIENCE_CAP)
    message: Optional[str] = None
    template_id: Optional[str] = None


# ── Guards ────────────────────────────────────────────────────────
def _require_admin(user: dict) -> None:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Bulk SMS is admin-only")


def _k72_safety_guards(tenant: dict, user: dict) -> None:
    """Mirror of ``routers/mass_messaging.send_broadcast`` K72 belts:

    (1) ``CI_BLOCK_MASS_MESSAGING=1`` short-circuits every send.
    (2) ``is_real=True`` tenant on a non-production pod short-
        circuits every send.

    Both fire BEFORE audience resolution so no customers are loaded
    on a blocked run.
    """
    if (os.environ.get("CI_BLOCK_MASS_MESSAGING") or "").strip() == "1":
        logger.warning(
            "[KK] customers/bulk-sms blocked by CI_BLOCK_MASS_MESSAGING "
            "tenant=%s user=%s", tenant.get("id"), user.get("id"),
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "K72_CI_MASS_MESSAGING_BLOCKED",
                "message": (
                    "Mass-messaging is disabled in this CI run via "
                    "CI_BLOCK_MASS_MESSAGING=1."
                ),
            },
        )
    if tenant.get("is_real") is True:
        app_env = (os.environ.get("APP_ENV") or "").strip().lower()
        if app_env != "production":
            logger.warning(
                "[KK] customers/bulk-sms blocked — real tenant on "
                "non-prod pod. tenant=%s app_env=%s user=%s",
                tenant.get("id"), app_env, user.get("id"),
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "K72_REAL_TENANT_NON_PROD_BLOCKED",
                    "message": (
                        "Broadcast blocked: this tenant is flagged "
                        "is_real=true and the current APP_ENV is not "
                        "'production'. A test or preview pod cannot "
                        "fire real-customer broadcasts against a "
                        "production tenant."
                    ),
                    "tenant_id": tenant.get("id"),
                    "app_env": app_env or "(unset)",
                },
            )


# ── Fanout background task ────────────────────────────────────────
async def _run_bulk_sms(
    *,
    tenant_id: str,
    batch_id: str,
    customers: List[Dict[str, Any]],
    sms_body: str,
    template_id: Optional[str],
    initiated_by: str,
) -> None:
    """Iterate the resolved customers, strip admin-owned recipients,
    skip opt-outs, fire the SMS via ``services.sms.rc_adapter.send``,
    and record a ``marketing_deliveries`` row per (customer, 'sms')
    attempt. Updates the batch row's stats + status when done.

    Deliberately isolated from the mass_messaging ``_run_broadcast``
    orchestrator because KK is SMS-only, operator-authored (no
    merge-tag render pass), and skips the email branch entirely.
    """
    from services.sms.rc_adapter import send as _send_sms
    from services.comms_hardening.deny_list import (
        strip_admin_owned_recipients as _deny_strip,
    )

    stats: Dict[str, int] = {
        "sent": 0, "failed": 0, "suppressed": 0, "no_contact": 0,
    }

    logger.info(
        "[KK] bulk-sms fanout START batch=%s tenant=%s recipients=%d",
        batch_id, tenant_id, len(customers),
    )

    for c in customers:
        # Multi-contact mute guardrail (automation) — matches the
        # mass_messaging contract: a muted customer never receives
        # scheduler-triggered marketing.
        if c.get("automations_muted"):
            try:
                from services.customer_multi_contact import log_mute_suppressed
                await log_mute_suppressed(
                    tenant_id=tenant_id, customer_id=c.get("id"),
                    channel="sms", cluster="customers_bulk_sms",
                    context="automation",
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("[KK] log_mute_suppressed failed: %s", exc)
            stats["suppressed_muted"] = stats.get("suppressed_muted", 0) + 1
            continue

        phone = (c.get("phone") or "").strip()
        if phone:
            _kept, _stripped = await _deny_strip(
                tenant_id=tenant_id, kind="customer_facing",
                channel="sms", recipients=[phone],
                context={
                    "trigger": "customers_bulk_sms",
                    "batch_id": batch_id,
                    "customer_id": c.get("id"),
                },
            )
            if not _kept:
                stats["denied_admin_owned"] = stats.get("denied_admin_owned", 0) + 1
                await _log_delivery(
                    tenant_id=tenant_id, batch_id=batch_id, customer=c,
                    channel="sms", subject=None, body="",
                    status="denied_admin_owned", provider="none",
                    error=str(_stripped),
                )
                phone = ""

        if not phone:
            stats["no_contact"] += 1
            await _log_delivery(
                tenant_id=tenant_id, batch_id=batch_id, customer=c,
                channel="sms", subject=None, body="",
                status="no_contact", provider="none",
            )
            continue

        try:
            res = await _send_sms(
                to=phone, body=sms_body,
                category="marketing",
                tenant_id=tenant_id, customer_id=c.get("id"),
                idempotency_key=f"kk:{batch_id}:{c.get('id')}:sms",
            )
            status = _classify_provider_status(res)
            err = None if status == "sent" else (res or {}).get("error")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[KK] sms adapter raised batch=%s cust=%s: %s",
                batch_id, c.get("id"), exc,
            )
            res = {}
            status = "failed"
            err = str(exc)

        stats[status] = stats.get(status, 0) + 1
        await _log_delivery(
            tenant_id=tenant_id, batch_id=batch_id, customer=c,
            channel="sms", subject=None, body=sms_body,
            status=status,
            provider=(res or {}).get("provider") or "ringcentral",
            provider_response_id=(res or {}).get("provider_response_id"),
            error=err,
        )

    await db.mass_messaging_batches.update_one(
        {"id": batch_id},
        {"$set": {
            "stats": stats,
            "status": "completed",
            "completed_at": now_iso(),
        }},
    )
    logger.info(
        "[KK] bulk-sms fanout END batch=%s stats=%s",
        batch_id, stats,
    )


# ═════════════════════════════════════════════════════════════════
# POST /customers/bulk-sms
# ═════════════════════════════════════════════════════════════════
@router.post(
    "/customers/bulk-sms",
    tags=["customers", "mass-messaging"],
    operation_id="customers.bulkSms",
)
async def customers_bulk_sms(
    body: BulkSmsIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    _k72_safety_guards(tenant, user)

    # Payload validation — must have either a free-text message or a
    # template_id. Both-present is fine (message wins; see below).
    msg_override = (body.message or "").strip()
    if not msg_override and not body.template_id:
        raise HTTPException(400, {
            "code": "BULK_SMS_EMPTY_PAYLOAD",
            "message": "Either `message` or `template_id` must be provided.",
        })

    # Rate limit BEFORE audience resolution — a tenant that already
    # fired a broadcast in the window can't quietly enumerate the
    # audience again. Shares the ``mass_messaging_batches`` window
    # with ``/mass-messaging/send``.
    tenant_id = tenant["id"]
    await _enforce_rate_limit(tenant_id)

    # Resolve selected ids strictly to the caller's tenant. Foreign
    # ids silently drop into ``skipped_cross_tenant`` — never 403, so
    # a tampered client can't probe tenant membership. Dedupe + hard-
    # cap at ``_AUDIENCE_CAP``.
    unique_ids: List[str] = list(dict.fromkeys(body.customer_ids))
    if len(unique_ids) > _AUDIENCE_CAP:
        raise HTTPException(400, {
            "code": "AUDIENCE_TOO_LARGE",
            "size": len(unique_ids), "cap": _AUDIENCE_CAP,
        })
    customers = await db.customers.find(
        {"tenant_id": tenant_id, "id": {"$in": unique_ids}},
        {"_id": 0},
    ).to_list(_AUDIENCE_CAP + 10)
    resolved_ids = {c.get("id") for c in customers}
    skipped_cross_tenant = len([i for i in unique_ids if i not in resolved_ids])

    # Resolve the SMS body: free-text `message` wins when present,
    # otherwise fall through to the template body. ``_load_template``
    # raises 404 on a cross-tenant template_id (same guard the
    # mass_messaging flow relies on).
    sms_body = msg_override
    if not sms_body and body.template_id:
        tpl = await _load_template(tenant_id, body.template_id, "sms")
        sms_body = (tpl.get("body") or "").strip()
    if not sms_body:
        raise HTTPException(400, {
            "code": "BULK_SMS_EMPTY_BODY",
            "message": "Resolved SMS body is empty.",
        })

    # Pre-count queued vs skipped synchronously so the client can
    # surface honest numbers in the "Sent to N / M opted-out skipped"
    # toast without waiting for the background fanout.
    queued = 0
    skipped_opt_out = 0
    skipped_no_phone = 0
    fanout_targets: List[Dict[str, Any]] = []
    for c in customers:
        if not (c.get("phone") or "").strip():
            skipped_no_phone += 1
            continue
        if await _is_suppressed(tenant_id, c, "sms"):
            skipped_opt_out += 1
            continue
        queued += 1
        fanout_targets.append(c)

    # Persist the batch row so the operator sees this broadcast in the
    # existing mass_messaging_batches history and so the rate-limit
    # window ticks forward.
    batch_id = new_id()
    await db.mass_messaging_batches.insert_one({
        "id": batch_id,
        "tenant_id": tenant_id,
        "initiated_by_user_id": user["id"],
        "channels": ["sms"],
        "template_id": body.template_id,
        "custom_subject": None,
        "custom_body": msg_override or None,
        "audience": "customers_bulk_sms",
        "filters_applied": {
            "audience": "customers_bulk_sms",
            "customer_ids_count": len(unique_ids),
            "resolved_count": len(customers),
            "skipped_cross_tenant": skipped_cross_tenant,
        },
        "started_at": now_iso(),
        "completed_at": None,
        "stats": {"sent": 0, "failed": 0, "suppressed": 0, "no_contact": 0},
        "status": "running",
        "queued_email": 0,
        "queued_sms": queued,
    })

    # Fire the actual fanout in background so the HTTP response lands
    # inside the request budget regardless of recipient count.
    background_tasks.add_task(
        _run_bulk_sms,
        tenant_id=tenant_id,
        batch_id=batch_id,
        customers=fanout_targets,
        sms_body=sms_body,
        template_id=body.template_id,
        initiated_by=user["id"],
    )

    return {
        "batch_id": batch_id,
        "selected_count": len(unique_ids),
        "resolved_count": len(customers),
        "skipped_cross_tenant": skipped_cross_tenant,
        "skipped_opt_out": skipped_opt_out,
        "skipped_no_phone": skipped_no_phone,
        "queued": queued,
        "status": "running",
    }
