"""Phase 4B · Stripe Live Payments — canonical PaymentIntent + refund
router (user-facing spec).

Endpoints exposed under ``/api``:

    POST /api/payments/create-payment-intent   authenticated OR magic-link
    POST /api/payments/refund                  admin OR manager
    GET  /api/payments/{payment_intent_id}     status lookup (owner/admin)
    POST /api/dev/stripe-config-check          admin — smoke test
    GET  /api/config/public                    public — pk_live + mode
    GET  /api/invoices/{iid}/magic-link        admin — issue portal token

Money-moving contract
=====================
* All amounts are integer cents end-to-end. Client-supplied amounts are
  *ignored* — the payable amount is resolved from the invoice row
  server-side (`total` − `amount_paid`).
* Idempotency keys are attached to every Stripe write:
    * PaymentIntent  →  ``pi:{invoice_id}:{attempt_counter}``
    * Refund         →  ``rf:{payment_intent_id}:{amount_cents}``
* Every successful create records a ``stripe_payments_live`` ledger row
  (separate from the pre-existing Phase-53 ``stripe_payments`` ledger to
  avoid entangling the two flows).

Roles
=====
* create-payment-intent: authenticated user (customer owning the
  invoice, admin, or super_admin) OR a valid magic-link token.
* refund: admin, super_admin, or manager.
* config-check: admin, super_admin.

Never echoes secret / webhook / account values in responses or logs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from config import JWT_ALGO, JWT_SECRET, db, logger
from routers.tenants import get_current_tenant
from services.stripe_client import get_stripe, is_configured, mode
from utils import deny_impersonation, get_current_user, new_id, now_iso

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def assert_cents(x) -> int:
    """Guard against floats leaking into the money boundary."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise ValueError("amount must be an integer number of cents")
    if x < 0:
        raise ValueError("amount must be non-negative")
    return x


def _dollars_to_cents(v) -> int:
    return int(round(float(v or 0) * 100))


def _mask_key(k: str) -> str:
    if not k or len(k) < 8:
        return "***"
    return f"{k[:7]}…{k[-4:]}"


def _mode() -> str:
    return mode() or "none"


def _outstanding_cents(inv: dict) -> int:
    total = _dollars_to_cents(inv.get("total"))
    paid = _dollars_to_cents(inv.get("amount_paid"))
    return max(total - paid, 0)


def _payable_states(inv: dict) -> bool:
    """Slice-2a: payable = status in {sent, partially_paid, overdue} AND balance > 0.
    We also accept legacy 'unpaid'/'partial' aliases used elsewhere in the
    codebase, and honour 'draft' as *not* payable. Anything already 'paid'
    or 'voided' is not payable."""
    status = (inv.get("status") or "").lower()
    pstatus = (inv.get("payment_status") or "").lower()
    if pstatus in ("paid", "refunded", "voided"):
        return False
    # Draft invoices aren't payable.
    if status in ("draft", "voided"):
        return False
    return _outstanding_cents(inv) > 0


