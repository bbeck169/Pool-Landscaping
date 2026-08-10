from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timezone, timedelta
import os
import uuid
import jwt
import bcrypt

from config import db, JWT_SECRET, JWT_ALGO, TOKEN_EXPIRE_MINUTES, logger

security = HTTPBearer(auto_error=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def create_token(user: dict, impersonator_id: str = None) -> str:
    # Impersonation tokens carry an `act` (actor) claim (RFC 8693) identifying the
    # admin behind the session and use a shorter expiry.
    exp_minutes = 30 if impersonator_id else TOKEN_EXPIRE_MINUTES
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=exp_minutes),
    }
    if impersonator_id:
        payload["act"] = {"sub": impersonator_id}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Feb-2026 · Team page admin actions — hard-401 any request from a
    # soft-deleted user. This gives real "kick them out now" semantics
    # for the ``POST /users/{uid}/soft-delete`` endpoint: existing JWTs
    # stop working on the very next request rather than waiting for
    # natural token expiry.
    if user.get("deleted_at"):
        raise HTTPException(status_code=401, detail="account_deleted")
    # SEC-004 hotfix — cached (30s TTL) active-state check. Existing tokens
    # for a deactivated user stop working within one cache window.
    if _active_is_false(user):
        raise HTTPException(status_code=401, detail="Account is deactivated")
    # Surface impersonation context so sensitive endpoints can guard against it.
    act = payload.get("act") or {}
    if act.get("sub"):
        user["is_impersonated"] = True
        user["impersonator_id"] = act["sub"]
    return user


_ACTIVE_CACHE: dict = {}
_ACTIVE_TTL = 30.0  # seconds

def _active_is_false(user: dict) -> bool:
    import time as _t
    uid = user.get("id")
    if not uid:
        return False
    now = _t.time()
    hit = _ACTIVE_CACHE.get(uid)
    if hit and (now - hit[0]) < _ACTIVE_TTL:
        return hit[1] == False  # noqa: E712 — explicit False match (not None/0/'')
    active = user.get("active")
    _ACTIVE_CACHE[uid] = (now, active)
    return active == False  # noqa: E712 — explicit False match (not None/0/'')


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    # Phase 34 · Task X · Feb 2026 — admin-equivalent roles. Any user
    # whose role is ``admin``, ``super_admin``, or ``owner`` on the
    # acting tenant passes this gate. Cross-tenant scoping is still
    # enforced downstream via ``get_current_tenant`` on every mutating
    # endpoint, so a tenant-A admin remains unable to edit tenant-B
    # jobs.
    if user.get("role") not in ("admin", "super_admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


# Feb-2026 · Phase 2 REWORK addendum — GPS read lockdown.
#
# The human owner tightened GPS visibility: read access to every GPS
# feature (live positions, stops, route, geofences, scorecard, exports,
# settings) is restricted to admin / super_admin / manager / dispatcher
# / owner. Techs and customers are explicitly denied — techs still POST
# pings (that path is deliberately not gated by this dep) but they must
# not READ any GPS data. Applied at include_router() time in server.py
# so every route on a gated router picks up the guard uniformly.
_GPS_READ_ROLES = {"admin", "super_admin", "owner", "manager", "dispatcher"}


def require_gps_read(user: dict = Depends(get_current_user)) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _GPS_READ_ROLES:
        raise HTTPException(status_code=403,
                             detail="GPS access restricted to admin, super admin, manager, or dispatcher")
    return user


# Phase 56.9b Step 8 — RBAC gate for Zillow-backed surfaces (property
# lookup, save/list/delete, D2D sold-leads canvassing). Techs get access
# to the same data admins do, but the paid endpoints are additionally
# rate-limited + budget-guarded via services.zillow_rate_limit. Customers
# + anonymous callers are still blocked.
def require_zillow_access(user: dict = Depends(get_current_user)) -> dict:
    # Phase 5A · Feb 2026 — Property Lookup / Zillow enrichment is now
    # admin/manager only. Techs get 403 (the tile was also removed from
    # every tech nav surface, see roleNav.js + ToolsHub.jsx). Marketing
    # still has a separate audience-segmentation path via
    # marketing_forms.py; no change there.
    role = (user or {}).get("role")
    if role in ("super_admin", "admin", "manager"):
        return user
    raise HTTPException(status_code=403, detail="Property Lookup requires admin or manager role")


# Feb-2026 · Weather widget on tech dashboard header — techs need
# read access to the proxied WeatherAPI.com endpoints, and admins
# need it too for testing / preview. Customers + anonymous stay
# blocked.
def require_tech_or_admin(user: dict = Depends(get_current_user)) -> dict:
    role = (user or {}).get("role")
    if role in ("super_admin", "admin", "technician"):
        return user
    raise HTTPException(status_code=403, detail="Tech or admin required")


def deny_impersonation(user: dict) -> None:
    """Block money-moving / credential actions while an admin is viewing as a customer."""
    if user.get("is_impersonated"):
        raise HTTPException(status_code=403, detail="This action is disabled while viewing as a customer.")


def send_sms(to: str, body: str) -> bool:
    """Legacy sync-return SMS helper.

    Feb-2026 · Twilio→RC consolidation — delegates to the shipped
    RingCentral adapter (``services.sms.rc_adapter.send``). The adapter
    is async; we hop threads via ``asyncio.run`` (safe here because this
    helper is invoked from sync fire-and-forget code paths like
    ``notify_customer``). Returns True on any successful queue/send,
    False otherwise — matches the historical return shape callers
    already handle."""
    if not to:
        return False
    try:
        import asyncio
        # Lazy import to break circular dep with routers/marketing_preferences
        # which in turn imports helpers from this module.  # noqa: E402
        from services.sms.rc_adapter import send as _sms_send

        async def _go():
            return await _sms_send(to=to, body=body, category="transactional")

        try:
            # Running under an existing loop? Delegate to it.
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            res = asyncio.run(_go())
        else:
            fut = asyncio.run_coroutine_threadsafe(_go(), loop)
            res = fut.result(timeout=15)
        provider = res.get("provider")
        status = res.get("provider_status")
        # RC adapter returns provider="ringcentral" on live sends,
        # "mock" when unconfigured, and provider_status="dry_run" when
        # the comms_env_guard blocks the send. Only accept live RC
        # successes as True.
        return (provider == "ringcentral"
                and status in ("queued", "sent", "delivered", "accepted"))
    except Exception as e:
        logger.warning(f"SMS send failed: {e}")
        return False


async def notify_customer(customer_id: str, title: str, body: str, job_id: str = None, sms: bool = False):
    if not customer_id:
        return
    cust_user = await db.users.find_one({"customer_id": customer_id, "role": "customer"}, {"_id": 0})
    # Resolve tenant so the notification is visible under the tenant-scoped GET /notifications.
    tenant_id = (cust_user or {}).get("tenant_id")
    if not tenant_id:
        cust_doc = await db.customers.find_one({"id": customer_id}, {"_id": 0, "tenant_id": 1})
        tenant_id = (cust_doc or {}).get("tenant_id")
    notif = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "user_id": cust_user["id"] if cust_user else None,
        "customer_id": customer_id,
        "title": title,
        "body": body,
        "job_id": job_id,
        "read": False,
        "created_at": now_iso(),
    }
    await db.notifications.insert_one(notif)
    await _push_notification(notif)
    if sms:
        cust = await db.customers.find_one({"id": customer_id}, {"_id": 0})
        if cust and cust.get("phone"):
            send_sms(cust["phone"], f"{title}: {body}")


