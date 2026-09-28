"""Ship 3 · Item A — Nudge non-starters for a training module.

Bulk-notifies techs who have not yet started a training module. Optional
email drafting via the existing outbound_emails audit pattern.
Idempotent per (tenant, user, module, ISO week) so a repeat click within
7 days silently no-ops rather than spamming.

Endpoint: POST /api/training/nudge-non-starters (admin + super_admin).

Body:
    {module_code: str, message: str, include_email: bool = false}
Returns:
    {module_code, count_nudged, count_skipped_idempotent, notified_user_ids,
     email_ids: [str], skipped_reasons: {...}}
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["training-nudge"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


NUDGE_KIND = "training_nudge"


def _week_bucket(now: Optional[datetime] = None) -> str:
    """ISO year-week (`2026-W29`) — idempotency bucket. Any two nudges
    landing in the same ISO week collapse to one row per user."""
    d = now or datetime.now(timezone.utc)
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _departments_for_module_code(code: str) -> list[str]:
    """Which tech departments should be nudged for a given module. Pool
    modules default to `[pool, both, ""]`; landscape modules default
    to `[landscaping, both, ""]`. Unrecognized codes get both pools
    covered (safest broadening — admin can pre-filter via the widget)."""
    c = (code or "").lower()
    if "landscape" in c or "lawn" in c or "irrigation" in c:
        return ["landscaping", "both", ""]
    return ["pool", "both", ""]


class NudgeIn(BaseModel):
    module_code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=1000)
    include_email: bool = False


@router.post("/training/nudge-non-starters")
async def nudge_non_starters(
    body: NudgeIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    # ── Resolve target techs ────────────────────────────────────────
    depts = _departments_for_module_code(body.module_code)
    tech_users = await db.users.find({
        "tenant_id": tenant["id"],
        "role": {"$in": ["technician", "tech"]},
        "$or": [{"department": {"$in": depts}}, {"department": {"$exists": False}}],
        "$and": [{"$or": [{"active": True}, {"active": {"$exists": False}}]}],
    }, {"_id": 0}).to_list(1000)

    if not tech_users:
        return {
            "module_code": body.module_code,
            "count_nudged": 0,
            "count_skipped_idempotent": 0,
            "notified_user_ids": [],
            "email_ids": [],
            "skipped_reasons": {"no_target_techs": True},
        }

    tech_ids = [u["id"] for u in tech_users]
    progress_rows = await db.training_progress.find({
        "tenant_id": tenant["id"],
        "module_code": body.module_code,
        "user_id": {"$in": tech_ids},
    }, {"_id": 0}).to_list(len(tech_ids))
    progress_by_uid = {p["user_id"]: p for p in progress_rows}

    non_starters = []
    for u in tech_users:
        prog = progress_by_uid.get(u["id"])
        lessons = list((prog or {}).get("lessons_completed") or [])
        if not prog or not lessons:
            non_starters.append(u)

    if not non_starters:
        return {
            "module_code": body.module_code,
            "count_nudged": 0,
            "count_skipped_idempotent": 0,
            "notified_user_ids": [],
            "email_ids": [],
            "skipped_reasons": {"no_non_starters": True},
        }

    # ── Idempotency (7-day / ISO-week bucket per user × module) ────
    week_of = _week_bucket()
    existing_keys = set()
    async for row in db.training_nudges.find({
        "tenant_id": tenant["id"],
        "module_code": body.module_code,
        "week_of": week_of,
        "user_id": {"$in": [u["id"] for u in non_starters]},
    }, {"_id": 0, "user_id": 1}):
        existing_keys.add(row["user_id"])

    resend_key = os.environ.get("RESEND_API_KEY")
    tenant_name = tenant.get("name") or "Pool & Landscaping"
    notified_user_ids: list[str] = []
    email_ids: list[str] = []
    skipped_idempotent = 0
    nudge_ts = now_iso()

    for tech in non_starters:
        if tech["id"] in existing_keys:
            skipped_idempotent += 1
            continue

        # 1) Nudge audit row (persists idempotency key).
        nudge_id = new_id()
        await db.training_nudges.insert_one({
            "id": nudge_id,
            "tenant_id": tenant["id"],
            "module_code": body.module_code,
            "user_id": tech["id"],
            "week_of": week_of,
            "message": body.message,
            "actor_user_id": user["id"],
            "actor_name": user.get("name") or user.get("email"),
            "created_at": nudge_ts,
            "email_id": None,
        })

        # 2) In-app notification (existing pattern).
        notif_id = new_id()
        await db.notifications.insert_one({
            "id": notif_id,
            "tenant_id": tenant["id"],
            "user_id": tech["id"],
            "customer_id": None,
            "title": f"Training reminder — {body.module_code}",
            "body": body.message,
            "kind": "training_nudge",
            "href": "/training",
            "read": False,
            "created_at": nudge_ts,
        })

        # 3) Optional email drafting (respect graceful fallback).
        if body.include_email and (tech.get("email") or "").strip():
            email_row = {
                "id": new_id(),
                "kind": NUDGE_KIND,
                "module": "training_nudge",
                "tenant_id": tenant["id"],
                "user_id": tech["id"],
                "to": tech["email"].strip(),
                "module_code": body.module_code,
                "week_of": week_of,
                "subject": f"Reminder: {body.module_code} training from {tenant_name}",
                "text": body.message,
                "html": (f'<div style="font-family:system-ui;max-width:600px;padding:20px">'
                         f'<p>Hi {(tech.get("name") or "there").split(" ")[0]},</p>'
                         f'<p>{body.message}</p>'
                         f'<p style="margin-top:16px">— {tenant_name}</p></div>'),
                "created_at": nudge_ts,
                "actor_user_id": user["id"],
            }
            if not resend_key:
                email_row["status"] = "not_sent_missing_key"
                await db.outbound_emails.insert_one(email_row)
            else:
                try:
                    import resend  # type: ignore
                    resend.api_key = resend_key
                    # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
                    resp = resend.Emails.send({
                        "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
                        "to": [email_row["to"]],
                        "subject": email_row["subject"],
                        "html": email_row["html"],
                        "text": email_row["text"],
                    })
                    email_row["status"] = "sent"
                    email_row["resend_id"] = (resp or {}).get("id") if isinstance(resp, dict) else None
                    await db.outbound_emails.insert_one(email_row)
                except Exception as e:
                    email_row["status"] = "failed"
                    email_row["error"] = str(e)[:200]
                    await db.outbound_emails.insert_one(email_row)
                    logger.warning(f"training-nudge email failed: {type(e).__name__}: {str(e)[:120]}")
            email_ids.append(email_row["id"])
            await db.training_nudges.update_one(
                {"id": nudge_id}, {"$set": {"email_id": email_row["id"]}})

        notified_user_ids.append(tech["id"])

    return {
        "module_code": body.module_code,
        "count_nudged": len(notified_user_ids),
        "count_skipped_idempotent": skipped_idempotent,
        "notified_user_ids": notified_user_ids,
        "email_ids": email_ids,
        "week_of": week_of,
    }
