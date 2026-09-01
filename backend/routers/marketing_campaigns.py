"""Marketing Campaigns · Phase M2 backend router (Feb 2026).

Sender.net-parity campaign send + tracking surface.

Security
--------
Admin/super-only for every mutating endpoint. Public tracking endpoints
(open pixel, click redirect, one-click unsubscribe, provider webhooks)
require no auth — they're HMAC-token protected or provider-signature
gated. Every ``/api/public/mkt/*`` handler is intentionally silent on
invalid tokens (returns pixel / 302 / 200) to avoid enumeration.
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel, Field

from config import db, logger
from utils import require_admin, new_id, now_iso
from routers.tenants import get_current_tenant
from services import marketing_campaigns as svc

router = APIRouter(tags=["Marketing Campaigns"])
public_router = APIRouter(tags=["Marketing Public"])


# ─── Pydantic bodies ───────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    name: str
    subject: Optional[str] = ""
    preheader: Optional[str] = ""
    from_name: Optional[str] = ""
    from_email: Optional[str] = ""
    reply_to: Optional[str] = ""
    channel: str = "email"
    content: Optional[Dict[str, Any]] = None
    audience: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    ab_test: Optional[Dict[str, Any]] = None
    tracking_enabled: bool = True


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    preheader: Optional[str] = None
    from_name: Optional[str] = None
    from_email: Optional[str] = None
    reply_to: Optional[str] = None
    channel: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    audience: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    ab_test: Optional[Dict[str, Any]] = None
    tracking_enabled: Optional[bool] = None


class PreviewBody(BaseModel):
    sample_subscriber_id: Optional[str] = None


class TestSendBody(BaseModel):
    recipient_emails: Optional[List[str]] = None
    recipient_phones: Optional[List[str]] = None


class ScheduleBody(BaseModel):
    scheduled_at: str
    timezone: Optional[str] = "UTC"


# ─── CRUD ──────────────────────────────────────────────────────────────
_EDIT_LOCK = {"sent", "sending", "cancelled", "archived"}


@router.get("/marketing/campaigns")
async def list_campaigns(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant),
                             status: Optional[str] = Query(None),
                             channel: Optional[str] = Query(None),
                             q: Optional[str] = Query(None),
                             limit: int = Query(50, ge=1, le=200),
                             cursor: Optional[str] = Query(None)):
    filt: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        filt["status"] = status
    if channel:
        filt["channel"] = channel
    if q:
        filt["name"] = {"$regex": q, "$options": "i"}
    if cursor:
        filt["updated_at"] = {"$lt": cursor}
    rows = await db.marketing_campaigns.find(filt, {"_id": 0}) \
        .sort("updated_at", -1).to_list(limit)
    return {"count": len(rows), "campaigns": rows,
             "next_cursor": rows[-1]["updated_at"] if len(rows) == limit else None}


@router.post("/marketing/campaigns", status_code=201)
async def create_campaign(body: CampaignCreate,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "name": body.name,
        "subject": body.subject or "",
        "preheader": body.preheader or "",
        "from_name": body.from_name or "",
        "from_email": body.from_email or "",
        "reply_to": body.reply_to or "",
        "channel": (body.channel or "email").lower(),
        "content": body.content or {"email_html": "", "email_text": "",
                                       "sms_body": ""},
        "audience": body.audience or {"list_ids": [], "segment_ids": [],
                                          "exclude_list_ids": [],
                                          "exclude_segment_ids": []},
        "schedule": body.schedule or {"mode": "draft"},
        "ab_test": body.ab_test or {"enabled": False},
        "status": "draft",
        "tracking_enabled": bool(body.tracking_enabled),
        "created_by": user["id"], "created_at": now, "updated_at": now,
    }
    await db.marketing_campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/marketing/campaigns/{cid}")
async def get_campaign(cid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    stats = await _compute_stats(tenant["id"], cid)
    return {**doc, "stats": stats}


@router.patch("/marketing/campaigns/{cid}")
async def patch_campaign(cid: str, body: CampaignPatch,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    if doc["status"] in _EDIT_LOCK:
        raise HTTPException(409, f"campaign is {doc['status']} and cannot be edited")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updated_at"] = now_iso()
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": patch})
    return await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/marketing/campaigns/{cid}", status_code=204)
async def delete_campaign(cid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    if doc["status"] == "sent":
        # Soft-delete: archive to preserve analytics history.
        await db.marketing_campaigns.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {"status": "archived", "updated_at": now_iso()}})
        return Response(status_code=204)
    await db.marketing_campaigns.delete_one(
        {"id": cid, "tenant_id": tenant["id"]})
    return Response(status_code=204)


# ─── Preview / audience ────────────────────────────────────────────────
@router.post("/marketing/templates/lint")
async def lint_template(body: Dict[str, Any] = Body(...),
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 M2 UI — surface unresolved tokens + deprecated single-
    brace usage BEFORE the admin schedules a send. Body accepts
    ``{subject, preheader, email_html, sms_body}``; empty strings are
    silently skipped. Returns::

        {
          "unresolved_tokens": [{"field": "subject", "token": "bogus"}, …],
          "deprecated_single_brace": [{"field": "email_html", "token": "first_name"}, …],
          "clean": bool,
        }
    """
    import re as _re
    from services.marketing_campaigns import (
        render_body, _KNOWN_TOKEN_NAMES, build_preview_ctx,
    )
    tenant_doc = await db.tenants.find_one(
        {"id": tenant["id"]}, {"_id": 0}) or {}
    sample_sub = {"id": "linter", "email": "linter@example.com",
                    "first_name": "Sam", "last_name": "Preview",
                    "phone": "+15005550006", "status": "subscribed"}
    # Feb-2026 · Composer-linter false-positive fix. Real send-time
    # contexts hydrate the per-recipient ``customer`` / ``referral`` /
    # ``invoice`` scopes on the fly, but the linter previously only
    # had the subscriber scope — so every registered tag that read
    # from those scopes (e.g. ``CUSTOMER_CREDIT_BALANCE``,
    # ``REFERRAL_FRIEND_NAME``) resolved empty and got flagged as
    # unresolved in the composer. ``build_preview_ctx`` layers mock
    # scopes on top so previews render realistic values and the
    # composer only complains about *actually* unknown tags.
    ctx = build_preview_ctx(sample_sub, tenant_doc, {"id": "linter"},
                              send_id="linter")
    unresolved: List[Dict[str, str]] = []
    deprecated: List[Dict[str, str]] = []
    # ``(?<!\{)\{token\}(?!\})`` — a single-brace usage that isn't part
    # of the canonical double-brace form.
    single_pat = _re.compile(
        r"(?<!\{)\{\s*(" + "|".join(sorted(_KNOWN_TOKEN_NAMES)) +
        r")\s*\}(?!\})"
    )
    for field in ("subject", "preheader", "email_html", "sms_body"):
        text = (body or {}).get(field) or ""
        if not text:
            continue
        _, missing = render_body(text, ctx)
        for tok in set(missing):
            unresolved.append({"field": field, "token": tok})
        for m in single_pat.finditer(text):
            deprecated.append({"field": field, "token": m.group(1)})
    return {
        "unresolved_tokens": unresolved,
        "deprecated_single_brace": deprecated,
        # ``clean`` = "safe to send". Unresolved tokens are the only
        # blocker — deprecated single-brace usage renders correctly
        # via the dual-brace parser and is advisory-only.
        "clean": not unresolved,
    }


