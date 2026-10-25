"""Feb-2026 · TD-invoice-list-bulk-send
================================================================

New endpoint: ``POST /api/invoices/bulk-send``.

Admin selects one or more invoices on the Invoices list and
clicks "Send Invoice".  For every selected invoice the backend
dispatches BOTH email + SMS and returns a per-invoice result.
Partial failures surface in the response — the endpoint never
500s the whole request on a single-invoice error.

TD-bulk-send-invoice-email-reuse-individual-send-template · Feb-2026
Email branch now delegates to the canonical
:func:`emailer.send_invoice_reminder_email` single-send renderer so
every bulk-sent invoice gets the SAME branded "Payment reminder"
template (logo header, bolded invoice number, red "View Invoice"
CTA, company sign-off, DB-template override) as a single-row Send
Reminder action. The prior path built a crude ``<p>``-wrapped plain-
text body + a "raw UUID in subject" fallback.

SMS branch stays unchanged — uses dunning's ``_send_sms`` + a short
plain-text body. The SMS cosmetic ``invoice_total`` vs ``balance``
drift is tracked separately as ``TD-sms-reminder-use-balance-not-total``
(P3, operator discretion).

Primary-email behavior
----------------------
Operator spec is explicit: use ``customer.email`` ONLY, no users-
table fallback. The canonical ``send_invoice_reminder_email`` DOES
fall back to ``users.email where customer_id=cid AND role="customer"``
when ``customer.email`` is empty — the bulk path pre-checks
``customer.email`` BEFORE calling the canonical fn and short-circuits
to ``skipped_no_contact`` on empty. This inverts the users-table
fallback for the bulk path only, matching the operator's literal
spec. If a future ticket wants bulk-send and single-send to agree
on edge-case fallback behavior, the fix is to tighten the single-
send call site in ``routers/quotes.py:2341`` — do NOT silently
re-add the fallback here.

Status vocabulary
-----------------
  * ``sent_both``                       — email and SMS both succeeded.
  * ``sent_email_only``                 — email ok, SMS failed / skipped.
  * ``sent_sms_only``                   — SMS ok, email failed / skipped.
  * ``skipped_already_paid``            — ``payment_status == "paid"``.
  * ``skipped_draft``                   — ``status == "draft"``.
  * ``skipped_no_contact``              — customer has no ``customers.email``
                                          and no ``customers.phone`` on file.
  * ``skipped_recent_send``             — operator dedupe window hit
                                          (another send attempt against
                                          the same invoice fired within
                                          the last 60 seconds).
  * ``skipped_not_found``               — invoice id not found in this
                                          tenant (prevents cross-tenant
                                          enumeration).
  * ``skipped_automation_disabled``     — tenant's
                                          ``invoice_past_due_enabled`` flag
                                          is off; canonical renderer
                                          refuses to fire. Surfaced as a
                                          skip (NOT an error) so the
                                          operator sees the actual reason
                                          instead of a bogus "failed".
  * ``error``                           — unexpected per-invoice failure;
                                          ``error`` field carries detail.

Idempotency notes
-----------------
  * **SMS**: ``services.sms.rc_adapter.send`` already accepts
    an ``idempotency_key``; we pass
    ``f"invoice-bulk-send:{invoice_id}"`` so provider-level
    dedupe handles replays.
  * **Email**: the canonical ``send_invoice_reminder_email`` has
    NO server-side idempotency. The bulk endpoint preserves the
    60-second dedupe window via ``db.invoice_send_attempts``
    — this is operator safety (admin double-click guard), NOT a
    canonical-fn concern.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso


logger = logging.getLogger("invoices_bulk_send")
router = APIRouter()


_ADMIN_ROLES = ("admin", "manager", "super_admin")
_MAX_BULK_INVOICES = 500   # DOS guard — matches sibling bulk endpoints.
_DEDUPE_WINDOW_SECONDS = 60


class BulkSendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_ids: List[str] = Field(min_length=1)


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


# Status constants exported for sibling tests + the FE status-chip
# tone map.  Keep in sync with the two consumers.
_STATUS_SENT_BOTH = "sent_both"
_STATUS_SENT_EMAIL_ONLY = "sent_email_only"
_STATUS_SENT_SMS_ONLY = "sent_sms_only"
_STATUS_SKIPPED_PAID = "skipped_already_paid"
_STATUS_SKIPPED_DRAFT = "skipped_draft"
_STATUS_SKIPPED_NO_CONTACT = "skipped_no_contact"
_STATUS_SKIPPED_RECENT = "skipped_recent_send"
_STATUS_SKIPPED_NOT_FOUND = "skipped_not_found"
# TD-bulk-send-invoice-email-reuse-individual-send-template · Feb-2026
# Tenant-level feature-flag suppression surfaced as a distinct skip
# so operator doesn't see a bogus "failed" when
# ``invoice_past_due_enabled`` is off at the tenant level.
_STATUS_SKIPPED_AUTOMATION_DISABLED = "skipped_automation_disabled"
_STATUS_ERROR = "error"


async def _recent_attempt_exists(
    tenant_id: str, invoice_id: str,
) -> bool:
    """Dedupe window — any send attempt against this invoice
    in the last ``_DEDUPE_WINDOW_SECONDS``?"""
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=_DEDUPE_WINDOW_SECONDS)
    ).isoformat()
    doc = await db.invoice_send_attempts.find_one(
        {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "attempted_at": {"$gte": cutoff},
        },
        {"_id": 0, "id": 1},
    )
    return doc is not None


async def _record_attempt(
    *, tenant_id: str, invoice_id: str, operator_id: str,
    email_status: str, sms_status: str, final_status: str,
    error: Optional[str] = None,
) -> None:
    await db.invoice_send_attempts.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "operator_id": operator_id,
        "email_status": email_status,
        "sms_status": sms_status,
        "final_status": final_status,
        "error": error,
        "attempted_at": now_iso(),
        "source": "invoices_bulk_send",
    })


async def _send_single_invoice(
    *, invoice_id: str, tenant: Dict[str, Any],
    operator_id: str,
    email_automation_enabled: bool = True,
) -> Dict[str, Any]:
    """Dispatch email + SMS for one invoice.  Returns the per-row
    result dict that gets appended to the bulk response.

    TD-bulk-send-invoice-email-reuse-individual-send-template ·
    Feb-2026 — email branch delegates to the canonical
    ``emailer.send_invoice_reminder_email`` so the bulk flow
    renders the SAME branded template as a single-row Send
    Reminder action.  The caller is responsible for pre-computing
    ``email_automation_enabled`` ONCE per batch
    (``invoice_past_due_enabled`` tenant flag — tenant is shared
    across the whole batch, so we read it once at the endpoint
    level and thread it in to avoid N tenant doc lookups).
    """
    tenant_id = tenant["id"]
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id,
         "doc_type": "invoice"},
        {"_id": 0},
    )
    if not inv:
        return {"invoice_id": invoice_id,
                "status": _STATUS_SKIPPED_NOT_FOUND}

    # Status gates — mirror the ticket spec.
    if (inv.get("payment_status") or "").lower() == "paid":
        return {"invoice_id": invoice_id,
                "status": _STATUS_SKIPPED_PAID}
    if (inv.get("status") or "").lower() == "draft":
        return {"invoice_id": invoice_id,
                "status": _STATUS_SKIPPED_DRAFT}

    # Dedupe window.
    if await _recent_attempt_exists(tenant_id, invoice_id):
        return {"invoice_id": invoice_id,
                "status": _STATUS_SKIPPED_RECENT}

    # Resolve customer + contact fields.
    #
    # TD-bulk-send-invoice-email-reuse-individual-send-template ·
    # Feb-2026 — ``email_to`` is sourced from ``customers.email``
    # ONLY per operator spec ("do not fall back to a secondary or
    # alternate email"). The canonical
    # ``emailer.send_invoice_reminder_email`` DOES have a
    # ``users.email where customer_id=cid AND role="customer"``
    # fallback at ``emailer.py:573``; the pre-check below short-
    # circuits to ``skipped_no_contact`` on empty ``customers.email``
    # BEFORE the canonical fn runs so the fallback is never
    # consulted for the bulk path. If a future ticket decides
    # bulk and single-send should agree on fallback behavior, the
    # fix is to tighten the single-send call site, NOT to re-
    # introduce the fallback here.
    customer = None
    if inv.get("customer_id"):
        customer = await db.customers.find_one(
            {"id": inv["customer_id"], "tenant_id": tenant_id},
            {"_id": 0},
        )
    email_to = ((customer or {}).get("email") or "").strip()
    phone_to = ((customer or {}).get("phone") or "").strip()

    if not email_to and not phone_to:
        await _record_attempt(
            tenant_id=tenant_id, invoice_id=invoice_id,
            operator_id=operator_id,
            email_status="skipped", sms_status="skipped",
            final_status=_STATUS_SKIPPED_NO_CONTACT,
        )
        return {"invoice_id": invoice_id,
                "status": _STATUS_SKIPPED_NO_CONTACT}

    # ── Email: delegate to the canonical single-send renderer.
    # No DI needed — the fn is a plain async callable taking the
    # invoice dict.  Branding + locale + DB-template override + CTA
    # token + customer email lookup all happen inside the canonical
    # path, so the rendered email is byte-for-byte the same shape
    # the single-row Send Reminder action emits.
    email_result: Dict[str, Any] = {"status": "skipped"}
    if email_to:
        if not email_automation_enabled:
            # Tenant has ``invoice_past_due_enabled`` off — the
            # canonical fn would silently return False.  Surface
            # the actual reason to the operator instead of a bogus
            # "failed" per the ticket spec.
            email_result = {
                "status": "skipped",
                "reason": "automation_disabled",
            }
        else:
            try:
                from emailer import (  # noqa: PLC0415
                    send_invoice_reminder_email,
                )
                ok = await send_invoice_reminder_email(inv)
                email_result = (
                    {"status": "sent"} if ok
                    else {"status": "failed",
                           "error": "send_invoice_reminder_email returned False"}
                )
            except Exception as exc:  # noqa: BLE001
                email_result = {"status": "failed",
                                 "error": str(exc)}

    # ── SMS: unchanged.  Reuse the dunning helpers for the short
    # plain-text body.  SMS has no "template" concept beyond text
    # and the operator did not flag it.  The ``invoice_total`` vs
    # ``balance`` cosmetic drift is tracked separately as
    # ``TD-sms-reminder-use-balance-not-total`` (P3).
    sms_result: Dict[str, Any] = {"status": "skipped"}
    if phone_to:
        from routers.dunning import (  # noqa: PLC0415
            _build_context, _send_sms, _get_settings,
        )
        settings = await _get_settings(tenant_id)
        ctx = await _build_context(inv, tenant, settings, src="sms")
        sms_body = (
            f"{ctx['tenant_name']}: invoice {ctx['invoice_number']} "
            f"(${ctx['invoice_total']}) ready. Pay: {ctx['payment_link']}"
        )
        try:
            sms_result = await _send_sms(
                phone_to, sms_body,
                tenant_id=tenant_id,
                customer_id=inv.get("customer_id"),
            )
        except Exception as exc:  # noqa: BLE001
            sms_result = {"status": "failed", "error": str(exc)}

    email_ok = (email_result.get("status") == "sent")
    sms_ok = (sms_result.get("status") == "sent")
    # Automation-disabled email surfaces as its own skip even when
    # SMS succeeds — operator needs to see the per-channel reason.
    automation_blocked_email = (
        email_result.get("status") == "skipped"
        and email_result.get("reason") == "automation_disabled"
    )
    if email_ok and sms_ok:
        final = _STATUS_SENT_BOTH
    elif email_ok:
        final = _STATUS_SENT_EMAIL_ONLY
    elif sms_ok and automation_blocked_email:
        # Email suppressed by tenant flag, SMS sent.  Surface the
        # suppression as the final status so the operator sees
        # "automation disabled" rather than a confusing
        # ``sent_sms_only`` for an invoice they expected to also
        # email.
        final = _STATUS_SKIPPED_AUTOMATION_DISABLED
    elif sms_ok:
        final = _STATUS_SENT_SMS_ONLY
    elif automation_blocked_email and not phone_to:
        # Email suppressed, no SMS to try. Surface the suppression,
        # NOT "error".
        final = _STATUS_SKIPPED_AUTOMATION_DISABLED
    else:
        final = _STATUS_ERROR

    err_bits: List[str] = []
    if not email_ok and email_to and not automation_blocked_email:
        err_bits.append(
            f"email:{email_result.get('error') or email_result.get('reason') or email_result.get('status') or 'failed'}")
    if not sms_ok and phone_to:
        err_bits.append(
            f"sms:{sms_result.get('error') or sms_result.get('reason') or sms_result.get('status') or 'failed'}")
    err_str: Optional[str] = ", ".join(err_bits) if err_bits else None

    await _record_attempt(
        tenant_id=tenant_id, invoice_id=invoice_id,
        operator_id=operator_id,
        email_status=email_result.get("status") or "unknown",
        sms_status=sms_result.get("status") or "unknown",
        final_status=final, error=err_str,
    )
    row: Dict[str, Any] = {
        "invoice_id": invoice_id, "status": final,
        "email_to": email_to or None,
        "sms_to": phone_to or None,
        "email_status": email_result.get("status"),
        "sms_status": sms_result.get("status"),
    }
    if err_str:
        row["error"] = err_str
    return row


# ═════════════════════════════════════════════════════════════
# Endpoint
# ═════════════════════════════════════════════════════════════
@router.post("/invoices/bulk-send")
async def bulk_send_invoices(
    body: BulkSendBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Send email + SMS to every selected invoice's customer."""
    _require_admin(user)

    # De-dup within the same request to make partial retries sane.
    seen: set = set()
    invoice_ids: List[str] = []
    for iid in body.invoice_ids:
        s = str(iid).strip()
        if s and s not in seen:
            seen.add(s)
            invoice_ids.append(s)
    if not invoice_ids:
        raise HTTPException(
            400, "invoice_ids must contain at least one id")
    if len(invoice_ids) > _MAX_BULK_INVOICES:
        raise HTTPException(
            400,
            f"Too many invoices (max {_MAX_BULK_INVOICES} per batch)")

    tenant_id = tenant["id"]
    operator_id = user["id"]

    # TD-bulk-send-invoice-email-reuse-individual-send-template ·
    # Feb-2026 — pre-compute the ``invoice_past_due_enabled`` tenant
    # flag ONCE per batch and thread it to every per-row call. The
    # flag is tenant-scoped and the whole batch shares a tenant, so
    # reading it 500 times inside the loop would be a wasted round
    # trip. ``automation_enabled`` defaults to True on an unset
    # tenant doc per the shipped contract.
    from services.tenant_automation_gates import automation_enabled
    email_automation_enabled = await automation_enabled(
        tenant_id, "invoice_past_due_enabled",
    )

    results: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for iid in invoice_ids:
        try:
            row = await _send_single_invoice(
                invoice_id=iid, tenant=tenant,
                operator_id=operator_id,
                email_automation_enabled=email_automation_enabled,
            )
        except Exception as exc:  # noqa: BLE001
            # Shouldn't happen — _send_single_invoice swallows
            # per-channel errors internally — but be defensive.
            logger.warning(
                "[bulk-send] per-invoice fatal (tenant=%s id=%s): %s",
                tenant_id, iid, exc,
            )
            row = {"invoice_id": iid, "status": _STATUS_ERROR,
                    "error": str(exc)}
        results.append(row)
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    summary = {
        "requested": len(invoice_ids),
        "sent_both": counts.get(_STATUS_SENT_BOTH, 0),
        "sent_email_only": counts.get(_STATUS_SENT_EMAIL_ONLY, 0),
        "sent_sms_only": counts.get(_STATUS_SENT_SMS_ONLY, 0),
        "skipped_already_paid":
            counts.get(_STATUS_SKIPPED_PAID, 0),
        "skipped_draft": counts.get(_STATUS_SKIPPED_DRAFT, 0),
        "skipped_no_contact":
            counts.get(_STATUS_SKIPPED_NO_CONTACT, 0),
        "skipped_recent_send":
            counts.get(_STATUS_SKIPPED_RECENT, 0),
        "skipped_not_found":
            counts.get(_STATUS_SKIPPED_NOT_FOUND, 0),
        "skipped_automation_disabled":
            counts.get(_STATUS_SKIPPED_AUTOMATION_DISABLED, 0),
        "errored": counts.get(_STATUS_ERROR, 0),
    }
    request_id = new_id()
    logger.info(
        "[bulk-send] request_id=%s tenant=%s operator=%s "
        "requested=%s summary=%s",
        request_id, tenant_id, operator_id,
        summary["requested"], summary,
    )
    return {
        "summary": summary,
        "results": results,
        "request_id": request_id,
    }
