"""Feb-2026 · Chemical Cost Report — `/api/reports/chemical-costs`.

Aggregates paid invoice line items where the linked pricebook item
has ``category`` matching the case-insensitive "chemical" bucket.
Uses ``wholesale_cost_snapshot`` (captured at invoice-line write
time per the Pricebook Cost Flow ship) so the report reflects the
COST OF GOODS at the moment of sale — never re-priced.

RBAC: super_admin, admin, manager only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user


router = APIRouter()
logger = logging.getLogger("chemical_cost_report")

_REPORT_ROLES = {"super_admin", "admin", "manager"}


def _require(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _REPORT_ROLES:
        raise HTTPException(403, "forbidden")


def _to_dt_end(iso_date: str) -> str:
    """Coerce a YYYY-MM-DD to an ISO end-of-day UTC string so range
    filters don't accidentally exclude same-day invoices."""
    if len(iso_date) == 10:
        return f"{iso_date}T23:59:59+00:00"
    return iso_date


@router.get("/reports/chemical-costs")
async def chemical_cost_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    tech_id: Optional[str] = Query(None),
    chemical_ids: Optional[str] = Query(
        None, description="Comma-separated pricebook item ids to restrict"),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require(user)
    tid = tenant["id"]

    # Step 1 — resolve the chemical id-set from the pricebook.
    pb_filter: Dict[str, Any] = {
        "tenant_id": tid,
        "$or": [
            {"category": {"$regex": "^chemical$", "$options": "i"}},
            {"is_chemical": True},
        ],
    }
    if chemical_ids:
        ids = [x.strip() for x in chemical_ids.split(",") if x.strip()]
        if ids:
            pb_filter["id"] = {"$in": ids}
    pb_map: Dict[str, Dict[str, Any]] = {}
    async for row in db.items.find(
        pb_filter,
        {"_id": 0, "id": 1, "name": 1, "unit": 1, "category": 1},
    ):
        pb_map[row["id"]] = row
    if not pb_map:
        return {
            "date_range": {"start": date_from, "end": date_to},
            "totals": {"total_wholesale_cost": 0.0, "total_qty": 0,
                        "job_count": 0},
            "by_chemical": [],
        }

    # Step 2 — invoice filter (paid + date + optional customer).
    inv_filter: Dict[str, Any] = {
        "tenant_id": tid,
        "doc_type": "invoice",
        "payment_status": "paid",
    }
    date_gate: Dict[str, Any] = {}
    if date_from:
        date_gate["$gte"] = date_from
    if date_to:
        date_gate["$lte"] = _to_dt_end(date_to)
    if date_gate:
        # Prefer ``paid_at`` when set, fall back to ``created_at``.
        inv_filter["$or"] = [
            {"paid_at": date_gate},
            {"$and": [
                {"paid_at": {"$exists": False}},
                {"created_at": date_gate},
            ]},
        ]
    if customer_id:
        inv_filter["customer_id"] = customer_id

    # Step 3 — collect matching invoices, filter line items to
    # chemicals, aggregate per pricebook item.
    per_chem: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    total_qty = 0
    matched_jobs: set = set()
    matched_customers: Dict[str, Dict[str, Any]] = {}
    matched_techs: Dict[str, Dict[str, Any]] = {}

    async for inv in db.quotes.find(
        inv_filter,
        {"_id": 0, "id": 1, "job_id": 1, "customer_id": 1,
          "customer_name": 1, "line_items": 1},
    ):
        job_id = inv.get("job_id")
        cust_id = inv.get("customer_id")
        cust_name = inv.get("customer_name") or "Unknown"
        # Optional tech filter — resolve via job's technician_id.
        if tech_id:
            job_doc = None
            if job_id:
                job_doc = await db.jobs.find_one(
                    {"id": job_id, "tenant_id": tid},
                    {"_id": 0, "technician_id": 1},
                )
            if not job_doc or job_doc.get("technician_id") != tech_id:
                continue
        for li in (inv.get("line_items") or []):
            item_id = li.get("item_id")
            if not item_id or item_id not in pb_map:
                continue
            chem = pb_map[item_id]
            qty = float(li.get("quantity") or 0)
            # Wholesale cost captured at write time per Bug 1 ship.
            wc = float(li.get("wholesale_cost_snapshot")
                        or li.get("wholesale_cost")
                        or 0)
            line_cost = round(qty * wc, 4)
            bucket = per_chem.setdefault(item_id, {
                "chemical_id": item_id,
                "chemical_name": chem.get("name") or item_id,
                "unit": chem.get("unit"),
                "qty_used": 0.0,
                "total_cost": 0.0,
                "job_ids": set(),
                "customers": {},
                "techs": {},
            })
            bucket["qty_used"] += qty
            bucket["total_cost"] += line_cost
            if job_id:
                bucket["job_ids"].add(job_id)
                matched_jobs.add(job_id)
            if cust_id:
                c = bucket["customers"].setdefault(cust_id, {
                    "id": cust_id, "name": cust_name, "cost": 0.0,
                })
                c["cost"] += line_cost
                matched_customers.setdefault(cust_id, c)
            total_cost += line_cost
            total_qty += qty

    # Resolve top tech per chemical — one join pass per job set.
    tech_names: Dict[str, str] = {}
    if per_chem:
        all_jobs: set = set()
        for b in per_chem.values():
            all_jobs |= b["job_ids"]
        job_to_tech: Dict[str, Optional[str]] = {}
        if all_jobs:
            async for j in db.jobs.find(
                {"tenant_id": tid, "id": {"$in": list(all_jobs)}},
                {"_id": 0, "id": 1, "technician_id": 1},
            ):
                job_to_tech[j["id"]] = j.get("technician_id")
        tech_ids_seen = {v for v in job_to_tech.values() if v}
        if tech_ids_seen:
            async for t in db.technicians.find(
                {"tenant_id": tid, "id": {"$in": list(tech_ids_seen)}},
                {"_id": 0, "id": 1, "name": 1},
            ):
                tech_names[t["id"]] = t.get("name") or t["id"]
        for b in per_chem.values():
            for jid_ in b["job_ids"]:
                tid_ = job_to_tech.get(jid_)
                if not tid_:
                    continue
                # For "top tech" we pick the tech touching the most jobs.
                b["techs"].setdefault(tid_, {"id": tid_,
                                              "name": tech_names.get(tid_, tid_),
                                              "jobs": 0})["jobs"] += 1

    # Emit the shape the frontend expects.
    by_chemical: List[Dict[str, Any]] = []
    for b in per_chem.values():
        top_cust = max(b["customers"].values(),
                        key=lambda c: c["cost"],
                        default=None)
        top_tech = max(b["techs"].values(),
                        key=lambda t: t["jobs"],
                        default=None)
        job_ct = len(b["job_ids"])
        by_chemical.append({
            "chemical_id": b["chemical_id"],
            "chemical_name": b["chemical_name"],
            "unit": b["unit"],
            "qty_used": round(b["qty_used"], 3),
            "total_cost": round(b["total_cost"], 2),
            "job_count": job_ct,
            "avg_per_job": round(b["total_cost"] / job_ct, 2) if job_ct else 0.0,
            "top_customer": (
                {"id": top_cust["id"], "name": top_cust["name"],
                  "cost": round(top_cust["cost"], 2)}
                if top_cust else None
            ),
            "top_tech": (
                {"id": top_tech["id"], "name": top_tech["name"],
                  "jobs": top_tech["jobs"]}
                if top_tech else None
            ),
        })
    by_chemical.sort(key=lambda x: x["total_cost"], reverse=True)

    return {
        "date_range": {"start": date_from, "end": date_to},
        "totals": {
            "total_wholesale_cost": round(total_cost, 2),
            "total_qty": round(total_qty, 3),
            "job_count": len(matched_jobs),
        },
        "by_chemical": by_chemical,
    }