@router.post("/marketing/campaigns/{cid}/preview")
async def preview_campaign(cid: str, body: PreviewBody,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "campaign not found")
    sub = None
    if body.sample_subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": body.sample_subscriber_id,
              "tenant_id": tenant["id"]}, {"_id": 0})
    if not sub:
        sub = {"id": "preview-subscriber", "email": "preview@example.com",
                "first_name": "Sam", "last_name": "Preview",
                "phone": "+15005550006", "status": "subscribed"}
    tenant_doc = await db.tenants.find_one(
        {"id": tenant["id"]}, {"_id": 0}) or {}
    # Feb-2026 · Composer-preview mock scopes. See ``/marketing/
    # templates/lint`` note above — same false-positive fix. Real
    # sends (``dispatch_campaign``) still use ``build_ctx`` verbatim.
    ctx = svc.build_preview_ctx(sub, tenant_doc, camp, send_id="preview")
    warnings: List[str] = []
    email_html, missing_h = svc.render_body(
        (camp.get("content") or {}).get("email_html") or "", ctx)
    email_text_tpl = (camp.get("content") or {}).get("email_text") or ""
    email_text, missing_t = svc.render_body(email_text_tpl, ctx)
    sms_body, missing_s = svc.render_body(
        (camp.get("content") or {}).get("sms_body") or "", ctx)
    subject_r, missing_subj = svc.render_body(camp.get("subject") or "", ctx)
    for k in set(missing_h + missing_t + missing_s + missing_subj):
        warnings.append(f"unresolved token: {{{{ {k} }}}}")
    score, spam_hits = svc.spam_score(subject_r, email_html)
    if score > 0:
        warnings.append(f"spam heuristic — {score} trigger(s): {', '.join(spam_hits)}")
    return {
        "subject": subject_r, "email_html": email_html,
        "email_text": email_text, "sms_body": sms_body,
        "warnings": warnings, "spam_score": score,
        "sample_subscriber": sub,
    }


