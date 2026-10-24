"""TD-customer-list-bulk-request-card-on-file · Feb-2026
======================================================================

New endpoint: ``POST /api/customers/bulk-request-card``.

Admin selects one or more customers on the Customers list and clicks
"Request card on file".  For every selected customer the backend
dispatches BOTH email AND SMS (channel-appropriate per customer
contact fields) using the operator-chosen marketing templates for
each channel.  Partial failures and per-channel skips surface in
the response — the endpoint never 500s the whole request on a
single-customer error.

Tenant isolation is STRICT (preflight 403, not per-row skip):
  * Any ``customer_id`` that resolves to a different tenant OR
    doesn't exist at all → 403 with a categorised ``errors`` list
    before any send fires.
  * Either ``template_id`` that resolves to a different tenant OR
    doesn't exist → 403 with the same error shape.
Rationale: tenant mismatch is a structural breach (symmetry with
Ticket G crew save).  Ticket D's lenient per-row ``skipped_not_found``
is specific to invoice bulk-send where missing contact info is a
lifecycle condition, not a structural issue.

Status vocabulary (per-row terminal status):
  * ``sent_both``           — email and SMS both succeeded.
  * ``sent_email_only``     — email ok, SMS skipped (no phone) /
                              failed.
  * ``sent_sms_only``       — SMS ok, email skipped (no email) /
                              failed.
  * ``skipped_no_contact``  — customer has no email AND no phone.
  * ``error``               — unexpected per-customer failure;
                              ``error`` field carries detail.

See ``memory/TD-customer-list-bulk-request-card-mobile-parity.md``
for the follow-up ticket covering the mobile tech-app surface.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, now_iso


logger = logging.getLogger("customers_bulk_request_card")
router = APIRouter()


_ADMIN_ROLES = ("admin", "manager", "super_admin")
_MAX_BULK_CUSTOMERS = 500   # DOS guard — matches sibling bulk endpoints.


class BulkRequestCardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_ids: List[str] = Field(min_length=1, max_length=_MAX_BULK_CUSTOMERS)
    # One template per channel. Operator chooses in the modal; the FE
    # auto-pre-selects the ``add_card_request_email`` /
    # ``add_card_request_sms`` codes when the tenant has them seeded.
    # Nullable so a tenant that only wants email (no SMS templates
    # seeded, say) can still ship — but then the ``sms_template_id``
    # being null means every customer gets SMS skipped.
    email_template_id: Optional[str] = None
    sms_template_id: Optional[str] = None


# Status constants exported for the FE status-chip tone map.
_STATUS_SENT_BOTH = "sent_both"
_STATUS_SENT_EMAIL_ONLY = "sent_email_only"
_STATUS_SENT_SMS_ONLY = "sent_sms_only"
_STATUS_SKIPPED_NO_CONTACT = "skipped_no_contact"
_STATUS_ERROR = "error"


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


async def _preflight_customers(
    customer_ids: List[str], tenant_id: str,
) -> Dict[str, Dict[str, Any]]:
    """Resolve every customer_id in one Mongo pass and return
    ``{customer_id: doc}``.  Any id that fails to resolve to a
    row scoped to ``tenant_id`` becomes grounds for the preflight
    403 — the caller categorises foreign_tenant vs orphan by
    probing the global ``customers`` collection for the missing
    ids separately.
    """
    rows = await db.customers.find(
        {"id": {"$in": customer_ids}, "tenant_id": tenant_id},
        {"_id": 0},
    ).to_list(len(customer_ids) + 1)
    return {r["id"]: r for r in rows}


async def _categorise_missing_customers(
    missing_ids: List[str],
) -> List[Dict[str, str]]:
    """For each id that didn't resolve inside the caller's tenant,
    probe the global ``customers`` collection to decide if it's
    ``foreign_tenant`` (exists elsewhere) or ``orphan`` (nowhere).
    Returns the per-id entry for the 403 ``errors`` list.
    """
    cat: List[Dict[str, str]] = []
    cursor = db.customers.find(
        {"id": {"$in": missing_ids}},
        {"_id": 0, "id": 1, "tenant_id": 1},
    )
    foreign_hits: Dict[str, str] = {}
    async for doc in cursor:
        foreign_hits[doc["id"]] = doc.get("tenant_id") or ""
    for mid in missing_ids:
        if mid in foreign_hits:
            cat.append({
                "customer_id": mid, "reason": "foreign_tenant",
                "tenant_id": foreign_hits[mid],
            })
        else:
            cat.append({"customer_id": mid, "reason": "orphan"})
    return cat


async def _preflight_template(
    template_id: Optional[str], channel: str, tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Resolve a template_id scoped to ``tenant_id`` and the
    expected ``channel``.  Returns the doc on success, or raises
    the preflight 403 with a categorised error entry.
    ``None`` input returns ``None`` (channel disabled for this
    submit).
    """
    if not template_id:
        return None
    row = await db.marketing_templates.find_one(
        {"id": template_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not row:
        # Probe the global collection to categorise.
        other = await db.marketing_templates.find_one(
            {"id": template_id},
            {"_id": 0, "tenant_id": 1},
        )
        err: Dict[str, Any] = {"template_id": template_id}
        if other:
            err["reason"] = "foreign_tenant"
            err["tenant_id"] = other.get("tenant_id") or ""
        else:
            err["reason"] = "orphan"
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tenant_isolation_breach",
                "errors": [err],
            },
        )
    if (row.get("channel") or "").lower() != channel:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "template_channel_mismatch",
                "template_id": template_id,
                "expected_channel": channel,
                "actual_channel": row.get("channel"),
            },
        )
    return row


