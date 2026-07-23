"""Feb-2026 · One-shot idempotent migration.

Transfers ownership of every 3rd-party integration in the aquaterra
tenant to a new super_admin user ``brian@plofv.com``. Also updates
``business_card.email`` + ``internal_lead_notifications`` to route
to Brian.

Idempotent — running twice is a no-op. Called from the boot
lifecycle in ``server.py``. Return payload includes:

* ``brian_user_id``          — new or existing.
* ``temp_password``           — set only when Brian was CREATED this
                                run (None on subsequent runs).
* ``owner_report``           — post-migration table of integration
                                ownership.
"""
from __future__ import annotations

import os
import secrets
import string
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import hash_password, new_id, now_iso


BRIAN_EMAIL = "brian@plofv.com"
TENANT_SLUG = "aquaterra"


def _strong_password(n: int = 16) -> str:
    alpha = string.ascii_letters + string.digits + "!@#$%^*+-="
    while True:
        pw = "".join(secrets.choice(alpha) for _ in range(n))
        if (any(c.islower() for c in pw)
                and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and any(c in "!@#$%^*+-=" for c in pw)):
            return pw


async def _find_aquaterra_tenant() -> Optional[Dict[str, Any]]:
    return await db.tenants.find_one(
        {"$or": [{"slug": TENANT_SLUG}, {"name": {"$regex": TENANT_SLUG, "$options": "i"}}]},
        {"_id": 0},
    )


