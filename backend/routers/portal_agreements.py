"""Phase F1.2 · Feb-2026 — Customer-portal agreement renewal.

Public route (no auth) that lets a customer click the CTA in the
A4-produced renewal proposal email and flip their agreement to
``renewed`` + spawn a follow-up ``warranty_contracts`` row for the
next term. HMAC token comes from
``services.intelligence.renewal_scan.sign_renewal_token``; we verify
via the sibling ``verify_renewal_token`` helper so key rotation is
tied to the same ``JWT_SECRET`` lifecycle as every other signed
artefact.

Endpoints
---------
* ``POST /api/portal/agreements/{agreement_id}/renew`` — public.
  Body: ``{"token": "<HMAC token>"}``.

Error posture
-------------
* Missing / malformed body        → 422 (FastAPI default).
* Expired token                    → 410 ``token_expired``.
* Signature mismatch / wrong id    → 403 ``token_invalid``.
* Agreement not found              → 409 ``agreement_state_invalid``.
* Agreement already renewed        → 409 ``agreement_state_invalid``.
* Agreement inactive               → 409 ``agreement_state_invalid``.
* All other unexpected server-side → 500 (uncaught).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from config import db, RESEND_API_KEY, EMAIL_FROM
from services.intelligence.renewal_scan import verify_renewal_token

logger = logging.getLogger("portal_agreements")
router = APIRouter(tags=["portal-agreements"])


class _RenewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_end_date(raw: Any) -> Optional[date]:
    """Best-effort parse of ``warranty_contracts.end_date``.  Accepts
    ``date``, full ISO datetime string, or short ``YYYY-MM-DD``."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not raw:
        return None
    s = str(raw)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _compute_new_end_date(
    orig_start: Optional[date],
    orig_end: Optional[date],
    today: date,
) -> date:
    """Derive next term's end. Prefer ``end - start`` (the honest
    term length); fall back to a 365-day annual term when either
    bound is missing."""
    if orig_start and orig_end:
        span = max((orig_end - orig_start).days, 1)
    else:
        span = 365
    return today + timedelta(days=span)


async def _send_renewal_confirmation(
    *,
    contract: Dict[str, Any],
    customer: Dict[str, Any],
    tenant: Dict[str, Any],
    new_end_iso: str,
) -> Optional[str]:
    """Fire the renewal confirmation email through the same Resend +
    DRY-RUN guard pipeline as the proposal email. Never raises."""
    to = (customer or {}).get("email")
    if not to:
        return None
    if not RESEND_API_KEY:
        return None
    try:
        from services.comms_env_guard import guard_outbound
        verdict = guard_outbound(kind="email", to=to)
        if verdict.blocked:
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        from services.i18n.email_locale import resolve_email_locale
        from services.email_body_i18n import t_email_body
    except Exception:  # noqa: BLE001
        return None
    locale = resolve_email_locale(recipient=customer, tenant=tenant)
    plan_name = (contract.get("plan_name_snapshot")
                  or "maintenance plan")
    first_name = ((customer.get("name") or "").split(" ")[0]
                   or "there")
    price_val = float(contract.get("price_paid") or 0)
    monthly = f"${price_val:,.2f}"
    currency = ((tenant.get("settings") or {}).get("currency")
                  or "USD").upper()
    try:
        subject = t_email_body(
            locale, "email.renewal_confirmation.subject",
            plan_name=plan_name,
        )
        intro = t_email_body(
            locale, "email.renewal_confirmation.body_intro",
            customer_first_name=first_name, plan_name=plan_name,
        )
        term = t_email_body(
            locale, "email.renewal_confirmation.body_term",
            next_expires_at_short=new_end_iso,
        )
        price = t_email_body(
            locale, "email.renewal_confirmation.body_price",
            monthly_amount=monthly, currency=currency,
        )
        footer = t_email_body(
            locale, "email.renewal_confirmation.body_footer",
        )
    except KeyError as exc:
        logger.warning(
            "[portal-renewal] confirmation i18n key missing: %s", exc)
        return None
    html = (
        f"<p>{intro}</p><p>{term}</p><p>{price}</p><p>{footer}</p>"
    )
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from":    EMAIL_FROM,
            "to":      to,
            "subject": subject,
            "html":    html,
        })
        return to
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[portal-renewal] confirmation email send failed: %s", exc)
        return None


