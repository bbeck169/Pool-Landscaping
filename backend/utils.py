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
    # Surface impersonation context so sensitive endpoints can guard against it.
    act = payload.get("act") or {}
    if act.get("sub"):
        user["is_impersonated"] = True
        user["impersonator_id"] = act["sub"]
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def deny_impersonation(user: dict) -> None:
    """Block money-moving / credential actions while an admin is viewing as a customer."""
    if user.get("is_impersonated"):
        raise HTTPException(status_code=403, detail="This action is disabled while viewing as a customer.")


def send_sms(to: str, body: str) -> bool:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    frm = os.environ.get("TWILIO_FROM_NUMBER")
    if not (sid and token and frm and to):
        return False  # SMS not configured — in-app notification still delivered
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(to=to, from_=frm, body=body)
        return True
    except Exception as e:
        logger.warning(f"SMS send failed: {e}")
        return False


async def notify_customer(customer_id: str, title: str, body: str, job_id: str = None, sms: bool = False):
    if not customer_id:
        return
    cust_user = await db.users.find_one({"customer_id": customer_id, "role": "customer"}, {"_id": 0})
    notif = {
        "id": new_id(),
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
        "id": new_id(), "user_id": u["id"], "customer_id": None,
        "title": title, "body": body, "job_id": job_id,
        "read": False, "created_at": now_iso(),
    }
    await db.notifications.insert_one(notif)
    await _push_notification(notif)


async def create_staff_notification(title: str, body: str, job_id: str = None):
    """Create an in-app notification for every admin user."""
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1}).to_list(100)
    for a in admins:
        notif = {
            "id": new_id(), "user_id": a["id"], "customer_id": None,
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



def auth_response(user: dict, impersonator_id: str = None, impersonator_name: str = None):
    token = create_token(user, impersonator_id=impersonator_id)
    resp = {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"], "email": user["email"], "role": user["role"],
            "name": user.get("name", ""), "avatar": user.get("avatar", ""),
            "technician_id": user.get("technician_id"),
            "customer_id": user.get("customer_id"),
        },
    }
    if impersonator_id:
        resp["impersonating"] = True
        resp["impersonator_name"] = impersonator_name or "Admin"
    return resp

