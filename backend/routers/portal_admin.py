"""Phase 4 additions:
- Portal home aggregate dashboard
- Portal invite / reset / revoke admin actions

Existing portal endpoints (`/me/*`, `/documents`, `/communications`, `/payments/checkout/{qid}`, `/setup-session`) are reused unchanged.
"""
import os
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from config import db, logger, APP_PUBLIC_URL
from utils import now_iso, new_id, require_admin, get_current_user, hash_password
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter()


def _random_password(n: int = 12) -> str:
    """Generate a compliant password: >=8 chars, has upper+lower+digit."""
    alpha_lower = "abcdefghjkmnpqrstuvwxyz"
    alpha_upper = "ABCDEFGHJKMNPQRSTUVWXYZ"
    digits = "23456789"
    seed = [
        secrets.choice(alpha_upper),
        secrets.choice(alpha_lower),
        secrets.choice(digits),
    ]
    pool = alpha_upper + alpha_lower + digits
    seed += [secrets.choice(pool) for _ in range(max(1, n - 3))]
    secrets.SystemRandom().shuffle(seed)
    return "".join(seed)


# ─── Portal home aggregate ──────────────────────────────────────────────────
@router.get("/portal/home")
async def portal_home(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    """Aggregated dashboard payload for the logged-in customer.

    Feb-2026 P0 defense-in-depth — every Mongo lookup is now scoped
    by ``tenant_id`` in addition to ``customer_id``. A misseeded
    ``users.customer_id`` cannot leak another tenant's customer/
    invoices/jobs into the response. Also emits a
    ``identity_mismatch`` flag when the JWT's ``email`` claim does
    not match the resolved customer's primary email — surfaces
    data-integrity issues immediately in the frontend without
    breaking legitimate rebinds.
    """
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Not a customer")
    cid = user["customer_id"]
    tid = tenant["id"]
    now = datetime.now(timezone.utc)
    today_iso = now.date().isoformat()

    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0}
    ) or {}
    # Feb-2026 P0 · JWT ↔ customer email sanity check. Log-only for
    # now (no 403) so a benign rebind doesn't lock a legitimate user
    # out; the identity_mismatch flag lets the frontend render a
    # "please re-sign-in" banner and lets ops grep the warning.
    identity_mismatch = False
    if customer and user.get("email") and customer.get("email"):
        if str(user["email"]).lower() != str(customer["email"]).lower():
            identity_mismatch = True
            logger.warning(
                "[portal_home] JWT identity mismatch — "
                "user_id=%s user_email=%s customer_id=%s customer_email=%s tenant=%s",
                user.get("id"), user.get("email"),
                customer.get("id"), customer.get("email"), tid,
            )
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tid}, {"_id": 0}
    ).sort("scheduled_date", 1).to_list(200)

    upcoming = [
        j for j in jobs
        if (j.get("status") in ("scheduled", "active", "pending", "requested"))
        and (not j.get("scheduled_date") or str(j["scheduled_date"])[:10] >= today_iso)
    ]
    past = [
        j for j in jobs
        if j.get("status") in ("completed", "cancelled") or (j.get("scheduled_date") and str(j["scheduled_date"])[:10] < today_iso)
    ]
    past.sort(key=lambda j: j.get("completed_at") or j.get("scheduled_date") or "", reverse=True)

    invs = await db.quotes.find(
        {"customer_id": cid, "tenant_id": tid, "doc_type": "invoice"}, {"_id": 0}
    ).to_list(500)
    overdue_count = 0
    outstanding = 0.0
    for i in invs:
        remaining = max(0.0, float(i.get("total") or 0) - float(i.get("amount_paid") or 0))
        outstanding += remaining
        if remaining > 0 and i.get("due_date") and str(i["due_date"])[:10] < today_iso:
            overdue_count += 1

    estimates = await db.quotes.find(
        {"customer_id": cid, "tenant_id": tid, "doc_type": "quote"}, {"_id": 0}
    ).to_list(500)
    pending_estimates = [
        e for e in estimates
        if e.get("status") in ("sent", "draft") and e.get("decision") not in ("approved", "declined")
    ]

    unread_msgs = 0
    try:
        threads = await db.communications.find(
            {"customer_id": cid, "tenant_id": tid}, {"messages": 1, "_id": 0}
        ).to_list(200)
        for t in threads:
            for m in (t.get("messages") or []):
                if not m.get("read_by_customer") and m.get("from_role") in ("admin", "technician", "assistant"):
                    unread_msgs += 1
    except Exception:
        pass

    return {
        "customer": customer,
        "next_visit": upcoming[0] if upcoming else None,
        "last_visit": past[0] if past else None,
        "counts": {
            "upcoming_jobs": len(upcoming),
            "overdue_invoices": overdue_count,
            "outstanding_total": round(outstanding, 2),
            "pending_estimates": len(pending_estimates),
            "unread_messages": unread_msgs,
        },
        # Feb-2026 P0 · surface the JWT ↔ customer email mismatch to
        # the frontend so a stale prod session (or a mis-linked
        # ``users.customer_id``) is immediately visible.
        "identity_mismatch": identity_mismatch,
    }


