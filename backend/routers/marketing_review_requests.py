"""Feb-2026 · Marketing Slice M6 — Automated review-request nurture.

M6 owns its own tick + collection (``review_requests``) rather than
lean on the M5 sequence engine.  The two systems still share the
same mock-delivery pipeline (``marketing_deliveries``), so downstream
M7 analytics counts M5 drips and M6 review requests uniformly.

Endpoints (admin, unless flagged public)::

    GET    /api/marketing/review-requests/config
    PATCH  /api/marketing/review-requests/config
    GET    /api/marketing/review-requests
    POST   /api/marketing/review-requests/manual/{customer_id}
    POST   /api/marketing/review-requests/{id}/cancel
    GET    /api/portal/review-token/verify              (public)
    POST   /api/portal/reviews/via-token                (public — token-gated)

Magic-link tokens are JWTs signed with ``JWT_SECRET`` carrying
``{sub:"rr", cid, rid, srid, exp}``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from config import db, JWT_SECRET, JWT_ALGO, logger
from utils import new_id, now_iso, require_admin, get_current_user
from routers.tenants import get_current_tenant
from services.marketing.render import (
    render_subject_and_body, strip_html, DEFAULT_SAMPLE_CONTEXT,
)

router = APIRouter()

TOKEN_SUB = "rr"   # subject claim for review-request magic links
DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "channel": "email",           # email | sms | both
    "delay_hours": 72,
    "email_template_id": None,
    "sms_template_id": None,
    "quiet_hours_start": "18:00",
    "quiet_hours_end": "09:00",
    "expire_days": 30,
    # Slice A · A/B testing on review requests.  Off by default.
    "ab_test_enabled": False,
    "ab_split_pct": 50,
    "email_template_id_variant": None,
    "sms_template_id_variant": None,
}


# ── Config models ────────────────────────────────────────────────────
class ReviewRequestConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    channel: Optional[str] = None
    delay_hours: Optional[int] = Field(None, ge=0, le=24 * 60)
    email_template_id: Optional[str] = None
    sms_template_id: Optional[str] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    expire_days: Optional[int] = Field(None, ge=1, le=365)
    # Slice A — A/B testing knobs.  Every field optional; validation
    # runs cross-field in :func:`patch_review_requests_config`.
    ab_test_enabled: Optional[bool] = None
    ab_split_pct: Optional[int] = Field(None, ge=0, le=100)
    email_template_id_variant: Optional[str] = None
    sms_template_id_variant: Optional[str] = None

    @field_validator("channel")
    @classmethod
    def _channel_ok(cls, v):
        if v is not None and v not in ("email", "sms", "both"):
            raise ValueError("channel must be email|sms|both")
        return v


# ── Config helpers ───────────────────────────────────────────────────
async def _config_for(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "review_requests_config": 1},
    ) or {}
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(t.get("review_requests_config") or {})
    return cfg


async def _validate_template(tenant_id: str, tpl_id: Optional[str],
                              expected_channel: str) -> None:
    if not tpl_id:
        return
    tpl = await db.marketing_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant_id},
        {"_id": 0, "channel": 1},
    )
    if not tpl:
        raise HTTPException(422, f"template {tpl_id} not found")
    if tpl.get("channel") != expected_channel:
        raise HTTPException(
            422,
            f"template {tpl_id} has channel {tpl.get('channel')!r},"
            f" expected {expected_channel!r}",
        )


# ── Magic link helpers ───────────────────────────────────────────────
def _sign_token(customer_id: str, review_request_id: str,
                service_report_id: Optional[str],
                expire_days: int) -> str:
    """Return a JWT string that grants a single-purpose review-request
    session for the specified customer + row."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TOKEN_SUB,
        "cid": customer_id,
        "rid": review_request_id,
        "srid": service_report_id,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=max(1, int(expire_days or 30))),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _verify_token(tok: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Review link has expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid review link")
    if payload.get("sub") != TOKEN_SUB:
        raise HTTPException(401, "Invalid review link")
    return payload


def _build_magic_link(customer_id: str, review_request_id: str,
                       service_report_id: Optional[str],
                       expire_days: int) -> str:
    tok = _sign_token(customer_id, review_request_id, service_report_id,
                       expire_days)
    q = f"?token={tok}"
    if service_report_id:
        q += f"&service_report_id={service_report_id}"
    # Public review-landing route (no auth). Logged-in customers who
    # click a link they were also emailed still work — the same
    # PortalReviews component is mounted at /portal/reviews for the
    # in-shell path.
    return f"/r/review{q}"


# ── Public: config GET/PATCH ─────────────────────────────────────────
@router.get("/marketing/review-requests/config")
async def get_review_requests_config(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    return await _config_for(tenant["id"])


@router.patch("/marketing/review-requests/config")
async def patch_review_requests_config(
    body: ReviewRequestConfigPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    current = await _config_for(tenant["id"])
    new_cfg = dict(current)
    for k, v in body.model_dump(exclude_unset=True).items():
        new_cfg[k] = v
    # Cross-field validation.
    if new_cfg["enabled"]:
        if new_cfg["channel"] in ("email", "both") and not new_cfg["email_template_id"]:
            raise HTTPException(422, "email_template_id required when enabling email channel")
        if new_cfg["channel"] in ("sms", "both") and not new_cfg["sms_template_id"]:
            raise HTTPException(422, "sms_template_id required when enabling sms channel")
    await _validate_template(tenant["id"], new_cfg.get("email_template_id"), "email")
    await _validate_template(tenant["id"], new_cfg.get("sms_template_id"), "sms")
    # Slice A — A/B test cross-field validation + variant template checks.
    if new_cfg.get("ab_test_enabled"):
        ch = new_cfg["channel"]
        if ch in ("email", "both"):
            if not new_cfg.get("email_template_id"):
                raise HTTPException(422,
                    "email_template_id required as A/B control for the email channel")
            if not new_cfg.get("email_template_id_variant"):
                raise HTTPException(422,
                    "email_template_id_variant required when ab_test_enabled and channel includes email")
        if ch in ("sms", "both"):
            if not new_cfg.get("sms_template_id"):
                raise HTTPException(422,
                    "sms_template_id required as A/B control for the sms channel")
            if not new_cfg.get("sms_template_id_variant"):
                raise HTTPException(422,
                    "sms_template_id_variant required when ab_test_enabled and channel includes sms")
    await _validate_template(tenant["id"],
                              new_cfg.get("email_template_id_variant"), "email")
    await _validate_template(tenant["id"],
                              new_cfg.get("sms_template_id_variant"), "sms")
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"review_requests_config": new_cfg,
                    "review_requests_config_updated_at": now_iso()}},
    )
    return new_cfg