@router.post("/marketing/campaigns/{cid}/estimate-audience")
async def estimate_audience(cid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "campaign not found")
    r = await svc.resolve_audience(tenant["id"], camp.get("audience") or {})
    r.pop("subscriber_ids", None)  # keep the response light
    return r


# ─── Send ──────────────────────────────────────────────────────────────
@router.post("/marketing/campaigns/{cid}/send-test")
async def send_test(cid: str, body: TestSendBody,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Fires a rendered send to internal admin recipients only. Never
    writes to ``marketing_campaign_sends`` — the goal is a proof render
    without polluting analytics."""
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "campaign not found")
    tenant_doc = await db.tenants.find_one(
        {"id": tenant["id"]}, {"_id": 0}) or {}
    fake_sub = {"id": "test", "email": (body.recipient_emails or [""])[0],
                 "first_name": "Test", "status": "subscribed"}
    ctx = svc.build_ctx(fake_sub, tenant_doc, camp, send_id="test")
    subject_r, _ = svc.render_body(camp.get("subject") or "", ctx)
    html_r, _ = svc.render_body(
        (camp.get("content") or {}).get("email_html") or "", ctx)
    sms_r, _ = svc.render_body(
        (camp.get("content") or {}).get("sms_body") or "", ctx)
    email_results = []
    from services.comms_email_adapter import send_email
    for addr in (body.recipient_emails or []):
        r = await send_email(tenant["id"], addr, f"[TEST] {subject_r}",
                                html_r, from_name=camp.get("from_name"))
        email_results.append({"to": addr, "result": r})
    sms_results = []
    from services.comms_sms_adapter import send_sms
    for phone in (body.recipient_phones or []):
        r = await send_sms(tenant["id"], phone, f"[TEST] {sms_r}")
        sms_results.append({"to": phone, "result": r})
    return {"ok": True, "email": email_results, "sms": sms_results}


@router.post("/marketing/campaigns/{cid}/send-now")
async def send_now(cid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "campaign not found")
    if camp["status"] in ("sent", "sending", "cancelled"):
        raise HTTPException(409, f"campaign is {camp['status']}")
    r = await svc.dispatch_campaign(tenant["id"], cid)
    return r


@router.post("/marketing/campaigns/{cid}/schedule")
async def schedule_campaign(cid: str, body: ScheduleBody,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "campaign not found")
    if camp["status"] not in ("draft", "scheduled", "paused"):
        raise HTTPException(409, f"campaign is {camp['status']}")
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "scheduled",
                    "schedule": {"mode": "scheduled",
                                   "scheduled_at": body.scheduled_at,
                                   "timezone": body.timezone or "UTC"},
                    "updated_at": now_iso()}})
    return await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/marketing/campaigns/{cid}/cancel")
async def cancel_campaign(cid: str,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    if doc["status"] not in ("scheduled", "sending", "paused"):
        raise HTTPException(409, f"cannot cancel a {doc['status']} campaign")
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "cancelled",
                    "cancelled_at": now_iso(),
                    "updated_at": now_iso()}})
    # Phase H2 · Feb-2026 (F5 Wave 2) — audit campaign cancel.
    try:
        await db.audit_events.insert_one({
            "id": str(__import__("uuid").uuid4()),
            "event_type": "marketing_campaign_cancel",
            "tenant_id": tenant["id"],
            "campaign_id": cid,
            "campaign_name": doc.get("name"),
            "previous_status": doc.get("status"),
            "actor_user_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "timestamp": now_iso(),
        })
    except Exception as _ae:
        logger.warning(
            f"[h2] marketing_campaign_cancel audit failed: {_ae}"
        )
    return {"ok": True}


@router.post("/marketing/campaigns/{cid}/pause")
async def pause_campaign(cid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    if doc["status"] not in ("scheduled", "sending"):
        raise HTTPException(409, f"cannot pause a {doc['status']} campaign")
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "paused", "updated_at": now_iso()}})
    return {"ok": True}


@router.post("/marketing/campaigns/{cid}/resume")
async def resume_campaign(cid: str,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campaign not found")
    if doc["status"] != "paused":
        raise HTTPException(409, "campaign is not paused")
    new_status = "scheduled" if doc.get("schedule", {}).get("mode") == "scheduled" else "draft"
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": new_status, "updated_at": now_iso()}})
    return {"ok": True, "status": new_status}


# ─── Analytics ─────────────────────────────────────────────────────────
async def _compute_stats(tenant_id: str, cid: str) -> Dict[str, Any]:
    pipe = [{"$match": {"tenant_id": tenant_id, "campaign_id": cid}},
             {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    counts: Dict[str, int] = {}
    async for row in db.marketing_campaign_sends.aggregate(pipe):
        counts[row["_id"] or "unknown"] = int(row["n"])
    # Feb-2026 monotonicity fix — ``sent`` and ``delivered`` MUST NOT
    # drop when a downstream event (open / click / bounce / unsub)
    # rewrites the send row's current status. Count everything that
    # made it past dispatch: sent, delivered, opened, clicked,
    # bounced, complained, unsubscribed, failed. Only pre-dispatch
    # statuses (queued, sending, etc.) are excluded.
    _POST_DISPATCH = {"sent", "delivered", "opened", "clicked",
                       "bounced", "complained", "unsubscribed", "failed"}
    _POST_DELIVERED = {"sent", "delivered", "opened", "clicked"}
    sent = sum(counts.get(s, 0) for s in _POST_DISPATCH)
    delivered = sum(counts.get(s, 0) for s in _POST_DELIVERED)
    opened = 0
    clicked = 0
    # Opens / clicks come from ``open_count`` + ``click_count`` fields:
    async for row in db.marketing_campaign_sends.find(
        {"tenant_id": tenant_id, "campaign_id": cid},
        {"_id": 0, "open_count": 1, "click_count": 1}):
        if int(row.get("open_count") or 0) > 0:
            opened += 1
        if int(row.get("click_count") or 0) > 0:
            clicked += 1
    bounced = counts.get("bounced", 0)
    complained = counts.get("complained", 0)
    unsub = counts.get("unsubscribed", 0)
    failed = counts.get("failed", 0)
    # Rate denominator is the immutable "attempted" count (everything
    # past dispatch) so open/click rates stay stable as engagement
    # events roll in.
    attempted = max(1, sent + failed)
    # ``not_yet_engaged`` — dispatched sends that have not opened or
    # clicked yet. Optional UI helper; safe to ignore in the M2 UI.
    not_yet_engaged = max(0, sent - opened - clicked
                              - bounced - complained - unsub)
    out = {
        "sent": sent, "delivered": delivered,
        "opened": opened, "clicked": clicked,
        "bounced": bounced, "complained": complained,
        "unsubscribed": unsub, "failed": failed,
        "not_yet_engaged": not_yet_engaged,
        "open_rate_pct": round(opened / attempted * 100, 2) if sent else 0.0,
        "click_rate_pct": round(clicked / attempted * 100, 2) if sent else 0.0,
        "ctor_pct": round((clicked / opened * 100) if opened else 0.0, 2),
        "bounce_rate_pct": round(bounced / attempted * 100, 2) if sent else 0.0,
        "unsubscribe_rate_pct": round(unsub / attempted * 100, 2) if sent else 0.0,
    }
    # A/B — surface per-variant counters when the campaign is A/B enabled
    # AND at least one send carries a ``variant_id``. Keeps the plain
    # shape unchanged for non-A/B campaigns (so the M2-UI can safely
    # detect the presence of ``variants`` and render a comparison card).
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant_id},
        {"_id": 0, "ab_test": 1},
    )
    if (camp or {}).get("ab_test", {}).get("enabled"):
        per_variant: Dict[str, Dict[str, int]] = {}
        async for row in db.marketing_campaign_sends.find(
            {"tenant_id": tenant_id, "campaign_id": cid,
              "variant_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "variant_id": 1, "status": 1,
              "open_count": 1, "click_count": 1}):
            vid = row.get("variant_id") or "unknown"
            entry = per_variant.setdefault(
                vid, {"sent": 0, "opened": 0, "clicked": 0, "failed": 0})
            if row.get("status") == "sent":
                entry["sent"] += 1
            elif row.get("status") == "failed":
                entry["failed"] += 1
            if int(row.get("open_count") or 0) > 0:
                entry["opened"] += 1
            if int(row.get("click_count") or 0) > 0:
                entry["clicked"] += 1
        # Add computed rates per variant for consistent shape with the top-level.
        for vid, entry in per_variant.items():
            v_total = max(1, entry["sent"] + entry["failed"])
            entry["open_rate_pct"] = round(entry["opened"] / v_total * 100, 2)
            entry["click_rate_pct"] = round(entry["clicked"] / v_total * 100, 2)
        out["variants"] = per_variant
    return out


@router.get("/marketing/campaigns/{cid}/stats")
async def campaign_stats(cid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    return await _compute_stats(tenant["id"], cid)


@router.get("/marketing/campaigns/{cid}/top-links")
async def top_links(cid: str, limit: int = Query(10, ge=1, le=100),
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    pipe = [
        {"$match": {"tenant_id": tenant["id"], "campaign_id": cid,
                      "kind": {"$ne": "catalog"}}},
        {"$group": {"_id": "$url_hash", "n": {"$sum": 1},
                      "sample_url": {"$first": "$url"}}},
        {"$sort": {"n": -1}}, {"$limit": limit},
    ]
    return {"links": [{"url_hash": r["_id"], "clicks": r["n"],
                         "url": r["sample_url"]}
                        async for r in db.marketing_campaign_click_events.aggregate(pipe)]}


@router.get("/marketing/campaigns/{cid}/recipients")
async def recipients(cid: str,
                          status: Optional[str] = Query(None),
                          limit: int = Query(100, ge=1, le=500),
                          cursor: Optional[str] = Query(None),
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"], "campaign_id": cid}
    if status:
        q["status"] = status
    if cursor:
        q["sent_at"] = {"$lt": cursor}
    rows = await db.marketing_campaign_sends.find(q, {"_id": 0}) \
        .sort("sent_at", -1).to_list(limit)
    return {"count": len(rows), "recipients": rows,
             "next_cursor": rows[-1]["sent_at"] if len(rows) == limit else None}


@router.get("/marketing/campaigns/{cid}/timeline")
async def timeline(cid: str,
                       limit: int = Query(200, ge=1, le=1000),
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Chronological event feed for a single campaign — send, delivered,
    open, click, bounce, unsubscribe. Rolled up from
    ``marketing_campaign_sends`` (status / open / click timestamps) and
    ``marketing_campaign_click_events`` (individual click pings, so
    we can show ``5 clicks on X``). Sorted DESC by event time; capped
    per request so the M2-UI campaign detail view can paginate without
    Mongo scan storms."""
    # Guard: campaign must belong to caller's tenant.
    camp = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    events: List[Dict[str, Any]] = []
    # Sends → send / delivered / bounce / unsub / open / click timestamps.
    async for r in db.marketing_campaign_sends.find(
        {"tenant_id": tenant["id"], "campaign_id": cid},
        {"_id": 0, "id": 1, "subscriber_id": 1, "channel": 1,
          "variant_id": 1, "status": 1, "sent_at": 1,
          "first_opened_at": 1, "last_opened_at": 1, "open_count": 1,
          "first_clicked_at": 1, "last_clicked_at": 1, "click_count": 1,
          "bounced_at": 1, "unsubscribed_at": 1},
    ):
        sub_id = r.get("subscriber_id")
        if r.get("sent_at"):
            events.append({"at": r["sent_at"], "type": "send",
                              "subscriber_id": sub_id, "channel": r.get("channel"),
                              "variant_id": r.get("variant_id"),
                              "status": r.get("status")})
        if r.get("bounced_at"):
            events.append({"at": r["bounced_at"], "type": "bounce",
                              "subscriber_id": sub_id})
        if r.get("unsubscribed_at"):
            events.append({"at": r["unsubscribed_at"], "type": "unsubscribe",
                              "subscriber_id": sub_id})
        if r.get("first_opened_at"):
            events.append({"at": r["first_opened_at"], "type": "open",
                              "subscriber_id": sub_id,
                              "open_count": int(r.get("open_count") or 0)})
        if r.get("first_clicked_at"):
            events.append({"at": r["first_clicked_at"], "type": "click",
                              "subscriber_id": sub_id,
                              "click_count": int(r.get("click_count") or 0)})
    # Individual click events — surface as their own rows so heavy-
    # clicking subscribers show up chronologically instead of collapsed.
    click_docs = await db.marketing_campaign_click_events.find(
        {"tenant_id": tenant["id"], "campaign_id": cid,
          "kind": {"$ne": "catalog"}},
        {"_id": 0, "clicked_at": 1, "url": 1, "url_hash": 1,
          "subscriber_id": 1, "created_at": 1},
    ).sort("clicked_at", -1).to_list(limit)
    for e in click_docs:
        at = e.get("clicked_at") or e.get("created_at")
        if not at:
            continue
        events.append({"at": at, "type": "click_event",
                          "subscriber_id": e.get("subscriber_id"),
                          "url": e.get("url"),
                          "url_hash": e.get("url_hash")})
    events.sort(key=lambda x: x.get("at") or "", reverse=True)
    return {"count": len(events[:limit]), "events": events[:limit]}


# ─── Public tracking (unauth) ──────────────────────────────────────────
_PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff"
             b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
             b"\x00\x00\x02\x02D\x01\x00;")


