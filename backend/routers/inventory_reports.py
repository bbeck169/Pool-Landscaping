"""Phase 18 · Chemical Cost Report + Per-Tech Inventory + Department admin.

Endpoints (all mounted with the /api prefix by server.py):

  GET  /api/reports/chemical-costs       — Admin+ only. Aggregated
       chemical cost report from ``chemical_usage_events``. Filters:
       ``start``, ``end`` (ISO dates), ``department``
       (``pool|landscape|both``), ``tech_id``. Groups by tech +
       department + product_slug. Cost math is drawn STRICTLY from
       ``chemical_usage_events.unit_cost_at_time_cents *
       quantity_used`` per user's snapshot-priced source-of-truth
       decision.

  GET  /api/inventory/my-inventory       — Tech-visible read-only.
       Returns the tenant's ``inventory_items`` list stripped of
       cost fields (never exposes ``unit_cost`` or wholesale data to
       techs) plus a per-tech ``my_recent_usage`` block sourced from
       ``chemical_usage_events`` filtered to ``created_by=me``.

  PUT  /api/admin/users/{uid}/department — Admin+. Set a user's
       ``department`` enum (``pool_tech|landscape_tech|both`` or None
       to clear). No bulk migration — rows stay null until admin sets.

  PUT  /api/admin/inventory/{iid}/department — Admin+. Set a SKU's
       ``department`` enum (``pool|landscape|both``).

  POST /api/admin/suggest-departments    — Admin+. Infers each tech's
       likely department from their last-90-day ``jobs.service_type``
       distribution. Read-only; returns a suggestion list for a UI
       bulk-apply modal.

Visibility of cost data: the report endpoint is gated to
``require_admin`` (admin + super_admin + owner). Techs / customers get
403.  The tech mobile endpoint intentionally sanitizes cost fields
out of every row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, require_admin
from routers.tenants import get_current_tenant


router = APIRouter(tags=["Phase 18 · Inventory Reports"])


# ══════════════════════════════════════════════════════════════════
# 1) Chemical Cost Report — Admin+ only.
# ══════════════════════════════════════════════════════════════════
@router.get("/reports/chemical-costs")
async def chemical_cost_report(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
    start: Optional[str] = Query(None,
        description="ISO date/time (inclusive). Default: 30 days ago."),
    end: Optional[str] = Query(None,
        description="ISO date/time (inclusive). Default: now."),
    department: Optional[str] = Query(None,
        pattern="^(pool|landscape|both)$"),
    tech_id: Optional[str] = Query(None,
        description="Filter to a single technician (user_id)."),
):
    """Aggregate `chemical_usage_events` for the tenant.

    Cost math (per user's locked decision):
        cost = SUM(quantity_used * unit_cost_at_time_cents) — no pricebook
        lookup at report time (values are snapshot-priced at the moment
        of the service report submission by
        ``chemical_products.snapshot_chemical_usage``).
    """
    tenant_id = tenant["id"]

    # Default window: last 30 days.
    if not end:
        end = datetime.now(timezone.utc).isoformat()
    if not start:
        start_dt = datetime.now(timezone.utc) - timedelta(days=30)
        start = start_dt.isoformat()

    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "occurred_at": {"$gte": start, "$lte": end},
    }
    if tech_id:
        q["created_by"] = tech_id

    events = await db.chemical_usage_events.find(q, {"_id": 0}).to_list(20000)

    # Preload SKU → department map (chemicals table lives in
    # inventory_items now that Phase 18 seeded ``department`` on them).
    sku_dept: Dict[str, str] = {}
    async for it in db.inventory_items.find(
        {"tenant_id": tenant_id,
         "$or": [{"category": "chemical"},
                 {"is_seeded_chemical": True}]},
        {"_id": 0, "sku": 1, "name": 1, "department": 1},
    ):
        dept = it.get("department") or None
        nm = (it.get("name") or "").lower()
        sku = (it.get("sku") or "").lower()
        if sku and dept:
            sku_dept[sku] = dept
        if nm and dept:
            sku_dept[nm] = dept

    # Preload tech → (name, department) map.
    user_lookup: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
         "role": 1, "department": 1},
    ):
        user_lookup[u["id"]] = {
            "id": u["id"],
            "name": u.get("name") or u.get("email") or "(unknown)",
            "email": u.get("email"),
            "role": u.get("role"),
            "department": u.get("department"),
        }

    def _dept_of_event(ev: Dict[str, Any]) -> str:
        """Resolve the department for a single usage event."""
        slug = (ev.get("product_slug") or "").lower()
        nm = (ev.get("name") or "").lower()
        d = sku_dept.get(f"p18-{slug}") \
            or sku_dept.get(slug) \
            or sku_dept.get(nm)
        return d or "unassigned"

    def _tech_dept(uid: Optional[str]) -> str:
        if not uid:
            return "unassigned"
        return (user_lookup.get(uid, {}).get("department")
                or "unassigned")

    # Filter by department if requested.
    if department:
        events = [e for e in events if _dept_of_event(e) == department
                  or (department == "both"
                      and _dept_of_event(e) in ("pool", "landscape"))]

    # ─── Aggregate.
    total_cost_cents = 0
    total_quantity = 0.0
    by_product: Dict[str, Dict[str, Any]] = {}
    by_tech: Dict[str, Dict[str, Any]] = {}
    by_department: Dict[str, Dict[str, Any]] = {}
    for e in events:
        qty = float(e.get("quantity_used") or 0)
        cost = int(e.get("total_cost_cents") or 0)
        total_cost_cents += cost
        total_quantity += qty
        # Per-product.
        slug = e.get("product_slug") or "unknown"
        prod = by_product.setdefault(slug, {
            "product_slug": slug, "name": e.get("name"),
            "unit": e.get("unit"),
            "quantity_used": 0.0, "total_cost_cents": 0,
            "event_count": 0,
        })
        prod["quantity_used"] += qty
        prod["total_cost_cents"] += cost
        prod["event_count"] += 1
        # Per-tech.
        uid = e.get("created_by") or "unassigned"
        u = user_lookup.get(uid, {})
        tech = by_tech.setdefault(uid, {
            "user_id": uid,
            "name": u.get("name") or "(system / unknown)",
            "email": u.get("email"),
            "department": _tech_dept(uid),
            "quantity_used": 0.0, "total_cost_cents": 0,
            "event_count": 0,
        })
        tech["quantity_used"] += qty
        tech["total_cost_cents"] += cost
        tech["event_count"] += 1
        # Per-department (SKU-derived, per user 5ab).
        dep = _dept_of_event(e)
        d = by_department.setdefault(dep, {
            "department": dep, "quantity_used": 0.0,
            "total_cost_cents": 0, "event_count": 0,
        })
        d["quantity_used"] += qty
        d["total_cost_cents"] += cost
        d["event_count"] += 1

    return {
        "range": {"start": start, "end": end},
        "filters": {"department": department, "tech_id": tech_id},
        "totals": {
            "total_cost_cents": total_cost_cents,
            "total_quantity": round(total_quantity, 3),
            "event_count": len(events),
        },
        "per_product": sorted(
            by_product.values(),
            key=lambda x: x["total_cost_cents"], reverse=True),
        "per_tech": sorted(
            by_tech.values(),
            key=lambda x: x["total_cost_cents"], reverse=True),
        "per_department": sorted(
            by_department.values(),
            key=lambda x: x["total_cost_cents"], reverse=True),
    }


# ══════════════════════════════════════════════════════════════════
# 2) Tech mobile · my-inventory (NO COST DATA).
# ══════════════════════════════════════════════════════════════════
@router.get("/inventory/my-inventory")
async def my_inventory(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-only per-tech on-hand list.

    Techs, admins, super_admins, owners, and marketing users can call
    this. Customers → 403. Cost fields are STRIPPED — this endpoint
    NEVER exposes ``unit_cost``, ``cost_per_unit_cents``, or any
    wholesale margin data to a tech user. (Admins can see costs via
    /inventory/items which is a different endpoint.)
    """
    if user.get("role") == "customer":
        raise HTTPException(403, "Not permitted")

    tenant_id = tenant["id"]
    rows = await db.inventory_items.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "category": 1, "unit": 1, "sku": 1,
         "current_qty": 1, "reorder_point": 1, "reorder_qty": 1,
         "department": 1, "is_seeded_chemical": 1, "location": 1,
         "low_stock_notified_at": 1},
    ).to_list(2000)
    for r in rows:
        cur = float(r.get("current_qty") or 0)
        rp = r.get("reorder_point")
        r["low_stock"] = (rp is not None
                          and cur <= float(rp))
        r["out_of_stock"] = cur <= 0
    rows.sort(key=lambda r: (
        0 if r["out_of_stock"] else (1 if r["low_stock"] else 2),
        (r.get("name") or "").lower(),
    ))

    # Per-tech usage snapshot (last 30 days).
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    my_events = await db.chemical_usage_events.find(
        {"tenant_id": tenant_id,
         "created_by": user["id"],
         "occurred_at": {"$gte": since}},
        {"_id": 0, "product_slug": 1, "name": 1,
         "quantity_used": 1, "unit": 1, "occurred_at": 1},
    ).sort("occurred_at", -1).to_list(500)

    # Aggregate my usage by product for a "you used X" panel — again
    # NO COST FIELDS.
    usage_by_product: Dict[str, Dict[str, Any]] = {}
    for e in my_events:
        slug = e.get("product_slug") or "unknown"
        p = usage_by_product.setdefault(slug, {
            "product_slug": slug, "name": e.get("name"),
            "unit": e.get("unit"), "quantity_used": 0.0,
            "event_count": 0,
        })
        p["quantity_used"] += float(e.get("quantity_used") or 0)
        p["event_count"] += 1

    return {
        "items": rows,
        "total_items": len(rows),
        "low_stock_count": sum(1 for r in rows if r["low_stock"]),
        "out_of_stock_count": sum(1 for r in rows if r["out_of_stock"]),
        "my_recent_usage": sorted(
            usage_by_product.values(),
            key=lambda x: x["quantity_used"], reverse=True),
    }