# ── Admin list ───────────────────────────────────────────────────────
@router.get("/marketing/review-requests")
async def list_review_requests(
    status: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    if customer_id: q["customer_id"] = customer_id
    if since: q.setdefault("requested_at", {})["$gte"] = since
    if until: q.setdefault("requested_at", {})["$lte"] = until
    total = await db.marketing_review_requests.count_documents(q)
    rows = await db.marketing_review_requests.find(q, {"_id": 0}).sort(
        "requested_at", -1,
    ).skip(offset).limit(limit).to_list(limit)
    # Hydrate customer name for display.
    ids = list({r["customer_id"] for r in rows})
    cust_map = {}
    if ids:
        async for c in db.customers.find(
            {"id": {"$in": ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1},
        ):
            cust_map[c["id"]] = c.get("name")
    for r in rows:
        r["customer_name"] = cust_map.get(r["customer_id"])
    return {"review_requests": rows, "total": total}


# ── Manual enqueue ───────────────────────────────────────────────────
class ManualIn(BaseModel):
    service_report_id: Optional[str] = None


@router.post("/marketing/review-requests/manual/{customer_id}",
              status_code=201)
async def enqueue_manual(
    customer_id: str, body: ManualIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    cfg = await _config_for(tenant["id"])
    row = await _enqueue_one(
        tenant["id"], customer_id, body.service_report_id, cfg,
        source="manual",
    )
    if not row:
        raise HTTPException(409, "A review request already exists for this service")
    return row


# ── Cancel ───────────────────────────────────────────────────────────
@router.post("/marketing/review-requests/{rid}/cancel")
async def cancel_review_request(
    rid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    r = await db.marketing_review_requests.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not r:
        raise HTTPException(404, "Not found")
    if r["status"] in ("reviewed", "expired", "failed"):
        raise HTTPException(409, f"Cannot cancel a {r['status']} request")
    await db.marketing_review_requests.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"status": "failed", "halt_reason": "cancelled",
                    "updated_at": now_iso()}},
    )
    r["status"] = "failed"
    r["halt_reason"] = "cancelled"
    return r


# ── Portal: token verify ─────────────────────────────────────────────
@router.get("/portal/review-token/verify")
async def verify_review_token(token: str = Query(...)):
    payload = _verify_token(token)
    rr = await db.marketing_review_requests.find_one(
        {"id": payload["rid"]}, {"_id": 0},
    )
    if not rr:
        raise HTTPException(401, "Invalid review link")
    if rr.get("customer_id") != payload.get("cid"):
        raise HTTPException(401, "Invalid review link")
    if rr["status"] in ("reviewed", "expired", "failed"):
        # Still return context so the portal can render an
        # informative "already submitted / expired" state, but flag it.
        pass
    cust = await db.customers.find_one(
        {"id": rr["customer_id"], "tenant_id": rr["tenant_id"]},
        {"_id": 0, "id": 1, "name": 1},
    ) or {}
    sr_ctx = None
    srid = rr.get("service_report_id")
    if srid:
        sr = await db.service_reports.find_one(
            {"id": srid, "tenant_id": rr["tenant_id"]},
            {"_id": 0, "job_id": 1, "submitted_at": 1},
        ) or {}
        job_id = sr.get("job_id")
        job = None
        if job_id:
            job = await db.jobs.find_one(
                {"id": job_id, "tenant_id": rr["tenant_id"]},
                {"_id": 0, "service_type": 1, "title": 1,
                  "scheduled_at": 1, "completed_at": 1},
            ) or {}
        sr_ctx = {
            "service_report_id": srid,
            "service_type": (job or {}).get("service_type") or (job or {}).get("title"),
            "completed_at": (job or {}).get("completed_at") or sr.get("submitted_at"),
        }
    # Best-effort "opened" transition — only the first landing flips it.
    if rr["status"] not in ("opened", "reviewed", "expired", "failed"):
        await db.marketing_review_requests.update_one(
            {"id": rr["id"]},
            {"$set": {"status": "opened", "opened_at": now_iso()}},
        )
    return {
        "review_request_id": rr["id"],
        "customer_id": rr["customer_id"],
        "customer_name": cust.get("name"),
        "tenant_id": rr["tenant_id"],
        "service_context": sr_ctx,
        "status": rr["status"],
    }


# ── Portal: submit review via token (public, no login required) ──────
class ViaTokenReviewIn(BaseModel):
    token: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = ""


@router.post("/portal/reviews/via-token", status_code=201)
async def submit_review_via_token(body: ViaTokenReviewIn):
    payload = _verify_token(body.token)
    rr = await db.marketing_review_requests.find_one(
        {"id": payload["rid"]}, {"_id": 0},
    )
    if not rr or rr.get("customer_id") != payload.get("cid"):
        raise HTTPException(401, "Invalid review link")
    if rr["status"] == "reviewed":
        raise HTTPException(409, "Review already submitted for this request")
    if rr["status"] in ("expired", "failed"):
        raise HTTPException(410, "This review link is no longer active")

    # Reuse Slice-6 rating gate: rating>=4 goes public, else private.
    is_public = int(body.rating) >= 4
    rid = new_id()
    doc = {
        "id": rid,
        "tenant_id": rr["tenant_id"],
        "customer_id": rr["customer_id"],
        "customer_name": None,           # backfilled below
        "rating": int(body.rating),
        "comment": (body.comment or "").strip(),
        "is_public": is_public,
        "google_redirect": False,
        "status": "new",
        "created_at": now_iso(),
        "read_at": None,
        "admin_notes": "",
        "service_report_id": rr.get("service_report_id"),
        "review_request_id": rr["id"],
    }
    cust = await db.customers.find_one(
        {"id": rr["customer_id"]}, {"_id": 0, "name": 1},
    ) or {}
    doc["customer_name"] = cust.get("name") or "Customer"
    await db.customer_portal_reviews.insert_one(doc)

    # Flip the review-request row.
    await db.marketing_review_requests.update_one(
        {"id": rr["id"]},
        {"$set": {"status": "reviewed",
                    "review_id": rid,
                    "review_rating": int(body.rating),
                    "reviewed_at": now_iso()}},
    )

    google_url = None
    if is_public:
        t = await db.tenants.find_one(
            {"id": rr["tenant_id"]}, {"_id": 0, "google_review_url": 1},
        ) or {}
        google_url = t.get("google_review_url")
        if google_url:
            await db.customer_portal_reviews.update_one(
                {"id": rid}, {"$set": {"google_redirect": True}},
            )
    return {
        "ok": True, "review_id": rid,
        "is_public": is_public,
        "google_review_url": google_url,
    }


# ═══════════════════════════════════════════════════════════════════════
# Domain helpers (called from service_reports hook + M6 tick + expiry cron)
# ═══════════════════════════════════════════════════════════════════════
async def _enqueue_one(
    tenant_id: str, customer_id: str, service_report_id: Optional[str],
    cfg: Dict[str, Any], source: str = "auto",
) -> Optional[Dict[str, Any]]:
    """Insert a queued review-request row.  Returns ``None`` if a
    row already exists for this (customer, service_report) — idempotent
    guard is REQUIRED by the M6 duplicate-safety spec."""
    # Duplicate guard.
    dup_q: Dict[str, Any] = {
        "tenant_id": tenant_id, "customer_id": customer_id,
        "status": {"$nin": ["failed", "expired"]},
    }
    if service_report_id:
        dup_q["service_report_id"] = service_report_id
    dup = await db.marketing_review_requests.find_one(dup_q, {"_id": 0, "id": 1})
    if dup:
        return None

    delay = int(cfg.get("delay_hours") or 0)
    now = datetime.now(timezone.utc)
    next_send = now + timedelta(hours=delay)
    channel = cfg.get("channel") or "email"
    # If "both", queue an email row now; SMS is out of MVP scope — email
    # covers the primary channel and the config stays forward-compat.
    active_channel = "email" if channel == "both" else channel
    control_template = (
        cfg.get("email_template_id")
        if active_channel == "email"
        else cfg.get("sms_template_id")
    )
    variant_template = (
        cfg.get("email_template_id_variant")
        if active_channel == "email"
        else cfg.get("sms_template_id_variant")
    )
    # Slice A · A/B — pick variant using SystemRandom for
    # cryptographic-quality per-row randomness.
    variant_label: Optional[str] = None
    template_id = control_template
    if cfg.get("ab_test_enabled") and control_template and variant_template:
        import secrets as _secrets
        split_pct = int(cfg.get("ab_split_pct") if cfg.get("ab_split_pct") is not None else 50)
        # secrets.SystemRandom().random() returns [0.0, 1.0); B gets picked
        # when the roll lands under ``split_pct/100``.
        if _secrets.SystemRandom().random() * 100.0 < split_pct:
            variant_label = "B"
            template_id = variant_template
        else:
            variant_label = "A"
            template_id = control_template
    rid = new_id()
    doc = {
        "id": rid, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service_report_id": service_report_id,
        "drip_enrolment_id": None,
        "channel": active_channel,
        "template_id": template_id,
        "variant": variant_label,          # Slice A — "A" | "B" | None
        "delivery_id": None,
        "magic_link": _build_magic_link(
            customer_id, rid, service_report_id,
            cfg.get("expire_days") or 30,
        ),
        "status": "queued",
        "requested_at": now.isoformat(),
        "next_send_at": next_send.isoformat(),
        "expire_at": (now + timedelta(days=int(cfg.get("expire_days") or 30))
                       ).isoformat(),
        "sent_at": None, "opened_at": None, "reviewed_at": None,
        "review_id": None, "review_rating": None,
        "source": source,
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }
    await db.marketing_review_requests.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def enqueue_from_service_completed(
    tenant_id: str, customer_id: Optional[str],
    service_report_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Best-effort entry point called from
    ``routers.service_reports.submit_service_report`` after the M5c
    drip hook.  No-op when the tenant hasn't opted in."""
    if not (tenant_id and customer_id):
        return None
    cfg = await _config_for(tenant_id)
    if not cfg.get("enabled"):
        return None
    try:
        return await _enqueue_one(
            tenant_id, customer_id, service_report_id, cfg,
            source="service_completed",
        )
    except Exception as exc:  # pragma: no cover — belt & braces
        logger.warning("[m6] enqueue on service_completed crashed: %s", exc)
        return None


# ── Tick + expiry sweep ──────────────────────────────────────────────
async def m6_tick_all_tenants() -> Dict[str, int]:
    """Every 5 minutes — send every queued row whose ``next_send_at``
    is due, in every tenant.  Deliveries are mocked into
    ``marketing_deliveries``."""
    now = datetime.now(timezone.utc)
    q = {"status": "queued", "next_send_at": {"$lte": now.isoformat()}}
    due = await db.marketing_review_requests.find(q, {"_id": 0}).to_list(1000)
    sent = 0
    for rr in due:
        try:
            await _deliver(rr, now)
            sent += 1
        except Exception as exc:  # pragma: no cover
            logger.warning("[m6] deliver crashed for %s: %s", rr.get("id"), exc)
    logger.info("[m6] tick — due=%s sent=%s", len(due), sent)
    return {"due": len(due), "sent": sent}


async def _deliver(rr: Dict[str, Any], now: datetime) -> None:
    """Render the tenant-configured template, record a mock delivery,
    flip the row to ``sent``.  Reuses M5's ``marketing_deliveries``
    collection so downstream M7 analytics counts M5+M6 uniformly.

    Slice F · suppression check runs BEFORE template render; a
    suppressed row is flipped to ``failed`` with
    ``halt_reason='suppressed'`` and NO delivery is recorded (compliance
    guarantee: mocked or live, a suppressed contact never receives)."""
    cust = await db.customers.find_one(
        {"id": rr["customer_id"], "tenant_id": rr["tenant_id"]},
        {"_id": 0, "name": 1, "email": 1, "phone": 1},
    ) or {}
    from routers.marketing_preferences import is_suppressed, build_unsubscribe_url
    try:
        suppressed = await is_suppressed(
            rr["tenant_id"], cust,
            channel=rr["channel"], category="review_requests",
        )
    except Exception as exc:  # pragma: no cover — loop-cache defense
        logger.warning("[m6] is_suppressed crashed: %s", exc)
        suppressed = False
    if suppressed:
        await db.marketing_review_requests.update_one(
            {"id": rr["id"]},
            {"$set": {"status": "failed",
                        "halt_reason": "suppressed",
                        "updated_at": now.isoformat()}},
        )
        logger.info("[m6] suppressed rr=%s cust=%s", rr["id"], rr["customer_id"])
        return
    tpl = None
    if rr.get("template_id"):
        tpl = await db.marketing_templates.find_one(
            {"id": rr["template_id"], "tenant_id": rr["tenant_id"]},
            {"_id": 0},
        )
    ctx = dict(DEFAULT_SAMPLE_CONTEXT)
    first = (cust.get("name") or "there").split(" ", 1)[0]
    ctx.setdefault("customer", {})
    ctx["customer"] = {
        **ctx.get("customer", {}),
        "first_name": first,
        "full_name": cust.get("name") or first,
        "email": cust.get("email") or ctx["customer"].get("email"),
        "phone": cust.get("phone") or ctx["customer"].get("phone"),
    }
    ctx["portal_review_url"] = _absolute_portal_url(rr["magic_link"])
    ctx["unsubscribe_url"] = _absolute_portal_url(
        build_unsubscribe_url(rr["customer_id"], rr["tenant_id"]),
    )
    subj, body, missing = render_subject_and_body(
        (tpl or {}).get("subject") or "",
        (tpl or {}).get("body") or "",
        ctx,
    )
    if rr["channel"] == "sms":
        body = strip_html(body)
    delivery_id = new_id()
    # Slice N / S · Resend for email, Twilio for SMS.
    provider_status = None
    provider = "mock"
    provider_response_id = None
    attempts = 0
    if rr["channel"] == "email":
        try:
            from services.email.resend_adapter import send as _resend_send
            res = await _resend_send(
                to=(cust.get("email") or "").strip(),
                subject=subj,
                html=body,
                category="review_request",
                tenant_id=rr["tenant_id"],
                customer_id=rr["customer_id"],
                idempotency_key=f"m6:{rr['id']}",
            )
            provider = res.get("provider") or "mock"
            provider_status = res.get("provider_status")
            provider_response_id = res.get("provider_response_id")
            attempts = res.get("attempts") or 0
        except Exception as exc:  # pragma: no cover
            logger.warning("[m6] resend adapter failed: %s", exc)
            provider_status = "failed"
    elif rr["channel"] == "sms":
        try:
            from services.sms.twilio_adapter import send as _twilio_send
            res = await _twilio_send(
                to=(cust.get("phone") or "").strip(),
                body=body,
                category="review_request",
                tenant_id=rr["tenant_id"],
                customer_id=rr["customer_id"],
                idempotency_key=f"m6:{rr['id']}",
            )
            provider = res.get("provider") or "mock"
            provider_status = res.get("provider_status")
            provider_response_id = res.get("provider_response_id")
            attempts = res.get("attempts") or 0
        except Exception as exc:  # pragma: no cover
            logger.warning("[m6] twilio adapter failed: %s", exc)
            provider_status = "failed"
    await db.marketing_deliveries.insert_one({
        "id": delivery_id,
        "tenant_id": rr["tenant_id"],
        "sequence_id": None,               # M6 rows aren't sequence-driven
        "review_request_id": rr["id"],
        "enrolment_id": None,
        "step_index": 0,
        "customer_id": rr["customer_id"],
        "channel": rr["channel"],
        "template_id": rr.get("template_id"),
        "subject_rendered": subj if rr["channel"] == "email" else None,
        "body_rendered": body,
        "mock": provider == "mock",
        "provider": provider,
        "provider_status": provider_status,
        "provider_response_id": provider_response_id,
        "attempts": attempts,
        "sent_at": now.isoformat(),
        "provider_response_stub": {"ok": True, "id": f"mock-{delivery_id[:8]}"},
    })
    await db.marketing_review_requests.update_one(
        {"id": rr["id"]},
        {"$set": {"status": "sent",
                    "sent_at": now.isoformat(),
                    "delivery_id": delivery_id,
                    "updated_at": now.isoformat()}},
    )


def _absolute_portal_url(path: str) -> str:
    """Best-effort absolute URL for the magic link.  The frontend base
    is read from ``REACT_APP_BACKEND_URL`` at runtime — we don't have
    the frontend base in the backend env, so the path-only link is
    also acceptable in the mocked delivery."""
    import os as _os
    base = _os.environ.get("PUBLIC_APP_URL") or ""
    return f"{base.rstrip('/')}{path}" if base else path


async def m6_expiry_sweep() -> Dict[str, int]:
    """Daily — flip any queued/sent/opened row past its ``expire_at``
    to ``status=expired``."""
    now = datetime.now(timezone.utc).isoformat()
    r = await db.marketing_review_requests.update_many(
        {"status": {"$in": ["queued", "sent", "opened"]},
         "expire_at": {"$lte": now}},
        {"$set": {"status": "expired", "updated_at": now}},
    )
    logger.info("[m6] expiry sweep — expired=%s", r.modified_count)
    return {"expired": r.modified_count}
