"""Feb-2026 · Item 8 — Auto-trigger a review request after a job is
marked completed.

Tenant opt-out via ``tenants.settings.review_auto_request_after_job``
(default: True — Aquaterra + all new tenants get it on by default).

Dedup: never fires if a review_request already exists for this
customer within the last 14 days. This is stricter than the manual
7-day dedup guard so a manual send from the admin never races an
auto-send back-to-back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from config import db, logger


async def maybe_auto_request_after_job(
    tenant: Dict[str, Any], job: Dict[str, Any]
) -> Optional[str]:
    """Returns the new review-request id, or None if we skipped."""
    settings = (tenant or {}).get("settings") or {}
    if settings.get("review_auto_request_after_job") is False:
        return None
    # Feb-2026 (BUG-C+ follow-up) — recurring jobs (weekly service
    # plans etc.) must NEVER auto-trigger a review request. The
    # tenant would carpet-bomb their customers every week.
    if job.get("is_recurring") is True:
        return None
    if job.get("recurring_template_id"):
        return None
    tid = tenant.get("id")
    cid = job.get("customer_id")
    if not tid or not cid:
        return None

    # 14-day dedup.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    dup = await db.review_requests.find_one(
        {"tenant_id": tid, "customer_id": cid, "sent_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1},
    )
    if dup:
        logger.info(
            "[review-auto] skip customer=%s job=%s (dedup)",
            cid, job.get("id"),
        )
        return None

    # Delegate to the standard create path so all downstream
    # bookkeeping (comms sends, notifications, logging) stays in one
    # place. We hand-craft the model bypass to skip the FastAPI
    # dependency chain — instead call the helper directly.
    from routers.reviews import (
        _new_token, _DEFAULT_EXPIRY_DAYS, _send_via_comms,
    )
    from utils import new_id, now_iso

    request_doc = {
        "id": new_id(),
        "tenant_id": tid,
        "token": _new_token(),
        "customer_id": cid,
        "job_id": job.get("id"),
        "technician_id": job.get("technician_id") or job.get("assigned_tech_id"),
        "sent_via": settings.get("review_auto_request_channel") or "both",
        "sent_at": now_iso(),
        "communication_send_ids": [],
        "landing_visited_at": None,
        "star_rating_submitted": None,
        "star_submitted_at": None,
        "platform_chosen": None,
        "platform_clicked_at": None,
        "outcome": "pending",
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=_DEFAULT_EXPIRY_DAYS)
        ).isoformat(),
        "created_by_user_id": None,
        "created_at": now_iso(),
        "auto_source": "job_completed",
    }
    await db.review_requests.insert_one(request_doc)
    try:
        send_ids = await _send_via_comms(
            tenant, request_doc, request_doc["sent_via"]
        )
        if send_ids:
            await db.review_requests.update_one(
                {"id": request_doc["id"]},
                {"$set": {"communication_send_ids": send_ids}},
            )
    except Exception as e:
        logger.warning(f"[review-auto] send failed: {e}")
    return request_doc["id"]
