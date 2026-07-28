# ruff: noqa: F403,F405
import os
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import _ensure_default_tenant
from models import LoginRequest, SignupRequest

router = APIRouter()

# --- Brute-force / account-lockout policy (SOC2/ISO 27001 technical control) ---
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _audit_auth(event: str, email: str, ip: str, status: str, details: str = ""):
    """Immutable-ish audit record of authentication events."""
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "event": event, "email": email, "ip_address": ip,
            "status": status, "details": details, "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"audit log write failed: {e}")


@router.post("/auth/login")
async def login(request: Request, body: LoginRequest):
    email = body.email.lower()
    ip = _client_ip(request)
    user = await db.users.find_one({"email": email})
    now = datetime.now(timezone.utc)

    # Generic message to avoid user enumeration.
    invalid = HTTPException(status_code=401, detail="Incorrect email or password")

    if not user:
        await _audit_auth("login", email, ip, "failure", "user not found")
        raise invalid

    # 1) Account lockout check
    lock = user.get("lockout_until")
    if lock:
        lock_dt = lock if isinstance(lock, datetime) else datetime.fromisoformat(lock)
        if lock_dt.tzinfo is None:
            lock_dt = lock_dt.replace(tzinfo=timezone.utc)
        if lock_dt > now:
            await _audit_auth("login_locked", email, ip, "failure", "attempt while locked")
            mins = max(1, int((lock_dt - now).total_seconds() // 60) + 1)
            raise HTTPException(status_code=429, detail=f"Account temporarily locked. Try again in {mins} minute(s).")

    # 2) Verify password
    if not verify_password(body.password, user.get("password_hash", "")):
        attempts = int(user.get("failed_login_attempts", 0)) + 1
        upd = {"failed_login_attempts": attempts}
        if attempts >= MAX_FAILED_ATTEMPTS:
            upd["lockout_until"] = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            await _audit_auth("account_lockout", email, ip, "failure", f"locked {LOCKOUT_MINUTES}m after {attempts} attempts")
        else:
            await _audit_auth("login", email, ip, "failure", f"attempt {attempts}")
        await db.users.update_one({"id": user["id"]}, {"$set": upd})
        raise invalid

    # 3) Success -> reset counters
    if user.get("failed_login_attempts") or user.get("lockout_until"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"failed_login_attempts": 0, "lockout_until": None}})
    # SEC-004 hotfix — deactivated accounts cannot obtain a token.
    if user.get("active") is False:
        await _audit_auth("login", email, ip, "failure", "account deactivated")
        raise HTTPException(status_code=403, detail="Account is deactivated")
    await _audit_auth("login", email, ip, "success")
    # Feb-2026 Portal Access ship — stamp the customer doc with the
    # last portal login timestamp/IP + write a dedicated ``portal_login``
    # audit row so the admin Portal Access panel can show the customer's
    # recent activity without scanning the raw auth audit stream.
    if user.get("role") == "customer" and user.get("customer_id"):
        try:
            await db.customers.update_one(
                {"id": user["customer_id"], "tenant_id": user.get("tenant_id")},
                {"$set": {
                    "last_portal_login_at": now_iso(),
                    "last_portal_login_ip": ip,
                }},
            )
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": user.get("tenant_id"),
                "event": "portal_login",
                "target_customer_id": user["customer_id"],
                "target_user_id": user["id"],
                "email": email,
                "ip_address": ip,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.warning(f"portal_login audit skipped: {e}")
    return auth_response(user)


