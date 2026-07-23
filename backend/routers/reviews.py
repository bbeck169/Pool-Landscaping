"""Reviews Phase 1 · Backend router (Feb 2026).

First-class review-request lifecycle. Design decisions are locked in
``/app/memory/PRD.md``; the short version:

* 4 collections: ``reviews``, ``review_requests``,
  ``tenant_review_platforms``, ``private_feedback_events``.
* Magic-link tokens stored on the row (CSAT pattern) — one-shot,
  revocable, no expiry math in the code path.
* Star-gate is server-side: a 4-5 rating returns
  ``next_step=choose_platform``, a 1-3 rating returns
  ``next_step=private_feedback``.
* Public widget is CORS-open, rate-limited via
  ``services/reviews_rate_limit.py``.
* Comms integration uses the new catalog-syntax templates in
  ``comms_seed/system_data.py``; nothing in the legacy
  ``sequences.py`` / ``marketing_studio.py`` seed pool is touched.
"""
from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from config import db, logger
from routers.tenants import get_current_tenant
from services.reviews_rate_limit import check_and_charge, WIDGET_MAX_PER_MINUTE
from utils import (
    get_current_user, new_id, now_iso, require_admin,
    create_staff_notification,
)

router = APIRouter()

# ── constants ──────────────────────────────────────────────────────────
_PLATFORMS = {"google", "facebook", "yelp", "bbb", "custom"}
_SENT_VIA = {"email", "sms", "both", "link_only"}
_SOURCES = {"internal_capture", "google_scraped", "facebook_scraped",
             "yelp_scraped", "bbb_scraped", "manual_entry"}
_OUTCOMES = {"pending", "public_posted_intent", "private_feedback_captured",
              "expired", "opted_out"}
_TOKEN_PUBLIC_SUBMIT_HOURLY_CAP = 5      # per-token spam guard
_DEFAULT_EXPIRY_DAYS = 30
_REQUEST_DEDUP_DAYS = 7                  # 1 request per customer per week