async def _ensure_brian_user(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Create Brian's admin user if missing. Idempotent — returns the
    existing row on subsequent runs. Sets Brian as super_admin so he
    can manage everything. When creating for the first time we also
    demote the seeded admin@aquaterra.com from super_admin (if that's
    its role) to plain admin, so the tenant has exactly one super
    admin slot occupied by Brian."""
    existing = await db.users.find_one(
        {"email": BRIAN_EMAIL}, {"_id": 0},
    )
    if existing:
        return {"user": existing, "created": False, "temp_password": None}

    temp_pw = _strong_password()
    uid = new_id()
    row = {
        "id": uid,
        "tenant_id": tenant["id"],
        "email": BRIAN_EMAIL,
        "name": "Brian Beck",
        "first_name": "Brian",
        "last_name": "Beck",
        "role": "super_admin",
        "phone": tenant.get("settings", {}).get("internal_lead_notifications", {}).get("sms_to") or "",
        "password_hash": hash_password(temp_pw),
        "must_change_password_on_next_login": True,
        "has_seen_customer_tour": True,   # admin never sees the customer tour
        "created_at": now_iso(),
        "created_by": "migration.transfer_integrations_to_brian",
    }
    await db.users.insert_one(row)

    # Demote a legacy super_admin if it's the seeded admin@aquaterra.com
    # and there's a conflict — otherwise leave it alone.
    try:
        legacy = await db.users.find_one(
            {"email": "admin@aquaterra.com", "role": "super_admin",
             "tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "email": 1},
        )
        if legacy:
            await db.users.update_one(
                {"id": legacy["id"]},
                {"$set": {"role": "admin",
                            "demoted_at": now_iso(),
                            "demoted_by": "migration.transfer_integrations_to_brian"}},
            )
            logger.info(
                "[migration:brian] demoted legacy super_admin %s → admin",
                legacy.get("email"),
            )
    except Exception as e:
        logger.warning(f"[migration:brian] legacy demote failed: {e}")

    # Send the welcome email (best-effort).
    try:
        await _send_admin_welcome_email(tenant, row, temp_pw)
    except Exception as e:
        logger.warning(f"[migration:brian] welcome email failed: {e}")

    return {"user": row, "created": True, "temp_password": temp_pw}


async def _send_admin_welcome_email(
    tenant: Dict[str, Any], brian: Dict[str, Any], temp_pw: str,
) -> None:
    from services.email.resend_adapter import send as _resend_send
    from urllib.parse import urljoin

    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    company_display = card.get("company_name") or tenant.get("name") or "AquaTerra"
    origin = os.environ.get("FRONTEND_BASE_URL") or "https://app.aquaterra.com"
    login_url = urljoin(origin.rstrip("/") + "/", "login")
    html = f"""<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f4f6f8;padding:24px 0;margin:0;color:#111827">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <h1 style="margin:0 0 12px 0;font-size:20px">You're the {company_display} admin, Brian 🎉</h1>
  <p style="margin:0 0 16px 0;line-height:1.55">
    Every 3rd-party integration on the platform has been transferred
    to your account. Sign in with the temporary password below —
    you'll be asked to change it on first login.
  </p>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin:0 0 20px 0">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px">Temporary password</div>
    <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;font-weight:600">{temp_pw}</div>
  </div>
  <p style="text-align:center;margin:0 0 22px 0">
    <a href="{login_url}" style="background:#0f766e;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">Sign in</a>
  </p>
</div></body></html>"""
    subject = f"You're the {company_display} admin"
    result = await _resend_send(
        to=BRIAN_EMAIL, subject=subject, html=html,
        category="transactional",
        idempotency_key=f"brian-welcome-{brian['id']}",
        tenant_id=tenant["id"],
    )
    status = result.get("provider_status") or "failed"
    try:
        await db.communications_log.insert_one({
            "id": new_id(), "tenant_id": tenant["id"], "channel": "email",
            "to": BRIAN_EMAIL, "subject": subject,
            "template": "admin_account_created_email",
            "status": status, "provider": result.get("provider") or "resend",
            "provider_response_id": result.get("provider_response_id"),
            "error": result.get("error"),
            "trigger_entity": {"kind": "admin_account_created", "id": brian["id"]},
            "created_at": now_iso(),
        })
    except Exception:
        pass


async def _reassign_ownership(tenant: Dict[str, Any], brian_id: str) -> Dict[str, Any]:
    """Point every integration ownership field on the tenant doc at
    Brian. Also updates ``business_card.email`` and
    ``internal_lead_notifications.email_to``. Returns a diff so the
    caller can audit."""
    tid = tenant["id"]
    settings = tenant.get("settings") or {}
    integrations = settings.get("integrations") or {}
    diff: Dict[str, Any] = {}

    updates: Dict[str, Any] = {}

    known_integrations = [
        "stripe", "ringcentral", "resend", "google_maps",
        "openweb_ninja_zillow", "cloudflare_turnstile", "emergent_llm",
    ]
    for kind in known_integrations:
        block = dict(integrations.get(kind) or {})
        prev_owner = block.get("owned_by_user_id")
        if prev_owner != brian_id:
            block["owned_by_user_id"] = brian_id
            block["admin_user_id"] = brian_id
            block["contact_user_id"] = brian_id
            block["last_owner_transfer_at"] = now_iso()
            diff[kind] = {"old": prev_owner, "new": brian_id}
        integrations[kind] = block
    updates["settings.integrations"] = integrations

    # business_card.email → Brian's email.
    card = dict(settings.get("business_card") or {})
    if card.get("email") != BRIAN_EMAIL:
        diff["business_card.email"] = {"old": card.get("email"), "new": BRIAN_EMAIL}
        card["email"] = BRIAN_EMAIL
    updates["settings.business_card"] = card

    # internal_lead_notifications.email_to → Brian's email.
    ilnf = dict(settings.get("internal_lead_notifications") or {})
    if ilnf.get("email_to") != BRIAN_EMAIL:
        diff["internal_lead_notifications.email_to"] = {
            "old": ilnf.get("email_to"), "new": BRIAN_EMAIL,
        }
        ilnf["email_to"] = BRIAN_EMAIL
    updates["settings.internal_lead_notifications"] = ilnf

    if diff:
        await db.tenants.update_one({"id": tid}, {"$set": updates})
        await db.audit_log.insert_one({
            "id": new_id(), "tenant_id": tid,
            "actor_user_id": None,
            "action": "integrations.owner_transfer",
            "changes": diff,
            "at": now_iso(),
            "notes": "brian@plofv.com set as owner of every integration",
        })

    return diff


async def _owner_report_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    settings = t.get("settings") or {}
    integrations = settings.get("integrations") or {}
    rows: List[Dict[str, Any]] = []
    for kind, block in integrations.items():
        owner_id = (block or {}).get("owned_by_user_id")
        owner = None
        if owner_id:
            owner = await db.users.find_one(
                {"id": owner_id}, {"_id": 0, "email": 1, "name": 1},
            )
        rows.append({
            "integration": kind,
            "owner_user_id": owner_id,
            "owner_email": (owner or {}).get("email"),
            "owner_name": (owner or {}).get("name"),
        })
    return sorted(rows, key=lambda r: r["integration"])


async def run() -> Dict[str, Any]:
    tenant = await _find_aquaterra_tenant()
    if not tenant:
        logger.warning("[migration:brian] aquaterra tenant not found — skip")
        return {"ok": False, "reason": "tenant_not_found"}

    ensured = await _ensure_brian_user(tenant)
    brian = ensured["user"]
    diff = await _reassign_ownership(tenant, brian["id"])
    report = await _owner_report_for_tenant(tenant["id"])
    if ensured["created"] or diff:
        logger.info(
            "[migration:brian] created_user=%s diff_keys=%s",
            ensured["created"], sorted(diff.keys()),
        )
    return {
        "ok": True,
        "brian_user_id": brian["id"],
        "brian_user_created": ensured["created"],
        "temp_password": ensured["temp_password"],
        "diff": diff,
        "owner_report": report,
    }
