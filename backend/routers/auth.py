from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import _ensure_default_tenant
from models import *

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
    await _audit_auth("login", email, ip, "success")
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
        tenant = await db.tenants.find_one({"slug": slug, "active": True}, {"_id": 0})
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
    return user


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
async def access_history(admin: dict = Depends(require_admin)):
    """Audit trail of admin 'view as customer' sessions."""
    logs = await db.audit_logs.find(
        {"event": {"$in": ["impersonation_started", "impersonation_ended"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(300)
    # Enrich started events with the customer's name.
    cust_ids = list({l.get("target_customer_id") for l in logs if l.get("target_customer_id")})
    names = {}
    if cust_ids:
        async for c in db.customers.find({"id": {"$in": cust_ids}}, {"_id": 0, "id": 1, "name": 1}):
            names[c["id"]] = c.get("name", "")
    for l in logs:
        l["customer_name"] = names.get(l.get("target_customer_id"), "")
    return logs



