"""Feb-2026 · Phase 20 P5 — NFC review-request card.

Public unauthenticated endpoint that returns the tenant's business
card + a fresh tokenized review-request URL. Rate limited: max 1
token per IP per 15 minutes to prevent scraping.

On first token issuance for a given IP, a lightweight review_request
row is created with fallback identity "Recent visitor" and a masked
IP tail (no PII).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from config import db, logger
from utils import new_id, now_iso

router = APIRouter(tags=["NFC Review Card"])

RATE_LIMIT_S = 15 * 60
_ip_cache: Dict[str, float] = {}


def _mask_ip(ip: str) -> str:
    if not ip:
        return "unknown"
    if ":" in ip:  # ipv6 — mask last 4 groups.
        parts = ip.split(":")
        return ":".join(parts[:4] + ["***"] * max(0, len(parts) - 4))
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.x.x"
    return "masked"


@router.get("/public/nfc-review-card/{tenant_slug}",
             operation_id="nfcReviewCard.get")
async def get_nfc_review_card(tenant_slug: str, request: Request):
    tenant = await db.tenants.find_one(
        {"$or": [{"slug": tenant_slug}, {"id": tenant_slug}]},
        {"_id": 0},
    )
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    client_ip = (
        (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
        or "unknown"
    )
    now = time.time()
    key = f"{tenant['id']}:{client_ip}"
    last = _ip_cache.get(key, 0)
    if now - last < RATE_LIMIT_S:
        raise HTTPException(
            429, f"Rate limit — please try again in "
                   f"{int(RATE_LIMIT_S - (now - last))}s")
    _ip_cache[key] = now

    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}

    # Create a fresh review_request row with a token so the customer
    # can rate. Reuse the existing helpers if available.
    from routers.reviews import _new_token, _DEFAULT_EXPIRY_DAYS
    from datetime import timedelta
    token = _new_token()
    review_req = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "token": token,
        "customer_id": None,   # walk-in / NFC visitor
        "customer_display_name": f"Recent visitor · IP-{_mask_ip(client_ip)}",
        "job_id": None,
        "technician_id": None,
        "sent_via": "nfc",
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
        "created_at": now_iso(),
        "auto_source": "nfc_card",
    }
    await db.review_requests.insert_one(review_req)

    return {
        "tenant_slug": tenant_slug,
        "business_card": card,
        "nfc_review_token": token,
        "review_link": f"/r/{token}",
    }
