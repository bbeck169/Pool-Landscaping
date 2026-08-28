"""Feb-2026 · Chemical Cost Report — ``/api/reports/chemical-costs``.

**Rewrite (Option 2, Multi-body Phase 1)**

Aggregates from ``chemical_usage_events`` (the write-time canonical
snapshot of "what the tech used, at that time, at that cost") instead
of invoice line items. Reasons:

* The event row already carries per-chemical qty + ``unit_cost_at_time_cents``
  + ``occurred_at``, so we get the same cost accuracy without depending
  on the invoice-line-item shape being consistent across the two auto-
  invoice paths (submit-time vs. job-complete-time).
* Under multi-body reports the event now carries
  ``water_body_id / water_body_type / water_body_label`` so we can
  split rollups per body without a schema shift on invoices.
* Fixes the ``wholesale_cost_snapshot`` typo transparently: the report
  no longer reads from invoice snapshots at all. The legacy field is
  ignored except in the legacy-tolerance test that asserts an event
  written pre-rework still counts.

Payment gate: the "only paid work counts" contract is preserved by
joining to ``db.quotes`` (the invoice collection) on ``job_id`` and
requiring ``payment_status: "paid"``.

RBAC: super_admin, admin, manager only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    """Coerce ``YYYY-MM-DD`` → ``YYYY-MM-DDT23:59:59+00:00`` so range
    filters don't accidentally exclude same-day events."""
    if len(iso_date) == 10:
        return f"{iso_date}T23:59:59+00:00"
    return iso_date