def _build_customer_ctx(
    customer: Dict[str, Any], tenant: Dict[str, Any],
) -> Dict[str, Any]:
    """Minimum context for ``render_body`` — supports the canonical
    merge-tag catalog (CUSTOMER_FIRST_NAME, CUSTOMER_PORTAL_LOGIN_LINK,
    TENANT_NAME, etc.) via the ``services.marketing.merge_tags``
    resolvers.
    """
    first = (customer.get("first_name")
             or (customer.get("name") or "").split(" ")[0])
    last = (customer.get("last_name")
            or " ".join((customer.get("name") or "").split(" ")[1:]))
    return {
        "customer": {
            "id": customer.get("id"),
            "name": customer.get("name") or f"{first} {last}".strip(),
            "full_name": customer.get("name"),
            "first_name": first,
            "last_name": last,
            "email": customer.get("email"),
            "phone": customer.get("phone"),
        },
        "tenant": {
            "id": tenant.get("id"),
            "name": tenant.get("name"),
        },
    }


async def _dispatch_one(
    *, customer: Dict[str, Any], tenant: Dict[str, Any],
    email_tpl: Optional[Dict[str, Any]],
    sms_tpl: Optional[Dict[str, Any]],
    operator_id: str,
) -> Dict[str, Any]:
    """Fire email + SMS for a single customer.  Returns the per-row
    result dict appended to the bulk response.
    """
    tenant_id = tenant["id"]
    cid = customer["id"]
    email_to = (customer.get("email") or "").strip()
    phone_to = (customer.get("phone") or "").strip()

    if not email_to and not phone_to:
        return {"customer_id": cid,
                "status": _STATUS_SKIPPED_NO_CONTACT,
                "email_status": "skipped",
                "sms_status": "skipped"}

    # ─ Render bodies via the canonical merge-tag engine.
    from services.marketing_campaigns import render_body
    ctx = _build_customer_ctx(customer, tenant)

    email_status = "skipped"
    sms_status = "skipped"
    err: Optional[str] = None

    # ─── Email branch ───────────────────────────────────────────
    if email_to and email_tpl:
        try:
            subject_tpl = (email_tpl.get("subject") or "").strip() \
                or "Please add a card on file"
            subject, _ = render_body(subject_tpl, ctx)
            body_rendered, _ = render_body(email_tpl.get("body") or "", ctx)
            from services.comms_email_adapter import send_email
            from services.comms_env_guard import CommsContext
            html_body = (
                '<pre style="font-family:inherit;white-space:pre-wrap">'
                f"{body_rendered}</pre>"
            )
            res = await send_email(
                tenant_id, email_to, subject=subject or "Please add a card on file",
                html=html_body, context=CommsContext.SYSTEM,
            )
            email_status = res.get("status") or "sent"
            await db.communications_log.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "customer_id": cid,
                "channel": "email",
                "direction": "outbound",
                "recipient": email_to,
                "subject": subject or "",
                "body": body_rendered,
                "delivery_status": email_status,
                "provider": "resend",
                "provider_response_id": res.get("provider_id"),
                "trigger_entity": {
                    "kind": "customer_bulk_request_card",
                    "customer_id": cid,
                    "template_id": email_tpl.get("id"),
                    "sent_by": operator_id,
                },
                "created_at": now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            email_status = "failed"
            err = f"email: {exc!s}"
            logger.exception(
                "[bulk-request-card] email send failed for %s: %s",
                cid, exc,
            )
    elif email_to and not email_tpl:
        email_status = "skipped"   # no template chosen for channel

    # ─── SMS branch ─────────────────────────────────────────────
    if phone_to and sms_tpl:
        try:
            sms_body_rendered, _ = render_body(sms_tpl.get("body") or "", ctx)
            from services.sms.rc_adapter import send as _sms_send
            res = await _sms_send(
                phone_to, sms_body_rendered,
                tenant_id=tenant_id,
                customer_id=cid,
                idempotency_key=f"customer-bulk-request-card:{cid}",
            )
            sms_status = res.get("status") or "sent"
            await db.communications_log.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "customer_id": cid,
                "channel": "sms",
                "direction": "outbound",
                "recipient": phone_to,
                "subject": None,
                "body": sms_body_rendered,
                "delivery_status": sms_status,
                "provider": "ringcentral",
                "provider_response_id": res.get("provider_id"),
                "trigger_entity": {
                    "kind": "customer_bulk_request_card",
                    "customer_id": cid,
                    "template_id": sms_tpl.get("id"),
                    "sent_by": operator_id,
                },
                "created_at": now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            sms_status = "failed"
            err = (err + "; " if err else "") + f"sms: {exc!s}"
            logger.exception(
                "[bulk-request-card] sms send failed for %s: %s",
                cid, exc,
            )
    elif phone_to and not sms_tpl:
        sms_status = "skipped"

    # Terminal status.
    if email_status == "sent" and sms_status == "sent":
        terminal = _STATUS_SENT_BOTH
    elif email_status == "sent":
        terminal = _STATUS_SENT_EMAIL_ONLY
    elif sms_status == "sent":
        terminal = _STATUS_SENT_SMS_ONLY
    elif email_status == "failed" or sms_status == "failed":
        terminal = _STATUS_ERROR
    else:
        # Both skipped (template missing on the only available
        # channel, or sends weren't fired).  Not strictly a
        # structural skip but close enough for the summary.
        terminal = _STATUS_SKIPPED_NO_CONTACT

    out: Dict[str, Any] = {
        "customer_id": cid,
        "status": terminal,
        "email_status": email_status,
        "sms_status": sms_status,
    }
    if err:
        out["error"] = err
    return out