# ─── Portal invite / reset / revoke ────────────────────────────────────────
class PortalInviteResp(BaseModel):
    ok: bool = True
    email: str
    login_url: str
    password: Optional[str] = None
    emailed: bool = False


async def _upsert_customer_user(cid: str, tenant_id: str, email: str, password: str) -> None:
    hashed = hash_password(password)
    existing = await db.users.find_one({"customer_id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {"password_hash": hashed, "email": email.lower(), "active": True}},
        )
    else:
        await db.users.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": (await db.customers.find_one({"id": cid, "tenant_id": tenant_id}) or {}).get("name", ""),
            "email": email.lower(),
            "password_hash": hashed,
            "role": "customer",
            "avatar": "",
            "technician_id": None,
            "customer_id": cid,
            "active": True,
            "created_at": now_iso(),
        })
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant_id}, {"$set": {"email": email.lower(), "has_login": True}}
    )


async def _try_send_reset_email(to: str, name: str, temp_password: str, login_url: str) -> bool:
    from config import RESEND_API_KEY, EMAIL_FROM
    if not RESEND_API_KEY:
        return False
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to],
            "subject": "Your customer portal login",
            "html": (
                f"<p>Hi {name or ''},</p>"
                f"<p>Your portal login is ready.</p>"
                f"<p><strong>Email:</strong> {to}<br>"
                f"<strong>Temporary password:</strong> <code>{temp_password}</code></p>"
                f"<p><a href='{login_url}'>Sign in here</a> and change your password from Profile.</p>"
            ),
        })
        return True
    except Exception as e:
        logger.warning(f"Portal invite email failed: {e}")
        return False


