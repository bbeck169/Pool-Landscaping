"""Feb-2026 · Slice 6 — Customer-portal review widget (rating-gated).

This is a separate surface from the pre-existing ``routers/reviews.py``
(the magic-link CSAT system mounted under ``/api/reviews/*``).  The
Slice 6 flow lives entirely inside the authenticated customer portal
so a logged-in customer can drop a review straight from the "Leave a
Review" tab — no email token dance required.

The review flow is deliberately split at the 4-star boundary:

* ``rating < 4`` — private feedback path.  Stored with
  ``is_public=false``, immediately escalates to the admin group
  (internal message + bell + best-effort push, reusing the Slice 3D
  infrastructure), and the customer sees a "Thank you — we'll follow
  up" screen.
* ``rating >= 4`` — public review path.  Stored with ``is_public=true``.
  If the tenant has configured ``google_review_url``, the endpoint
  returns it in the response so the frontend can render a big CTA
  routing the happy customer to Google to leave the public rating.
  A missing URL is logged (admin will see the warning line in the
  service logs) and the frontend renders a graceful thank-you
  without the CTA.

Every read/write is scoped by ``tenant_id + customer_id`` — cross-
tenant / cross-customer leaks are impossible by construction.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def _require_customer(user: dict) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(403, "Customer id missing on user")
    return cid


_RATE_LIMIT_WINDOW = timedelta(minutes=5)


async def _too_soon(tenant_id: str, customer_id: str) -> bool:
    """1 portal-review per 5 minutes per customer — cheap guard
    against accidental double-taps and spammy bots.  Scoped to the
    Slice 6 doc kind so the pre-existing magic-link reviews don't
    accidentally trip the limiter."""
    cutoff = (datetime.now(timezone.utc) - _RATE_LIMIT_WINDOW).isoformat()
    last = await db.customer_portal_reviews.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1},
    )
    return last is not None


# Acceptable Google review URL shapes.  We reject anything that
# doesn't obviously target Google to avoid tenants pasting a Yelp /
# Facebook link into the wrong slot.
_GOOGLE_URL_PATTERN = re.compile(
    r"^https?://("
    r"(www\.)?google\.[a-z.]{2,10}(/.+)?"
    r"|g\.page(/.+)?"
    r"|(www\.)?maps\.google\.[a-z.]{2,10}(/.+)?"
    r"|search\.google\.com/local/writereview\?.+"
    r")$",
    re.IGNORECASE,
)


def _looks_like_google_url(url: str) -> bool:
    return bool(_GOOGLE_URL_PATTERN.match((url or "").strip()))


# ═══════════════════════════════════════════════════════════════════════
# Customer routes
# ═══════════════════════════════════════════════════════════════════════
class ReviewIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = ""
    service_report_id: Optional[str] = None

    @field_validator("comment", mode="before")
    @classmethod
    def _default_comment(cls, v):
        return "" if v is None else str(v)


@router.post("/customer-portal/reviews", status_code=201)
async def submit_review(
    body: ReviewIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Submit a review from the authenticated customer portal.

    Response shape::

        {
          "ok": true,
          "review_id": "...",
          "is_public": true|false,
          "google_review_url": "https://…" | null
        }
    """
    cid = _require_customer(user)

    if await _too_soon(tenant["id"], cid):
        raise HTTPException(
            429,
            "Please wait a few minutes before submitting another review.",
        )

    is_public = body.rating >= 4
    rid = new_id()
    doc = {
        "id": rid,
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "customer_name": user.get("name") or "Customer",
        "rating": int(body.rating),
        "comment": body.comment.strip(),
        "is_public": is_public,
        "google_redirect": False,
        "status": "new",
        "created_at": now_iso(),
        "read_at": None,
        "admin_notes": "",
        "service_report_id": body.service_report_id,
    }
    await db.customer_portal_reviews.insert_one(doc)

    google_url: Optional[str] = None
    if is_public:
        t = await db.tenants.find_one(
            {"id": tenant["id"]}, {"_id": 0, "google_review_url": 1},
        ) or {}
        google_url = t.get("google_review_url")
        if google_url:
            await db.customer_portal_reviews.update_one(
                {"id": rid}, {"$set": {"google_redirect": True}},
            )
        else:
            logger.warning(
                "review %s: tenant %s has no google_review_url configured — "
                "customer sees graceful thank-you without CTA",
                rid, tenant["id"],
            )
    else:
        # Private feedback → fire the Slice 3D escalation.
        try:
            from services.notifications import enqueue_for_tenant_admins

            title = (
                f"Private review from {user.get('name') or 'Customer'}"
                f" · {body.rating}★"
            )
            summary = (body.comment or "").strip()[:200] or "(no comment)"
            msg_id = new_id()
            await db.messages.insert_one({
                "id": msg_id,
                "tenant_id": tenant["id"],
                "customer_id": cid,
                "sender": "customer",
                "sender_name": user.get("name") or "Customer",
                "text": f"{title}\n\n{summary}",
                "kind": "review",
                "review": {
                    "review_id": rid,
                    "rating": body.rating,
                    "is_public": False,
                },
                "read_by_customer": True,
                "read_by_staff": False,
                "created_at": now_iso(),
            })
            await enqueue_for_tenant_admins(
                tenant["id"],
                kind="inbound_customer_message",
                title=title,
                body=summary,
                source_ref={
                    "kind": "review",
                    "review_id": rid,
                    "customer_id": cid,
                    "message_id": msg_id,
                },
                href=f"/communication/{cid}",
                priority="high",
            )
        except Exception as exc:  # pragma: no cover — logged, never blocks
            logger.warning("review %s escalation failed: %s", rid, exc)

    # Feb-2026 · Marketing Slice M5c — drip event bus (review_left).
    try:
        from services.marketing.drip_events import on_event as _drip_on_event
        await _drip_on_event("review_left", tenant["id"], cid)
    except Exception:
        pass

    return {
        "ok": True,
        "review_id": rid,
        "is_public": is_public,
        "google_review_url": google_url,
    }