async def notify_technician(technician_id: str, title: str, body: str, job_id: str = None):
    """In-app notification to a single technician's user account."""
    if not technician_id:
        return
    u = await db.users.find_one({"technician_id": technician_id, "role": "technician"}, {"_id": 0})
    if not u:
        return
    notif = {
        "id": new_id(), "tenant_id": u.get("tenant_id"),
        "user_id": u["id"], "customer_id": None,
        "title": title, "body": body, "job_id": job_id,
        "read": False, "created_at": now_iso(),
    }
    await db.notifications.insert_one(notif)
    await _push_notification(notif)


async def create_staff_notification(title: str, body: str, job_id: str = None, tenant_id: str = None):
    """Create an in-app notification for every admin user (optionally scoped to one tenant)."""
    q = {"role": "admin"}
    if tenant_id:
        q["tenant_id"] = tenant_id
    admins = await db.users.find(q, {"_id": 0, "id": 1, "tenant_id": 1}).to_list(500)
    for a in admins:
        notif = {
            "id": new_id(), "tenant_id": a.get("tenant_id") or tenant_id,
            "user_id": a["id"], "customer_id": None,
            "title": title, "body": body, "job_id": job_id,
            "read": False, "created_at": now_iso(),
        }
        await db.notifications.insert_one(notif)
        await _push_notification(notif)


async def _push_notification(notif: dict) -> None:
    """Best-effort realtime fan-out. Silent no-op if the bus isn't importable
    (e.g. during isolated unit tests)."""
    try:
        from routers.realtime import bus  # local import to avoid circular
    except Exception:
        return
    user_id = notif.get("user_id")
    if not user_id:
        return
    try:
        await bus.broadcast(user_id, {
            "type": "notification",
            "payload": {
                "id": notif["id"],
                "title": notif.get("title"),
                "body": notif.get("body"),
                "job_id": notif.get("job_id"),
                "created_at": notif.get("created_at"),
            },
        })
    except Exception as e:
        logger.warning(f"realtime push failed: {e}")
    # Phase 15C — also fire an Expo mobile push if the user has registered devices.
    try:
        from routers.mobile_push import send_push_to_user  # local import to avoid circular
        await send_push_to_user(user_id, notif.get("title", ""), notif.get("body", ""),
                                data={"notification_id": notif.get("id"), "job_id": notif.get("job_id")})
    except Exception:
        pass



def auth_response(user: dict, impersonator_id: str = None, impersonator_name: str = None):
    token = create_token(user, impersonator_id=impersonator_id)
    # BUG E — expose the server-authoritative ToS gate flag so the
    # frontend gate can render immediately after login without an extra
    # /auth/me roundtrip. Import inline to avoid a boot-time cycle.
    from config_tos import compute_must_accept_tos
    resp = {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"], "email": user["email"], "role": user["role"],
            "name": user.get("name", ""), "avatar": user.get("avatar", ""),
            "technician_id": user.get("technician_id"),
            "customer_id": user.get("customer_id"),
            # Phase 49.3 — expose `department` so the web + mobile
            # LandscapingClockWidget can self-hide for non-landscaping users
            # without an extra /auth/me roundtrip.
            "department": user.get("department"),
            # BUG E — ToS gate fields. ``must_accept_tos`` is the ONLY
            # value the frontend should key off; the other two are for
            # display / debugging only.
            "must_accept_tos": compute_must_accept_tos(user),
            "tos_version_accepted": user.get("tos_version_accepted"),
            "tos_accepted_at": user.get("tos_accepted_at"),
        },
    }
    if impersonator_id:
        resp["impersonating"] = True
        resp["impersonator_name"] = impersonator_name or "Admin"
    return resp