@router.post("/customers/{cid}/portal-invite", response_model=PortalInviteResp)
async def portal_invite(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Provisions the customer's portal login with an auto-generated password.
    Emails it via Resend if configured; otherwise returns the password in-body
    so the admin can send it manually."""
    return await _do_portal_provision(cid, tenant["id"], user, explicit_password=None)


class PortalResetBody(BaseModel):
    password: Optional[str] = None


@router.post("/customers/{cid}/portal-reset", response_model=PortalInviteResp)
async def portal_reset(
    cid: str,
    body: Optional[PortalResetBody] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Rotates the customer's portal password.
    If `password` is provided in body, sets it explicitly (validated against
    the standard password policy). Otherwise generates a random one."""
    explicit = (body.password if body else None) or None
    return await _do_portal_provision(cid, tenant["id"], user, explicit_password=explicit)


async def _do_portal_provision(cid: str, tenant_id: str, actor: dict,
                                 explicit_password: Optional[str]) -> PortalInviteResp:
    from models import validate_password_strength
    # SEC-002 hotfix: tenant-scoped customer lookup. Cross-tenant CID → 404.
    cust = await db.customers.find_one({"id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    email = (cust.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    if explicit_password:
        try:
            validate_password_strength(explicit_password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        password = explicit_password
    else:
        password = _random_password()

    await _upsert_customer_user(cid, tenant_id, email, password)
    # Audit-log the portal-reset action for accountability.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "portal_reset",
            "actor_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "target_customer_id": cid,
            "target_email": email,
            "created_at": now_iso(),
        })
    except Exception:
        pass
    login_url = f"{APP_PUBLIC_URL or ''}/login"
    emailed = False
    if not explicit_password:
        emailed = await _try_send_reset_email(email, cust.get("name", ""), password, login_url)
    return PortalInviteResp(
        email=email,
        login_url=login_url,
        password=password if not emailed else None,
        emailed=emailed,
    )


# ─── K30 · Feb-2026 · Admin-triggered tokenized password-reset link ────
#
# Sits alongside ``/customers/{cid}/portal-reset`` (which emails a
# temp password) — this endpoint emits a SINGLE-USE opaque token
# link into ``password_reset_tokens`` (30-min TTL, matches the
# ``/auth/forgot-password`` self-serve flow) so the customer never
# sees a raw password over email. Admin-only, tenant-scoped, and
# uses the ``allow_off_allowlist=True`` bypass on the resend
# adapter because admin-driven support actions must land in the
# customer's inbox even from preview environments.

class PortalResetLinkResp(BaseModel):
    ok: bool = True
    sent_to: str
    token_ttl_minutes: int = 30
    provisioned_user: bool = False


def _mask_email_for_response(email: str) -> str:
    """Return ``t***@example.com`` shape so audit/UI never echoes the
    full address back through the admin response body."""
    if not email or "@" not in email:
        return email or ""
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


@router.post("/customers/{cid}/portal-reset-link", response_model=PortalResetLinkResp)
async def portal_reset_link(cid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """K30 · Feb-2026 — Admin-triggered password-reset LINK.

    Distinct from the pre-existing ``/portal-reset`` (temp password)
    and ``/portal-invite`` (temp password) endpoints. Behaviour:

    1. Tenant-scoped customer lookup — ``deleted_at`` is permitted
       (per K30 policy Q2 the reset link may still be issued for a
       soft-deleted customer, though login itself will remain
       gated by ``routers.auth.login`` until the customer is
       restored — see ``/customers/{cid}/restore``).
    2. Auto-provision a ``role="customer"`` ``users`` row if one is
       missing, reusing ``_upsert_customer_user`` with a random
       throwaway password (the customer never learns it — they set
       their own via the reset link).
    3. Mint an opaque single-use token in ``password_reset_tokens``
       (30-min TTL, invalidate prior unused tokens for the same
       user — mirrors the ``/auth/forgot-password`` contract).
    4. Send the reset-link email via the guarded Resend adapter with
       ``allow_off_allowlist=True`` so admin-triggered support
       actions leave preview environments.
    5. Audit event ``admin_password_reset_triggered`` on
       ``db.audit_logs`` with actor id + email, target customer id,
       tenant id, masked recipient, and adapter outcome.

    Response: ``{ok, sent_to (masked), token_ttl_minutes: 30,
    provisioned_user: bool}``. Never leaks the full recipient email
    or the token itself to the caller.
    """
    from routers.auth import _password_reset_email_html

    tid = tenant["id"]
    cust = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")

    email = (cust.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    # Auto-provision the portal user row if missing.
    existing = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tid, "role": "customer"},
        {"_id": 0, "id": 1, "email": 1},
    )
    provisioned_user = False
    if not existing:
        await _upsert_customer_user(cid, tid, email, _random_password(16))
        existing = await db.users.find_one(
            {"customer_id": cid, "tenant_id": tid, "role": "customer"},
            {"_id": 0, "id": 1, "email": 1},
        )
        provisioned_user = True

    if not existing:
        # Provisioning must have succeeded above; defensive guard.
        raise HTTPException(500, "Failed to provision portal user")

    # Mint the reset token — mirrors auth.forgot_password shape 1:1.
    from datetime import datetime, timezone, timedelta
    from routers.auth import _RESET_TTL_MINUTES

    await db.password_reset_tokens.update_many(
        {"user_id": existing["id"], "used_at": None},
        {"$set": {"invalidated_at": now_iso()}},
    )
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token": token,
        "user_id": existing["id"],
        "tenant_id": tid,
        "email": email,
        "expires_at": expires_at.isoformat(),
        "used_at": None,
        "invalidated_at": None,
        "created_at": now_iso(),
        "created_ip": None,
        "source": "admin_reset_link",
        "actor_user_id": (user or {}).get("id"),
    })

    frontend_url = (APP_PUBLIC_URL or os.environ.get("FRONTEND_URL") or "").rstrip("/")
    reset_link = f"{frontend_url}/reset-password?token={token}"

    first_name = (
        cust.get("first_name")
        or (cust.get("name") or "").split(" ")[0]
        or "there"
    )
    html = _password_reset_email_html(
        first_name=first_name,
        reset_link=reset_link,
        expiry_minutes=_RESET_TTL_MINUTES,
    )

    send_outcome: dict = {"provider_status": "not_attempted"}
    try:
        from services.email.resend_adapter import send as _send_email
        send_outcome = await _send_email(
            to=email,
            subject="Reset your password",
            html=html,
            category="transactional",
            tenant_id=tid,
            customer_id=cid,
            allow_off_allowlist=True,
        )
        logger.info(
            "[k30] admin_password_reset_triggered actor=%s cid=%s status=%s attempts=%s",
            (user or {}).get("email"), cid,
            send_outcome.get("provider_status"),
            send_outcome.get("attempts"),
        )
    except Exception as exc:  # pragma: no cover — belt-and-braces
        logger.warning("[k30] admin reset link send failed: %s", exc)
        send_outcome = {"provider_status": "failed",
                         "error": f"{type(exc).__name__}: {exc}"}

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "event": "admin_password_reset_triggered",
            "actor_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "target_customer_id": cid,
            "target_email_masked": _mask_email_for_response(email),
            "provisioned_user": provisioned_user,
            "provider_status": send_outcome.get("provider_status"),
            "provider_attempts": send_outcome.get("attempts"),
            "customer_soft_deleted": bool(cust.get("deleted_at")),
            "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover
        logger.warning("[k30] audit_logs insert failed")

    return PortalResetLinkResp(
        sent_to=_mask_email_for_response(email),
        token_ttl_minutes=_RESET_TTL_MINUTES,
        provisioned_user=provisioned_user,
    )


