"""Phase 51.I · Recurring-Job Scheduling Engine.

Collection `recurring_job_templates` — schema in the router docstring.
Every generated job carries `recurring_template_id`. A unique index on
`(recurring_template_id, scheduled_date)` guarantees idempotent
regeneration.

Endpoints (all admin/super_admin unless noted):
    POST   /api/recurring-jobs
    GET    /api/recurring-jobs?active=true
    GET    /api/recurring-jobs/{id}
    PATCH  /api/recurring-jobs/{id}
    DELETE /api/recurring-jobs/{id}                        (soft-delete)
    POST   /api/recurring-jobs/{id}/generate?through=YYYY-MM-DD

The nightly cron `run_recurring_job_generator()` walks every active
template across every tenant and generates jobs from
`last_generated_through + 1` through `today + 14 days`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter(tags=["recurring_jobs"])

VALID_FREQ = {"weekly", "biweekly", "monthly", "custom"}


class RecurringJobIn(BaseModel):
    customer_id: str
    service_type: str
    frequency: str
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)
    start_date: str
    end_date: Optional[str] = None
    assigned_tech_id: Optional[str] = None
    price_cents: int = 0
    notes: str = ""
    allow_sunday: bool = False
    active: bool = True


class RecurringJobPatch(BaseModel):
    service_type: Optional[str] = None
    frequency: Optional[str] = None
    interval_days: Optional[int] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    assigned_tech_id: Optional[str] = None
    price_cents: Optional[int] = None
    notes: Optional[str] = None
    allow_sunday: Optional[bool] = None
    active: Optional[bool] = None


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _validate(body: RecurringJobIn | RecurringJobPatch) -> None:
    freq = body.frequency
    if freq is not None and freq not in VALID_FREQ:
        raise HTTPException(422, f"frequency must be one of {sorted(VALID_FREQ)}")
    if freq == "custom" and not body.interval_days:
        raise HTTPException(422, "interval_days is required for custom frequency")
    if freq in ("weekly", "biweekly") and body.day_of_week is None:
        raise HTTPException(422, "day_of_week (0=Mon…6=Sun) is required for weekly/biweekly")
    if freq == "monthly" and body.day_of_month is None:
        raise HTTPException(422, "day_of_month is required for monthly")


def _next_occurrences(tpl: Dict[str, Any], anchor: date,
                        horizon_end: date, max_count: int = 60) -> List[date]:
    """Return every occurrence date strictly ≥ anchor and ≤ horizon_end
    that satisfies the template's frequency rules. Sunday is skipped by
    default unless `allow_sunday` is True. Respects `end_date`."""
    start = _parse_date(tpl.get("start_date")) or anchor
    end_date = _parse_date(tpl.get("end_date"))
    allow_sunday = bool(tpl.get("allow_sunday"))
    freq = tpl.get("frequency")
    dow = tpl.get("day_of_week")
    dom = tpl.get("day_of_month")
    interval = int(tpl.get("interval_days") or 7)

    # Anchor the walk: never before `start_date`.
    walker = max(start, anchor)
    if end_date and walker > end_date:
        return []
    hard_stop = min(horizon_end, end_date) if end_date else horizon_end

    out: List[date] = []
    if freq == "weekly":
        # Snap forward to next matching weekday.
        while walker.weekday() != dow:
            walker += timedelta(days=1)
        step = timedelta(days=7)
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    elif freq == "biweekly":
        while walker.weekday() != dow:
            walker += timedelta(days=1)
        # Anchor cadence to start_date so biweekly stays aligned across regenerations.
        base = start
        while base.weekday() != dow:
            base += timedelta(days=1)
        diff = (walker - base).days
        offset = diff % 14
        if offset:
            walker += timedelta(days=(14 - offset))
        step = timedelta(days=14)
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    elif freq == "monthly":
        # Walk month-by-month; pick day_of_month clamped to the month's length.
        import calendar as _cal
        y, m = walker.year, walker.month
        while len(out) < max_count:
            last_day = _cal.monthrange(y, m)[1]
            picked_day = min(dom or 1, last_day)
            candidate = date(y, m, picked_day)
            if candidate < walker:
                # push to next month
                m += 1
                if m > 12:
                    m = 1; y += 1
                continue
            if candidate > hard_stop:
                break
            if allow_sunday or candidate.weekday() != 6:
                out.append(candidate)
            m += 1
            if m > 12:
                m = 1; y += 1
    elif freq == "custom":
        step = timedelta(days=interval)
        # Anchor cadence to start_date so custom stays aligned.
        base = start
        diff = (walker - base).days
        offset = diff % interval
        if offset:
            walker += timedelta(days=(interval - offset))
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    return out


async def _ensure_indexes():
    try:
        await db.recurring_job_templates.create_index(
            [("tenant_id", 1), ("active", 1)]
        )
        # Unique on (recurring_template_id, scheduled_date) — guarantees
        # idempotent regeneration. `sparse` so pre-existing jobs (no
        # template) are unaffected.
        await db.jobs.create_index(
            [("recurring_template_id", 1), ("scheduled_date", 1)],
            unique=True, sparse=True,
        )
    except Exception as e:
        logger.warning(f"recurring_jobs index: {e}")


@router.post("/recurring-jobs")
async def create_recurring(body: RecurringJobIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    _validate(body)
    await _ensure_indexes()
    cust = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0, "name": 1}
    )
    if not cust:
        raise HTTPException(404, "customer not found")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_name": cust.get("name"),
        "last_generated_through": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
    })
    await db.recurring_job_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/recurring-jobs")
async def list_recurring(active: Optional[bool] = Query(None),
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if active is not None:
        q["active"] = bool(active)
    rows = await db.recurring_job_templates.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Attach the next 3 upcoming occurrences so the UI table can render a preview.
    today = date.today()
    horizon = today + timedelta(days=90)
    for r in rows:
        try:
            occ = _next_occurrences(r, today, horizon, max_count=3)
            r["upcoming"] = [d.isoformat() for d in occ]
        except Exception:
            r["upcoming"] = []
    return {"items": rows, "count": len(rows)}


@router.get("/recurring-jobs/{tpl_id}")
async def get_recurring(tpl_id: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "template not found")
    today = date.today()
    horizon = today + timedelta(days=90)
    doc["upcoming"] = [d.isoformat() for d in _next_occurrences(doc, today, horizon, max_count=6)]
    return doc


@router.patch("/recurring-jobs/{tpl_id}")
async def patch_recurring(tpl_id: str, body: RecurringJobPatch,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    _validate(body)
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None or k == "active"}
    updates["updated_at"] = now_iso()
    res = await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "template not found")
    return await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/recurring-jobs/{tpl_id}")
async def delete_recurring(tpl_id: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    res = await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant["id"]},
        {"$set": {"active": False, "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "template not found")
    return {"id": tpl_id, "active": False}


async def _generate_from_template(tpl: Dict[str, Any], through: date) -> Dict[str, Any]:
    """Idempotent — inserts jobs for occurrences that aren't already
    materialized. Returns {inserted, skipped, dates}."""
    tenant_id = tpl["tenant_id"]
    # Walk from `last_generated_through + 1` OR `start_date`, whichever is later.
    last = _parse_date(tpl.get("last_generated_through"))
    start = _parse_date(tpl.get("start_date")) or date.today()
    anchor = (last + timedelta(days=1)) if last else start
    dates = _next_occurrences(tpl, anchor, through, max_count=200)
    if not dates:
        return {"inserted": 0, "skipped": 0, "dates": []}
    # Look up customer + tech for the payload.
    cust = await db.customers.find_one(
        {"id": tpl.get("customer_id"), "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "address": 1},
    ) or {}
    tech = None
    if tpl.get("assigned_tech_id"):
        tech = await db.users.find_one({"id": tpl["assigned_tech_id"]},
                                          {"_id": 0, "name": 1, "technician_id": 1})
    tech_id = tpl.get("assigned_tech_id")
    tech_name = (tech or {}).get("name") or None

    price_dollars = round((tpl.get("price_cents") or 0) / 100.0, 2)
    inserted, skipped = 0, 0
    inserted_dates: List[str] = []
    for d in dates:
        iso = d.isoformat()
        try:
            await db.jobs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "title": tpl.get("service_type") or "Recurring Service",
                "service_type": tpl.get("service_type"),
                "customer_id": tpl.get("customer_id"),
                "customer_name": cust.get("name") or tpl.get("customer_name"),
                "address": cust.get("address") or "",
                "technician_id": tech_id,
                "technician_name": tech_name,
                "scheduled_date": iso,
                "status": "scheduled",
                "price": price_dollars,
                "notes": tpl.get("notes") or "",
                "recurring_template_id": tpl["id"],
                "created_at": now_iso(),
            })
            inserted += 1
            inserted_dates.append(iso)
        except Exception as e:
            # Duplicate key = already exists → idempotent skip.
            if "duplicate key" in str(e).lower() or "E11000" in str(e):
                skipped += 1
            else:
                logger.warning(f"recurring insert skipped: {e}")
                skipped += 1
    await db.recurring_job_templates.update_one(
        {"id": tpl["id"], "tenant_id": tenant_id},
        {"$set": {"last_generated_through": dates[-1].isoformat(),
                    "updated_at": now_iso()}},
    )
    return {"inserted": inserted, "skipped": skipped, "dates": inserted_dates}


@router.post("/recurring-jobs/{tpl_id}/generate")
async def generate_now(tpl_id: str,
                         through: Optional[str] = Query(None),
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    tpl = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"], "active": True}, {"_id": 0}
    )
    if not tpl:
        raise HTTPException(404, "template not found or inactive")
    horizon = _parse_date(through) or (date.today() + timedelta(days=14))
    return await _generate_from_template(tpl, horizon)


# ─── APScheduler nightly cron ────────────────────────────────────────
async def run_recurring_job_generator() -> Dict[str, Any]:
    """Iterate every active template across every tenant and generate
    the rolling 2-week horizon."""
    await _ensure_indexes()
    today = date.today()
    horizon = today + timedelta(days=14)
    total_inserted = 0
    total_skipped = 0
    templates_processed = 0
    async for tpl in db.recurring_job_templates.find({"active": True}, {"_id": 0}):
        try:
            result = await _generate_from_template(tpl, horizon)
            total_inserted += result["inserted"]
            total_skipped += result["skipped"]
            templates_processed += 1
        except Exception as e:
            logger.warning(f"recurring generator error for {tpl.get('id')}: {e}")
    logger.info(
        f"Recurring job generator: templates={templates_processed} "
        f"inserted={total_inserted} skipped={total_skipped}"
    )
    return {"templates_processed": templates_processed,
             "inserted": total_inserted, "skipped": total_skipped}
