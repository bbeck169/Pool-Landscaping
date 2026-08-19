"""Phase 4 additions:
- Portal home aggregate dashboard
- Portal invite / reset / revoke admin actions

Existing portal endpoints (`/me/*`, `/documents`, `/communications`, `/payments/checkout/{qid}`, `/setup-session`) are reused unchanged.
"""
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from config import db, logger, APP_PUBLIC_URL
from utils import now_iso, new_id, require_admin, get_current_user, hash_password
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
              "impersonation_started", "impersonation_ended")
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