# ─── K30.status-chip · Feb-2026 · latest reset-link status ─────────────
#
# Lightweight read endpoint powering the "Reset link" chip on the
# Portal Access panel. Reads only the LATEST row in
# ``password_reset_tokens`` for the customer's linked ``users`` row
# and classifies it into one of four states. Never returns the
# token value itself — the chip is purely a UX signal for the
# front-office ("did the customer click it yet?").

class PortalResetLinkStatusResp(BaseModel):
    status: str  # "none" | "issued" | "used" | "expired"
    issued_at: Optional[str] = None
    used_at: Optional[str] = None
    expires_at: Optional[str] = None
    source: Optional[str] = None  # "admin_reset_link" | "forgot_password" | None


@router.get("/customers/{cid}/portal-reset-link-status",
            response_model=PortalResetLinkStatusResp)
async def portal_reset_link_status(cid: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    """K30.status-chip · Feb-2026 — Return the state of the LATEST
    ``password_reset_tokens`` row for this customer's portal user.

    Contract:

    * ``none``     — no reset token has ever been minted for this
                      customer's user row (or no user row exists).
    * ``issued``   — a token exists, ``used_at`` is null, and
                      ``expires_at`` is in the future.
    * ``used``     — the latest token has ``used_at`` set (customer
                      completed the reset).
    * ``expired``  — the latest token has ``used_at`` null AND
                      ``expires_at`` is in the past (or the row
                      carries ``invalidated_at`` and no newer token
                      exists).

    Never returns the raw ``token`` — the chip is metadata only.
    """
    from datetime import datetime, timezone

    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")

    cust_user = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"_id": 0, "id": 1},
    )
    if not cust_user:
        return PortalResetLinkStatusResp(status="none")

    row = await db.password_reset_tokens.find_one(
        {"user_id": cust_user["id"], "tenant_id": tenant["id"]},
        {"_id": 0, "token": 0},  # NEVER return the token value
        sort=[("created_at", -1)],
    )
    if not row:
        return PortalResetLinkStatusResp(status="none")

    if row.get("used_at"):
        return PortalResetLinkStatusResp(
            status="used",
            issued_at=row.get("created_at"),
            used_at=row.get("used_at"),
            expires_at=row.get("expires_at"),
            source=row.get("source"),
        )

    # Not used — decide between issued and expired.
    exp_raw = row.get("expires_at")
    is_expired = bool(row.get("invalidated_at"))
    if not is_expired and exp_raw:
        try:
            exp_dt = (exp_raw if isinstance(exp_raw, datetime)
                       else datetime.fromisoformat(exp_raw))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            is_expired = exp_dt < datetime.now(timezone.utc)
        except Exception:  # pragma: no cover — fail closed as expired
            is_expired = True

    return PortalResetLinkStatusResp(
        status="expired" if is_expired else "issued",
        issued_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
        source=row.get("source"),
    )


