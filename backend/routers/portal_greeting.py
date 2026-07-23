"""Feb-2026 · Item 9 — Portal home greeting-tile state.

Single-shot endpoint that returns everything the greeting tile needs
in one round trip: time-of-day bucket (America/Phoenix), first name,
tenant business_card details, and the highest-priority subline.

Priority order (first match wins):
  1. today_visit         — customer has a scheduled job on today.
  2. upcoming_visit      — customer has a scheduled job in ≤7 days.
  3. unpaid_invoice      — customer has an unpaid invoice.
  4. unread_message      — customer has an unread thread message.
  5. default             — fallback pleasant message.

In-memory per-user 2s cache to keep the tile snappy on rapid page
loads.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import get_current_user

router = APIRouter(tags=["Portal Greeting"])

_CACHE: Dict[str, Any] = {}
_CACHE_TTL_S = 2.0
_TENANT_TZ = ZoneInfo("America/Phoenix")


def _time_of_day_bucket(now_tz: datetime) -> str:
    h = now_tz.hour
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    return "evening"


def _cache_key(user_id: str) -> str:
    return f"greet:{user_id}"


@router.get("/customers/me/greeting-state",
             operation_id="portal.greetingState")
async def greeting_state(user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer login required")

    ck = _cache_key(user.get("id") or "")
    cached = _CACHE.get(ck)
    if cached and (time.time() - cached["_at"]) < _CACHE_TTL_S:
        return cached["payload"]

    tenant = await db.tenants.find_one(
        {"id": user["tenant_id"]}, {"_id": 0},
    ) or {}
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}

    cust = await db.customers.find_one(
        {"id": user.get("customer_id"), "tenant_id": user["tenant_id"]},
        {"_id": 0, "name": 1, "first_name": 1},
    ) or {}
    # Fall back to the user's own display name when the linked
    # customer row is missing (test tenants sometimes have that
    # linkage broken). Prefer proper capitalisation over the "there"
    # placeholder.
    user_first = (user.get("name") or "").split(" ", 1)[0] if user.get("name") else ""
    first_name = (
        cust.get("first_name")
        or ((cust.get("name") or "").split(" ", 1)[0] if cust.get("name") else "")
        or user_first
        or "there"
    )

    now_tz = datetime.now(_TENANT_TZ)
    tod = _time_of_day_bucket(now_tz)
    today_iso = now_tz.date().isoformat()
    week_out_iso = (now_tz + timedelta(days=7)).date().isoformat()

    subline_priority = "default"
    subline_data: Dict[str, Any] = {}
    next_visit_job_id: Optional[str] = None
    unpaid_invoice_id: Optional[str] = None
    latest_message_thread_id: Optional[str] = None

    # ── 1. Today's scheduled visit ────────────────────────────────
    job_today = await db.jobs.find_one(
        {"tenant_id": user["tenant_id"], "customer_id": cust and user.get("customer_id"),
         "scheduled_date": today_iso,
         "status": {"$in": ["active", "scheduled", "in_progress"]}},
        {"_id": 0, "id": 1, "service_type": 1, "service_title": 1,
         "scheduled_time": 1, "scheduled_at": 1},
    )
    if job_today:
        next_visit_job_id = job_today.get("id")
        subline_priority = "today_visit"
        subline_data = {
            "service_title": job_today.get("service_title") or job_today.get("service_type") or "service",
            "visit_time": job_today.get("scheduled_time") or "",
            "visit_at": job_today.get("scheduled_at") or today_iso,
        }
    else:
        # ── 2. Upcoming (≤7 days) ────────────────────────────────
        job_upc = await db.jobs.find_one(
            {"tenant_id": user["tenant_id"], "customer_id": user.get("customer_id"),
             "scheduled_date": {"$gt": today_iso, "$lte": week_out_iso},
             "status": {"$in": ["active", "scheduled"]}},
            {"_id": 0, "id": 1, "service_type": 1, "service_title": 1,
             "scheduled_date": 1, "scheduled_at": 1},
            sort=[("scheduled_date", 1)],
        )
        if job_upc:
            next_visit_job_id = job_upc.get("id")
            subline_priority = "upcoming_visit"
            subline_data = {
                "service_title": job_upc.get("service_title") or job_upc.get("service_type") or "service",
                "visit_at": job_upc.get("scheduled_at") or job_upc.get("scheduled_date"),
            }
        else:
            # ── 3. Unpaid invoice ────────────────────────────────
            inv = await db.invoices.find_one(
                {"tenant_id": user["tenant_id"], "customer_id": user.get("customer_id"),
                 "status": {"$in": ["due", "past_due", "unpaid", "outstanding"]}},
                {"_id": 0, "id": 1, "total_cents": 1, "balance_cents": 1, "amount_due": 1},
                sort=[("created_at", 1)],
            )
            if inv:
                unpaid_invoice_id = inv.get("id")
                amt = (
                    inv.get("balance_cents")
                    or inv.get("amount_due")
                    or inv.get("total_cents")
                    or 0
                )
                subline_priority = "unpaid_invoice"
                subline_data = {"invoice_amount_cents": int(amt or 0)}
            else:
                # ── 4. Unread admin message ──────────────────────
                # ``message_threads`` is optional in some tenants — guard.
                try:
                    thread = await db.message_threads.find_one(
                        {"tenant_id": user["tenant_id"],
                         "customer_id": user.get("customer_id"),
                         "unread_for_customer": True},
                        {"_id": 0, "id": 1}, sort=[("last_message_at", -1)],
                    )
                except Exception:
                    thread = None
                if thread:
                    latest_message_thread_id = thread.get("id")
                    subline_priority = "unread_message"

    payload = {
        "first_name": first_name,
        "tenant_display_name": (
            card.get("company_name") or tenant.get("name") or "your service team"
        ),
        "tenant_logo_url": card.get("logo_url") or "",
        "gradient_from": card.get("gradient_from") or "#0EA5E9",
        "gradient_to": card.get("gradient_to") or "#16A34A",
        "time_of_day_bucket": tod,
        "subline_priority": subline_priority,
        "subline_data": subline_data,
        "unpaid_invoice_id": unpaid_invoice_id,
        "latest_message_thread_id": latest_message_thread_id,
        "next_visit_job_id": next_visit_job_id,
    }
    _CACHE[ck] = {"_at": time.time(), "payload": payload}
    return payload