def _new_token() -> str:
    # 32-char urlsafe token → ~192 bits. Matches spec "URL-safe 32-char".
    while True:
        t = secrets.token_urlsafe(24)
        if 30 <= len(t) <= 34:
            return t[:32]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _clean(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return d
    out = dict(d)
    out.pop("_id", None)
    return out


async def _ensure_indexes() -> None:
    try:
        await db.tenant_review_platforms.create_index(
            [("tenant_id", 1), ("platform", 1), ("custom_slug", 1)], unique=True,
        )
        await db.tenant_review_platforms.create_index(
            [("tenant_id", 1), ("is_active", 1), ("sort_order", 1)],
        )
        await db.review_requests.create_index("token", unique=True)
        await db.review_requests.create_index([("tenant_id", 1), ("outcome", 1)])
        await db.review_requests.create_index([("tenant_id", 1), ("customer_id", 1), ("sent_at", -1)])
        await db.review_requests.create_index(
            [("tenant_id", 1), ("technician_id", 1), ("star_rating_submitted", 1)],
        )
        await db.reviews.create_index([("tenant_id", 1), ("is_public", 1), ("star_rating", 1)])
        await db.reviews.create_index([("tenant_id", 1), ("technician_id", 1), ("star_rating", 1)])
        await db.reviews.create_index([("tenant_id", 1), ("created_at", -1)])
        await db.private_feedback_events.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception as e:
        logger.warning(f"[reviews] index setup partial: {e}")


# ═════════════════════════════════════════════════════════════════════════
# Platforms — admin CRUD
# ═════════════════════════════════════════════════════════════════════════

class PlatformIn(BaseModel):
    platform: str
    display_name: str = Field(..., min_length=1, max_length=80)
    review_url: str = Field(..., min_length=6, max_length=500)
    is_active: bool = True
    sort_order: int = 0
    custom_slug: Optional[str] = None

    @field_validator("platform")
    @classmethod
    def _plat(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(_PLATFORMS)}")
        return v


class PlatformPatch(BaseModel):
    display_name: Optional[str] = None
    review_url: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


@router.get("/platforms")
async def list_platforms(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    rows = await db.tenant_review_platforms.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("sort_order", 1).to_list(200)
    return {"platforms": rows}


@router.post("/platforms", status_code=201)
async def create_platform(body: PlatformIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    if body.platform == "custom" and not (body.custom_slug or "").strip():
        raise HTTPException(400, "custom platform requires custom_slug")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "platform": body.platform,
        "display_name": body.display_name.strip(),
        "review_url": body.review_url.strip(),
        "is_active": body.is_active,
        "sort_order": body.sort_order,
        "custom_slug": (body.custom_slug or None),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    try:
        await db.tenant_review_platforms.insert_one(doc)
    except Exception as e:
        # Unique-index violation on (tenant, platform, custom_slug).
        if "duplicate" in str(e).lower():
            raise HTTPException(409, "platform already configured for this tenant")
        raise
    return _clean(doc)


@router.patch("/platforms/{pid}")
async def patch_platform(pid: str, body: PlatformPatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    updates: Dict[str, Any] = {}
    for k in ("display_name", "review_url", "is_active", "sort_order"):
        v = getattr(body, k, None)
        if v is not None:
            updates[k] = v
    if not updates:
        raise HTTPException(422, "no fields to update")
    updates["updated_at"] = now_iso()
    res = await db.tenant_review_platforms.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if not res.matched_count:
        raise HTTPException(404, "platform not found")
    doc = await db.tenant_review_platforms.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return doc


@router.delete("/platforms/{pid}")
async def delete_platform(pid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    res = await db.tenant_review_platforms.delete_one(
        {"id": pid, "tenant_id": tenant["id"]},
    )
    if not res.deleted_count:
        raise HTTPException(404, "platform not found")
    return {"ok": True, "deleted": pid}


# ═════════════════════════════════════════════════════════════════════════
# Requests — admin + tech; hard 7-day dedup with super_admin bypass
# ═════════════════════════════════════════════════════════════════════════

class RequestIn(BaseModel):
    customer_id: str
    job_id: Optional[str] = None
    technician_id: Optional[str] = None
    sent_via: Literal["email", "sms", "both", "link_only"] = "email"
    channel_override: Optional[str] = None
    expedite: bool = False


def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


async def _recent_dup(tenant_id: str, customer_id: str) -> Optional[dict]:
    cutoff_iso = (_now_dt() - timedelta(days=_REQUEST_DEDUP_DAYS)).isoformat()
    return await db.review_requests.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "sent_at": {"$gte": cutoff_iso}},
        {"_id": 0, "id": 1, "sent_at": 1, "outcome": 1},
    )


async def _send_via_comms(tenant: dict, request_doc: dict, sent_via: str) -> List[str]:
    """Push the request through ``/api/comms`` delivery adapters. Returns
    the list of ``communication_sends.id`` created.

    ``link_only`` mode is a no-op — the URL will be handed back to the
    caller in the response payload for out-of-band sharing.
    """
    if sent_via == "link_only":
        return []

    from routers.comms import _deliver_one, _load_customer  # local import
    cust = await _load_customer(tenant["id"], request_doc["customer_id"])
    if not cust:
        logger.warning(f"[reviews] send skipped — customer not found for {request_doc['id']}")
        return []

    channels: List[str] = []
    if sent_via in ("email", "both"):
        channels.append("email")
    if sent_via in ("sms", "both"):
        channels.append("sms")

    template_email = "system.review_request_email"
    template_sms = "system.sms.review_request"

    # Extra context — the delivery adapter's ``build_context_for_customer``
    # doesn't know about review_request tokens, so we pre-render our
    # tokens into the customer sub-tree via a fake-inject on cust. But
    # the cleanest path: reach into ``services/comm_tokens`` and pre-
    # resolve tokens using our own context, then hand fully-rendered
    # subject / body to _deliver_one. However, _deliver_one already
    # takes template_code, so we depend on the template resolver seeing
    # our tokens. Solution: temporarily set on customer's tenant_context
    # via a companion function. Simplest: attach the extra tokens to a
    # module-level cache keyed by (tenant_id, customer_id) that
    # ``build_context_for_customer`` doesn't consult — so instead we
    # POST to the comms send-now endpoint indirectly by calling the
    # same deliver machinery and letting our context helper be invoked
    # via a lightweight monkey-patch on the customer doc: we stuff the
    # extra fields onto the ``cust`` dict so ``build_context_for_customer``
    # picks them up when they collide with its schema. Since our token
    # keys use the ``review_request.*`` / ``tech.*`` namespaces that
    # helper does NOT emit, we need a different path.
    #
    # Cleanest and lowest-risk: read the rendered blocks / body ourselves
    # here and write directly into ``communication_sends``. That's the
    # same path _deliver_one takes, but with our own context helper.
    from services.comm_tokens import (
        build_context_for_review_request, resolve_tokens, resolve_email_blocks,
        render_email_html,
    )
    from routers.comms import _find_email_template, _find_sms_template

    ctx = await build_context_for_review_request(tenant, request_doc)
    ctx["customer.email"] = cust.get("email") or ctx.get("customer.email") or ""
    ctx["customer.phone"] = cust.get("phone") or ctx.get("customer.phone") or ""

    send_ids: List[str] = []
    for ch in channels:
        if ch == "email":
            tpl = await _find_email_template(tenant["id"], template_email)
            if not tpl:
                logger.error(f"[reviews] missing template {template_email}")
                continue
            recipient = cust.get("email") or ""
            if not recipient:
                logger.info(f"[reviews] skip email — customer {cust.get('id')} has no email")
                continue
            resolved_subject = resolve_tokens(tpl["subject"] or "", ctx)
            resolved_html = render_email_html(tpl["blocks_json"] or [], ctx)
            send_doc = {
                "id": new_id(),
                "tenant_id": tenant["id"],
                "kind": "email",
                "channel": "email",
                "recipient_id": cust["id"],
                "recipient_address": recipient,
                "template_code": template_email,
                "subject": resolved_subject,
                "body_html": resolved_html,
                "status": "queued",
                "queued_at": now_iso(),
                "context_meta": {"review_request_id": request_doc["id"]},
            }
            await db.communication_sends.insert_one(send_doc)
            send_ids.append(send_doc["id"])
        else:  # sms
            tpl = await _find_sms_template(tenant["id"], template_sms)
            if not tpl:
                logger.error(f"[reviews] missing template {template_sms}")
                continue
            recipient = cust.get("phone") or ""
            if not recipient:
                logger.info(f"[reviews] skip sms — customer {cust.get('id')} has no phone")
                continue
            resolved_body = resolve_tokens(tpl["body"] or "", ctx)
            send_doc = {
                "id": new_id(),
                "tenant_id": tenant["id"],
                "kind": "sms",
                "channel": "sms",
                "recipient_id": cust["id"],
                "recipient_address": recipient,
                "template_code": template_sms,
                "body_text": resolved_body,
                "status": "queued",
                "queued_at": now_iso(),
                "context_meta": {"review_request_id": request_doc["id"]},
            }
            await db.communication_sends.insert_one(send_doc)
            send_ids.append(send_doc["id"])

    return send_ids


@router.post("/requests", status_code=201)
async def create_request(body: RequestIn,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    if _role(user) not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Only admins and technicians can send review requests")

    await _ensure_indexes()

    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    # 7-day dedup — super_admin can bypass with expedite=true.
    if not (body.expedite and _role(user) == "super_admin"):
        dup = await _recent_dup(tenant["id"], body.customer_id)
        if dup:
            raise HTTPException(
                409,
                {"detail": "A review request was already sent to this customer "
                            f"within the last {_REQUEST_DEDUP_DAYS} days",
                 "duplicate_of": dup.get("id"),
                 "sent_at": dup.get("sent_at")},
            )

    tech_id = body.technician_id
    job = None
    if body.job_id:
        job = await db.jobs.find_one(
            {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if job and not tech_id:
            tech_id = job.get("technician_id") or job.get("assigned_tech_id")

    now_iso_s = now_iso()
    expiry = (_now_dt() + timedelta(days=_DEFAULT_EXPIRY_DAYS)).isoformat()
    request_doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "token": _new_token(),
        "customer_id": body.customer_id,
        "job_id": body.job_id,
        "technician_id": tech_id,
        "sent_via": body.sent_via,
        "sent_at": now_iso_s,
        "communication_send_ids": [],
        "landing_visited_at": None,
        "star_rating_submitted": None,
        "star_submitted_at": None,
        "platform_chosen": None,
        "platform_clicked_at": None,
        "outcome": "pending",
        "expires_at": expiry,
        "created_by_user_id": user.get("id"),
        "created_at": now_iso_s,
    }
    await db.review_requests.insert_one(request_doc)

    # Deliver.
    send_ids = await _send_via_comms(tenant, request_doc, body.sent_via)
    if send_ids:
        await db.review_requests.update_one(
            {"id": request_doc["id"]},
            {"$set": {"communication_send_ids": send_ids}},
        )
        request_doc["communication_send_ids"] = send_ids

    # Add public_url for out-of-band sharing (link_only) or admin display.
    import os
    origin = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    public_url = f"{origin}/reviews/r/{request_doc['token']}" if origin else ""

    return {**_clean(request_doc), "public_url": public_url}


@router.get("/requests")
async def list_requests(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant),
                         status: Optional[str] = Query(None, alias="status"),
                         customer_id: Optional[str] = Query(None),
                         technician_id: Optional[str] = Query(None),
                         limit: int = Query(50, ge=1, le=500)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["outcome"] = status
    if customer_id:
        q["customer_id"] = customer_id
    if technician_id:
        q["technician_id"] = technician_id
    rows = await db.review_requests.find(q, {"_id": 0}).sort("sent_at", -1).to_list(limit)
    return {"requests": rows}


@router.get("/requests/{rid}")
async def get_request(rid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.review_requests.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.post("/requests/{rid}/resend")
async def resend_request(rid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    if _role(user) not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Only admins and technicians can resend")
    doc = await db.review_requests.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Not found")
    if _role(user) != "super_admin":
        dup = await _recent_dup(tenant["id"], doc["customer_id"])
        if dup and dup.get("id") != rid:
            raise HTTPException(409, "another review-request within 7 days blocks resend")
    new_send_ids = await _send_via_comms(tenant, doc, doc.get("sent_via") or "email")
    merged = list((doc.get("communication_send_ids") or []) + new_send_ids)
    await db.review_requests.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"communication_send_ids": merged, "sent_at": now_iso()}},
    )
    return {"ok": True, "resent_send_ids": new_send_ids}


# ═════════════════════════════════════════════════════════════════════════
# Feb-2026 · Item 8 — bulk review-request creation
# ═════════════════════════════════════════════════════════════════════════
class BulkRequestIn(BaseModel):
    customer_ids: List[str] = Field(..., min_length=1, max_length=500)
    sent_via: str = "both"
    skip_dedup: bool = False

    @field_validator("sent_via")
    @classmethod
    def _sent(cls, v: str) -> str:
        v = (v or "both").lower()
        if v not in _SENT_VIA:
            raise ValueError(f"sent_via must be one of {sorted(_SENT_VIA)}")
        return v


@router.post("/requests/bulk", status_code=201,
              operation_id="reviews.bulkRequest")
async def bulk_request(body: BulkRequestIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Item 8 — enqueue a review request for every listed
    customer. Skips customers with a duplicate in the last 7 days
    unless ``skip_dedup=true`` (super_admin only). Returns per-row
    outcome for admin display."""
    if _role(user) not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    await _ensure_indexes()

    results: List[Dict[str, Any]] = []
    for cid in body.customer_ids:
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not cust:
            results.append({"customer_id": cid, "status": "not_found"})
            continue
        if not (body.skip_dedup and _role(user) == "super_admin"):
            dup = await _recent_dup(tenant["id"], cid)
            if dup:
                results.append({"customer_id": cid, "status": "duplicate",
                                  "duplicate_of": dup.get("id")})
                continue
        request_doc = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "token": _new_token(),
            "customer_id": cid,
            "job_id": None,
            "technician_id": None,
            "sent_via": body.sent_via,
            "sent_at": now_iso(),
            "communication_send_ids": [],
            "landing_visited_at": None,
            "star_rating_submitted": None,
            "star_submitted_at": None,
            "platform_chosen": None,
            "platform_clicked_at": None,
            "outcome": "pending",
            "expires_at": (_now_dt() + timedelta(days=_DEFAULT_EXPIRY_DAYS)).isoformat(),
            "created_by_user_id": user.get("id"),
            "created_at": now_iso(),
            "auto_source": "bulk_admin",
        }
        await db.review_requests.insert_one(request_doc)
        send_ids = await _send_via_comms(tenant, request_doc, body.sent_via)
        if send_ids:
            await db.review_requests.update_one(
                {"id": request_doc["id"]},
                {"$set": {"communication_send_ids": send_ids}},
            )
        results.append({"customer_id": cid, "status": "queued",
                          "request_id": request_doc["id"]})
    return {
        "total": len(body.customer_ids),
        "queued": sum(1 for r in results if r["status"] == "queued"),
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"),
        "not_found": sum(1 for r in results if r["status"] == "not_found"),
        "results": results,
    }


# ═════════════════════════════════════════════════════════════════════════
# PUBLIC magic-link endpoints — no auth
# ═════════════════════════════════════════════════════════════════════════

async def _throttle_public(token: str, kind: str) -> None:
    """Per-token spam guard for public submits — 5 hits/hour keyed on
    (token, kind). Wrote inline (rather than into
    ``services/reviews_rate_limit.py``) because the semantics differ:
    that service throttles anonymous widget reads, this one guards
    write actions on a specific token."""
    cutoff = (_now_dt() - timedelta(hours=1)).isoformat()
    count = await db.review_request_hits.count_documents({
        "token": token, "kind": kind, "ts": {"$gte": cutoff},
    })
    if count >= _TOKEN_PUBLIC_SUBMIT_HOURLY_CAP:
        raise HTTPException(429, "Too many submissions for this link. Try again later.")
    await db.review_request_hits.insert_one({
        "token": token, "kind": kind, "ts": now_iso(),
    })


async def _resolve_public_request(token: str) -> dict:
    doc = await db.review_requests.find_one({"token": token}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invalid or expired link")
    now_iso_s = now_iso()
    if doc.get("expires_at") and doc["expires_at"] < now_iso_s:
        # Auto-flip outcome for observability.
        if doc.get("outcome") == "pending":
            await db.review_requests.update_one(
                {"id": doc["id"]}, {"$set": {"outcome": "expired"}},
            )
            doc["outcome"] = "expired"
    return doc


@router.get("/public/r/{token}")
async def public_landing(token: str):
    doc = await _resolve_public_request(token)
    tenant = await db.tenants.find_one({"id": doc["tenant_id"]}, {"_id": 0})
    customer = await db.customers.find_one(
        {"id": doc.get("customer_id"), "tenant_id": doc["tenant_id"]},
        {"_id": 0, "name": 1, "first_name": 1, "email": 1},
    )
    tech = None
    if doc.get("technician_id"):
        tech = await db.technicians.find_one(
            {"id": doc["technician_id"]}, {"_id": 0, "name": 1},
        )
    platforms = await db.tenant_review_platforms.find(
        {"tenant_id": doc["tenant_id"], "is_active": True},
        {"_id": 0},
    ).sort("sort_order", 1).to_list(20)

    # Feb-2026 · Item 8 fallback — when no platforms are configured
    # we still want a Google CTA on 4-5 star flow. Read the tenant
    # business_card.google_review_url; if THAT is empty too, fall
    # back to a Google search URL for the company name so the funnel
    # never dead-ends.
    if not platforms:
        settings = (tenant or {}).get("settings") or {}
        card = settings.get("business_card") or {}
        google_url = card.get("google_review_url")
        company = card.get("company_name") or (tenant or {}).get("name") or "Business"
        if not google_url:
            import urllib.parse as _up
            google_url = (
                "https://www.google.com/search?q="
                + _up.quote_plus(f"{company} reviews")
            )
        platforms = [{
            "platform": "google", "display_name": "Google",
            "review_url": google_url,
            "_synthetic_from_business_card": True,
        }]

    # Mark first-hit visit.
    if not doc.get("landing_visited_at"):
        await db.review_requests.update_one(
            {"id": doc["id"]}, {"$set": {"landing_visited_at": now_iso()}},
        )

    cust_first = (customer or {}).get("first_name") or (
        ((customer or {}).get("name") or "").split(" ", 1)[0]
    )
    tech_full = (tech or {}).get("name") or ""
    tech_first = tech_full.split(" ", 1)[0] if tech_full else ""

    return {
        "tenant_name": (tenant or {}).get("name") or "",
        "tenant_logo_url": (tenant or {}).get("logo_url") or "",
        "tenant_slug": (tenant or {}).get("slug") or "",
        "customer_first_name": cust_first or "",
        "tech_first_name": tech_first or "",
        "platforms": [
            {"platform": p["platform"], "display_name": p["display_name"],
             "review_url": p["review_url"]}
            for p in platforms
        ],
        "expired": doc["outcome"] == "expired",
        "already_submitted": doc.get("star_rating_submitted") is not None,
        "star_rating_submitted": doc.get("star_rating_submitted"),
        "outcome": doc["outcome"],
    }


class RatingIn(BaseModel):
    star_rating: int = Field(..., ge=1, le=5)


@router.post("/public/r/{token}/rating")
async def submit_rating(token: str, body: RatingIn):
    await _throttle_public(token, "rating")
    doc = await _resolve_public_request(token)
    if doc["outcome"] == "expired":
        raise HTTPException(410, "This link has expired")
    if doc.get("star_rating_submitted") is not None:
        raise HTTPException(409, "This link has already been submitted")

    star = body.star_rating
    next_step = "choose_platform" if star >= 4 else "private_feedback"
    updates = {
        "star_rating_submitted": star,
        "star_submitted_at": now_iso(),
    }
    await db.review_requests.update_one({"id": doc["id"]}, {"$set": updates})

    # Unified notifications — always fire ``review_received``. If the
    # star rating trips the low-star threshold (≤3) we ALSO fire
    # ``review_low_star`` so admins with the highlight kind toggled on
    # get an escalated ping regardless of whether they muted the
    # broad "review_received" category.
    try:
        from services.notifications import enqueue_for_tenant_admins
        customer = await db.customers.find_one(
            {"id": doc.get("customer_id"), "tenant_id": doc["tenant_id"]},
            {"_id": 0, "name": 1}) if doc.get("customer_id") else None
        who = (customer or {}).get("name") or "Anonymous"
        await enqueue_for_tenant_admins(
            doc["tenant_id"], "review_received",
            title=f"{star}★ review · {who}",
            body=f"Customer submitted a {star}-star rating.",
            source_ref={"kind": "review_request", "id": doc["id"]},
            href=f"/reviews/requests/{doc['id']}",
            priority=("high" if star <= 3 else "normal"),
        )
        if star <= 3:
            await enqueue_for_tenant_admins(
                doc["tenant_id"], "review_low_star",
                title=f"Low-star review · {star}★ from {who}",
                body="Follow up privately — a low rating just came in.",
                source_ref={"kind": "review_request", "id": doc["id"]},
                href=f"/reviews/requests/{doc['id']}",
                priority="high",
            )
    except Exception as _e:
        logger.warning(f"[reviews] unified notify failed: {_e}")

    return {"next_step": next_step, "star_rating": star}


class PlatformClickedIn(BaseModel):
    platform_code: str


@router.post("/public/r/{token}/platform-clicked")
async def platform_clicked(token: str, body: PlatformClickedIn):
    await _throttle_public(token, "platform_clicked")
    doc = await _resolve_public_request(token)
    if doc["outcome"] == "expired":
        raise HTTPException(410, "This link has expired")
    star = doc.get("star_rating_submitted")
    if star is None or star < 4:
        raise HTTPException(400, "Platform selection is only available after a 4-5 star rating")

    plat_doc = await db.tenant_review_platforms.find_one(
        {"tenant_id": doc["tenant_id"], "platform": body.platform_code, "is_active": True},
        {"_id": 0},
    )
    if not plat_doc:
        raise HTTPException(404, "Platform not configured for this tenant")

    await db.review_requests.update_one(
        {"id": doc["id"]},
        {"$set": {
            "platform_chosen": body.platform_code,
            "platform_clicked_at": now_iso(),
            "outcome": "public_posted_intent",
        }},
    )
    return {"redirect_url": plat_doc["review_url"]}


class PrivateFeedbackIn(BaseModel):
    body_text: str = Field(..., min_length=1, max_length=4000)


@router.post("/public/r/{token}/private-feedback")
async def private_feedback(token: str, body: PrivateFeedbackIn):
    await _throttle_public(token, "private_feedback")
    doc = await _resolve_public_request(token)
    if doc["outcome"] == "expired":
        raise HTTPException(410, "This link has expired")
    star = doc.get("star_rating_submitted")
    if star is None or star >= 4:
        raise HTTPException(
            400,
            "Private feedback is only available after a 1-3 star rating",
        )

    now_iso_s = now_iso()

    # 1) Persist the private_feedback_events row.
    pf_id = new_id()
    await db.private_feedback_events.insert_one({
        "id": pf_id,
        "tenant_id": doc["tenant_id"],
        "review_request_id": doc["id"],
        "customer_id": doc.get("customer_id"),
        "star_rating": star,
        "body_text": body.body_text.strip(),
        "admin_emails_notified": [],
        "created_at": now_iso_s,
    })

    # 2) Persist a matching reviews row (private, not visible on widget).
    review_id = new_id()
    await db.reviews.insert_one({
        "id": review_id,
        "tenant_id": doc["tenant_id"],
        "source": "internal_capture",
        "source_review_id": None,
        "review_request_id": doc["id"],
        "customer_id": doc.get("customer_id"),
        "technician_id": doc.get("technician_id"),
        "star_rating": star,
        "review_text": body.body_text.strip(),
        "reviewer_name": None,
        "platform": "private",
        "is_public": False,
        "visible_on_widget": False,
        "admin_response": None,
        "admin_response_at": None,
        "created_at": now_iso_s,
    })

    # 3) Flip the request outcome.
    await db.review_requests.update_one(
        {"id": doc["id"]},
        {"$set": {"outcome": "private_feedback_captured"}},
    )

    # 4) Admin notification — reuse the create_staff_notification helper
    # and the comms admin-alert template for email delivery.
    try:
        await create_staff_notification(
            title=f"Private feedback · {star}★",
            body=body.body_text[:200],
            tenant_id=doc["tenant_id"],
        )
    except Exception as e:
        logger.warning(f"[reviews] staff notification failed: {e}")

    admins_notified: List[str] = []
    try:
        from services.comm_tokens import (
            build_context_for_review_request, resolve_tokens, render_email_html,
        )
        from routers.comms import _find_email_template
        tenant = await db.tenants.find_one({"id": doc["tenant_id"]}, {"_id": 0})
        tpl = await _find_email_template(doc["tenant_id"], "system.review_private_feedback_admin_alert")
        if tenant and tpl:
            ctx = await build_context_for_review_request(tenant, doc)
            subject = resolve_tokens(tpl["subject"] or "", ctx)
            html_body = render_email_html(tpl["blocks_json"] or [], ctx)
            admin_users = await db.users.find(
                {"tenant_id": doc["tenant_id"], "role": {"$in": ["admin", "super_admin"]}},
                {"_id": 0, "email": 1},
            ).to_list(50)
            for a in admin_users:
                if not a.get("email"):
                    continue
                await db.communication_sends.insert_one({
                    "id": new_id(),
                    "tenant_id": doc["tenant_id"],
                    "kind": "email",
                    "channel": "email",
                    "recipient_id": None,
                    "recipient_address": a["email"],
                    "template_code": "system.review_private_feedback_admin_alert",
                    "subject": subject,
                    "body_html": html_body,
                    "status": "queued",
                    "queued_at": now_iso(),
                    "context_meta": {
                        "review_request_id": doc["id"],
                        "private_feedback_id": pf_id,
                    },
                })
                admins_notified.append(a["email"])
        if admins_notified:
            await db.private_feedback_events.update_one(
                {"id": pf_id},
                {"$set": {"admin_emails_notified": admins_notified}},
            )
    except Exception as e:
        logger.warning(f"[reviews] admin alert email failed: {e}")

    return {"ok": True, "private_feedback_id": pf_id, "review_id": review_id,
            "admin_emails_notified": len(admins_notified)}


# ═════════════════════════════════════════════════════════════════════════
# Reviews CRUD — admin
# ═════════════════════════════════════════════════════════════════════════

class ReviewIn(BaseModel):
    star_rating: int = Field(..., ge=1, le=5)
    review_text: Optional[str] = None
    reviewer_name: Optional[str] = None
    platform: str = "manual"
    customer_id: Optional[str] = None
    technician_id: Optional[str] = None
    is_public: bool = True
    visible_on_widget: Optional[bool] = None


class ReviewPatch(BaseModel):
    admin_response: Optional[str] = None
    visible_on_widget: Optional[bool] = None


@router.get("/reviews")
async def list_reviews(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant),
                        platform: Optional[str] = None,
                        min_star: Optional[int] = None,
                        is_public: Optional[bool] = None,
                        technician_id: Optional[str] = None,
                        limit: int = Query(50, ge=1, le=500)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if platform: q["platform"] = platform
    if min_star is not None: q["star_rating"] = {"$gte": min_star}
    if is_public is not None: q["is_public"] = is_public
    if technician_id: q["technician_id"] = technician_id
    rows = await db.reviews.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"reviews": rows}


@router.get("/reviews/{rid}")
async def get_review(rid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    doc = await db.reviews.find_one({"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Review not found")
    return doc


@router.post("/reviews", status_code=201)
async def create_review(body: ReviewIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    visible = body.visible_on_widget
    if visible is None:
        visible = body.is_public and body.star_rating >= 4
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "source": "manual_entry",
        "source_review_id": None,
        "review_request_id": None,
        "customer_id": body.customer_id,
        "technician_id": body.technician_id,
        "star_rating": body.star_rating,
        "review_text": (body.review_text or "").strip() or None,
        "reviewer_name": (body.reviewer_name or "").strip() or None,
        "platform": body.platform,
        "is_public": body.is_public,
        "visible_on_widget": visible,
        "admin_response": None,
        "admin_response_at": None,
        "created_at": now_iso(),
    }
    await db.reviews.insert_one(doc)
    return _clean(doc)


@router.patch("/reviews/{rid}")
async def patch_review(rid: str, body: ReviewPatch,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    updates: Dict[str, Any] = {}
    if body.admin_response is not None:
        updates["admin_response"] = body.admin_response.strip() or None
        updates["admin_response_at"] = now_iso() if updates["admin_response"] else None
    if body.visible_on_widget is not None:
        updates["visible_on_widget"] = body.visible_on_widget
    if not updates:
        raise HTTPException(422, "no fields to update")
    res = await db.reviews.update_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if not res.matched_count:
        raise HTTPException(404, "Review not found")
    return await db.reviews.find_one({"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/reviews/{rid}")
async def delete_review(rid: str,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    res = await db.reviews.delete_one({"id": rid, "tenant_id": tenant["id"]})
    if not res.deleted_count:
        raise HTTPException(404, "Review not found")
    return {"ok": True, "deleted": rid}


# ═════════════════════════════════════════════════════════════════════════
# Aggregations — admin
# ═════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def review_stats(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    q = {"tenant_id": tenant["id"]}
    total = await db.reviews.count_documents(q)
    count_public = await db.reviews.count_documents({**q, "is_public": True})
    count_private = total - count_public

    count_by_star: Dict[str, int] = {str(i): 0 for i in range(1, 6)}
    count_by_platform: Dict[str, int] = {}
    sum_stars = 0
    async for r in db.reviews.find(q, {"_id": 0, "star_rating": 1, "platform": 1}):
        star = r.get("star_rating") or 0
        if 1 <= star <= 5:
            count_by_star[str(star)] += 1
            sum_stars += star
        plat = r.get("platform") or "unknown"
        count_by_platform[plat] = count_by_platform.get(plat, 0) + 1
    avg_star = round(sum_stars / total, 2) if total else 0.0

    thirty_days_ago = (_now_dt() - timedelta(days=30)).isoformat()
    delta_30d = await db.reviews.count_documents(
        {**q, "created_at": {"$gte": thirty_days_ago}},
    )
    return {
        "total": total, "avg_star": avg_star,
        "count_by_star": count_by_star,
        "count_by_platform": count_by_platform,
        "count_public": count_public, "count_private": count_private,
        "delta_last_30d": delta_30d,
    }


@router.get("/leaderboard")
async def review_leaderboard(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant),
                              min_reviews: int = Query(3, ge=1, le=50)):
    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "technician_id": {"$ne": None}}},
        {"$group": {
            "_id": "$technician_id",
            "review_count": {"$sum": 1},
            "avg_star": {"$avg": "$star_rating"},
            "five_star_count": {"$sum": {"$cond": [{"$eq": ["$star_rating", 5]}, 1, 0]}},
        }},
        {"$match": {"review_count": {"$gte": min_reviews}}},
        {"$sort": {"avg_star": -1, "review_count": -1}},
    ]
    rows = []
    async for r in db.reviews.aggregate(pipeline):
        tech = await db.technicians.find_one({"id": r["_id"]}, {"_id": 0, "name": 1})
        rows.append({
            "technician_id": r["_id"],
            "technician_name": (tech or {}).get("name") or "Unknown",
            "review_count": r["review_count"],
            "avg_star": round(r["avg_star"], 2),
            "five_star_count": r["five_star_count"],
        })
    return {"leaderboard": rows}


# ═════════════════════════════════════════════════════════════════════════
# PUBLIC widget — rate-limited, CORS-open
# ═════════════════════════════════════════════════════════════════════════

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",", 1)[0].strip()
    return (request.client.host if request.client else "") or ""


@router.get("/public/widget/{tenant_slug}.js")
async def public_widget_js(tenant_slug: str, request: Request):
    ip = _client_ip(request)
    allowed, _ = await check_and_charge(ip, tenant_slug)
    if not allowed:
        return Response(
            content="console.warn('[reviews-widget] rate-limited');",
            media_type="application/javascript",
            headers={"Retry-After": "60", "Access-Control-Allow-Origin": "*"},
        )

    tenant = await db.tenants.find_one({"slug": tenant_slug, "active": True}, {"_id": 0})
    if not tenant:
        return Response(content="/* unknown workspace */", status_code=404,
                         media_type="application/javascript")

    # ``html.escape`` escapes both HTML entities AND quote characters, so
    # even if a review contained script markup the browser sees inert
    # text. All strings interpolated below are pre-escaped in JS on the
    # client side too (defense-in-depth).
    slug = html.escape(tenant_slug, quote=True)

    # The JS below is intentionally dependency-free — a single fetch,
    # inert DOM injection with ``textContent`` on user-supplied strings,
    # and a minimal star-row painter.
    js = (
        "(function(){"
        f"var TENANT_SLUG={_json(slug)};"
        "var ORIGIN=(document.currentScript && document.currentScript.src)"
        "  ? new URL(document.currentScript.src).origin : (window.location && window.location.origin) || '';"
        "var API=ORIGIN+'/api/reviews/public/widget/'+encodeURIComponent(TENANT_SLUG);"
        "var mount=document.getElementById('pool-crm-reviews');"
        "if(!mount){return;}"
        "function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}"
        "function stars(n){var out='';for(var i=0;i<5;i++){out+=(i<n?'\\u2605':'\\u2606');}return out;}"
        "fetch(API,{headers:{'Accept':'application/json'}}).then(function(r){return r.json();}).then(function(d){"
        "  var html=''+"
        "    '<div style=\"font-family:sans-serif;\">'+"
        "    '<div style=\"display:flex;align-items:baseline;gap:8px;margin-bottom:12px;\">'+"
        "      '<span style=\"font-size:24px;font-weight:700;\">'+esc((d.avg_star||0).toFixed(1))+'</span>'+"
        "      '<span style=\"color:#f6ac0a;font-size:18px;\">'+esc(stars(Math.round(d.avg_star||0)))+'</span>'+"
        "      '<span style=\"color:#666;font-size:13px;\">based on '+esc(d.total_public||0)+' reviews</span>'+"
        "    '</div>';"
        "  (d.reviews||[]).forEach(function(rv){"
        "    html+='<div style=\"padding:10px 0;border-top:1px solid #eee;\">'+"
        "      '<div style=\"color:#f6ac0a;font-size:14px;\">'+esc(stars(rv.star_rating||0))+'</div>'+"
        "      '<div style=\"font-size:14px;margin:4px 0;\">'+esc(rv.review_text||'')+'</div>'+"
        "      '<div style=\"color:#666;font-size:12px;\">— '+esc(rv.reviewer_name||'Anonymous')+' via '+esc(rv.platform||'')+'</div>'+"
        "      '</div>';"
        "  });"
        "  html+='</div>';"
        "  mount.innerHTML=html;"
        "}).catch(function(){"
        "  mount.textContent='(reviews temporarily unavailable)';"
        "});"
        "})();"
    )
    return Response(
        content=js,
        media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/public/widget/{tenant_slug}")
async def public_widget(tenant_slug: str, request: Request,
                         limit: int = Query(20, ge=1, le=100),
                         offset: int = Query(0, ge=0, le=1000)):
    # Route order matters: the ``.js`` variant is declared FIRST so
    # FastAPI matches it before this catch-all — otherwise ``.js`` would
    # be consumed as the slug value.
    if tenant_slug.endswith(".js"):
        # Belt-and-suspenders: some proxies rewrite the path; delegate.
        return await public_widget_js(tenant_slug[:-3], request)

    ip = _client_ip(request)
    allowed, count = await check_and_charge(ip, tenant_slug)
    if not allowed:
        return Response(
            status_code=429,
            content='{"detail":"Rate limit exceeded"}',
            media_type="application/json",
            headers={
                "Retry-After": "60",
                "X-Rate-Limit-Max": str(WIDGET_MAX_PER_MINUTE),
                "Access-Control-Allow-Origin": "*",
            },
        )

    tenant = await db.tenants.find_one({"slug": tenant_slug, "active": True}, {"_id": 0})
    if not tenant:
        raise HTTPException(404, "Unknown workspace")

    q = {"tenant_id": tenant["id"], "is_public": True, "visible_on_widget": True,
         "review_text": {"$ne": None, "$exists": True}}
    total = await db.reviews.count_documents(q)

    rows = await db.reviews.find(
        q, {"_id": 0, "star_rating": 1, "review_text": 1, "reviewer_name": 1,
            "platform": 1, "created_at": 1},
    ).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)

    # avg over ALL public reviews (with or without text).
    q_all_public = {"tenant_id": tenant["id"], "is_public": True}
    total_public = await db.reviews.count_documents(q_all_public)
    sum_stars = 0
    count_star = 0
    async for r in db.reviews.find(q_all_public, {"_id": 0, "star_rating": 1}):
        s = r.get("star_rating") or 0
        if 1 <= s <= 5:
            sum_stars += s
            count_star += 1
    avg = round(sum_stars / count_star, 2) if count_star else 0.0

    return Response(
        content='{'
                f'"tenant_name":{_json(tenant.get("name") or "")},'
                f'"avg_star":{avg},'
                f'"total_public":{total_public},'
                f'"total_with_text":{total},'
                f'"reviews":{_json_rows(rows)}'
                '}',
        media_type="application/json",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=60",
        },
    )


def _json(s: Any) -> str:
    import json
    return json.dumps(s)


def _json_rows(rows: List[dict]) -> str:
    import json
    return json.dumps(rows, default=str)