@router.post("/portal/agreements/{agreement_id}/renew")
async def renew_agreement(agreement_id: str, body: _RenewBody):
    """Verify the HMAC token, mark the original contract as renewed
    (idempotent — repeats after success return 409), and spawn a
    follow-up ``warranty_contracts`` row for the next term."""
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(403, detail="token_invalid")
    signed_id = verify_renewal_token(token)
    if signed_id is None:
        # Bucket the two failure modes — expired vs bad sig — via a
        # second parse so the frontend can tell them apart. The
        # sign_renewal_token helper embeds ``{contract_id}.{exp}.{sig}``
        # so a token that decoded but expired needs a distinct
        # error code from a mangled/forged one.
        parts = (token or "").split(".")
        if len(parts) == 3:
            try:
                exp = int(parts[1])
                if exp < int(_now_utc().timestamp()):
                    raise HTTPException(410, detail="token_expired")
            except ValueError:
                pass
        raise HTTPException(403, detail="token_invalid")
    if signed_id != agreement_id:
        raise HTTPException(403, detail="token_invalid")

    contract = await db.warranty_contracts.find_one(
        {"id": agreement_id}, {"_id": 0})
    if not contract:
        raise HTTPException(409, detail="agreement_state_invalid")
    status = (contract.get("status") or "").lower()
    if status == "renewed" or contract.get("renewed_at") \
       or contract.get("renewal_contract_id"):
        raise HTTPException(409, detail="agreement_state_invalid")
    if status not in ("active", ""):
        raise HTTPException(409, detail="agreement_state_invalid")

    tenant_id = contract.get("tenant_id")
    today = _now_utc().date()
    orig_start = _parse_end_date(contract.get("start_date"))
    orig_end = _parse_end_date(contract.get("end_date"))
    new_end = _compute_new_end_date(orig_start, orig_end, today)

    now_iso = _now_utc().isoformat()
    new_id = str(uuid.uuid4())

    # Copy the original contract's plan / customer snapshot so the
    # renewed row is standalone. NEVER carry over ``id``, ``status``,
    # or the renewal-linkage fields.
    child = {
        "id":         new_id,
        "tenant_id":  tenant_id,
        "customer_id":              contract.get("customer_id"),
        "customer_name_snapshot":   contract.get("customer_name_snapshot"),
        "plan_id":                  contract.get("plan_id"),
        "plan_name_snapshot":       contract.get("plan_name_snapshot"),
        "plan_kind_snapshot":       contract.get("plan_kind_snapshot"),
        "price_paid":               contract.get("price_paid"),
        "status":                   "active",
        "start_date":               today.isoformat(),
        "end_date":                 new_end.isoformat(),
        "created_at":               now_iso,
        "updated_at":               now_iso,
        "renewed_by_agreement_id":  agreement_id,
        "source":                   "customer_portal_renew",
    }
    await db.warranty_contracts.insert_one(child)

    # Flip the parent row's status + linkage in one round-trip.
    await db.warranty_contracts.update_one(
        {"id": agreement_id, "tenant_id": tenant_id},
        {"$set": {
            "status":              "renewed",
            "renewed_at":          now_iso,
            "renewal_contract_id": new_id,
            "updated_at":          now_iso,
        }},
    )

    # Fire-and-forget confirmation email (respects DRY-RUN guard).
    customer = {}
    if contract.get("customer_id") and tenant_id:
        customer = await db.customers.find_one(
            {"id": contract["customer_id"], "tenant_id": tenant_id},
            {"_id": 0},
        ) or {}
    tenant = {}
    if tenant_id:
        tenant = await db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0}) or {}
    await _send_renewal_confirmation(
        contract=contract, customer=customer, tenant=tenant,
        new_end_iso=new_end.isoformat(),
    )

    logger.info(
        "[portal-renewal] agreement=%s renewed → new=%s "
        "new_end=%s tenant=%s",
        agreement_id, new_id, new_end.isoformat(), tenant_id,
    )
    return {
        "ok":                 True,
        "new_agreement_id":   new_id,
        "next_expires_at":    new_end.isoformat(),
        "plan_name":          contract.get("plan_name_snapshot"),
        "price_paid":         contract.get("price_paid"),
    }


@router.get("/portal/agreements/{agreement_id}/summary")
async def summarize_agreement(agreement_id: str, token: str):
    """Read-only summary for the renewal landing page — same HMAC
    gating as the renew POST above. Returns the fields the page
    needs to render the plan card before the customer clicks
    ``Renew Now``."""
    signed_id = verify_renewal_token((token or "").strip())
    if signed_id is None:
        parts = (token or "").split(".")
        if len(parts) == 3:
            try:
                exp = int(parts[1])
                if exp < int(_now_utc().timestamp()):
                    raise HTTPException(410, detail="token_expired")
            except ValueError:
                pass
        raise HTTPException(403, detail="token_invalid")
    if signed_id != agreement_id:
        raise HTTPException(403, detail="token_invalid")
    contract = await db.warranty_contracts.find_one(
        {"id": agreement_id}, {"_id": 0})
    if not contract:
        raise HTTPException(409, detail="agreement_state_invalid")

    orig_start = _parse_end_date(contract.get("start_date"))
    orig_end = _parse_end_date(contract.get("end_date"))
    today = _now_utc().date()
    new_end = _compute_new_end_date(orig_start, orig_end, today)

    tenant = {}
    if contract.get("tenant_id"):
        tenant = await db.tenants.find_one(
            {"id": contract["tenant_id"]}, {"_id": 0}) or {}
    currency = ((tenant.get("settings") or {}).get("currency")
                  or "USD").upper()

    return {
        "agreement_id":       contract["id"],
        "plan_name":          contract.get("plan_name_snapshot"),
        "plan_kind":          contract.get("plan_kind_snapshot"),
        "customer_name":      contract.get("customer_name_snapshot"),
        "price_paid":         contract.get("price_paid"),
        "currency":           currency,
        "status":             contract.get("status"),
        "current_expires_at": (orig_end.isoformat()
                                 if orig_end else contract.get("end_date")),
        "next_expires_at":    new_end.isoformat(),
        "already_renewed":    bool(contract.get("renewed_at")
                                     or contract.get("renewal_contract_id")
                                     or (contract.get("status")
                                          or "").lower() == "renewed"),
    }