# ══════════════════════════════════════════════════════════════════
# 3) Department admin — users + items.
# ══════════════════════════════════════════════════════════════════
class UserDepartmentIn(BaseModel):
    # None clears the field; user decision 5ab kept enum flexible.
    department: Optional[str] = Field(
        None, pattern="^(pool_tech|landscape_tech|both)$")


class ItemDepartmentIn(BaseModel):
    department: Optional[str] = Field(
        None, pattern="^(pool|landscape|both)$")


@router.put("/admin/users/{uid}/department")
async def set_user_department(uid: str, body: UserDepartmentIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    r = await db.users.update_one(
        {"id": uid, "tenant_id": tenant["id"]},
        {"$set": {"department": body.department,
                  "department_updated_at": now_iso(),
                  "department_updated_by": user["id"]}},
    )
    if not r.matched_count:
        raise HTTPException(404, "user not found in this tenant")
    return {"ok": True, "user_id": uid, "department": body.department}


@router.put("/admin/inventory/{iid}/department")
async def set_item_department(iid: str, body: ItemDepartmentIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    r = await db.inventory_items.update_one(
        {"id": iid, "tenant_id": tenant["id"]},
        {"$set": {"department": body.department,
                  "updated_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "inventory item not found in this tenant")
    return {"ok": True, "item_id": iid, "department": body.department}


@router.post("/admin/suggest-departments")
async def suggest_departments(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
    days: int = Query(90, ge=7, le=365),
):
    """Infer each tech's likely department from their last-90-day job
    ``service_type`` distribution. Read-only — returns a suggestion
    list. Admins apply via the bulk-apply modal in the UI which POSTs
    the accepted rows to the ``/admin/users/{uid}/department``
    endpoint one at a time.

    Mapping heuristic:
        service_type contains "pool"/"chem"/"clean"     → pool_tech
        service_type contains "landscape"/"lawn"/"mow"  → landscape_tech
        mix of both (both categories ≥ 25%)             → both
        no jobs / no signal                             → null
    """
    tenant_id = tenant["id"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Pull all techs.
    techs = await db.users.find(
        {"tenant_id": tenant_id,
         "role": {"$in": ["technician", "tech", "landscaper"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "department": 1},
    ).to_list(2000)
    if not techs:
        return {"suggestions": [], "count": 0}

    tech_ids = [t["id"] for t in techs]
    # Sum service_type frequency per assigned_technician_id.
    pipeline: List[Dict[str, Any]] = [
        {"$match": {
            "tenant_id": tenant_id,
            "created_at": {"$gte": since},
            "$or": [
                {"assigned_technician_id": {"$in": tech_ids}},
                {"technician_id": {"$in": tech_ids}},
            ],
        }},
        {"$project": {
            "tech_id": {"$ifNull": ["$assigned_technician_id",
                                    "$technician_id"]},
            "service_type": {"$toLower": {"$ifNull":
                ["$service_type", "$type"]}},
        }},
        {"$group": {
            "_id": {"tech_id": "$tech_id", "service_type": "$service_type"},
            "n": {"$sum": 1},
        }},
    ]
    grp = await db.jobs.aggregate(pipeline).to_list(20000)
    per_tech: Dict[str, Dict[str, int]] = {}
    for row in grp:
        tid = row["_id"].get("tech_id")
        st = row["_id"].get("service_type") or ""
        if not tid:
            continue
        per_tech.setdefault(tid, {"pool": 0, "landscape": 0, "unknown": 0})
        if any(k in st for k in ("pool", "chem", "clean", "spa")):
            per_tech[tid]["pool"] += row["n"]
        elif any(k in st for k in ("landscape", "lawn", "mow", "turf",
                                    "garden", "hedge", "shrub")):
            per_tech[tid]["landscape"] += row["n"]
        else:
            per_tech[tid]["unknown"] += row["n"]

    suggestions: List[Dict[str, Any]] = []
    for t in techs:
        counts = per_tech.get(t["id"], {})
        pool = counts.get("pool", 0)
        landscape = counts.get("landscape", 0)
        total = pool + landscape
        suggested = None
        confidence = 0.0
        if total > 0:
            pool_pct = pool / total
            land_pct = landscape / total
            if pool_pct >= 0.75:
                suggested = "pool_tech"
                confidence = pool_pct
            elif land_pct >= 0.75:
                suggested = "landscape_tech"
                confidence = land_pct
            elif pool_pct >= 0.25 and land_pct >= 0.25:
                suggested = "both"
                confidence = 1 - abs(pool_pct - land_pct)
        suggestions.append({
            "user_id": t["id"],
            "name": t.get("name") or t.get("email"),
            "current_department": t.get("department"),
            "suggested_department": suggested,
            "confidence": round(confidence, 3),
            "signals": {
                "pool_jobs": pool,
                "landscape_jobs": landscape,
                "days_window": days,
            },
        })
    return {"suggestions": suggestions, "count": len(suggestions)}


# ══════════════════════════════════════════════════════════════════
# 4) Alert settings — Slack webhook + quiet hours (Admin+).
# ══════════════════════════════════════════════════════════════════
class AlertSettingsIn(BaseModel):
    slack_webhook_url: Optional[str] = None
    quiet_hours_utc: Optional[Dict[str, Any]] = None
    # e.g. {"start_hour": 22, "end_hour": 6}


@router.get("/admin/inventory-alert-settings")
async def get_alert_settings(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    s = await db.inventory_alert_settings.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ) or {"tenant_id": tenant["id"]}
    # Mask webhook URL like other Phase 55 patterns.
    if s.get("slack_webhook_url"):
        s["slack_webhook_url_masked"] = _mask_webhook(s["slack_webhook_url"])
        s.pop("slack_webhook_url", None)
    return s


@router.put("/admin/inventory-alert-settings")
async def put_alert_settings(body: AlertSettingsIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    upd: Dict[str, Any] = {"updated_at": now_iso(),
                           "updated_by": user["id"]}
    if body.slack_webhook_url is not None:
        upd["slack_webhook_url"] = body.slack_webhook_url
    if body.quiet_hours_utc is not None:
        upd["quiet_hours_utc"] = body.quiet_hours_utc
    await db.inventory_alert_settings.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {**upd, "tenant_id": tenant["id"]}},
        upsert=True,
    )
    return {"ok": True}


def _mask_webhook(url: str) -> str:
    if not url:
        return ""
    if len(url) < 12:
        return "***"
    return url[:20] + "…" + url[-4:]
