"""Slice O · Feb-2026 — Communications Log (admin only).

Full audit trail of every email + SMS attempted by the tenant.
Backed by the existing ``marketing_deliveries`` collection — every
send path already writes a row there (mass broadcast, transactional
reminders, referrals, alerts, drips, magic links, etc.) so this
router is pure read-side aggregation.

Endpoints:

* ``GET  /api/communications-log``          — list + filters + pagination.
* ``GET  /api/communications-log/summary``  — 30-day KPI cards.

Filters supported on the list endpoint:

* ``customer_id``          — restrict to one customer.
* ``channel``              — ``email`` | ``sms`` | ``all`` (default).
* ``date_from`` / ``date_to``  — ISO date, inclusive.
* ``status``               — ``sent`` | ``opened`` | ``clicked`` |
                              ``bounced`` | ``failed`` (derived).
* ``page`` / ``page_size`` (default 50, max 200).

Status derivation (server side, canonical for the UI):

    bounced   ← bounced_at present
    failed    ← delivery_status in {"failed","no_contact","undelivered"}
                or provider_status in {"failed","undelivered","bounced","complained"}
                (bounced already peeled off above)
    clicked   ← clicked_at present
    opened    ← opened_at present
    sent      ← everything else (adapter returned success)

SMS never surfaces "opened" — carriers don't expose reads. When
``sms_status_final == "delivered"`` the row still classifies as
``sent`` (the UI paints a gray "Delivered" pill instead of the
blue "Opened" pill to make the ceiling explicit).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


# ── Guards ────────────────────────────────────────────────────────
_ADMIN_ROLES = {"admin", "super_admin"}


def _require_admin(user: dict) -> None:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Communications log is admin-only")


# ── Status derivation ────────────────────────────────────────────
_FAIL_STATUSES = {"failed", "no_contact", "undelivered"}
_PROV_FAIL = {"failed", "undelivered", "complained"}


def _derive_status(row: Dict[str, Any]) -> str:
    """Compress the row's timestamps + delivery flags into a single
    UI pill token."""
    if row.get("bounced_at"):
        return "bounced"
    ds = (row.get("delivery_status") or "").lower()
    ps = (row.get("provider_status") or "").lower()
    if ds in _FAIL_STATUSES or ps in _PROV_FAIL:
        return "failed"
    if row.get("clicked_at"):
        return "clicked"
    if row.get("opened_at"):
        return "opened"
    return "sent"


def _body_preview(body: Optional[str], limit: int = 100) -> str:
    if not body:
        return ""
    # Rough HTML strip — no need for lxml; the log preview is throwaway.
    import re
    txt = re.sub(r"<[^>]+>", " ", body)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:limit] + ("…" if len(txt) > limit else "")


def _shape_row(row: Dict[str, Any], cust_map: Dict[str, str]) -> Dict[str, Any]:
    channel = (row.get("channel") or "").lower()
    email_recip = row.get("recipient") if channel == "email" else None
    sms_recip = row.get("recipient") if channel == "sms" else None
    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "channel": channel,
        "recipient_email": email_recip,
        "recipient_phone": sms_recip,
        "customer_id": row.get("customer_id"),
        "customer_name": cust_map.get(row.get("customer_id") or "") or "",
        "subject": row.get("subject"),
        "body_preview": _body_preview(row.get("body")),
        "provider": row.get("provider"),
        "provider_response_id": row.get("provider_response_id"),
        "status_derived": _derive_status(row),
        "delivery_status": row.get("delivery_status"),
        "provider_status": row.get("provider_status"),
        "opened_at": row.get("opened_at"),
        "clicked_at": row.get("clicked_at"),
        "bounced_at": row.get("bounced_at"),
        "delivered_at": row.get("delivered_at"),
        "sms_status_final": row.get("sms_status_final"),
        "sms_status_at": row.get("sms_status_at"),
        "trigger_entity": row.get("trigger_entity"),
        "batch_id": row.get("batch_id"),
    }


# ── List query ────────────────────────────────────────────────────
def _build_query(*, tenant_id: str, customer_id: Optional[str],
                  channel: Optional[str], date_from: Optional[str],
                  date_to: Optional[str],
                  status: Optional[str]) -> Dict[str, Any]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        q["customer_id"] = customer_id
    if channel and channel != "all":
        q["channel"] = channel
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            # inclusive — add a day-end anchor if only a date was given
            df = date_to
            if len(df) == 10:  # bare YYYY-MM-DD
                df = df + "T23:59:59.999999+00:00"
            rng["$lte"] = df
        q["created_at"] = rng
    if status:
        st = status.lower()
        if st == "bounced":
            q["bounced_at"] = {"$exists": True, "$ne": None}
        elif st == "clicked":
            q["clicked_at"] = {"$exists": True, "$ne": None}
        elif st == "opened":
            # opened rows may also be clicked — allow both; UI shows
            # the strongest state via `_derive_status`.
            q["opened_at"] = {"$exists": True, "$ne": None}
        elif st == "failed":
            q["$or"] = [
                {"delivery_status": {"$in": list(_FAIL_STATUSES)}},
                {"provider_status": {"$in": list(_PROV_FAIL)}},
            ]
        elif st == "sent":
            # Everything not falling into any of the above — cheapest
            # server-side filter is "none of the transitional fields
            # present", combined with `delivery_status != failed`.
            q["$and"] = [
                {"$or": [
                    {"bounced_at": {"$exists": False}},
                    {"bounced_at": None},
                ]},
                {"$or": [
                    {"delivery_status": {"$nin": list(_FAIL_STATUSES)}},
                    {"delivery_status": {"$exists": False}},
                ]},
                {"$or": [
                    {"provider_status": {"$nin": list(_PROV_FAIL)}},
                    {"provider_status": {"$exists": False}},
                ]},
            ]
    return q


@router.get("/communications-log", tags=["communications-log"],
             operation_id="communicationsLog.list")
async def list_communications(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    customer_id: Optional[str] = Query(None),
    channel: Optional[str] = Query(None, description="email | sms | all"),
    trigger_kind: Optional[str] = Query(None, description="Filter by trigger_kind, e.g. review_request | team_invite"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    _require_admin(user)
    if channel and channel not in ("email", "sms", "all"):
        raise HTTPException(400, "channel must be one of email|sms|all")
    if status and status not in ("sent", "opened", "clicked",
                                    "bounced", "failed"):
        raise HTTPException(400, "invalid status filter")

    q = _build_query(
        tenant_id=tenant["id"], customer_id=customer_id,
        channel=channel, date_from=date_from, date_to=date_to,
        status=status,
    )
    if trigger_kind:
        # BUG C fix — filter to a specific trigger kind (review_request,
        # team_invite, etc). Matches either the top-level field OR the
        # trigger_entity.kind sub-document.
        q["$or"] = [
            {"trigger_kind": trigger_kind},
            {"trigger_entity.kind": trigger_kind},
        ]

    total = await db.marketing_deliveries.count_documents(q)
    skip = (page - 1) * page_size
    rows = await db.marketing_deliveries.find(
        q, {"_id": 0}
    ).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)

    # Resolve customer names in a single batch.
    cust_ids = list({r.get("customer_id") for r in rows if r.get("customer_id")})
    cust_map: Dict[str, str] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"id": {"$in": cust_ids}}, {"_id": 0, "id": 1, "name": 1}
        ):
            cust_map[c["id"]] = c.get("name") or ""

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_shape_row(r, cust_map) for r in rows],
    }


# ── Summary KPIs ──────────────────────────────────────────────────
@router.get("/communications-log/summary", tags=["communications-log"],
             operation_id="communicationsLog.summary")
async def summary_communications(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    days: int = Query(30, ge=1, le=365),
):
    """Rolling-window KPIs for the header cards. Open rate + click
    rate are email-only (SMS carriers don't report either). Bounce
    rate spans both channels (failed SMS counts as a bounce-adjacent
    metric)."""
    _require_admin(user)
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q_all = {"tenant_id": tenant["id"], "created_at": {"$gte": since}}
    q_email = {**q_all, "channel": "email"}

    total = await db.marketing_deliveries.count_documents(q_all)
    email_total = await db.marketing_deliveries.count_documents(q_email)

    opened = await db.marketing_deliveries.count_documents({
        **q_email, "opened_at": {"$exists": True, "$ne": None},
    })
    clicked = await db.marketing_deliveries.count_documents({
        **q_email, "clicked_at": {"$exists": True, "$ne": None},
    })
    bounced = await db.marketing_deliveries.count_documents({
        **q_all, "bounced_at": {"$exists": True, "$ne": None},
    })
    failed = await db.marketing_deliveries.count_documents({
        **q_all, "$or": [
            {"delivery_status": {"$in": list(_FAIL_STATUSES)}},
            {"provider_status": {"$in": list(_PROV_FAIL)}},
        ],
    })

    def _pct(num: int, denom: int) -> float:
        return round((num / denom) * 100, 1) if denom else 0.0

    return {
        "window_days": days,
        "total_sent": total,
        "email_sent": email_total,
        "sms_sent": total - email_total,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "failed": failed,
        "open_rate_pct": _pct(opened, email_total),
        "click_rate_pct": _pct(clicked, email_total),
        "bounce_rate_pct": _pct(bounced, total),
    }