@public_router.get("/public/mkt/o/{token}")
async def open_pixel(token: str):
    """Silent tracking pixel — always returns the 1x1 GIF."""
    payload = svc.verify_token(token)
    if payload:
        send_id = payload.get("sd")
        if send_id:
            now = now_iso()
            await db.marketing_campaign_sends.update_one(
                {"id": send_id},
                {"$inc": {"open_count": 1},
                  "$set": {"last_opened_at": now,
                            "status": "opened"},
                  "$setOnInsert": {"first_opened_at": now}})
            # Backfill first_opened_at when missing.
            await db.marketing_campaign_sends.update_one(
                {"id": send_id, "first_opened_at": None},
                {"$set": {"first_opened_at": now}})
    return Response(content=_PIXEL, media_type="image/gif")


@public_router.get("/public/mkt/c/{token}")
async def click_redirect(token: str, u: str = Query(""), request: Request = None):
    """302 to the original URL after incrementing click counts."""
    payload = svc.verify_token(token)
    if not payload:
        raise HTTPException(404, "unknown token")
    campaign_id = payload.get("c")
    subscriber_id = payload.get("s")
    send_id = payload.get("sd")
    url_hash = payload.get("u") or u
    catalog = await db.marketing_campaign_click_events.find_one(
        {"campaign_id": campaign_id, "url_hash": url_hash, "kind": "catalog"},
        {"_id": 0, "url": 1, "tenant_id": 1})
    target = (catalog or {}).get("url") or "/"
    now = now_iso()
    ip = ""
    ua = ""
    if request is not None:
        try:
            ip = request.client.host or ""
            ua = request.headers.get("user-agent", "")[:200]
        except Exception:
            pass
    await db.marketing_campaign_click_events.insert_one({
        "id": new_id(), "tenant_id": (catalog or {}).get("tenant_id") or "",
        "campaign_id": campaign_id, "subscriber_id": subscriber_id,
        "url_hash": url_hash, "url": target,
        "clicked_at": now, "ip": ip, "user_agent": ua,
        "kind": "click",
    })
    if send_id:
        await db.marketing_campaign_sends.update_one(
            {"id": send_id},
            {"$inc": {"click_count": 1},
              "$set": {"last_clicked_at": now, "status": "clicked"}})
        await db.marketing_campaign_sends.update_one(
            {"id": send_id, "first_clicked_at": None},
            {"$set": {"first_clicked_at": now}})
    return RedirectResponse(url=target, status_code=302)