@router.post("/auth/signup")
async def signup(request: Request, body: SignupRequest):
    email = body.email.lower()
    ip = _client_ip(request)
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    # Resolve tenant from X-Tenant-Slug header if provided; else default tenant.
    tenant = None
    slug = request.headers.get("x-tenant-slug")
    if slug:
        # Phase 21 · Feb 2026 — tolerate ``slug_aliases`` (e.g. "plofv"
        # resolves to the same tenant as canonical "aquaterra").
        tenant = await db.tenants.find_one(
            {"$or": [{"slug": slug}, {"slug_aliases": slug}], "active": True},
            {"_id": 0},
        )
    if not tenant:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            tenant = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
    if not tenant:
        tenant = await _ensure_default_tenant()
    tid = tenant["id"]
    # Create a customer record for the new self-signed-up client
    customer = {
        "id": new_id(), "tenant_id": tid, "name": body.name, "email": email,
        "phone": body.phone or "", "address": body.address or "", "notes": "",
        "created_at": now_iso(),
    }
    await db.customers.insert_one(customer)
    user = {
        "id": new_id(), "tenant_id": tid, "name": body.name, "email": email,
        "password_hash": hash_password(body.password), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": customer["id"],
        "failed_login_attempts": 0, "lockout_until": None,
    }
    await db.users.insert_one(user)
    await _audit_auth("signup", email, ip, "success")
    return auth_response(user)


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    # BUG E — decorate the raw user doc with the server-authoritative
    # ToS gate flag so the frontend gate can read a single source of
    # truth without duplicating the role/version logic client-side.
    from config_tos import compute_must_accept_tos
    payload = {**user, "must_accept_tos": compute_must_accept_tos(user)}

    # Feb-2026 · mobile-flagged gap — detect orphan customer auth users
    # (role=customer but no linked customer record) so the frontend can
    # render a "complete your profile" prompt instead of 500-ing on a
    # missing customer_id downstream. We NEVER silently create records
    # here; a super_admin repair endpoint exists for that
    # (``POST /api/admin/users/{id}/create-customer-record``).
    if user.get("role") == "customer":
        cid = user.get("customer_id")
        cust = None
        if cid:
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": user.get("tenant_id")},
                {"_id": 0, "id": 1},
            )
        payload["customer_record_missing"] = cust is None

    # Feb-2026 · surface ``auto_clockin_enabled`` in the me payload so
    # the mobile Clock-In screen + web Team page can key off the same
    # authoritative flag. Defaults: True for tech, False otherwise.
    if "auto_clockin_enabled" not in payload:
        payload["auto_clockin_enabled"] = (user.get("role") == "technician")
    return payload


# ══════════════════════════════════════════════════════════════════════
# Phase 34 · Task O · Feb-2026 — Self-serve password reset
# ══════════════════════════════════════════════════════════════════════
# Two-endpoint flow:
#
#   POST /api/auth/forgot-password  → generic 200 (enum-safe). If the
#     email matches a user, mint a single-use opaque token, persist to
#     ``password_reset_tokens`` with a 30-min expiry, and send a
#     tokenized link via the guarded email adapter (dry-runs in preview
#     unless the recipient is on ``COMMS_TEST_ALLOWLIST_EMAILS`` — see
#     Task L).
#
#   POST /api/auth/reset-password   → accepts ``{token, new_password}``,
#     validates the token, enforces the same password policy the
#     admin change-password form uses, updates the auth-user hash,
#     invalidates the token.
#
# Design choices:
# * Opaque UUID tokens (not JWT) so a stolen backend log line without
#   the DB row can't derive the reset target.
# * Rate limit 5 requests / IP / hour (keyed in memory — good enough
#   for the current single-node preview; a Redis-backed limiter is
#   tracked as a Phase-35 follow-up).
# * Neutral response body — never disclose whether an account exists.
# * Every successful reset invalidates any other pending tokens for
#   the same user and unwinds ``failed_login_attempts`` / ``lockout_until``.
#
from collections import defaultdict, deque

_RESET_TTL_MINUTES = 30
_RESET_RATE_MAX_PER_HOUR = 5
_RESET_IP_HITS: Dict[str, deque] = defaultdict(deque)  # noqa: F821


def _password_policy_ok(pw: str) -> Optional[str]:
    """Return an error message if ``pw`` fails policy, else None."""
    if not pw or len(pw) < 8:
        return "Password must be at least 8 characters long."
    import re as _re
    if not _re.search(r"[a-z]", pw):
        return "Password must include a lowercase letter."
    if not _re.search(r"[A-Z]", pw):
        return "Password must include an uppercase letter."
    if not _re.search(r"[0-9]", pw):
        return "Password must include a digit."
    return None


