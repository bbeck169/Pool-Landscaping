"""Phase 23 · Inventory tracker.

Chemical + parts stock levels tied to job usage. Auto-decrement on
service-report submit. Low-stock alerts + reorder points + purchase
orders (manual for now).

Endpoints:
 - CRUD /items with adjust + movement history
 - Purchase orders lifecycle (pending → ordered → received → auto-restock)
 - Alerts + analytics
 - Seed defaults on first fetch per tenant
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


# Starter catalogs. Format: (name, category, unit, current, reorder_point)
_STARTER = [
    # Chemicals
    ("Liquid Chlorine", "chemical", "gal", 20, 5),
    ("Chlorine Tablets", "chemical", "tabs", 200, 50),
    ("Muriatic Acid", "chemical", "oz", 320, 80),
    ("Cal-Hypo Shock", "chemical", "lbs", 40, 10),
    ("Soda Ash", "chemical", "lbs", 50, 10),
    ("Sodium Bicarbonate", "chemical", "lbs", 50, 10),
    ("Cyanuric Acid", "chemical", "lbs", 25, 5),
    ("Pool Salt", "chemical", "lbs", 240, 40),
    ("Algaecide", "chemical", "gal", 5, 2),
    ("Clarifier", "chemical", "gal", 3, 1),
    ("Phosphate Remover", "chemical", "gal", 2, 1),
    ("Enzymes", "chemical", "gal", 2, 1),
    ("Calcium Chloride", "chemical", "lbs", 30, 10),
    # Parts
    ("DE Powder", "part", "lbs", 25, 10),
    ("Pool Filter Cartridge", "part", "ea", 3, 2),
    ("Pump O-Ring", "part", "ea", 5, 2),
    ("Salt Cell Cleaner", "part", "gal", 2, 1),
    ("Skimmer Basket", "part", "ea", 3, 2),
]


async def _seed_defaults(tenant_id: str) -> None:
    existing = await db.inventory_items.count_documents(
        {"tenant_id": tenant_id})
    if existing:
        return
    docs = []
    for (name, cat, unit, cur, rp) in _STARTER:
        docs.append({
            "id": new_id(), "tenant_id": tenant_id,
            "name": name, "category": cat, "unit": unit,
            "sku": "", "current_qty": float(cur),
            "reorder_point": float(rp),
            "reorder_qty": float(rp),
            "unit_cost": 0.0, "supplier": "", "location": "",
            "notes": "", "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    if docs:
        await db.inventory_items.insert_many(docs)


class ItemIn(BaseModel):
    name: str
    category: str = Field(..., pattern="^(chemical|part|equipment|consumable|other)$")
    unit: str = Field(..., pattern="^(gal|lbs|oz|tabs|ea|linft|sqft|hr|yd|other)$")
    sku: Optional[str] = ""
    current_qty: float = Field(0, ge=0)
    reorder_point: float = Field(0, ge=0)
    reorder_qty: float = Field(0, ge=0)
    unit_cost: Optional[float] = 0.0
    supplier: Optional[str] = ""
    location: Optional[str] = ""
    notes: Optional[str] = ""


class ItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    sku: Optional[str] = None
    reorder_point: Optional[float] = None
    reorder_qty: Optional[float] = None
    unit_cost: Optional[float] = None
    supplier: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class AdjustIn(BaseModel):
    delta: float
    reason: str = "manual adjustment"
    notes: Optional[str] = ""


class POItemIn(BaseModel):
    item_id: str
    qty: float = Field(..., gt=0)
    unit_cost: float = Field(0, ge=0)


class POIn(BaseModel):
    supplier: str
    items: List[POItemIn]
    expected_delivery: Optional[str] = None
    notes: Optional[str] = ""


class POPatch(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|ordered|received|cancelled)$")
    supplier: Optional[str] = None
    expected_delivery: Optional[str] = None
    notes: Optional[str] = None


async def require_reader(user: dict = Depends(get_current_user)) -> dict:
    """Admin + super_admin + technician + marketing can READ inventory.
    Customer → 403."""
    if user.get("role") in {"admin", "super_admin", "technician", "marketing"}:
        return user
    raise HTTPException(403, "Not permitted")


# ── Items ────────────────────────────────────────────────────────────

@router.get("/inventory/items")
async def list_items(category: Optional[str] = None,
                        low_stock: bool = False,
                        q: Optional[str] = None,
                        user: dict = Depends(require_reader),
                        tenant: dict = Depends(get_current_tenant)):
    await _seed_defaults(tenant["id"])
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if category:
        query["category"] = category
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    rows = await db.inventory_items.find(query, {"_id": 0}).sort(
        "name", 1).to_list(2000)
    if low_stock:
        rows = [r for r in rows
                 if float(r.get("current_qty", 0))
                    <= float(r.get("reorder_point", 0))]
    return {"items": rows, "total": len(rows)}


@router.post("/inventory/items")
async def create_item(body: ItemIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    doc = body.model_dump()
    doc.update({"id": new_id(), "tenant_id": tenant["id"],
                 "created_at": now_iso(), "updated_at": now_iso()})
    await db.inventory_items.insert_one(dict(doc))
    doc.pop("_id", None)
    # Initial movement so history isn't empty.
    if doc["current_qty"] > 0:
        await db.stock_movements.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "item_id": doc["id"], "delta": float(doc["current_qty"]),
            "kind": "initial", "reason": "initial stock",
            "ref_type": "manual", "ref_id": None,
            "performed_by": user["id"], "notes": "",
            "ts": now_iso(),
        })
    return doc


@router.patch("/inventory/items/{iid}")
async def update_item(iid: str, body: ItemPatch,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    it = await db.inventory_items.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not it:
        raise HTTPException(404, "Item not found")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if upd:
        upd["updated_at"] = now_iso()
        await db.inventory_items.update_one(
            {"id": iid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.inventory_items.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/inventory/items/{iid}")
async def delete_item(iid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.inventory_items.delete_one(
        {"id": iid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Item not found")
    return {"deleted": True}


@router.post("/inventory/items/{iid}/adjust")
async def adjust_item(iid: str, body: AdjustIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    it = await db.inventory_items.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not it:
        raise HTTPException(404, "Item not found")
    new_qty = max(0.0, float(it.get("current_qty", 0)) + float(body.delta))
    kind = ("restock" if body.delta > 0
              else "usage" if body.delta < 0
              else "correction")
    await db.inventory_items.update_one(
        {"id": iid, "tenant_id": tenant["id"]},
        {"$set": {"current_qty": new_qty, "updated_at": now_iso()}},
    )
    mv = {
        "id": new_id(), "tenant_id": tenant["id"], "item_id": iid,
        "delta": float(body.delta), "kind": kind, "reason": body.reason,
        "ref_type": "manual", "ref_id": None,
        "performed_by": user["id"], "notes": body.notes or "",
        "ts": now_iso(),
    }
    await db.stock_movements.insert_one(dict(mv))
    mv.pop("_id", None)
    return {"item_id": iid, "current_qty": new_qty, "movement": mv}


@router.get("/inventory/items/{iid}/movements")
async def item_movements(iid: str,
                            user: dict = Depends(require_reader),
                            tenant: dict = Depends(get_current_tenant)):
    it = await db.inventory_items.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1})
    if not it:
        raise HTTPException(404, "Item not found")
    rows = await db.stock_movements.find(
        {"item_id": iid, "tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("ts", -1).to_list(1000)
    return {"items": rows, "total": len(rows)}


# ── Purchase orders ──────────────────────────────────────────────────

@router.post("/inventory/purchase-orders")
async def create_po(body: POIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    # Validate items belong to tenant
    for it in body.items:
        m = await db.inventory_items.find_one(
            {"id": it.item_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1})
        if not m:
            raise HTTPException(404,
                f"Item {it.item_id} not found in tenant")
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "supplier": body.supplier,
        "items": [i.model_dump() for i in body.items],
        "expected_delivery": body.expected_delivery,
        "notes": body.notes or "",
        "status": "pending",
        "created_by": user["id"],
        "created_at": now_iso(),
        "total_cost": round(sum(i.qty * i.unit_cost for i in body.items), 2),
    }
    await db.purchase_orders.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/inventory/purchase-orders")
async def list_pos(status: Optional[str] = None,
                      user: dict = Depends(require_reader),
                      tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    rows = await db.purchase_orders.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.patch("/inventory/purchase-orders/{poid}")
async def update_po(poid: str, body: POPatch,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    po = await db.purchase_orders.find_one(
        {"id": poid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    upd: Dict[str, Any] = {}
    if body.supplier is not None: upd["supplier"] = body.supplier
    if body.expected_delivery is not None: upd["expected_delivery"] = body.expected_delivery
    if body.notes is not None: upd["notes"] = body.notes
    if body.status is not None and body.status != po.get("status"):
        upd["status"] = body.status
        if body.status == "ordered":
            upd["ordered_at"] = now_iso()
        elif body.status == "received":
            upd["received_at"] = now_iso()
            # Auto-restock on receive.
            for it in (po.get("items") or []):
                mv_id = new_id()
                res = await db.inventory_items.update_one(
                    {"id": it["item_id"], "tenant_id": tenant["id"]},
                    {"$inc": {"current_qty": float(it["qty"])},
                     "$set": {"updated_at": now_iso()}},
                )
                if res.matched_count:
                    await db.stock_movements.insert_one({
                        "id": mv_id, "tenant_id": tenant["id"],
                        "item_id": it["item_id"],
                        "delta": float(it["qty"]), "kind": "restock",
                        "reason": f"PO {poid[:8]} received",
                        "ref_type": "purchase_order", "ref_id": poid,
                        "performed_by": user["id"], "notes": "",
                        "ts": now_iso(),
                    })
    if upd:
        upd["updated_at"] = now_iso()
        await db.purchase_orders.update_one(
            {"id": poid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.purchase_orders.find_one(
        {"id": poid, "tenant_id": tenant["id"]}, {"_id": 0})


# ── Alerts + analytics ───────────────────────────────────────────────

@router.get("/inventory/alerts")
async def alerts(user: dict = Depends(require_reader),
                    tenant: dict = Depends(get_current_tenant)):
    await _seed_defaults(tenant["id"])
    rows = await db.inventory_items.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).to_list(2000)
    alerts = []
    for r in rows:
        cur = float(r.get("current_qty", 0))
        rp = float(r.get("reorder_point", 0))
        if cur <= rp:
            alerts.append({
                "item_id": r["id"], "name": r["name"],
                "category": r["category"], "unit": r["unit"],
                "current_qty": cur, "reorder_point": rp,
                "reorder_qty": float(r.get("reorder_qty", rp)),
                "suggested_action":
                    "OUT OF STOCK — order now" if cur <= 0
                    else "Below reorder point",
            })
    alerts.sort(key=lambda x: x["current_qty"])
    return {"items": alerts, "total": len(alerts)}


@router.get("/inventory/analytics")
async def analytics(user: dict = Depends(require_reader),
                        tenant: dict = Depends(get_current_tenant)):
    await _seed_defaults(tenant["id"])
    rows = await db.inventory_items.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).to_list(5000)
    total_value = sum(float(r.get("current_qty", 0))
                        * float(r.get("unit_cost", 0)) for r in rows)
    low = [r for r in rows
             if float(r.get("current_qty", 0))
                <= float(r.get("reorder_point", 0))]
    oos = [r for r in low if float(r.get("current_qty", 0)) <= 0]
    # Most used last 30d — sum |delta| where kind=="usage"
    cutoff = (datetime.now(timezone.utc)
                - timedelta(days=30)).isoformat()
    pipeline = [
        {"$match": {"tenant_id": tenant["id"],
                       "kind": "usage", "ts": {"$gte": cutoff}}},
        {"$group": {"_id": "$item_id",
                       "used": {"$sum": {"$abs": "$delta"}}}},
        {"$sort": {"used": -1}}, {"$limit": 10},
    ]
    most_used_raw = await db.stock_movements.aggregate(pipeline).to_list(50)
    by_id = {r["id"]: r for r in rows}
    most_used = [
        {"item_id": m["_id"],
          "name": (by_id.get(m["_id"]) or {}).get("name") or "?",
          "unit": (by_id.get(m["_id"]) or {}).get("unit") or "",
          "used": round(m["used"], 2)}
        for m in most_used_raw if m["_id"] in by_id
    ]
    return {
        "total_items": len(rows),
        "total_value": round(total_value, 2),
        "low_stock_count": len(low),
        "out_of_stock_count": len(oos),
        "most_used_last_30d": most_used,
        "reorder_forecast": [
            {"item_id": r["id"], "name": r["name"],
              "current_qty": float(r.get("current_qty", 0)),
              "reorder_point": float(r.get("reorder_point", 0))}
            for r in sorted(low, key=lambda r: float(r.get("current_qty", 0)))[:10]
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# Service-report integration — called from routers/service_reports.py
# ═══════════════════════════════════════════════════════════════════════

async def decrement_from_service_report(
    tenant_id: str, job: Dict[str, Any], report_id: str, user_id: str,
) -> Dict[str, Any]:
    """Decrement inventory based on `job.chemicals_added` and (optional)
    `job.parts_used`. Returns `{decremented, misses}`. Never raises —
    caller must NOT block submit on inventory errors."""
    await _seed_defaults(tenant_id)
    decremented: List[Dict[str, Any]] = []
    misses: List[str] = []
    all_items = await db.inventory_items.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "name": 1,
                                       "current_qty": 1,
                                       "reorder_point": 1, "unit": 1},
    ).to_list(2000)
    by_name = {(r.get("name") or "").strip().lower(): r
                for r in all_items}
    triggered_alerts: List[str] = []

    def _try_decrement_sync(entry_name: str, amount: float, kind: str):
        """Deferred to caller via a list; caller awaits at end."""
        key = (entry_name or "").strip().lower()
        matched = by_name.get(key)
        if not matched:
            misses.append(entry_name)
            return
        try:
            qty = float(amount)
        except Exception:
            return
        if qty <= 0:
            return
        pending.append((matched, qty, kind))

    pending: List[tuple] = []
    for c in (job.get("chemicals_added") or []):
        name = c.get("name") or c.get("chemical") or ""
        amount = c.get("amount") or c.get("qty") or 0
        _try_decrement_sync(name, amount, "usage")
    for p in (job.get("parts_used") or []):
        _try_decrement_sync(p.get("name") or "",
                              p.get("qty") or p.get("amount") or 0, "usage")

    for matched, qty, kind in pending:
        new_qty = max(0.0, float(matched.get("current_qty", 0)) - qty)
        await db.inventory_items.update_one(
            {"id": matched["id"], "tenant_id": tenant_id},
            {"$set": {"current_qty": new_qty, "updated_at": now_iso()}},
        )
        await db.stock_movements.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "item_id": matched["id"], "delta": -qty, "kind": kind,
            "reason": "service report chemicals/parts used",
            "ref_type": "service_report", "ref_id": report_id,
            "performed_by": user_id, "notes": "", "ts": now_iso(),
        })
        decremented.append({
            "item_id": matched["id"], "name": matched.get("name"),
            "amount": qty, "new_qty": new_qty,
        })
        if new_qty <= float(matched.get("reorder_point", 0)):
            triggered_alerts.append(matched["id"])

    return {"decremented": decremented, "misses": misses,
             "low_stock_alerts": triggered_alerts}


async def _persist_decrement(*args, **kwargs):
    """Deprecated helper kept for backward compat; no longer used."""
    return None


# ─── Phase 39 · Step 3 · Truck Inventory Reservation ─────────────────
# Reservations live alongside items in `inventory_reservations`. Phase 23
# has no per-tech truck stock — reservations sit against the shared tenant
# `inventory_items.current_qty` and `tech_user_id` is captured so a future
# per-truck rollout can pivot without a schema change. Shortage warnings
# are informational: reservations are NEVER blocked so techs can still add
# what a pool truly needs.
class ReserveIn(BaseModel):
    chemical: str
    quantity: float
    unit: Optional[str] = ""
    job_id: str
    tech_user_id: Optional[str] = None
    reservation_id: Optional[str] = None


async def _match_item(tenant_id: str, chemical: str):
    """Find the inventory item that matches a chemical name (case-insensitive,
    tries exact + startswith fallback)."""
    name = (chemical or "").strip()
    if not name:
        return None
    # Exact match first.
    it = await db.inventory_items.find_one(
        {"tenant_id": tenant_id,
         "name": {"$regex": f"^{name}$", "$options": "i"}}, {"_id": 0})
    if it:
        return it
    return await db.inventory_items.find_one(
        {"tenant_id": tenant_id,
         "name": {"$regex": f"^{name}", "$options": "i"}}, {"_id": 0})


async def _sum_active_reservations(tenant_id: str, chemical: str,
                                     exclude_id: str | None = None) -> float:
    q: dict = {"tenant_id": tenant_id, "status": "active",
                "chemical": {"$regex": f"^{chemical}$", "$options": "i"}}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    total = 0.0
    async for r in db.inventory_reservations.find(q, {"_id": 0, "quantity": 1}):
        total += float(r.get("quantity") or 0)
    return total


def _shortage_warning(chemical: str, unit: str, current_qty: float,
                       other_active: float, requested: float):
    available = current_qty - other_active - requested
    if available >= 0:
        return None
    shortfall = abs(available)
    return {
        "warning": f"Truck will be short {round(shortfall, 2)} {unit} of {chemical}",
        "suggested_restock": max(1, int(-(-shortfall * 1.5 // 1))),
        "current_qty": round(current_qty, 2),
        "already_reserved": round(other_active, 2),
        "requested": round(requested, 2),
    }


@router.post("/inventory/reserve")
async def reserve_inventory(body: ReserveIn,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not permitted")
    if body.quantity < 0:
        raise HTTPException(400, "quantity must be ≥ 0")
    now = now_iso()
    tenant_id = tenant["id"]

    item = await _match_item(tenant_id, body.chemical)
    unit = body.unit or (item or {}).get("unit") or ""
    current_qty = float((item or {}).get("current_qty") or 0)

    if body.reservation_id:
        existing = await db.inventory_reservations.find_one(
            {"id": body.reservation_id, "tenant_id": tenant_id,
             "status": "active"}, {"_id": 0})
        if not existing:
            raise HTTPException(404, "Reservation not found")
        # Zero quantity → auto-release.
        if body.quantity == 0:
            await db.inventory_reservations.update_one(
                {"id": existing["id"]},
                {"$set": {"status": "released", "released_at": now,
                           "updated_at": now, "quantity": 0}})
            return {"ok": True, "reservation_id": existing["id"],
                     "status": "released", "warning": None,
                     "delta": -float(existing["quantity"])}
        # Compute shortage using other active reservations.
        others = await _sum_active_reservations(tenant_id, body.chemical,
                                                  exclude_id=existing["id"])
        warn = _shortage_warning(body.chemical, unit, current_qty,
                                  others, body.quantity) if item else None
        await db.inventory_reservations.update_one(
            {"id": existing["id"]},
            {"$set": {"quantity": body.quantity, "unit": unit,
                       "updated_at": now,
                       "tech_user_id": body.tech_user_id or existing.get("tech_user_id")}})
        return {"ok": True, "reservation_id": existing["id"],
                 "status": "active", "warning": (warn or {}).get("warning"),
                 "suggested_restock": (warn or {}).get("suggested_restock"),
                 "matched_item_id": (item or {}).get("id"),
                 "delta": body.quantity - float(existing["quantity"])}

    # New reservation.
    others = await _sum_active_reservations(tenant_id, body.chemical)
    warn = _shortage_warning(body.chemical, unit, current_qty, others,
                              body.quantity) if item else None
    rid = new_id()
    doc = {
        "id": rid, "tenant_id": tenant_id,
        "job_id": body.job_id, "tech_user_id": body.tech_user_id,
        "chemical": body.chemical, "quantity": float(body.quantity),
        "unit": unit, "status": "active",
        "matched_item_id": (item or {}).get("id"),
        "created_at": now, "updated_at": now,
        "consumed_at": None, "released_at": None,
    }
    await db.inventory_reservations.insert_one(doc)
    return {"ok": True, "reservation_id": rid, "status": "active",
             "warning": (warn or {}).get("warning"),
             "suggested_restock": (warn or {}).get("suggested_restock"),
             "matched_item_id": doc["matched_item_id"], "delta": body.quantity,
             "unmatched": item is None}


@router.delete("/inventory/reserve/{reservation_id}")
async def release_reservation(reservation_id: str,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not permitted")
    r = await db.inventory_reservations.find_one(
        {"id": reservation_id, "tenant_id": tenant["id"],
         "status": "active"}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Reservation not found or already inactive")
    now = now_iso()
    await db.inventory_reservations.update_one(
        {"id": reservation_id},
        {"$set": {"status": "released", "released_at": now, "updated_at": now}})
    return {"ok": True, "released_at": now}


@router.post("/inventory/reservations/{job_id}/consume")
async def consume_job_reservations(job_id: str,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    """Called from service-report submit (server-side). Subtracts each
    active reservation from the shared item pool and stamps a
    stock_movement per line. Idempotent — already-consumed reservations
    are skipped."""
    now = now_iso()
    rows = await db.inventory_reservations.find(
        {"tenant_id": tenant["id"], "job_id": job_id,
         "status": "active"}, {"_id": 0}).to_list(200)
    consumed = []
    for r in rows:
        it = None
        if r.get("matched_item_id"):
            it = await db.inventory_items.find_one(
                {"id": r["matched_item_id"], "tenant_id": tenant["id"]},
                {"_id": 0})
        if it:
            new_qty = max(0.0, float(it.get("current_qty") or 0) - float(r["quantity"]))
            await db.inventory_items.update_one(
                {"id": it["id"]},
                {"$set": {"current_qty": new_qty, "updated_at": now}})
            await db.stock_movements.insert_one({
                "id": new_id(), "tenant_id": tenant["id"],
                "item_id": it["id"], "delta": -float(r["quantity"]),
                "reason": "reservation-consumed", "job_id": job_id,
                "reservation_id": r["id"], "at": now})
        await db.inventory_reservations.update_one(
            {"id": r["id"]},
            {"$set": {"status": "consumed", "consumed_at": now,
                       "updated_at": now}})
        consumed.append({"reservation_id": r["id"], "chemical": r["chemical"],
                          "quantity": r["quantity"], "matched": bool(it)})
    return {"ok": True, "consumed": consumed, "count": len(consumed)}


@router.post("/inventory/reservations/{job_id}/release")
async def release_job_reservations(job_id: str,
                                       user: dict = Depends(get_current_user),
                                       tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not permitted")
    now = now_iso()
    r = await db.inventory_reservations.update_many(
        {"tenant_id": tenant["id"], "job_id": job_id, "status": "active"},
        {"$set": {"status": "released", "released_at": now, "updated_at": now}})
    return {"ok": True, "released": r.modified_count}


@router.get("/inventory/truck/{tech_user_id}/reservations")
async def list_truck_reservations(tech_user_id: str,
                                       user: dict = Depends(get_current_user),
                                       tenant: dict = Depends(get_current_tenant)):
    """List active reservations for a tech. Admins can view any tech;
    techs can only view their own."""
    if user.get("role") == "technician" and user.get("id") != tech_user_id:
        raise HTTPException(403, "Techs can only see their own reservations")
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not permitted")
    rows = await db.inventory_reservations.find(
        {"tenant_id": tenant["id"], "tech_user_id": tech_user_id,
         "status": "active"}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": rows, "count": len(rows)}