async def _resolve_filter_to_slugs(
    tid: str, chemical_ids: Optional[str],
) -> Tuple[Optional[List[str]], Dict[str, Dict[str, Any]]]:
    """Turn the FE's ``chemical_ids=`` filter (comma-separated
    pricebook item ids **or** ``chemical_costs.chemical_slug`` values)
    into a canonical list of product slugs. Returns::

        (slugs_or_None, catalog_by_slug)

    ``slugs_or_None`` is ``None`` when the caller didn't restrict —
    which means "aggregate every chemical". ``catalog_by_slug`` is a
    lookup of ``chemical_costs`` docs keyed by slug so ``by_chemical``
    can emit human names + units.
    """
    catalog: Dict[str, Dict[str, Any]] = {}
    async for row in db.chemical_costs.find(
        {"tenant_id": tid},
        {"_id": 0, "chemical_slug": 1, "name": 1, "unit_kind": 1,
          "cost_per_unit_cents": 1},
    ):
        slug = str(row.get("chemical_slug") or "").lower()
        if slug:
            catalog[slug] = row

    if not chemical_ids:
        return None, catalog

    tokens = [x.strip() for x in chemical_ids.split(",") if x.strip()]
    if not tokens:
        return None, catalog

    # First, treat tokens as chemical_slugs.
    slugs = {t.lower() for t in tokens if t.lower() in catalog}

    # Any remaining tokens — try treating them as pricebook item ids
    # (the pre-rewrite behavior). Resolve via items.name → chemical_costs.name.
    unresolved = [t for t in tokens if t.lower() not in slugs]
    if unresolved:
        rows = await db.items.find(
            {"tenant_id": tid, "id": {"$in": unresolved}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(unresolved) + 5)
        names_by_id = {r["id"]: (r.get("name") or "").lower() for r in rows}
        name_to_slug = {
            (v.get("name") or "").lower(): k
            for k, v in catalog.items()
            if v.get("name")
        }
        for tok in unresolved:
            nm = names_by_id.get(tok)
            if nm and nm in name_to_slug:
                slugs.add(name_to_slug[nm])
    return sorted(slugs), catalog


@router.get("/reports/chemical-costs")
async def chemical_cost_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    tech_id: Optional[str] = Query(None),
    chemical_ids: Optional[str] = Query(
        None, description="Comma-separated pricebook item ids OR "
                            "chemical_costs.chemical_slug values."),
    include_unpaid: bool = Query(
        False, description="When true, includes chemical usage events "
                            "from unpaid invoices AND events where the "
                            "parent job has no invoice. Default is the "
                            "'paid work only' contract."),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require(user)
    tid = tenant["id"]

    # Step 1 — resolve the filter to canonical product_slugs.
    slug_filter, catalog = await _resolve_filter_to_slugs(tid, chemical_ids)

    if chemical_ids and not slug_filter:
        # Caller restricted to specific ids that resolved to nothing.
        return {
            "date_range": {"start": date_from, "end": date_to},
            "totals": {"total_wholesale_cost": 0.0, "total_qty": 0,
                        "job_count": 0},
            "by_chemical": [],
            "by_water_body": [],
        }

    # Step 2 — pull chemical_usage_events in the date window.
    event_filter: Dict[str, Any] = {"tenant_id": tid}
    date_gate: Dict[str, Any] = {}
    if date_from:
        date_gate["$gte"] = date_from
    if date_to:
        date_gate["$lte"] = _to_dt_end(date_to)
    if date_gate:
        event_filter["occurred_at"] = date_gate
    if customer_id:
        event_filter["customer_id"] = customer_id
    if slug_filter:
        event_filter["product_slug"] = {"$in": slug_filter}

    events = await db.chemical_usage_events.find(
        event_filter,
        {"_id": 0, "id": 1, "job_id": 1, "customer_id": 1,
          "product_slug": 1, "name": 1, "unit": 1,
          "quantity_used": 1, "unit_cost_at_time_cents": 1,
          "total_cost_cents": 1, "occurred_at": 1,
          "water_body_id": 1, "water_body_type": 1,
          "water_body_label": 1},
    ).to_list(50000)

    if not events:
        return {
            "date_range": {"start": date_from, "end": date_to},
            "totals": {"total_wholesale_cost": 0.0, "total_qty": 0,
                        "job_count": 0},
            "by_chemical": [],
            "by_water_body": [],
        }

    # Step 3 — gate on "paid" by joining to db.quotes on job_id.
    # ``include_unpaid`` bypasses the gate for admins doing a raw usage
    # audit; default keeps the pre-rework contract.
    job_ids = list({e.get("job_id") for e in events if e.get("job_id")})
    paid_jobs: set = set()
    if job_ids and not include_unpaid:
        cursor = db.quotes.find(
            {"tenant_id": tid,
              "doc_type": "invoice",
              "job_id": {"$in": job_ids},
              "payment_status": "paid"},
            {"_id": 0, "job_id": 1},
        )
        async for inv in cursor:
            paid_jobs.add(inv["job_id"])
        events = [e for e in events if e.get("job_id") in paid_jobs]

    # Step 4 — optional tech filter via jobs.technician_id.
    if tech_id:
        job_ids_now = list({e.get("job_id") for e in events if e.get("job_id")})
        allowed_jobs: set = set()
        if job_ids_now:
            async for j in db.jobs.find(
                {"tenant_id": tid, "id": {"$in": job_ids_now},
                  "technician_id": tech_id},
                {"_id": 0, "id": 1},
            ):
                allowed_jobs.add(j["id"])
        events = [e for e in events if e.get("job_id") in allowed_jobs]

    if not events:
        return {
            "date_range": {"start": date_from, "end": date_to},
            "totals": {"total_wholesale_cost": 0.0, "total_qty": 0,
                        "job_count": 0},
            "by_chemical": [],
            "by_water_body": [],
        }

    # Step 5 — per-chemical + per-body aggregation in one pass.
    per_chem: Dict[str, Dict[str, Any]] = {}
    per_body: Dict[str, Dict[str, Any]] = {}
    total_cost_cents = 0
    total_qty = 0.0
    matched_jobs: set = set()
    matched_customers: Dict[str, str] = {}

    for ev in events:
        slug = str(ev.get("product_slug") or "").lower()
        qty = float(ev.get("quantity_used") or 0)
        cents = int(ev.get("total_cost_cents") or 0)
        job_id = ev.get("job_id")
        cust_id = ev.get("customer_id")

        catalog_row = catalog.get(slug) if slug else None
        chem_name = (ev.get("name")
                       or (catalog_row or {}).get("name")
                       or slug
                       or "Unknown")
        chem_unit = (ev.get("unit")
                       or (catalog_row or {}).get("unit_kind")
                       or "")

        bucket = per_chem.setdefault(slug or ev.get("id"), {
            "chemical_id":   slug or ev.get("id"),
            "product_slug":  slug or None,
            "chemical_name": chem_name,
            "unit":          chem_unit,
            "qty_used":      0.0,
            "total_cost":    0.0,
            "job_ids":       set(),
            "customers":     {},
            "techs":         {},
        })
        bucket["qty_used"] += qty
        bucket["total_cost"] += cents / 100.0
        if job_id:
            bucket["job_ids"].add(job_id)
            matched_jobs.add(job_id)
        if cust_id:
            c = bucket["customers"].setdefault(cust_id, {
                "id": cust_id, "name": None, "cost": 0.0,
            })
            c["cost"] += cents / 100.0
            matched_customers.setdefault(cust_id, cust_id)

        # Per-body bucket. Events with ``water_body_id=None`` collapse
        # into a single synthetic ``legacy`` bucket per the brief.
        wb_id = ev.get("water_body_id")
        wb_type = (ev.get("water_body_type") or "").lower() or None
        wb_label = ev.get("water_body_label")
        if wb_id:
            body_key = wb_id
            body_type_out = wb_type or "other"
            body_label_out = wb_label or wb_type or "Body"
        else:
            body_key = "__legacy__"
            body_type_out = "legacy"
            body_label_out = "Legacy (pre-multi-body)"
        bkt = per_body.setdefault(body_key, {
            "water_body_id":        None if body_key == "__legacy__" else wb_id,
            "body_type":            body_type_out,
            "body_label":           body_label_out,
            "total_qty":            0.0,
            "total_wholesale_cost": 0.0,
            "chemical_count":       0,
            "job_ids":              set(),
        })
        bkt["total_qty"] += qty
        bkt["total_wholesale_cost"] += cents / 100.0
        bkt["chemical_count"] += 1
        if job_id:
            bkt["job_ids"].add(job_id)

        total_cost_cents += cents
        total_qty += qty

    # Step 6 — resolve customer + tech display names in a single pass.
    if matched_customers:
        async for c in db.customers.find(
            {"tenant_id": tid, "id": {"$in": list(matched_customers.keys())}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            for b in per_chem.values():
                if c["id"] in b["customers"]:
                    b["customers"][c["id"]]["name"] = c.get("name") or c["id"]

    if matched_jobs:
        job_to_tech: Dict[str, Optional[str]] = {}
        async for j in db.jobs.find(
            {"tenant_id": tid, "id": {"$in": list(matched_jobs)}},
            {"_id": 0, "id": 1, "technician_id": 1},
        ):
            job_to_tech[j["id"]] = j.get("technician_id")
        tech_ids = {v for v in job_to_tech.values() if v}
        tech_names: Dict[str, str] = {}
        if tech_ids:
            async for t in db.technicians.find(
                {"tenant_id": tid, "id": {"$in": list(tech_ids)}},
                {"_id": 0, "id": 1, "name": 1},
            ):
                tech_names[t["id"]] = t.get("name") or t["id"]
        for b in per_chem.values():
            for jid_ in b["job_ids"]:
                tid_ = job_to_tech.get(jid_)
                if not tid_:
                    continue
                b["techs"].setdefault(tid_, {
                    "id":   tid_,
                    "name": tech_names.get(tid_, tid_),
                    "jobs": 0,
                })["jobs"] += 1

    # Step 7 — emit the FE-facing shape.
    by_chemical: List[Dict[str, Any]] = []
    for b in per_chem.values():
        top_cust = max(b["customers"].values(),
                        key=lambda c: c["cost"], default=None)
        top_tech = max(b["techs"].values(),
                        key=lambda t: t["jobs"], default=None)
        job_ct = len(b["job_ids"])
        by_chemical.append({
            "chemical_id":  b["chemical_id"],
            "product_slug": b["product_slug"],
            "chemical_name": b["chemical_name"],
            "unit":         b["unit"],
            "qty_used":     round(b["qty_used"], 3),
            "total_cost":   round(b["total_cost"], 2),
            "job_count":    job_ct,
            "avg_per_job":  round(b["total_cost"] / job_ct, 2) if job_ct else 0.0,
            "top_customer": (
                {"id":   top_cust["id"],
                 "name": top_cust["name"] or top_cust["id"],
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

    by_water_body: List[Dict[str, Any]] = []
    for b in per_body.values():
        by_water_body.append({
            "water_body_id":        b["water_body_id"],
            "body_type":            b["body_type"],
            "body_label":           b["body_label"],
            "total_qty":            round(b["total_qty"], 3),
            "total_wholesale_cost": round(b["total_wholesale_cost"], 2),
            "chemical_count":       b["chemical_count"],
            "job_count":            len(b["job_ids"]),
        })
    # Deterministic order: legacy bucket last, then by cost desc.
    by_water_body.sort(
        key=lambda x: (x["body_type"] == "legacy", -x["total_wholesale_cost"]),
    )

    return {
        "date_range": {"start": date_from, "end": date_to},
        "totals": {
            "total_wholesale_cost": round(total_cost_cents / 100.0, 2),
            "total_qty":            round(total_qty, 3),
            "job_count":            len(matched_jobs),
        },
        "by_chemical":   by_chemical,
        "by_water_body": by_water_body,
    }