def _check_reset_rate_limit(ip: str) -> bool:
    """In-process rolling-window rate limiter. Returns True if the
    request is within budget, False if it has exceeded the cap."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    q = _RESET_IP_HITS[ip]
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= _RESET_RATE_MAX_PER_HOUR:
        return False
    q.append(now)
    return True


class ForgotPasswordRequest(BaseModel):  # noqa: F405 — models module uses star import
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/auth/forgot-password")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Self-serve request-a-reset endpoint.

    Always returns the same neutral 200 payload so callers can't
    enumerate whether an account exists. When the email matches a
    real user we mint a single-use opaque token, persist it to
    ``password_reset_tokens`` (TTL 30 min, ``used_at`` field on
    consumption), and hand a tokenized link to the guarded email
    adapter (dry-run in preview unless the recipient is on
    ``COMMS_TEST_ALLOWLIST_EMAILS``).
    """
    ip = _client_ip(request)
    if not _check_reset_rate_limit(ip):
        await _audit_auth("password_reset_request", (body.email or "").lower(),
                          ip, "failure", "rate_limited")
        # Still return the neutral 200 so a bad actor can't tell the
        # difference between rate-limit and "no such account".
        return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}

    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}

    user = await db.users.find_one({"email": email})
    # Mint + send only if the user actually exists; return the same
    # neutral response either way.
    if user:
        # Invalidate any prior unused tokens for this user so only the
        # most-recent link works.
        await db.password_reset_tokens.update_many(
            {"user_id": user["id"], "used_at": None},
            {"$set": {"invalidated_at": now_iso()}},
        )
        import secrets
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)
        await db.password_reset_tokens.insert_one({
            "id": new_id(),
            "token": token,
            "user_id": user["id"],
            "tenant_id": user.get("tenant_id"),
            "email": email,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
            "invalidated_at": None,
            "created_at": now_iso(),
            "created_ip": ip,
        })

        frontend_url = (os.environ.get("APP_PUBLIC_URL")  # noqa: F821
                        or os.environ.get("FRONTEND_URL")
                        or "").rstrip("/")
        reset_link = f"{frontend_url}/reset-password?token={token}"

        # Send via the guarded adapter. Preview will dry-run for any
        # recipient not on the allow-list; Brian's account IS allow-
        # listed so his link goes live (subject to the Resend key).
        try:
            from services.email.resend_adapter import send as _send_email

            first_name = (
                user.get("first_name")
                or (user.get("name") or "").split(" ")[0]
                or "there"
            )
            html = _password_reset_email_html(
                first_name=first_name,
                reset_link=reset_link,
                expiry_minutes=_RESET_TTL_MINUTES,
            )
            res = await _send_email(
                to=email,
                subject="Reset your password",
                html=html,
                category="transactional",
                tenant_id=user.get("tenant_id"),
                customer_id=user.get("customer_id"),
            )
            # Always log the reset link (behind INFO) so ops can help
            # a stuck customer out-of-band, and so preview dry-run
            # traffic is visually verifiable per the Task O brief.
            logger.info(
                "[task-o] password_reset link=%s to=%s status=%s attempts=%s",
                reset_link, email,
                res.get("provider_status"), res.get("attempts"),
            )
        except Exception as exc:  # pragma: no cover — never blocks the neutral response
            logger.warning("password_reset email send failed: %s", exc)

        await _audit_auth("password_reset_request", email, ip, "success",
                          f"token_minted expires_in_min={_RESET_TTL_MINUTES}")
    else:
        # No user with that email. Log for ops visibility; still
        # return neutral to the caller.
        await _audit_auth("password_reset_request", email, ip, "success",
                          "no_user_matched")
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