def _issue_invoice_magic_token(invoice_id: str, tenant_id: str, days: int = 30) -> str:
    payload = {
        "sub": "invoice_pay",
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _verify_invoice_magic_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Magic link expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid magic link")
    if payload.get("sub") != "invoice_pay" or not payload.get("invoice_id"):
        raise HTTPException(401, "Invalid magic link")
    return payload


async def _load_invoice_anytenant(invoice_id: str) -> Optional[dict]:
    return await db.quotes.find_one({"id": invoice_id, "doc_type": "invoice"}, {"_id": 0})


async def _load_invoice_scoped(invoice_id: str, tenant_id: str) -> dict:
    doc = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Invoice not found")
    return doc


def _authorize_pay(user: dict, inv: dict) -> None:
    role = (user or {}).get("role") or ""
    if role in ("admin", "super_admin"):
        return
    if role == "customer":
        if inv.get("customer_id") == (user or {}).get("customer_id"):
            return
        raise HTTPException(403, "You can only pay your own invoices")
    raise HTTPException(403, "Not authorized to initiate payments")


def _require_admin_or_manager(user: dict) -> None:
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Refunds require admin or manager role")


# ──────────────────────────────────────────────────────────────────────
# GET /api/config/public — expose non-secret runtime config
# ──────────────────────────────────────────────────────────────────────
@router.get("/config/public")
async def config_public():
    """Publicly-consumable runtime config. NEVER echoes secret keys."""
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY") or ""
    return {
        "stripe_publishable_key": pk,
        "stripe_mode": _mode() if pk else "none",
        "app_public_url": os.getenv("APP_PUBLIC_URL") or "",
    }


# ──────────────────────────────────────────────────────────────────────
# POST /api/dev/stripe-config-check — admin smoke test (no secrets)
# ──────────────────────────────────────────────────────────────────────
@router.post("/dev/stripe-config-check")
async def stripe_config_check(user: dict = Depends(get_current_user)):
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    sk = os.getenv("STRIPE_SECRET_KEY") or ""
    ws = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY") or ""
    aid = os.getenv("STRIPE_ACCOUNT_ID") or ""
    ready = bool(sk and ws and pk)
    aid_masked = (f"{aid[:6]}…{aid[-4:]}" if aid and len(aid) >= 10 else (aid or None))
    hint = (os.getenv("APP_PUBLIC_URL") or "").rstrip("/") + "/api/webhooks/stripe"
    return {
        "mode": _mode(),
        "has_secret": bool(sk),
        "has_webhook_secret": bool(ws),
        "has_publishable": bool(pk),
        "account_id_masked": aid_masked,
        "ready": ready,
        "webhook_endpoint_hint": hint,
    }


# ──────────────────────────────────────────────────────────────────────
# POST /api/dev/stripe-live-ping — round-trip auth against live Stripe
# ──────────────────────────────────────────────────────────────────────
@router.post("/dev/stripe-live-ping")
async def stripe_live_ping(user: dict = Depends(get_current_user)):
    """Admin-only Stripe key round-trip health-check.

    Calls ``stripe.Account.retrieve()`` with the loaded ``sk_live`` and
    returns a sanitized status. Returns HTTP 200 in both success + failure
    so monitoring tools can diff the ``ok`` field directly. Never echoes
    ``sk_``, ``whsec_``, or ``rk_`` prefixed values in the response.
    """
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    if not is_configured():
        return {
            "ok": False,
            "error_type": "not_configured",
            "error_message": "Stripe SDK is not configured (STRIPE_SECRET_KEY missing).",
            "mode": _mode(),
        }
    stripe = get_stripe()
    try:
        acct = stripe.Account.retrieve()
    except Exception as exc:
        # Sanitize the message so we never accidentally leak the key
        # (Stripe's error text sometimes echoes the key prefix + last 4).
        raw = str(exc)
        for banned in ("sk_live_", "sk_test_", "rk_live_", "rk_test_", "whsec_"):
            raw = raw.replace(banned, banned[:3] + "…")
        etype = type(exc).__name__
        logger.warning(f"[phase4b] stripe-live-ping failed: {etype}")
        return {
            "ok": False,
            "error_type": etype,
            "error_message": raw[:400],
            "mode": _mode(),
        }
    # dict-vs-object indirection so unit tests can pass either shape.
    def _get(o, k, d=None):
        if isinstance(o, dict):
            return o.get(k, d)
        return getattr(o, k, d)
    return {
        "ok": True,
        "account_id": _get(acct, "id"),
        "account_country": _get(acct, "country"),
        "charges_enabled": bool(_get(acct, "charges_enabled")),
        "payouts_enabled": bool(_get(acct, "payouts_enabled")),
        "details_submitted": bool(_get(acct, "details_submitted")),
        "mode": _mode(),
    }


# ──────────────────────────────────────────────────────────────────────
# POST /api/dev/stripe-key-health-run — manual invocation of the daily
#                                        scheduled health scan.
# ──────────────────────────────────────────────────────────────────────
@router.post("/dev/stripe-key-health-run")
async def stripe_key_health_run(user: dict = Depends(get_current_user)):
    """Admin-only. Invokes the same scan the daily cron runs and returns
    an inspection-friendly summary. Reuses the 4-hour idempotency guard
    — a repeat trigger within 4h returns ``cooldown_active=true`` and
    does NOT fire a fresh email/SMS burst."""
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    logger.info(f"[stripe-key-alert] manual run by user={user.get('id')}")
    from services.stripe_key_health import run_stripe_key_health_scan
    res = await run_stripe_key_health_scan()
    ran_at = now_iso()
    if res.get("skipped"):
        return {"ran_at": ran_at, "skipped": True,
                 "reason": "stripe mode is not live"}
    return {
        "ran_at": ran_at,
        "ping": res.get("ping"),
        "alert_fanned_out": bool(res.get("alerted")),
        "deliveries_created": {
            "email": int(res.get("email_sent") or 0),
            "sms": int(res.get("sms_sent") or 0),
        },
        "cooldown_active": bool(res.get("cooldown_active")),
        "cooldown_expires_at": res.get("cooldown_expires_at"),
    }


# ──────────────────────────────────────────────────────────────────────
# GET /api/invoices/{iid}/magic-link — admin issues portal token
# ──────────────────────────────────────────────────────────────────────
@router.get("/invoices/{iid}/magic-link")
async def issue_invoice_magic_link(
    iid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if (user or {}).get("role") not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Admin or manager only")
    await _load_invoice_scoped(iid, tenant["id"])
    token = _issue_invoice_magic_token(iid, tenant["id"])
    base = (os.getenv("APP_PUBLIC_URL") or "").rstrip("/")
    return {
        "magic_token": token,
        "expires_days": 30,
        "url": f"{base}/pay/invoice/{iid}?token={token}" if base else None,
    }


# ──────────────────────────────────────────────────────────────────────
# GET /api/invoices/{iid}/full-magic?token=… — public viewer for magic-link
# ──────────────────────────────────────────────────────────────────────
@router.get("/invoices/{iid}/full-magic")
async def invoice_full_magic(iid: str, token: str = ""):
    """Public — no auth. Returns the same shape as
    ``GET /api/invoices/{iid}/full`` after verifying the magic token
    matches the invoice."""
    if not token:
        raise HTTPException(401, "Magic token required")
    payload = _verify_invoice_magic_token(token)
    if payload.get("invoice_id") != iid:
        raise HTTPException(401, "Magic token / invoice mismatch")
    tenant = await db.tenants.find_one({"id": payload["tenant_id"]}, {"_id": 0})
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    # Reuse the pre-existing aggregator so the payload shape stays
    # identical to the authenticated ``/full`` response.
    from routers.invoice_viewer import _build_viewer_payload
    # Synthesise an admin-like user so the aggregator's RBAC guard
    # (403 for tech, 404 for wrong customer) is bypassed — the magic
    # token already established ownership.
    virt_user = {"role": "admin", "id": "magic-link"}
    return await _build_viewer_payload(iid, tenant, virt_user)


class CreatePIBody(BaseModel):
    invoice_id: str
    source: str = Field(..., description="portal | authenticated")
    magic_token: Optional[str] = None
    # `amount_cents` is intentionally accepted but IGNORED. Present so
    # older clients don't 422. Server resolves amount from the invoice.
    amount_cents: Optional[int] = None


@router.post("/payments/create-payment-intent")
async def create_payment_intent(
    body: CreatePIBody,
    request: Request,
):
    if not is_configured():
        raise HTTPException(503, "Stripe not configured")

    inv: dict
    tenant_id: str

    if body.source == "portal":
        if not body.magic_token:
            raise HTTPException(401, "Magic token required for portal source")
        payload = _verify_invoice_magic_token(body.magic_token)
        if payload.get("invoice_id") != body.invoice_id:
            raise HTTPException(401, "Magic token / invoice mismatch")
        loaded = await db.quotes.find_one(
            {"id": body.invoice_id, "tenant_id": payload["tenant_id"], "doc_type": "invoice"},
            {"_id": 0},
        )
        if not loaded:
            raise HTTPException(404, "Invoice not found")
        inv = loaded
        tenant_id = payload["tenant_id"]
    else:
        # Authenticated path — decode the bearer token manually so we
        # can share a single endpoint with the magic-link branch.
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "Authentication required")
        token = auth.split(" ", 1)[1].strip()
        try:
            claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token expired")
        except jwt.PyJWTError:
            raise HTTPException(401, "Invalid token")
        u = await db.users.find_one({"id": claims.get("sub")}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(401, "User not found")
        act = (claims.get("act") or {})
        if act.get("sub"):
            u["is_impersonated"] = True
        deny_impersonation(u)
        # Resolve tenant via X-Tenant-Slug or user's default tenant.
        slug = request.headers.get("X-Tenant-Slug") or ""
        t = None
        if slug:
            t = await db.tenants.find_one({"slug": slug}, {"_id": 0})
        if not t and u.get("tenant_id"):
            t = await db.tenants.find_one({"id": u["tenant_id"]}, {"_id": 0})
        if not t:
            # fall back to invoice's tenant if the user's tenant is
            # ambiguous (customers created before multi-tenant may lack
            # ``tenant_id`` on the user row).
            candidate = await _load_invoice_anytenant(body.invoice_id)
            if candidate:
                t = await db.tenants.find_one({"id": candidate.get("tenant_id")}, {"_id": 0})
        if not t:
            raise HTTPException(400, "Tenant not resolved")
        inv = await _load_invoice_scoped(body.invoice_id, t["id"])
        _authorize_pay(u, inv)
        tenant_id = t["id"]

    if not _payable_states(inv):
        raise HTTPException(400, "Invoice is not in a payable state")
    amt_cents = assert_cents(_outstanding_cents(inv))
    if amt_cents <= 0:
        raise HTTPException(400, "Invoice has no outstanding balance")

    currency = (inv.get("currency") or "usd").lower()

    # Per-invoice attempt counter for idempotency-key rotation.
    attempts_before = await db.stripe_payments_live.count_documents(
        {"invoice_id": inv["id"], "tenant_id": tenant_id, "kind": "payment_intent"},
    )
    idem_key = f"pi:{inv['id']}:{attempts_before + 1}"

    stripe = get_stripe()
    try:
        pi = stripe.PaymentIntent.create(
            amount=amt_cents,
            currency=currency,
            automatic_payment_methods={"enabled": True},
            metadata={
                "tenant_id": tenant_id,
                "invoice_id": inv["id"],
                "customer_id": inv.get("customer_id") or "",
                "source": body.source,
            },
            idempotency_key=idem_key,
        )
    except Exception as e:
        logger.warning(f"[phase4b] payment_intent create failed: {type(e).__name__}")
        raise HTTPException(502, "Stripe could not create the payment intent")

    ledger_id = new_id()
    await db.stripe_payments_live.insert_one({
        "id": ledger_id,
        "tenant_id": tenant_id,
        "invoice_id": inv["id"],
        "customer_id": inv.get("customer_id"),
        "kind": "payment_intent",
        "payment_intent_id": pi["id"],
        "amount_cents": amt_cents,
        "currency": currency,
        "status": "initiated",
        "source": body.source,
        "idempotency_key": idem_key,
        "attempt": attempts_before + 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    return {
        "client_secret": pi["client_secret"],
        "payment_intent_id": pi["id"],
        "amount_cents": amt_cents,
        "currency": currency,
    }


# The FastAPI Depends() form doesn't compose neatly with the
# "authenticated OR magic-token" branch above — the endpoint decodes
# the bearer token inline (see body of ``create_payment_intent``).


# ──────────────────────────────────────────────────────────────────────
# GET /api/payments/{payment_intent_id}
# ──────────────────────────────────────────────────────────────────────
@router.get("/payments/{payment_intent_id}")
async def get_payment_status(
    payment_intent_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if (user or {}).get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    row = await db.stripe_payments_live.find_one(
        {"payment_intent_id": payment_intent_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Payment not found")
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin", "manager"):
        if role != "customer" or (user.get("customer_id") or "") != (row.get("customer_id") or ""):
            raise HTTPException(403, "Not authorized")
    if not is_configured():
        return {**row, "stripe_status": None}
    stripe = get_stripe()
    try:
        pi = stripe.PaymentIntent.retrieve(payment_intent_id)
        s = pi.get("status") if isinstance(pi, dict) else getattr(pi, "status", None)
    except Exception as e:
        logger.warning(f"[phase4b] pi retrieve failed: {type(e).__name__}")
        s = None
    return {
        "payment_intent_id": payment_intent_id,
        "ledger_status": row.get("status"),
        "stripe_status": s,
        "amount_cents": row.get("amount_cents"),
        "currency": row.get("currency"),
        "invoice_id": row.get("invoice_id"),
    }


# ──────────────────────────────────────────────────────────────────────
# POST /api/payments/refund
# ──────────────────────────────────────────────────────────────────────
class RefundBody(BaseModel):
    payment_intent_id: str
    amount_cents: Optional[int] = Field(None, ge=1)
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/payments/refund")
async def refund_payment(
    body: RefundBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    deny_impersonation(user)
    _require_admin_or_manager(user)
    if not is_configured():
        raise HTTPException(503, "Stripe not configured")
    if not (body.reason or "").strip() or len((body.reason or "").strip()) < 3:
        raise HTTPException(422, "reason is required (min 3 chars)")

    row = await db.stripe_payments_live.find_one(
        {"payment_intent_id": body.payment_intent_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Payment not found in ledger")
    if row.get("status") not in ("paid", "partially_refunded"):
        raise HTTPException(400, "Only paid payments can be refunded")

    total_cents = int(row.get("amount_cents") or 0)
    refunded_so_far = int(row.get("refunded_cents") or 0)
    max_refundable = total_cents - refunded_so_far
    if max_refundable <= 0:
        raise HTTPException(400, "Nothing left to refund")
    amt = int(body.amount_cents) if body.amount_cents else max_refundable
    if amt > max_refundable:
        raise HTTPException(400, "Refund amount exceeds remaining refundable balance")
    assert_cents(amt)

    idem_key = f"rf:{body.payment_intent_id}:{amt}"
    stripe = get_stripe()
    try:
        refund = stripe.Refund.create(
            payment_intent=body.payment_intent_id,
            amount=amt,
            metadata={
                "tenant_id": tenant["id"],
                "invoice_id": row.get("invoice_id") or "",
                "reason": (body.reason or "")[:180],
                "refunded_by": user.get("id") or "",
            },
            idempotency_key=idem_key,
        )
    except Exception as e:
        logger.warning(f"[phase4b] refund create failed: {type(e).__name__}")
        raise HTTPException(502, "Stripe could not create the refund")

    new_refunded = refunded_so_far + amt
    new_status = "refunded" if new_refunded >= total_cents else "partially_refunded"
    await db.stripe_payments_live.update_one(
        {"id": row["id"]},
        {"$set": {
            "refunded_cents": new_refunded,
            "status": new_status,
            "updated_at": now_iso(),
            "last_refund_reason": body.reason,
        }, "$push": {"refunds": {
            "refund_id": refund.get("id") if isinstance(refund, dict) else getattr(refund, "id", None),
            "amount_cents": amt,
            "reason": body.reason,
            "at": now_iso(),
            "by": user.get("id"),
        }}},
    )
    # Sync invoice — decrement amount_paid.
    if row.get("invoice_id"):
        inv = await db.quotes.find_one(
            {"id": row["invoice_id"], "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if inv:
            new_paid = max(float(inv.get("amount_paid") or 0) - amt / 100.0, 0.0)
            total = float(inv.get("total") or 0)
            fully_paid = new_paid + 0.01 >= total
            partial = 0 < new_paid < total
            await db.quotes.update_one(
                {"id": inv["id"], "tenant_id": tenant["id"]},
                {"$set": {
                    "amount_paid": round(new_paid, 2),
                    "payment_status": "paid" if fully_paid else ("partial" if partial else "unpaid"),
                }},
            )
    rid = refund.get("id") if isinstance(refund, dict) else getattr(refund, "id", None)
    return {
        "refund_id": rid,
        "payment_intent_id": body.payment_intent_id,
        "amount_cents": amt,
        "status": new_status,
    }


# ──────────────────────────────────────────────────────────────────────
# Test hooks (only registered when ALLOW_TEST_HOOKS=1). Never available
# in production because deployment omits the env var. Not authenticated
# because pytest doesn't have a session — the endpoints are ONLY safe
# because they mutate in-process SDK stubs; the mutations never reach
# real Stripe.
# ──────────────────────────────────────────────────────────────────────
if os.getenv("ALLOW_TEST_HOOKS") == "1":
    import uuid as _uuid

    _ORIGINALS: dict = {}

    class _FakePI(dict):
        pass

    def _pi_create(**kwargs):
        pi_id = f"pi_test_{_uuid.uuid4().hex[:12]}"
        return _FakePI({
            "id": pi_id,
            "client_secret": f"{pi_id}_secret_stub",
            "amount": kwargs.get("amount"),
            "currency": kwargs.get("currency"),
            "status": "requires_payment_method",
            "metadata": kwargs.get("metadata"),
        })

    def _refund_create(**kwargs):
        return _FakePI({"id": f"re_test_{_uuid.uuid4().hex[:12]}",
                         "amount": kwargs.get("amount"),
                         "payment_intent": kwargs.get("payment_intent")})

    def _pi_retrieve(pi_id, **_kw):
        return _FakePI({"id": pi_id, "status": "requires_payment_method"})

    def _construct(payload, sig, secret):
        if sig == "BADSIG":
            raise Exception("bad sig")
        import json as _json
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return _json.loads(payload)

    class _FakeAccount(dict):
        pass

    # Toggle for the live-ping stub — some tests want an auth failure.
    _ACCT_MODE = {"raise": False, "class_name": "AuthenticationError"}

    def _acct_retrieve(*_args, **_kw):
        if _ACCT_MODE["raise"]:
            cls = type(_ACCT_MODE["class_name"], (Exception,), {})
            raise cls("Invalid API Key provided: sk_live_…test")
        return _FakeAccount({
            "id": "acct_test_phase4b_ok",
            "country": "US",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        })

    @router.post("/dev/_phase4b_stub_stripe")
    async def _phase4b_stub_stripe():
        st = get_stripe()
        _ORIGINALS.setdefault("PaymentIntent.create", st.PaymentIntent.create)
        _ORIGINALS.setdefault("PaymentIntent.retrieve", st.PaymentIntent.retrieve)
        _ORIGINALS.setdefault("Refund.create", st.Refund.create)
        _ORIGINALS.setdefault("Webhook.construct_event", st.Webhook.construct_event)
        _ORIGINALS.setdefault("Account.retrieve", st.Account.retrieve)
        st.PaymentIntent.create = _pi_create
        st.PaymentIntent.retrieve = _pi_retrieve
        st.Refund.create = _refund_create
        st.Webhook.construct_event = _construct
        st.Account.retrieve = _acct_retrieve
        return {"stubbed": True}

    @router.post("/dev/_phase4b_stub_account_raise")
    async def _phase4b_stub_account_raise():
        _ACCT_MODE["raise"] = True
        return {"stubbed": True}

    @router.post("/dev/_phase4b_stub_account_ok")
    async def _phase4b_stub_account_ok():
        _ACCT_MODE["raise"] = False
        return {"stubbed": True}

    from pydantic import BaseModel as _BM

    class _EnvSet(_BM):
        key: str
        value: str

    @router.post("/dev/_phase4b_env_set")
    async def _phase4b_env_set(body: _EnvSet):
        # Test-only in-process env toggle. Gated by ALLOW_TEST_HOOKS so
        # it never mounts in production. Restricted to STRIPE_MODE +
        # STRIPE_ACCOUNT_ID — the two vars whose test-runtime flipping
        # the tests need. Anything else is a no-op.
        if body.key not in ("STRIPE_MODE", "STRIPE_ACCOUNT_ID"):
            return {"ok": False, "reason": "key not whitelisted"}
        os.environ[body.key] = body.value or ""
        return {"ok": True, "key": body.key}

    @router.post("/dev/_phase4b_unstub_stripe")
    async def _phase4b_unstub_stripe():
        st = get_stripe()
        for k, v in list(_ORIGINALS.items()):
            obj_name, attr = k.split(".")
            setattr(getattr(st, obj_name), attr, v)
        _ORIGINALS.clear()
        return {"unstubbed": True}
