"""Feb-2026 · Customer-portal shared endpoints (Slice 3 · 3A + 3B + 3D).

3B — ``GET /api/customer-portal/summary`` returns the four numbers
     rendered as tiles at the top of the portal home page:
     balance_due, past_due, credit, next_service.

3A — ``POST /api/customer-portal/payment-methods/ach/link-session``
     kicks off a Stripe Financial Connections session for ACH bank
     verification. Wire-ready — behaves as a stub when
     ``STRIPE_SECRET_KEY`` is not configured (or the SDK call fails)
     so the frontend can render a disabled Connect button.

3D — ``POST /api/customer-portal/service-requests`` books an internal
     message + bell notification + best-effort Expo push to every
     admin in the customer's tenant when the customer taps the
     "Request Service" CTA on the portal.

All routes require ``role == "customer"`` and scope every read/write
strictly to ``current_user.customer_id`` in the current tenant.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 3B · Portal summary tiles
# ═══════════════════════════════════════════════════════════════════════
def _require_customer(user: dict) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(403, "Customer id missing on user")
    return cid


def _num(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/customer-portal/summary")
async def get_portal_summary(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """4-tile aggregate for the portal landing.

    Response shape::

        {
          "balance_due": 214.50,          # unpaid remaining on all open invoices
          "past_due": 89.00,              # subset of balance_due whose due_date < today
          "credit": 0.00,                 # overpayments across paid invoices
          "next_service": {               # or ``None``
            "date": "2026-08-05",
            "service_type": "Pool cleaning",
            "job_id": "…"
          },
          "breakdown": {
            "open_invoice_count": 3,
            "past_due_invoice_count": 1
          }
        }
    """
    cid = _require_customer(user)
    today = datetime.now(timezone.utc).date().isoformat()

    invs: List[Dict[str, Any]] = await db.quotes.find(
        {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "doc_type": "invoice",
            # Feb-2026 · Item 3 — soft-deleted invoices MUST NEVER
            # surface in the customer portal (service history,
            # invoices tab, balance / past-due / credit rollups).
            # Match both "field absent" (legacy rows) and "null".
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        },
        {"_id": 0},
    ).to_list(2000)

    balance_due = 0.0
    past_due = 0.0
    credit = 0.0
    open_ct = 0
    past_ct = 0
    for inv in invs:
        total = _num(inv.get("total"))
        paid = _num(inv.get("amount_paid"))
        remaining = round(total - paid, 2)
        due_date = str(inv.get("due_date") or "")[:10]
        if remaining > 0:
            balance_due += remaining
            open_ct += 1
            if due_date and due_date < today:
                past_due += remaining
                past_ct += 1
        elif remaining < 0:
            # Overpayment → treat the absolute difference as customer credit.
            credit += -remaining

    # ── Phase P47 · Feb-2026 · Next-service query fix ────────────
    # Pre-P47 this used ``find_one`` with sort
    # ``(scheduled_start ASC, scheduled_date ASC)`` and a Python
    # post-filter ``if str(scheduled)[:10] >= today``.  BSON sorts
    # nulls FIRST in ascending order, so a customer with any stale
    # ``status=scheduled`` row (past-dated, never marked completed)
    # would see the stalest row surfaced by the sort and then DROPPED
    # by the Python guard — with no fallthrough to the actual next
    # upcoming job.  Portal "Next Service" tile went blank.
    #
    # Fix: push the date guard into the DB query itself.  Two OR
    # branches:
    #   1) ``scheduled_start >= now_iso`` — has a specific ISO ts
    #      and it's in the future.
    #   2) ``scheduled_start`` null/missing AND
    #      ``scheduled_date >= today`` (YYYY-MM-DD compare is safe
    #      even against legacy full-ISO ``scheduled_date`` values
    #      because ``2026-09-24`` < ``2026-09-24T…`` lexicographically
    #      still evaluates the truth correctly for same-day
    #      comparisons — see P47 test 3 for the invariant lock).
    #
    # The ``deleted_at`` guard uses ``$and`` explicitly so the two
    # top-level ``$or`` clauses don't collide (Mongo query grammar
    # only allows one ``$or`` at a level).
    now_iso = datetime.now(timezone.utc).isoformat()
    today_ymd = today  # already computed above as ``YYYY-MM-DD``
    next_job = await db.jobs.find_one(
        {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "status": {"$in": ["scheduled", "active", "pending",
                                 "requested"]},
            "$and": [
                {"$or": [
                    {"deleted_at": None},
                    {"deleted_at": {"$exists": False}},
                ]},
                {"$or": [
                    # Rung 1 — has a real scheduled_start ≥ now.
                    {"scheduled_start": {"$gte": now_iso}},
                    # Rung 2 — no scheduled_start; date ≥ today.
                    {"$and": [
                        {"$or": [
                            {"scheduled_start": None},
                            {"scheduled_start": ""},
                            {"scheduled_start": {"$exists": False}},
                        ]},
                        {"scheduled_date": {"$gte": today_ymd}},
                    ]},
                ]},
            ],
        },
        {"_id": 0},
        sort=[("scheduled_start", 1), ("scheduled_date", 1)],
    )
    next_service = None
    if next_job:
        scheduled = (
            next_job.get("scheduled_start")
            or next_job.get("scheduled_date")
            or next_job.get("scheduled_at")
        )
        # Defensive belt — the query guard should have already
        # excluded past rows, but leave the check so a schema drift
        # can't sneak one through.
        if scheduled and str(scheduled)[:10] >= today:
            next_service = {
                "job_id": next_job.get("id"),
                "date": str(scheduled)[:10],
                "scheduled_start": scheduled,
                "service_type": (
                    next_job.get("service_type")
                    or next_job.get("job_type")
                    or next_job.get("title")
                    or "Service visit"
                ),
                "title": next_job.get("title"),
            }

    return {
        "balance_due": round(balance_due, 2),
        "past_due": round(past_due, 2),
        "credit": round(credit, 2),
        "next_service": next_service,
        "breakdown": {
            "open_invoice_count": open_ct,
            "past_due_invoice_count": past_ct,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 3A · ACH · Stripe Financial Connections link session (stubbed wire)
# ═══════════════════════════════════════════════════════════════════════
class AchLinkSessionResp(BaseModel):
    ok: bool
    reason: Optional[str] = None
    client_secret: Optional[str] = None
    session_id: Optional[str] = None


def _stripe_key_is_placeholder(key: str) -> bool:
    """Return True when ``key`` is empty or a well-known placeholder
    that must NOT be sent to Stripe.

    Anything Stripe would reject as malformed before hitting network
    (empty prefix, quotes accidentally captured from ``.env``, blank
    string, etc.) counts as a placeholder.  This lets the frontend
    render a grey "Coming soon" button in dev environments where an
    admin hasn't wired real credentials yet, without incurring a
    round-trip that would time out anyway.
    """
    k = (key or "").strip().strip('"').strip("'")
    if not k:
        return True
    # Well-known placeholder shapes.  ``sk_test_`` / ``sk_live_`` with no
    # suffix means someone pasted only the prefix.
    if k in {"sk_test_", "sk_live_", "sk_test_placeholder",
              "sk_live_placeholder", "sk_placeholder", "your_key_here"}:
        return True
    # A real Stripe key is always at least ~30 chars after the prefix.
    # ``sk_test_`` = 8 chars, so anything shorter than 24 total can't be
    # a live/test secret.
    if len(k) < 24:
        return True
    return False


def _stripe_configured() -> bool:
    """Phase 47d · Feb-2026 — RESTORED after the Phase LZ4 retirement.

    User has directed every payment surface to route through Stripe
    directly. ACH capture via ``stripe.SetupIntent.create(
    payment_method_types=["us_bank_account"])`` doesn't require the
    Financial Connections product — the bank account is captured
    through Stripe Elements' ``PaymentElement`` (or via manual
    routing/account entry). This helper now reflects whether the
    Stripe SDK has a usable secret key available.
    """
    import os as _os
    return bool(
        _os.environ.get("STRIPE_SECRET_KEY_LIVE")
        or _os.environ.get("STRIPE_SECRET_KEY_TEST")
        or _os.environ.get("STRIPE_API_KEY")
    )


@router.post(
    "/customer-portal/payment-methods/ach/link-session",
    response_model=AchLinkSessionResp,
)
async def start_ach_link_session(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Create an ACH bank-verification session for the customer.

    Phase 47d · Feb-2026 — RESTORED. Wires directly to
    ``stripe.SetupIntent.create(payment_method_types=["us_bank_account"])``
    via the shared ``services.payments.stripe_charge`` helper. The
    frontend mounts Stripe's ``PaymentElement`` against the returned
    ``client_secret`` and handles the routing/account entry UX.
    """
    cid = _require_customer(user)
    if not _stripe_configured():
        return {"ok": False, "reason": "stripe_not_configured"}
    from services.payments import stripe_charge as stripe_svc
    try:
        out = await stripe_svc.create_setup_intent(
            tenant_id=tenant["id"],
            customer_id=cid,
            actor_user_id=user.get("id"),
            payment_method_types=["us_bank_account"],
        )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("phase47d").warning(
            "[phase47d] ACH SetupIntent failed for customer=%s: %s", cid, exc)
        return {"ok": False, "reason": "stripe_error"}
    return {
        "ok": True,
        "client_secret": out.get("client_secret"),
        "publishable_key": out.get("publishable_key"),
        "mode": out.get("mode"),
    }