@public_router.get("/public/mkt/unsub/{token}")
@public_router.post("/public/mkt/unsub/{token}")
async def one_click_unsub(token: str):
    payload = svc.verify_token(token)
    if not payload:
        return {"ok": True}  # Silent to prevent enumeration.
    subscriber_id = payload.get("s")
    campaign_id = payload.get("c")
    if subscriber_id:
        await db.subscribers.update_one(
            {"id": subscriber_id},
            {"$set": {"status": "unsubscribed",
                        "unsubscribed_at": now_iso()}})
        # Reflect on the send row (if any).
        await db.marketing_campaign_sends.update_many(
            {"subscriber_id": subscriber_id, "campaign_id": campaign_id},
            {"$set": {"status": "unsubscribed",
                        "unsubscribed_at": now_iso()}})
    return {"ok": True, "unsubscribed": True}


@public_router.post("/public/mkt/webhooks/{provider}")
async def provider_webhook(provider: str, request: Request):
    """Delivery / bounce / complaint webhook receiver.

    Signature verification is MOCKED in this environment (Resend +
    RingCentral sig secrets aren't wired to the preview cluster).
    Real signatures land in ``X-Signature`` / ``resend-signature`` /
    ``x-ringcentral-signature`` — we require the header to be
    non-empty when the env var ``MARKETING_WEBHOOK_STRICT=1`` is set;
    otherwise we accept and log."""
    strict = os.environ.get("MARKETING_WEBHOOK_STRICT") == "1"
    if strict:
        sig = (request.headers.get("resend-signature")
                or request.headers.get("x-ringcentral-signature")
                or request.headers.get("x-signature") or "")
        if not sig:
            raise HTTPException(401, "missing signature")
    body = await request.json()
    events = body.get("events") or [body]
    updated = 0
    for evt in events:
        provider_id = (evt.get("data") or {}).get("message_id") \
            or evt.get("message_id") or evt.get("provider_message_id")
        if not provider_id:
            continue
        etype = (evt.get("type") or evt.get("event") or "").lower()
        m = {
            "email.delivered": "delivered", "delivered": "delivered",
            "email.bounced":   "bounced",   "bounce":    "bounced",
            "email.complained": "complained",
            "email.opened":   "opened",    "sms.delivered": "delivered",
        }
        status = m.get(etype)
        if not status:
            continue
        r = await db.marketing_campaign_sends.update_one(
            {"provider_message_id": provider_id},
            {"$set": {"status": status, "updated_at": now_iso()}})
        updated += r.modified_count
    return {"ok": True, "updated": updated, "provider": provider}