@router.post("/customers/{cid}/portal-revoke")
async def portal_revoke(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Deactivates the customer's portal login. SEC-002 hotfix: tenant-scoped."""
    res = await db.users.update_many(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"$set": {"active": False, "revoked_at": now_iso()}},
    )
    await db.customers.update_one({"id": cid, "tenant_id": tenant["id"]},
                                    {"$set": {"has_login": False}})
    # Feb-2026 Portal Access ship — audit trail for revocations too.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": "portal_revoke",
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "target_customer_id": cid,
            "created_at": now_iso(),
        })
    except Exception:
        pass
    return {"ok": True, "revoked": res.modified_count}


# ─── Feb-2026 Portal Access ship ──────────────────────────────────────
# Two admin-only read endpoints that back the customer-detail Portal
# Access card: current status + recent activity feed.

@router.get("/customers/{cid}/portal-status")
async def portal_status(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Compact view of a customer's portal login state for the admin
    Portal Access card.

    Returns::

        {
          "has_login": bool,
          "active": bool,               # false when revoked
          "email": str | None,
          "last_portal_login_at": str | None,
          "last_portal_login_ip": str | None,
          "revoked_at": str | None,
        }
    """
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    cust_user = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"_id": 0},
    )
    return {
        "has_login": bool(cust_user),
        "active": bool(cust_user and cust_user.get("active", True)),
        "email": (cust_user or {}).get("email") or cust.get("email") or None,
        "last_portal_login_at": cust.get("last_portal_login_at"),
        "last_portal_login_ip": cust.get("last_portal_login_ip"),
        "revoked_at": (cust_user or {}).get("revoked_at"),
    }


@router.get("/customers/{cid}/portal-history")
async def portal_history(cid: str,
                           limit: int = 50,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Recent portal-related audit events for a single customer:
    portal_login (customer signed in), portal_reset (admin rotated
    password), portal_revoke (admin killed access), and
    impersonation_started / impersonation_ended (admin viewed as
    customer).  Admin-only + tenant-scoped."""
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    lim = max(1, min(int(limit or 50), 500))
    events = ("portal_login", "portal_reset", "portal_revoke",
              "impersonation_started", "impersonation_ended",
              "admin_password_reset_triggered")
    rows = await db.audit_logs.find(
        {"tenant_id": tenant["id"],
          "target_customer_id": cid,
          "event": {"$in": list(events)}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(lim)
    return {
        "customer_id": cid,
        "count": len(rows),
        "events": rows,
    }


# ─── Phase H1 · Feb-2026 — Bulk portal invite ──────────────────────────
class _H1BulkInviteBody(BaseModel):
    customer_ids: list[str]
    reason: Optional[str] = None


_H1_BULK_MAX = 200
_H1_RATE_WINDOW_SECS = 60 * 60
_H1_RATE_MAX_PER_WINDOW = 500


@router.post("/admin/customers/portal-invite/bulk")
async def portal_invite_bulk(
    body: _H1BulkInviteBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase H1 · Feb-2026 — bulk portal invite / password rotate.

    Reuses the single-invite pipeline (``_do_portal_provision``) verbatim
    so send behaviour, audit trail, and idempotency stay in lockstep
    with the ``POST /customers/{cid}/portal-invite`` endpoint that
    already ships. Never parallel — 100ms delay between invites to
    respect RC / Resend upstream throttling.

    Rate-limit: 500 invites per tenant per 60-min window, tracked in
    ``db.portal_invite_rate_limit`` (created lazily). Exceeding
    returns 429.  Batch cap: ``_H1_BULK_MAX`` (200); exceeding
    returns 400 forcing the client to page.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta

    tid = tenant["id"]
    ids = [i for i in (body.customer_ids or []) if isinstance(i, str)]
    if not ids:
        raise HTTPException(400, "customer_ids required (non-empty list)")
    if len(ids) > _H1_BULK_MAX:
        raise HTTPException(
            400,
            f"Batch too large ({len(ids)} > {_H1_BULK_MAX}). "
            f"Page the client into batches of {_H1_BULK_MAX} or smaller.",
        )

    # Rate-limit sliding window
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=_H1_RATE_WINDOW_SECS)
    already_sent = await db.portal_invite_rate_limit.count_documents({
        "tenant_id": tid,
        "sent_at": {"$gte": window_start.isoformat()},
    })
    remaining = max(0, _H1_RATE_MAX_PER_WINDOW - already_sent)
    if remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail={
                "detail": "portal_invite_rate_limited",
                "message": (
                    f"Tenant limit of {_H1_RATE_MAX_PER_WINDOW} portal "
                    f"invites per {_H1_RATE_WINDOW_SECS // 60} minutes "
                    f"reached. Try again shortly."
                ),
                "window_seconds": _H1_RATE_WINDOW_SECS,
                "limit": _H1_RATE_MAX_PER_WINDOW,
            },
        )

    batch_id = new_id()
    counts = {
        "requested": len(ids),
        "sent": 0,
        "skipped_already_activated": 0,
        "skipped_no_contact": 0,
        "skipped_wrong_tenant": 0,
        "failed_send": 0,
    }
    failures: list[dict] = []

    # De-dupe within a single batch (case A calls a→b, b already ran)
    seen: set = set()

    for cid in ids:
        if cid in seen:
            counts["skipped_already_activated"] += 1
            continue
        seen.add(cid)

        # Stop if rate window budget exhausted mid-batch
        if counts["sent"] >= remaining:
            failures.append({
                "customer_id": cid,
                "reason": "rate_limit_mid_batch",
            })
            counts["failed_send"] += 1
            continue

        cust = await db.customers.find_one(
            {"id": cid}, {"_id": 0, "id": 1, "tenant_id": 1,
                          "email": 1, "phone": 1, "has_login": 1},
        )
        if not cust or cust.get("tenant_id") != tid:
            counts["skipped_wrong_tenant"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "wrong_tenant_or_missing",
            })
            continue
        if cust.get("has_login") is True:
            counts["skipped_already_activated"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "already_activated",
            })
            continue
        if not (cust.get("email") or "").strip() and \
                not (cust.get("phone") or "").strip():
            counts["skipped_no_contact"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "no_email_or_phone",
            })
            continue

        try:
            # Reuse the single-invite pipeline verbatim.
            await _do_portal_provision(
                cid, tid, user, explicit_password=None,
            )
            counts["sent"] += 1
            # Stamp rate-limit ledger AFTER a successful send.
            await db.portal_invite_rate_limit.insert_one({
                "id": new_id(),
                "tenant_id": tid,
                "customer_id": cid,
                "batch_id": batch_id,
                "actor_id": (user or {}).get("id"),
                "sent_at": now_iso(),
            })
        except HTTPException as exc:
            counts["failed_send"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "http_error",
                "error": str(exc.detail)[:200],
            })
        except Exception as exc:  # noqa: BLE001
            counts["failed_send"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "exception",
                "error": str(exc)[:200],
            })

        # 100ms polite spacing so we don't spike RC/Resend upstream
        # rate-limits — only applied between invites, not after the
        # last one.
        await asyncio.sleep(0.1)

    payload = {
        **counts,
        "batch_id": batch_id,
        "failures": failures,
    }
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "portal_invite_bulk",
            "tenant_id": tid,
            "actor_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "reason": (body.reason or "")[:200] or None,
            "timestamp": now_iso(),
            "payload": {k: v for k, v in payload.items() if k != "failures"},
            "failure_count": len(failures),
        })
    except Exception as _ae:  # noqa: BLE001
        logger.warning(f"[phase-h1] audit_events insert failed: {_ae}")

    return payload