@router.post("/customers/bulk-request-card")
async def bulk_request_card_on_file(
    body: BulkRequestCardBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Fire ``Request card on file`` to a batch of customers.

    See module docstring for the full status vocabulary + tenant-
    isolation contract.
    """
    _require_admin(user)

    # Dedupe + preserve operator order.
    seen: set = set()
    customer_ids: List[str] = []
    for cid in body.customer_ids:
        if cid in seen:
            continue
        seen.add(cid)
        customer_ids.append(cid)

    # ─── Preflight: templates. ───────────────────────────────────
    # 403s fire inside the helper if either template is foreign-tenant
    # or orphan.  We only hit the per-row loop after both templates
    # have been proven in-tenant.
    email_tpl = await _preflight_template(
        body.email_template_id, "email", tenant["id"])
    sms_tpl = await _preflight_template(
        body.sms_template_id, "sms", tenant["id"])

    # ─── Preflight: customers. ───────────────────────────────────
    resolved = await _preflight_customers(customer_ids, tenant["id"])
    missing = [cid for cid in customer_ids if cid not in resolved]
    if missing:
        errors = await _categorise_missing_customers(missing)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tenant_isolation_breach",
                "errors": errors,
            },
        )

    # ─── Per-row dispatch. ───────────────────────────────────────
    results: List[Dict[str, Any]] = []
    counts = {"email_sent": 0, "sms_sent": 0, "skipped": 0, "error": 0}
    for cid in customer_ids:
        row = await _dispatch_one(
            customer=resolved[cid], tenant=tenant,
            email_tpl=email_tpl, sms_tpl=sms_tpl,
            operator_id=user.get("id"),
        )
        results.append(row)
        if row["email_status"] == "sent":
            counts["email_sent"] += 1
        if row["sms_status"] == "sent":
            counts["sms_sent"] += 1
        if row["status"] == _STATUS_SKIPPED_NO_CONTACT:
            counts["skipped"] += 1
        elif row["status"] == _STATUS_ERROR:
            counts["error"] += 1

    return {"results": results, "counts": counts}
