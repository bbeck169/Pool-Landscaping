"""Feb-2026 · smart enhancement — Weekly reputation trend digest.

Cron ``weekly_reputation_trend_digest`` runs Mondays 08:00 tenant
tz. For each tenant with the digest opt-in enabled it composes a
summary email covering:

* 7-day avg star rating
* Delta vs prior 7 days
* Count of new reviews
* Top-quoted 5★ line (truncated 140 chars)
* Top-quoted 1-3★ line if any
* One recommended action from the latest ``seo_scans.fixes[0]``

Skip when zero reviews in the last 7 days.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


async def _stats(tenant_id: str, window_start: datetime, window_end: datetime) -> Dict[str, Any]:
    pipe = [
        {"$match": {"tenant_id": tenant_id,
                     "created_at": {"$gte": window_start.isoformat(),
                                       "$lt": window_end.isoformat()},
                     "star_rating": {"$gte": 1, "$lte": 5}}},
        {"$group": {"_id": None, "count": {"$sum": 1},
                     "avg": {"$avg": "$star_rating"}}},
    ]
    rows = await db.reviews.aggregate(pipe).to_list(1)
    if not rows:
        return {"count": 0, "avg": 0.0}
    return {"count": int(rows[0].get("count") or 0),
             "avg": round(float(rows[0].get("avg") or 0.0), 2)}


async def _top_quote(tenant_id: str, low: int, high: int,
                       since_iso: str) -> Optional[str]:
    row = await db.reviews.find_one(
        {"tenant_id": tenant_id,
         "created_at": {"$gte": since_iso},
         "star_rating": {"$gte": low, "$lte": high},
         "public_comment": {"$exists": True, "$ne": ""}},
        {"_id": 0, "public_comment": 1, "customer_name": 1},
        sort=[("created_at", -1)],
    )
    if not row:
        return None
    txt = (row.get("public_comment") or "")[:140]
    who = row.get("customer_name") or "a customer"
    return f'"{txt}" — {who}'


async def _seo_recommendation(tenant_id: str) -> Optional[str]:
    scan = await db.seo_scans.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "result": 1},
        sort=[("run_at", -1)],
    )
    if not scan:
        return None
    fixes = ((scan.get("result") or {}).get("fixes") or [])
    if not fixes:
        return None
    top = fixes[0]
    return top.get("fix_hint") or None


async def compose_summary(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Pure compute path — no send. Handy for pytest dry-run."""
    tid = tenant["id"]
    now = datetime.now(timezone.utc)
    this_start = now - timedelta(days=7)
    prev_start = now - timedelta(days=14)
    prev_end = now - timedelta(days=7)

    this = await _stats(tid, this_start, now)
    prev = await _stats(tid, prev_start, prev_end)
    delta = round((this["avg"] - prev["avg"]), 2) if this["count"] and prev["count"] else 0
    top_high = await _top_quote(tid, 5, 5, this_start.isoformat())
    top_low = await _top_quote(tid, 1, 3, this_start.isoformat())
    seo_reco = await _seo_recommendation(tid)

    return {
        "tenant_id": tid,
        "this_week": this,
        "prev_week": prev,
        "delta": delta,
        "top_high_quote": top_high,
        "top_low_quote": top_low,
        "seo_recommendation": seo_reco,
    }


async def send_weekly_for_tenant(tenant: Dict[str, Any]) -> Dict[str, Any]:
    settings = tenant.get("settings") or {}
    if settings.get("weekly_reputation_digest_enabled") is False:
        return {"tenant_id": tenant.get("id"), "sent": False, "reason": "opted_out"}
    if settings.get("daily_review_digest_enabled") is False and \
       settings.get("weekly_reputation_digest_enabled") is None:
        # user's spec: "daily=true" acts as default opt-in. If they
        # explicitly opted out of daily and never set the weekly
        # toggle, respect the opt-out.
        return {"tenant_id": tenant.get("id"), "sent": False, "reason": "opted_out_via_daily"}

    summary = await compose_summary(tenant)
    if summary["this_week"]["count"] == 0:
        return {"tenant_id": tenant.get("id"), "sent": False,
                 "reason": "no_reviews_this_week", **summary}

    from services.email.resend_adapter import send as _resend_send
    company = (settings.get("business_card") or {}).get("company_name") or tenant.get("name") or "Team"
    subject = (
        f"{summary['this_week']['count']} reviews · "
        f"avg {summary['this_week']['avg']}★ "
        f"({'+' if summary['delta'] >= 0 else ''}{summary['delta']} vs last week)"
    )
    html_parts: List[str] = [
        f"<h1>{company} · Weekly reputation trend</h1>",
        f"<p>{subject}</p>",
    ]
    if summary["top_high_quote"]:
        html_parts.append(f"<div><strong>Top 5★:</strong> {summary['top_high_quote']}</div>")
    if summary["top_low_quote"]:
        html_parts.append(f"<div><strong>Needs love (1-3★):</strong> {summary['top_low_quote']}</div>")
    if summary["seo_recommendation"]:
        html_parts.append(f"<div><strong>SEO tip:</strong> {summary['seo_recommendation']}</div>")
    html = f'<html><body style="font-family:system-ui;padding:24px">{"".join(html_parts)}</body></html>'

    # Recipient — Resend owner email or ilnf.
    integrations = settings.get("integrations") or {}
    owner_id = ((integrations.get("resend") or {}).get("owned_by_user_id"))
    to_email = None
    if owner_id:
        owner = await db.users.find_one(
            {"id": owner_id}, {"_id": 0, "email": 1},
        )
        to_email = (owner or {}).get("email")
    if not to_email:
        to_email = (settings.get("internal_lead_notifications") or {}).get("email_to")
    if not to_email:
        return {"tenant_id": tenant.get("id"), "sent": False,
                 "reason": "no_recipient", **summary}

    result = await _resend_send(
        to=to_email, subject=subject, html=html,
        category="transactional",
        idempotency_key=f"weekly-digest-{tenant['id']}-{datetime.now(timezone.utc).date().isoformat()}",
        tenant_id=tenant["id"],
        # Phase K72 · Feb-2026 — recipient is the tenant's Resend
        # owner (admin). Bypasses the K72 kill switch.
        audience="internal",
    )
    status = result.get("provider_status") or "failed"
    try:
        await db.communications_log.insert_one({
            "id": new_id(), "tenant_id": tenant["id"], "channel": "email",
            "to": to_email, "subject": subject,
            "template": "weekly_reputation_trend_email",
            "status": status, "provider": result.get("provider") or "resend",
            "provider_response_id": result.get("provider_response_id"),
            "error": result.get("error"),
            "trigger_entity": {"kind": "weekly_reputation_digest", "id": tenant["id"]},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"[weekly-digest] log write failed: {e}")
    return {"tenant_id": tenant.get("id"), "sent": status == "sent",
             "recipient": to_email, "provider_status": status, **summary}


async def run_weekly_reputation_trend_digest() -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    async for t in db.tenants.find(
        {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ):
        try:
            results.append(await send_weekly_for_tenant(t))
        except Exception as e:
            logger.warning(f"[weekly-digest] tenant {t.get('id')} crashed: {e}")
    return {"tenants": len(results), "results": results}