@router.post("/auth/reset-password")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Complete a password reset started by ``/auth/forgot-password``.

    Validates the token (exists, not used, not expired, not
    invalidated), enforces the shared password policy, updates the
    auth-user's hash, marks the token used, and clears any
    ``failed_login_attempts`` / ``lockout_until`` so the customer
    can sign in immediately with the new credential.
    """
    ip = _client_ip(request)
    tok = (body.token or "").strip()
    if not tok:
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")

    err = _password_policy_ok(body.new_password or "")
    if err:
        raise HTTPException(400, err)

    row = await db.password_reset_tokens.find_one({"token": tok}, {"_id": 0})
    if not row:
        await _audit_auth("password_reset_complete", "", ip, "failure", "unknown_token")
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    if row.get("used_at"):
        await _audit_auth("password_reset_complete", row.get("email", ""), ip,
                          "failure", "token_reused")
        raise HTTPException(400, "This reset link has already been used. Please request a new one.")
    if row.get("invalidated_at"):
        await _audit_auth("password_reset_complete", row.get("email", ""), ip,
                          "failure", "token_invalidated")
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    # Expiry
    exp_raw = row.get("expires_at")
    try:
        exp_dt = (exp_raw if isinstance(exp_raw, datetime)
                   else datetime.fromisoformat(exp_raw))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    except Exception:
        exp_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    if exp_dt < datetime.now(timezone.utc):
        await _audit_auth("password_reset_complete", row.get("email", ""), ip,
                          "failure", "token_expired")
        raise HTTPException(400, "This reset link has expired. Please request a new one.")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user:
        # Highly unlikely — but defensive.
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")

    new_hash = hash_password(body.new_password)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": new_hash,
            "failed_login_attempts": 0,
            "lockout_until": None,
            "must_change_password_on_next_login": False,
            "password_updated_at": now_iso(),
        }},
    )
    await db.password_reset_tokens.update_one(
        {"token": tok},
        {"$set": {"used_at": now_iso(), "used_ip": ip}},
    )
    # Any OTHER unused tokens for this user become invalid — belt-and-
    # braces so a leaked earlier link can't be replayed.
    await db.password_reset_tokens.update_many(
        {"user_id": user["id"], "used_at": None, "token": {"$ne": tok}},
        {"$set": {"invalidated_at": now_iso()}},
    )
    await _audit_auth("password_reset_complete", user.get("email", ""), ip,
                      "success", f"user_id={user['id']}")
    return {"ok": True, "message": "Password reset. Please sign in."}


def _password_reset_email_html(*, first_name: str, reset_link: str,
                                 expiry_minutes: int) -> str:
    """Render the Task-O password-reset email body. Kept inline to
    avoid a new template collection; visual polish can graduate to
    the ``email_templates`` seed later (``password_reset_self_serve``)."""
    return (
        f"<div style=\"font-family:-apple-system,'Inter',sans-serif;"
        f"color:#0F172A;max-width:560px;margin:0 auto;padding:24px;\">"
        f"<h2 style=\"margin:0 0 12px;\">Reset your password</h2>"
        f"<p style=\"margin:0 0 12px;font-size:15px;line-height:1.55;\">"
        f"Hi {first_name},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:1.55;\">"
        f"We received a request to reset your Pool &amp; Landscaping "
        f"portal password. Click the button below to choose a new one.</p>"
        f"<p style=\"margin:24px 0;\">"
        f"<a href=\"{reset_link}\" "
        f"style=\"display:inline-block;background:#0284C7;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;"
        f"font-weight:600;\">Reset password</a></p>"
        f"<p style=\"margin:0 0 8px;font-size:13px;color:#475569;\">"
        f"This link expires in {expiry_minutes} minutes. If you didn't "
        f"request this reset you can safely ignore this email — your "
        f"password won't change.</p>"
        f"<p style=\"margin:16px 0 0;font-size:12px;color:#94A3B8;"
        f"word-break:break-all;\">"
        f"Or copy this link into your browser:<br/>"
        f"<a href=\"{reset_link}\" style=\"color:#475569;\">{reset_link}</a>"
        f"</p></div>"
    )


# ══════════════════════════════════════════════════════════════════════
# Phase 34 · Task O · Feb-2026 — In-portal "Change password" endpoint
# ══════════════════════════════════════════════════════════════════════
class ChangeMyPasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
async def change_my_password(request: Request,
                               body: ChangeMyPasswordRequest,
                               user: dict = Depends(get_current_user)):
    """Authenticated portal user updates their own password.

    Requires the current password (enforced via ``verify_password``)
    AND the same strength policy the reset flow uses. Returns 400
    with a clear message on any failure — no silent no-ops.
    """
    ip = _client_ip(request)
    if not body.current_password or not body.new_password:
        raise HTTPException(400, "Current and new password are required.")

    # Fetch WITH password_hash — ``get_current_user`` strips it.
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(body.current_password,
                                        full.get("password_hash", "")):
        await _audit_auth("password_change", user.get("email", ""), ip,
                          "failure", "bad_current_password")
        raise HTTPException(400, "Current password is incorrect.")

    err = _password_policy_ok(body.new_password)
    if err:
        raise HTTPException(400, err)

    new_hash = hash_password(body.new_password)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": new_hash,
            "failed_login_attempts": 0,
            "lockout_until": None,
            "must_change_password_on_next_login": False,
            "password_updated_at": now_iso(),
        }},
    )
    await _audit_auth("password_change", user.get("email", ""), ip, "success")
    return {"ok": True, "message": "Password updated."}


@router.post("/admin/impersonate/{customer_id}")
async def impersonate_customer(customer_id: str,
                                tenant_id: Optional[str] = None,
                                admin: dict = Depends(require_admin)):
    """Admin obtains a customer-scoped session token to view the app exactly as the customer.
    The token carries an `act` claim identifying the admin so the session can be reverted.

    Super admins may pass `?tenant_id=X` to impersonate a customer in a different tenant.
    Regular admins are restricted to their own tenant."""
    q = {"id": customer_id}
    if admin.get("role") == "super_admin" and tenant_id:
        q["tenant_id"] = tenant_id
    else:
        # Regular admin — restrict to their own tenant
        q["tenant_id"] = admin.get("tenant_id")
    customer = await db.customers.find_one(q, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")
    cust_user_q = {"customer_id": customer_id, "role": "customer",
                   "tenant_id": customer.get("tenant_id")}
    cust_user = await db.users.find_one(cust_user_q, {"_id": 0})
    if not cust_user:
        raise HTTPException(400, "This customer has no login yet. Create a login for them first.")
    await db.audit_logs.insert_one({
        "id": new_id(),
        "tenant_id": customer.get("tenant_id"),
        "event": "impersonation_started",
        "admin_id": admin["id"], "admin_name": admin.get("name", ""),
        "admin_role": admin.get("role"),
        "target_customer_id": customer_id, "target_user_id": cust_user["id"],
        "target_tenant_id": customer.get("tenant_id"),
        "cross_tenant": admin.get("tenant_id") != customer.get("tenant_id"),
        "created_at": now_iso(),
    })
    return auth_response(cust_user, impersonator_id=admin["id"], impersonator_name=admin.get("name", "Admin"))


@router.post("/auth/revert-impersonation")
async def revert_impersonation(user: dict = Depends(get_current_user)):
    """End an impersonation session and restore the original admin session."""
    admin_id = user.get("impersonator_id")
    if not admin_id:
        raise HTTPException(403, "Not an active impersonation session")
    admin_user = await db.users.find_one(
        {"id": admin_id, "role": {"$in": ["admin", "super_admin"]}}, {"_id": 0}
    )
    if not admin_user:
        raise HTTPException(403, "Admin authorization is no longer valid")
    await db.audit_logs.insert_one({
        "id": new_id(),
        "tenant_id": user.get("tenant_id"),
        "event": "impersonation_ended",
        "admin_id": admin_id, "target_user_id": user.get("id"),
        "created_at": now_iso(),
    })
    return auth_response(admin_user)


@router.get("/admin/access-history")
async def access_history(admin: dict = Depends(require_admin),
                          all_tenants: bool = False):
    """Audit trail of admin 'view as customer' sessions.

    SEC-003 hotfix: tenant-scoped by default. Super-admin may pass
    `?all_tenants=true` to cross tenants; that access is itself logged.
    """
    tenant_id = admin.get("tenant_id")
    q: dict = {"event": {"$in": ["impersonation_started", "impersonation_ended"]}}
    role = admin.get("role")
    cross = bool(all_tenants) and role == "super_admin"
    if not cross:
        q["tenant_id"] = tenant_id
    if cross:
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "event": "access_history_cross_tenant",
                "actor_id": admin.get("id"),
                "actor_email": admin.get("email"),
                "created_at": now_iso(),
            })
        except Exception:
            pass
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)
    cust_ids = list({l.get("target_customer_id") for l in logs if l.get("target_customer_id")})
    names: dict = {}
    if cust_ids:
        cust_q = {"id": {"$in": cust_ids}}
        if not cross:
            cust_q["tenant_id"] = tenant_id
        async for c in db.customers.find(cust_q, {"_id": 0, "id": 1, "name": 1}):
            names[c["id"]] = c.get("name", "")
    for l in logs:
        l["customer_name"] = names.get(l.get("target_customer_id"), "")
    return logs