class AchAttachIn(BaseModel):
    """Phase 47d · Feb-2026 — Stripe-direct ACH attach payload.

    The frontend posts this after ``stripe.confirmSetup`` returns a
    ``payment_method`` id from the ``PaymentElement`` (US bank account
    flow). We mirror the row into ``db.payment_methods`` via the same
    helper the card-attach flow uses so the "list payment methods"
    endpoint returns a unified view.
    """

    payment_method_id: str
    # Kept for backward compatibility with in-flight LZ4 clients that
    # were still POSTing the Financial-Connections shape. Ignored.
    stripe_bank_account_id: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/customer-portal/payment-methods/ach/attach")
async def attach_ach_result(
    body: AchAttachIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Persist a Stripe US-bank-account PaymentMethod into
    ``db.payment_methods`` via the shared attach helper. Charges are NOT
    moved here — the row lands with the standard PM shape and is later
    reconciled by the Stripe webhook if/when auto-verification completes.
    """
    cid = _require_customer(user)
    if not _stripe_configured():
        raise HTTPException(400, "stripe_not_configured")
    if not body.payment_method_id:
        raise HTTPException(422, "payment_method_id required")
    from services.payments import stripe_charge as stripe_svc
    try:
        row = await stripe_svc.attach_payment_method(
            tenant_id=tenant["id"],
            customer_id=cid,
            payment_method_id=body.payment_method_id,
            set_default=False,  # ACH default-flag stays admin-controlled.
        )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("phase47d").warning(
            "[phase47d] ACH attach failed for customer=%s: %s", cid, exc)
        raise HTTPException(502, "attach_failed")
    # Phase K13 · Feb-2026 — stamp the mirrored payment_methods row
    # with the impersonating admin's id so audit trails can attribute
    # the write.  Non-impersonated flows are unchanged.
    if user.get("is_impersonated"):
        await db.payment_methods.update_one(
            {"provider_payment_method_id": body.payment_method_id,
             "tenant_id": tenant["id"]},
            {"$set": {"via_impersonation": True,
                       "acting_admin_id": user.get("impersonator_id")}},
        )
    return {
        "ok": True,
        "payment_method": {
            "last4": row.get("last4") or "",
            "brand": row.get("brand") or "us_bank_account",
            "is_default": bool(row.get("is_default")),
            "type": "ach",
        },
    }


@router.get("/customer-portal/payment-methods")
async def list_payment_methods(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List all payment methods (card + ACH) the customer has on file.

    Feb-2026 · Task 5 — card rows now come from the
    ``db.payment_methods`` mirror written by ``attach_payment_method``
    on Stripe webhook receipt. This is the same collection used to
    render admin-side card lists — one source of truth per PM.

    Legacy ``customers.default_payment_method_id`` / ``pm_brand`` /
    ``pm_last4`` values still surface as a fallback single-card entry
    for tenants who haven't yet run through the new attach flow so
    upgrade doesn't blank existing card ledgers.
    """
    cid = _require_customer(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    out: List[Dict[str, Any]] = []

    # Fresh path — rows written by ``attach_payment_method``.
    card_rows = await db.payment_methods.find(
        {"tenant_id": tenant["id"], "customer_id": cid,
         "type": {"$ne": "ach"}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    seen_pm_ids: set = set()
    for row in card_rows:
        pm_id = row.get("provider_payment_method_id") or ""
        if pm_id in seen_pm_ids:
            continue
        seen_pm_ids.add(pm_id)
        out.append({
            "type": "card",
            "id": row.get("id") or pm_id,
            "provider_payment_method_id": pm_id,
            "brand": row.get("brand") or "Card",
            "last4": row.get("last4") or "",
            "exp_month": row.get("exp_month"),
            "exp_year": row.get("exp_year"),
            "verified": True,
            "default": bool(row.get("is_default")),
            "created_at": row.get("created_at"),
            "created_from_invoice_id":
                row.get("created_from_invoice_id"),
        })

    # Legacy fallback — pre-migration single-card view.
    if not card_rows and cust.get("default_payment_method_id"):
        out.append({
            "type": "card",
            "brand": cust.get("pm_brand") or "Card",
            "last4": cust.get("pm_last4") or "",
            "verified": True,
            "default": True,
        })

    ach_rows = await db.payment_methods.find(
        {"tenant_id": tenant["id"], "customer_id": cid, "type": "ach"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    for row in ach_rows:
        out.append({
            "type": "ach",
            "id": row.get("id"),
            "verified": bool(row.get("verified")),
            "stripe_bank_account_id": row.get("stripe_bank_account_id"),
            "created_at": row.get("created_at"),
        })
    return {"methods": out, "stripe_configured": _stripe_configured()}


# ═══════════════════════════════════════════════════════════════════════
# Task 5 · Feb-2026 — customer-owned remove / set-default endpoints.
# ═══════════════════════════════════════════════════════════════════════
# PCI SAQ A posture — we never touch raw card data. Removal detaches
# the PM from the Stripe customer via ``PaymentMethod.detach`` and
# splices the mirror row from Mongo. Stripe is the source of truth for
# vaulting; we only proxy the customer's intent + reflect the outcome.


@router.delete("/customer-portal/payment-methods/{pm_id}")
async def customer_remove_payment_method(
    pm_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    tid = tenant["id"]
    # Tenant + customer scoped read — no cross-tenant / cross-customer leak.
    row = await db.payment_methods.find_one(
        {"tenant_id": tid, "customer_id": cid,
         "$or": [{"id": pm_id},
                 {"provider_payment_method_id": pm_id}]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "payment_method_not_found")
    provider_pm_id = row.get("provider_payment_method_id") or ""
    if provider_pm_id and _stripe_configured():
        try:
            import stripe as _stripe
            import os as _os
            _stripe.api_key = _os.environ.get("STRIPE_SECRET_KEY") or ""
            _stripe.PaymentMethod.detach(provider_pm_id)
        except Exception:  # noqa: BLE001
            # Detach failure is non-fatal — Mongo is the customer view.
            pass
    await db.payment_methods.delete_one(
        {"tenant_id": tid, "customer_id": cid,
         "provider_payment_method_id": provider_pm_id},
    )
    remaining = await db.payment_methods.count_documents(
        {"tenant_id": tid, "customer_id": cid},
    )
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"saved_payment_methods_count": remaining}},
    )
    return {"removed": True, "remaining": remaining}


class SetDefaultBody(BaseModel):
    is_default: bool = True


@router.patch("/customer-portal/payment-methods/{pm_id}/set-default")
async def customer_set_default_payment_method(
    pm_id: str,
    body: Optional[SetDefaultBody] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    tid = tenant["id"]
    row = await db.payment_methods.find_one(
        {"tenant_id": tid, "customer_id": cid,
         "$or": [{"id": pm_id},
                 {"provider_payment_method_id": pm_id}]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "payment_method_not_found")
    provider_pm_id = row.get("provider_payment_method_id") or ""
    if not provider_pm_id:
        raise HTTPException(400, "payment_method_missing_provider_id")
    await db.payment_methods.update_many(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"is_default": False}},
    )
    await db.payment_methods.update_one(
        {"tenant_id": tid, "customer_id": cid,
         "provider_payment_method_id": provider_pm_id},
        {"$set": {"is_default": True}},
    )
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"stripe_default_payment_method_id": provider_pm_id}},
    )
    return {"default_payment_method_id": provider_pm_id}


# ═══════════════════════════════════════════════════════════════════════
# 3D · Service-request CTA — fires internal message + bell + push
# ═══════════════════════════════════════════════════════════════════════
class ServiceRequestIn(BaseModel):
    service_type: Optional[str] = None
    preferred_date: Optional[str] = None
    notes: Optional[str] = None
    # Phase 34 · Feb-2026 · Task I — customer-portal service requests
    # now capture a single free-text field instead of a Service Type
    # dropdown. ``request_details`` supersedes ``notes`` when both are
    # supplied; ``notes`` is preserved so mobile clients still on the
    # old schema keep working during the rollout window.
    request_details: Optional[str] = None


# Phase 34 · Feb-2026 · Task I — where staff notifications land when a
# customer submits a service request. Values here are the PLOFV tenant
# defaults; production should lift these to tenant settings under
# ``settings.notifications.service_request_email/sms`` so multi-tenant
# operators can point them at their own dispatchers.
# TODO — Phase 35 · promote these to per-tenant settings + admin UI.
_SERVICE_REQUEST_EMAIL_FALLBACK = "brian@plofv.com"
# Phase PHONE-PURGE · Feb-2026 — removed hardcoded plofv-internal
# SMS fallback. Service-request SMS now sources ONLY from
# ``tenant.settings.notifications.service_request_sms``. When
# unset, the SMS branch short-circuits with an info log (see the
# service-request handler below) so we never dial a stale number.


def _resolve_service_request_email(tenant: Dict[str, Any]) -> str:
    notif = ((tenant or {}).get("settings") or {}).get("notifications") or {}
    return (notif.get("service_request_email")
            or _SERVICE_REQUEST_EMAIL_FALLBACK)


def _resolve_service_request_sms(tenant: Dict[str, Any]) -> str:
    """Return the tenant's configured service-request SMS number,
    or an empty string when unset. Callers MUST guard on the empty
    return value before invoking the SMS adapter — Phase PHONE-PURGE
    removed the hardcoded plofv-internal fallback so a
    misconfigured tenant now silently skips SMS rather than dialing
    a stale internal line."""
    notif = ((tenant or {}).get("settings") or {}).get("notifications") or {}
    return notif.get("service_request_sms") or ""


def _fmt_service_request_body(
    customer_name: str,
    address: str,
    service_type: Optional[str],
    preferred_date: Optional[str],
    notes: Optional[str],
) -> str:
    """Build the human-readable message body the admin sees in the inbox.

    Kept compact — the internal-messages UI truncates aggressively, so
    front-load the who + what.
    """
    lines = [
        f"New service request from {customer_name}.",
        f"Service: {service_type or 'Not specified'}",
    ]
    if preferred_date:
        lines.append(f"Preferred date: {preferred_date}")
    if address:
        lines.append(f"Address: {address}")
    if (notes or "").strip():
        lines.append("")
        lines.append("Notes:")
        lines.append(notes.strip())
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# Phase 34 · Task N · Feb-2026 — Editable customer profile
# ══════════════════════════════════════════════════════════════════════
class PatchMyProfileIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


def _normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return raw.strip() or None


def _valid_email(e: str) -> bool:
    import re as _re
    return bool(_re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (e or "").strip()))


@router.patch("/customer-portal/profile")
async def patch_my_profile(
    body: PatchMyProfileIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task N · Feb 2026 — customers edit their own contact info.

    Patches ``users`` + ``customers`` + mirrors the change onto the
    linked ``contacts`` record so the admin CRM view reflects the
    edit in real time. Writes an audit-log row and returns the merged
    profile view.

    Validation rules (server is source of truth — frontend just gives
    quick feedback):
      * ``first_name`` / ``last_name`` — if provided, ≥1 char each.
      * ``email`` — valid RFC-lite format AND must not collide with
        any OTHER user's email (uniqueness enforced globally).
      * ``phone`` — must produce a 10- or 11-digit number; normalized
        to E.164 (``+1XXXXXXXXXX``) before persistence.
      * ``address`` — ≥5 chars.
    """
    cid = _require_customer(user)

    patch_user: Dict[str, Any] = {}
    patch_cust: Dict[str, Any] = {}

    if body.first_name is not None:
        fn = (body.first_name or "").strip()
        if not fn:
            raise HTTPException(400, "First name is required.")
        patch_user["first_name"] = fn
        patch_cust["first_name"] = fn
    if body.last_name is not None:
        ln = (body.last_name or "").strip()
        if not ln:
            raise HTTPException(400, "Last name is required.")
        patch_user["last_name"] = ln
        patch_cust["last_name"] = ln
    if patch_user.get("first_name") or patch_user.get("last_name"):
        full = " ".join(x for x in [patch_user.get("first_name") or user.get("first_name"),
                                      patch_user.get("last_name") or user.get("last_name")]
                         if x).strip()
        if full:
            patch_user["name"] = full
            patch_cust["name"] = full

    if body.email is not None:
        em = (body.email or "").strip().lower()
        if not _valid_email(em):
            raise HTTPException(400, "Please enter a valid email address.")
        collision = await db.users.find_one(
            {"email": em, "id": {"$ne": user["id"]}}, {"_id": 0, "id": 1}
        )
        if collision:
            raise HTTPException(409, "That email is already in use.")
        patch_user["email"] = em
        patch_cust["email"] = em

    if body.phone is not None:
        p_norm = _normalize_phone(body.phone or "")
        if not p_norm or len("".join(c for c in p_norm if c.isdigit())) < 10:
            raise HTTPException(400, "Please enter a valid phone number.")
        patch_user["phone"] = p_norm
        patch_cust["phone"] = p_norm

    if body.address is not None:
        addr = (body.address or "").strip()
        if len(addr) < 5:
            raise HTTPException(400, "Address is required.")
        patch_cust["address"] = addr

    if not patch_user and not patch_cust:
        raise HTTPException(400, "No changes provided.")

    now = now_iso()

    # BEFORE snapshot for audit + diff.
    before_cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ) or {}
    before_user = await db.users.find_one(
        {"id": user["id"]}, {"_id": 0, "password_hash": 0}
    ) or {}

    if patch_user:
        patch_user["updated_at"] = now
        await db.users.update_one({"id": user["id"]}, {"$set": patch_user})
    if patch_cust:
        patch_cust["updated_at"] = now
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"$set": patch_cust}
        )

    # Contacts mirror — the admin CRM Contact page keeps a shadow copy
    # of the customer's contact info. Best-effort update; missing
    # collection or no matching row is not fatal.
    try:
        contact_patch = {**{k: v for k, v in patch_cust.items()
                             if k in ("first_name", "last_name", "name",
                                      "email", "phone", "address")},
                          "updated_at": now,
                          "updated_by": "customer_self_serve"}
        if contact_patch:
            await db.contacts.update_many(
                {"tenant_id": tenant["id"],
                 "$or": [
                     {"customer_id": cid},
                     {"email": (before_cust.get("email") or "").lower()},
                     {"email": patch_cust.get("email")},
                 ]},
                {"$set": contact_patch},
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("[task-n] contacts mirror failed: %s", exc)

    # Audit log — always write, non-fatal on failure.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user["id"],
            "actor_customer_id": cid,
            "event": "self_updated_profile",
            "diff": {
                "before": {k: before_cust.get(k) or before_user.get(k)
                             for k in set(patch_user) | set(patch_cust)},
                "after": {**patch_user, **patch_cust},
            },
            "created_at": now,
        })
    except Exception as exc:  # pragma: no cover
        logger.warning("[task-n] audit write failed: %s", exc)

    # Realtime broadcast so admin CRM views auto-refresh.
    try:
        from routers.realtime import bus
        await bus.broadcast(
            f"tenant:{tenant['id']}",
            {"type": "customer_profile_updated",
             "payload": {"customer_id": cid, "user_id": user["id"]}},
        )
    except Exception:
        pass

    merged = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1,
         "email": 1, "phone": 1, "address": 1},
    ) or {}
    return {"ok": True, "profile": merged}


@router.post("/customer-portal/service-requests")
async def create_service_request(
    body: ServiceRequestIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Customer taps "Request Service" → four effects fire:

    1. **Internal direct message** inserted into ``db.messages``.
    2. **Bell notifications** enqueued for every admin/super_admin.
    3. **Expo push** best-effort to every admin device.
    4. **Email to Brian + SMS to the operations line** (Phase 34 ·
       Task I). Both are wrapped in try/except so a failed email
       does not block the SMS and vice versa. Destinations resolve
       from ``tenant.settings.notifications.service_request_email
       / _sms`` with a hardcoded PLOFV fallback.

    Effects 2–4 are best-effort — transport failures never block the
    write. Effect 1 is authoritative: without the message doc the
    admin has nothing to open, so a persistence failure returns 500.
    """
    cid = _require_customer(user)

    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    # Feb-2026 · Phase F1 (P0-A) — SMS crosswire hardening.
    # ``customer_name`` and ``customer_phone`` in the outgoing SMS
    # MUST come from the customer row addressed by ``cid`` (which is
    # ``_require_customer(user)`` → ``user['customer_id']``). Any
    # drift between the session's ``customer_id`` and the actual
    # customer row is an internal invariant violation (bad token,
    # tenant leak, or seed corruption) — refuse to send instead of
    # broadcasting a mislabelled SMS to the ops line. 500 (not 400)
    # because the CLIENT did nothing wrong.
    if not cust:
        raise HTTPException(404, "Customer profile not found")
    if user.get("customer_id") and user["customer_id"] != cust.get("id"):
        logger.error(
            "service_request identity_drift session_customer_id=%s "
            "row_customer_id=%s tenant=%s",
            user.get("customer_id"), cust.get("id"), tenant["id"],
        )
        raise HTTPException(500, "Customer identity mismatch")
    # Strict single-source resolution — no fallbacks to ``user.*``.
    # Historically ``customer_name`` fell back to ``user.get("name")``
    # first, which meant a stale session paired with a fresh customer
    # row would ship the SMS with the wrong name attached to the
    # right phone (crosswire). Reading strictly from ``cust`` closes
    # that gap and ties the SMS identity to the customer row of
    # record for every request.
    customer_name = cust.get("name") or "Customer"
    customer_phone = (
        cust.get("phone")
        or cust.get("primary_phone")
        or ""
    )
    customer_email = cust.get("email") or ""
    address = (
        cust.get("address")
        or cust.get("street_address")
        or (cust.get("property") or {}).get("address")
        or ""
    )

    # Phase 34 · Task I — ``request_details`` is the new free-text
    # payload. Fall back to legacy ``notes`` when older clients still
    # POST that field so we don't break in-flight mobile builds.
    request_details = (
        (body.request_details or "").strip()
        or (body.notes or "").strip()
        or None
    )
    # ``service_type`` is now optional. Default to ``general_request``
    # server-side so downstream dashboards + auto-assign rules never
    # crash on a missing category.
    service_type = (body.service_type or "").strip() or "general_request"
    preferred_date = (body.preferred_date or "").strip() or None
    notes = request_details  # kept for backwards-compat consumers

    text = _fmt_service_request_body(
        customer_name=customer_name,
        address=address,
        service_type=service_type,
        preferred_date=preferred_date,
        notes=notes,
    )

    msg_id = new_id()
    msg_doc = {
        "id": msg_id,
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "sender": "customer",
        "sender_name": customer_name,
        "text": text,
        "kind": "service_request",
        "service_request": {
            "service_type": service_type,
            "preferred_date": preferred_date,
            "notes": notes,
            "request_details": request_details,
            "address": address,
        },
        "read_by_customer": True,
        "read_by_staff": False,
        "created_at": now_iso(),
    }
    await db.messages.insert_one(msg_doc)
    msg_doc.pop("_id", None)

    # ─── Bell + realtime + Expo push ─── best-effort, never raise.
    push_results: List[Dict[str, Any]] = []
    bell_ids: List[str] = []
    email_result: Dict[str, Any] = {"provider_status": "skipped"}
    sms_result: Dict[str, Any] = {"provider_status": "skipped"}
    try:
        from services.notifications import enqueue_for_tenant_admins

        title = f"Service request from {customer_name}"
        summary = (service_type or "Service request") + (
            f" · {preferred_date}" if preferred_date else ""
        )
        href = f"/communication/{cid}"
        bell_ids = await enqueue_for_tenant_admins(
            tenant["id"],
            kind="inbound_customer_message",
            title=title,
            body=summary,
            source_ref={
                "kind": "service_request",
                "message_id": msg_id,
                "customer_id": cid,
            },
            href=href,
            priority="normal",
        )
    except Exception as exc:  # pragma: no cover — logged, never blocks the ack
        logger.warning("service_request bell enqueue failed: %s", exc)

    # Realtime broadcast so any admin with the inbox open sees the row
    # arrive without polling.
    try:
        from routers.realtime import bus

        admins = await db.users.find(
            {
                "tenant_id": tenant["id"],
                "role": {"$in": ["admin", "super_admin"]},
            },
            {"_id": 0, "id": 1},
        ).to_list(200)
        payload = {
            "type": "service_request",
            "payload": {
                "customer_id": cid,
                "customer_name": customer_name,
                "service_type": service_type,
                "preferred_date": preferred_date,
                "message_id": msg_id,
            },
        }
        for a in admins:
            if a.get("id"):
                try:
                    await bus.broadcast(a["id"], payload)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("service_request realtime broadcast failed: %s", exc)

    # Expo push — silent no-op when the transport isn't wired.
    try:
        from routers.mobile_push import send_push_to_user

        admin_ids = await db.users.find(
            {
                "tenant_id": tenant["id"],
                "role": {"$in": ["admin", "super_admin"]},
            },
            {"_id": 0, "id": 1},
        ).to_list(200)
        push_title = "New service request"
        push_body = f"{customer_name} — {service_type or 'Service request'}"
        for a in admin_ids:
            if not a.get("id"):
                continue
            try:
                r = await send_push_to_user(
                    a["id"],
                    push_title,
                    push_body,
                    data={
                        "kind": "service_request",
                        "message_id": msg_id,
                        "customer_id": cid,
                    },
                )
                push_results.append({"user_id": a["id"], **(r or {})})
            except Exception as exc:
                push_results.append(
                    {"user_id": a["id"], "pushed": False, "reason": str(exc)[:120]}
                )
    except Exception as exc:
        logger.warning("service_request push fan-out failed: %s", exc)

    # ─── Phase 34 · Task I — Email + SMS notifications ───────────
    # Isolated try/except per channel so one transport failure never
    # blocks the other AND never masks the customer's success ack.
    to_email = _resolve_service_request_email(tenant)
    to_sms = _resolve_service_request_sms(tenant)
    request_short = (request_details or "").strip()[:140]
    deep_link = f"/communication/{cid}"

    try:
        from services.email.resend_adapter import send as _send_email

        # Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render.
        # Prefer the ``portal_service_request_admin_email`` row in
        # ``marketing_templates`` (tenant-specific > global default);
        # fall through to the hardcoded body below when the row is
        # absent OR the render fails.  ``TENANT_SERVICE_REQUEST_PHONE``
        # threads ``_resolve_service_request_sms(tenant)`` — empty
        # string when unset per the PHONE-PURGE invariant.
        subject_default = f"New Service Request from {customer_name}"
        app_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
        full_link = f"{app_url}{deep_link}" if app_url else ""
        subject = subject_default
        html_body: str = ""
        try:
            from services.marketing_template_lookup import (
                get_template_with_global_fallback,
            )
            from services.marketing.merge_tags import render_template
            tpl = await get_template_with_global_fallback(
                "portal_service_request_admin_email",
                (tenant or {}).get("id") or None,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "service_request template lookup failed — using "
                "hardcoded fallback: %s", exc,
            )
            tpl = None
        if tpl and tpl.get("body"):
            try:
                ctx = {
                    "tenant": tenant or {},
                    "customer_name": customer_name,
                    "customer_email": customer_email or "",
                    "customer_phone": customer_phone or "",
                    "property_address": address or "",
                    "service_type": (body.service_type or ""),
                    "preferred_date": preferred_date or "",
                    "request_details": (
                        (request_details or "No details provided").strip()
                    ),
                    "view_request_link": full_link,
                    "tenant_service_request_phone": to_sms or "",
                }
                rendered_subject, _ = render_template(
                    tpl.get("subject") or subject_default, ctx,
                    missing="empty",
                )
                rendered_body, _ = render_template(
                    tpl["body"], ctx, missing="empty",
                )
                if rendered_body:
                    subject = rendered_subject or subject_default
                    html_body = rendered_body
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "service_request template render failed — using "
                    "hardcoded fallback: %s", exc,
                )
                html_body = ""
        if not html_body:
            html_parts = [
                "<div style=\"font-family:-apple-system,'Inter',sans-serif;"
                "color:#0F172A;max-width:640px;margin:0 auto;padding:24px;\">",
                f"<h2 style=\"margin:0 0 12px;\">New Service Request</h2>",
                f"<p style=\"margin:0 0 4px;\"><b>Customer:</b> {customer_name}</p>",
            ]
            if customer_email:
                html_parts.append(
                    f"<p style=\"margin:0 0 4px;\"><b>Email:</b> "
                    f"<a href=\"mailto:{customer_email}\">{customer_email}</a></p>"
                )
            if customer_phone:
                html_parts.append(
                    f"<p style=\"margin:0 0 4px;\"><b>Phone:</b> "
                    f"<a href=\"tel:{customer_phone}\">{customer_phone}</a></p>"
                )
            if address:
                html_parts.append(
                    f"<p style=\"margin:0 0 4px;\"><b>Address:</b> {address}</p>"
                )
            if preferred_date:
                html_parts.append(
                    f"<p style=\"margin:0 0 4px;\"><b>Preferred date:</b> "
                    f"{preferred_date}</p>"
                )
            html_parts.append(
                "<hr style=\"border:none;border-top:1px solid #E2E8F0;"
                "margin:16px 0;\"/>"
            )
            html_parts.append(
                f"<div style=\"white-space:pre-wrap;font-size:15px;"
                f"line-height:1.5;\">{(request_details or 'No details provided').strip()}</div>"
            )
            if full_link:
                html_parts.append(
                    f"<p style=\"margin:20px 0 0;\">"
                    f"<a href=\"{full_link}\" style=\"display:inline-block;"
                    f"background:#0284C7;color:#fff;padding:10px 16px;"
                    f"border-radius:8px;text-decoration:none;font-weight:600;\">"
                    f"View request</a></p>"
                )
            html_parts.append("</div>")
            html_body = "".join(html_parts)
        email_result = await _send_email(
            to=to_email,
            subject=subject,
            html=html_body,
            category="transactional",
            tenant_id=tenant["id"],
            customer_id=cid,
        )
        logger.info(
            "service_request email_sent to=%s status=%s attempts=%s",
            to_email,
            email_result.get("provider_status"),
            email_result.get("attempts"),
        )
    except Exception as exc:  # pragma: no cover — never blocks the ack
        logger.warning("service_request email send failed: %s", exc)
        email_result = {"provider_status": "failed", "error": str(exc)[:200]}

    try:
        from services.sms.rc_adapter import send as _send_sms

        # Phase PHONE-PURGE · Feb-2026 — skip SMS entirely when the
        # tenant has not configured a service-request SMS recipient.
        # No hardcoded fallback: a misconfigured tenant sees an info
        # log and the email path (fired above) is still their notice.
        if not to_sms:
            logger.info(
                "service_request sms_skipped — no tenant.settings."
                "notifications.service_request_sms configured for "
                "tenant=%s", tenant.get("id"),
            )
            sms_result = {"provider_status": "skipped",
                          "reason": "no_tenant_sms_configured"}
        else:
            sms_short = request_short + ("…" if request_details and len(request_details) > 140 else "")
            sms_body = (
                f"New service request from {customer_name}"
                + (f" ({customer_phone})" if customer_phone else "")
                + f": {sms_short}"
                + (f" View: {deep_link}" if deep_link else "")
            )
            sms_result = await _send_sms(
                to=to_sms,
                body=sms_body,
                category="transactional",
                tenant_id=tenant["id"],
                customer_id=cid,
            )
            logger.info(
                "service_request sms_sent to=%s status=%s attempts=%s",
                to_sms,
                sms_result.get("provider_status"),
                sms_result.get("attempts"),
            )
    except Exception as exc:  # pragma: no cover — never blocks the ack
        logger.warning("service_request sms send failed: %s", exc)
        sms_result = {"provider_status": "failed", "error": str(exc)[:200]}

    return {
        "ok": True,
        "message_id": msg_id,
        "message": msg_doc,
        "notified_admins": len(bell_ids),
        "push_results": push_results,
        "email_notification": {
            "to": to_email,
            "status": email_result.get("provider_status"),
        },
        "sms_notification": {
            "to": to_sms,
            "status": sms_result.get("provider_status"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Priority 3 — Autobilling opt-in.
# ═══════════════════════════════════════════════════════════════════════
# Ship pairs with the ``save-on-first-payment`` addendum: after the
# customer completes checkout with ``save_for_future_billing=true``,
# ``/portal/payment-complete`` surfaces a CTA that lands here to flip
# ``customers.autobilling_enabled`` true. The recurring-billing runner
# (``services.finances.run_daily_autobilling``) checks the flag before
# auto-charging future invoices to the saved default payment method.
#
# Endpoint scope: portal-authenticated customer flipping their OWN
# opt-in flag. Admin-side toggling is out of scope for this ship (the
# admin billing-plans page owns that lever).
@router.get("/customer-portal/autobilling")
async def get_autobilling_status(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the caller's autobilling opt-in flag + whether they
    have a default payment method on file. Frontend uses this to
    decide whether the CTA on ``/portal/payment-complete`` is
    actionable (needs a saved PM) and whether it should even
    render (already opted in → no-op)."""
    cid = _require_customer(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "autobilling_enabled": 1,
          "default_payment_method_id": 1},
    ) or {}
    return {
        "autobilling_enabled": bool(cust.get("autobilling_enabled")),
        "has_default_payment_method": bool(
            cust.get("default_payment_method_id")
        ),
    }


@router.post("/customer-portal/autobilling/enable")
async def enable_autobilling(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Flip ``customers.autobilling_enabled`` to true for the caller.
    Requires a saved default payment method — 409 otherwise so the
    frontend can nudge the customer to the Add-card flow instead of
    landing them on a silent no-op.
    """
    cid = _require_customer(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "autobilling_enabled": 1,
          "default_payment_method_id": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    if not cust.get("default_payment_method_id"):
        raise HTTPException(
            409,
            "no_default_payment_method",
        )
    # Idempotent — repeated CTA clicks resolve as ok=true and
    # ``changed=false`` so double-tap on a flaky connection stays safe.
    already_on = bool(cust.get("autobilling_enabled"))
    if not already_on:
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {
                "autobilling_enabled": True,
                "autobilling_enabled_at": now_iso(),
            }},
        )
    return {
        "ok": True,
        "autobilling_enabled": True,
        "changed": not already_on,
    }


@router.post("/customer-portal/autobilling/disable")
async def disable_autobilling(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Opt-out. Mirrors ``enable`` — idempotent, returns the terminal
    state. Kept alongside the enable endpoint so the portal-side
    settings page (future ship) has both levers ready to wire."""
    cid = _require_customer(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "autobilling_enabled": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    already_off = not bool(cust.get("autobilling_enabled"))
    if not already_off:
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {
                "autobilling_enabled": False,
                "autobilling_disabled_at": now_iso(),
            }},
        )
    return {
        "ok": True,
        "autobilling_enabled": False,
        "changed": not already_off,
    }