@router.get("/customer-portal/reviews/my")
async def list_my_reviews(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    rows = await db.customer_portal_reviews.find(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0, "admin_notes": 0, "status": 0},   # hide admin-only fields
    ).sort("created_at", -1).to_list(50)
    return rows


# ═══════════════════════════════════════════════════════════════════════
# Admin routes
# ═══════════════════════════════════════════════════════════════════════
@router.get("/admin/reviews")
async def list_admin_reviews(
    is_public: Optional[bool] = Query(None),
    status: Optional[str] = Query(None),
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    max_rating: Optional[int] = Query(None, ge=1, le=5),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if is_public is not None:
        q["is_public"] = is_public
    if status:
        q["status"] = status
    if min_rating is not None or max_rating is not None:
        band: Dict[str, Any] = {}
        if min_rating is not None:
            band["$gte"] = int(min_rating)
        if max_rating is not None:
            band["$lte"] = int(max_rating)
        q["rating"] = band
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = since
        if until:
            rng["$lte"] = until
        q["created_at"] = rng

    total = await db.customer_portal_reviews.count_documents(q)
    rows = await db.customer_portal_reviews.find(q, {"_id": 0}).sort(
        "created_at", -1,
    ).skip(offset).limit(limit).to_list(limit)
    new_count = await db.customer_portal_reviews.count_documents(
        {"tenant_id": tenant["id"], "status": "new"},
    )
    return {
        "reviews": rows,
        "total": total,
        "new_count": new_count,
        "limit": limit,
        "offset": offset,
    }


class ReviewPatch(BaseModel):
    status: Optional[str] = None
    admin_notes: Optional[str] = None
    read: Optional[bool] = None


@router.patch("/admin/reviews/{rid}")
async def patch_admin_review(
    rid: str,
    body: ReviewPatch,
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.customer_portal_reviews.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Review not found")
    patch: Dict[str, Any] = {}
    if body.status is not None:
        if body.status not in ("new", "read", "resolved", "escalated"):
            raise HTTPException(422, "Invalid status")
        patch["status"] = body.status
    if body.admin_notes is not None:
        patch["admin_notes"] = str(body.admin_notes)
    if body.read is True and not row.get("read_at"):
        patch["read_at"] = now_iso()
        if not patch.get("status"):
            patch["status"] = "read"
    if not patch:
        return row
    await db.customer_portal_reviews.update_one({"id": rid}, {"$set": patch})
    row.update(patch)
    return row


# ═══════════════════════════════════════════════════════════════════════
# Tenant Google review URL — read (any auth role) + write (super_admin)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/tenants/mine/google-review-url")
async def get_google_review_url(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Customer needs it to click through, admin needs it for the
    # settings screen. Tech also allowed — the URL itself isn't
    # sensitive and keeping the read policy permissive prevents
    # future integrations from bumping into a spurious 403.
    t = await db.tenants.find_one(
        {"id": tenant["id"]}, {"_id": 0, "google_review_url": 1},
    ) or {}
    return {"url": t.get("google_review_url")}


class GoogleUrlIn(BaseModel):
    url: str


@router.patch("/tenants/mine/google-review-url")
async def set_google_review_url(
    body: GoogleUrlIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    url = (body.url or "").strip()
    if url and not _looks_like_google_url(url):
        raise HTTPException(
            422,
            "URL must be a Google review link — e.g. "
            "https://g.page/r/... or "
            "https://search.google.com/local/writereview?placeid=...",
        )
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"google_review_url": url or None,
                    "updated_at": now_iso()}},
    )
    return {"url": url or None}
