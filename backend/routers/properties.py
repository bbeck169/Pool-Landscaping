"""Multi-Property (MP1) — Feb-2026 ship.

New collection ``properties`` — one row per service address per customer,
capped at 8. Extends the customer schema with a ``master_billing_mode``
switch so admins can consolidate invoices across properties or route
individual invoices to a single billing contact.

Rules the caller can rely on:
  * Property CRUD is admin-only. Techs read via the schedule endpoint.
  * 8-property cap enforced on create + duplicate (400 with a clear msg).
  * Soft-delete only — sets ``active=False`` + guards on open jobs.
  * ``sort_order`` maintained automatically; ``POST /properties/reorder``
    updates it in bulk.
  * Lazy backfill: the first ``GET /customers/{cid}/properties`` call
    for a customer that has no property rows AND has an address on the
    customer doc lazily inserts a "Main" property from that address.
  * Startup migration ``migrate_customers_to_properties()`` runs the
    same lazy backfill idempotently across every tenant on boot.
  * Notification kinds ``property.created`` + ``property.deleted`` fire
    unified pings to admin (default push OFF).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter(tags=["Properties"])

MAX_PROPERTIES = 8
_ALLOWED_BILLING_MODES = {"off", "consolidated", "forward_to_master_contact"}


# ─── Models ───────────────────────────────────────────────────────────

class _AddressIn(BaseModel):
    # Feb-2026 MP1.5 tester polish (obs #2) — accept ``address_line1``
    # as an alias for ``line1`` so callers whose form model uses the
    # flat customer schema key don't silently drop the value. Same for
    # ``address_line2`` → ``line2``. The model_validator folds the
    # alias into the canonical field before serialization so downstream
    # code only has to know about ``line1`` / ``line2``.
    line1: Optional[str] = None
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "US"
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None

    @model_validator(mode="after")
    def _fold_address_aliases(self):
        if not self.line1 and self.address_line1:
            self.line1 = self.address_line1
        if not self.line2 and self.address_line2:
            self.line2 = self.address_line2
        # Drop the alias fields from the persisted representation.
        self.address_line1 = None
        self.address_line2 = None
        return self


class _SiteContactIn(BaseModel):
    name: Optional[str] = None
    mobiles: Optional[List[dict]] = None
    emails: Optional[List[dict]] = None
    is_primary_contact: Optional[bool] = False


class PropertyIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    address: _AddressIn
    pool_size_gallons: Optional[int] = None
    pool_type: Optional[str] = None
    landscape_sq_ft: Optional[int] = None
    service_types: Optional[List[str]] = None
    site_contact: Optional[_SiteContactIn] = None
    assigned_technician_id: Optional[str] = None
    assigned_route_id: Optional[str] = None
    service_notes: Optional[Dict[str, Optional[str]]] = None
    photo_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None


class PropertyPatch(BaseModel):
    label: Optional[str] = None
    address: Optional[_AddressIn] = None
    pool_size_gallons: Optional[int] = None
    pool_type: Optional[str] = None
    landscape_sq_ft: Optional[int] = None
    service_types: Optional[List[str]] = None
    site_contact: Optional[_SiteContactIn] = None
    assigned_technician_id: Optional[str] = None
    assigned_route_id: Optional[str] = None
    service_notes: Optional[Dict[str, Optional[str]]] = None
    photo_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    active: Optional[bool] = None


class MasterBillingIn(BaseModel):
    mode: str
    master_billing_contact_email: Optional[str] = None
    master_billing_contact_phone: Optional[str] = None


class ReorderIn(BaseModel):
    customer_id: str
    ordered_property_ids: List[str]


# ─── Helpers ──────────────────────────────────────────────────────────

def _strip(doc: Optional[dict]) -> Optional[dict]:
    if doc:
        doc.pop("_id", None)
    return doc


async def _next_sort_order(tenant_id: str, customer_id: str) -> int:
    docs = await db.properties.find(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "sort_order": 1},
    ).sort("sort_order", -1).to_list(1)
    if not docs:
        return 0
    return int(docs[0].get("sort_order") or 0) + 1


async def _active_count(tenant_id: str, customer_id: str) -> int:
    return await db.properties.count_documents({
        "tenant_id": tenant_id, "customer_id": customer_id,
        "active": {"$ne": False},
    })


async def _emit(kind: str, tenant_id: str, actor: dict,
                 customer_id: str, property_doc: dict) -> None:
    try:
        from services.notifications import emit as notify_emit
        # Feb-2026 tester fix — notify ALL tenant admins including the
        # actor. Previously we excluded the actor's own id, which meant
        # a single-admin tenant (or a test run where the acting admin
        # is the audience) saw no notification row at all. The actor
        # inclusion is intentional: property CRUD is a low-frequency
        # operation and admins want the audit trail in their own inbox
        # even for self-triggered actions.
        admins = await db.users.find(
            {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(50)
        aids = [a["id"] for a in admins if a.get("id")]
        if not aids:
            return
        who = actor.get("name") or actor.get("email") or "Admin"
        label = property_doc.get("label") or "property"
        verb = "added" if kind == "property.created" else "removed"
        await notify_emit(
            aids, kind=kind,
            title=f"Property {verb}: {label}",
            body=f"{who} {verb} property '{label}'",
            href=f"/customers/{customer_id}?tab=properties",
            tenant_id=tenant_id, audience="internal",
            source_ref={"kind": "property", "id": property_doc.get("id")},
            customer_id=customer_id,
        )
    except Exception as e:
        logger.warning(f"[properties] notify {kind} failed: {e}")


async def _lazy_backfill_from_customer(tenant_id: str, customer_id: str) -> Optional[dict]:
    """Called from GET /properties + the startup migration. If the
    customer has an address on their doc AND zero property rows yet,
    seed a single "Main" property."""
    existing = await db.properties.count_documents({
        "tenant_id": tenant_id, "customer_id": customer_id,
    })
    if existing:
        return None
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "address": 1, "address_line1": 1, "city": 1,
          "state": 1, "postal_code": 1, "phone": 1, "email": 1, "mobiles": 1,
          "emails": 1, "service_notes": 1},
    )
    if not cust:
        return None
    line1 = (cust.get("address_line1") or "").strip() or (cust.get("address") or "").strip()
    if not line1:
        return None
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "label": "Main",
        "address": {
            "line1": line1,
            "line2": None,
            "city": cust.get("city"),
            "state": cust.get("state"),
            "postal_code": cust.get("postal_code"),
            "country": "US",
        },
        "pool_size_gallons": None, "pool_type": None,
        "landscape_sq_ft": None,
        "service_types": [],
        "site_contact": {
            "name": None,
            "mobiles": cust.get("mobiles") or [],
            "emails": cust.get("emails") or [],
            "is_primary_contact": True,
        },
        "assigned_technician_id": None,
        "assigned_route_id": None,
        "service_notes": cust.get("service_notes") or {"pool": None, "landscape": None},
        "photo_urls": [], "video_urls": [],
        "active": True,
        "sort_order": 0,
        "backfilled_from_customer": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.properties.insert_one(doc)
    return _strip(doc)


async def migrate_customers_to_properties() -> int:
    """Idempotent startup migration. For every customer that has no
    property rows AND has address_line1/address on the doc, insert a
    single "Main" property + backfill any jobs missing property_id
    onto that new row."""
    n_props = 0
    n_jobs = 0
    async for cust in db.customers.find(
        {}, {"_id": 0, "id": 1, "tenant_id": 1, "address": 1,
              "address_line1": 1, "city": 1, "state": 1, "postal_code": 1,
              "phone": 1, "email": 1, "mobiles": 1, "emails": 1,
              "service_notes": 1},
    ):
        cid = cust.get("id")
        tid = cust.get("tenant_id")
        if not cid or not tid:
            continue
        existing = await db.properties.count_documents({
            "tenant_id": tid, "customer_id": cid,
        })
        if existing:
            # Customer already has properties — just make sure legacy
            # jobs are backfilled to the sole property if there is one.
            if existing == 1:
                prop = await db.properties.find_one(
                    {"tenant_id": tid, "customer_id": cid, "active": {"$ne": False}},
                    {"_id": 0, "id": 1},
                )
                if prop:
                    r = await db.jobs.update_many(
                        {"tenant_id": tid, "customer_id": cid,
                          "property_id": {"$in": [None, ""]}},
                        {"$set": {"property_id": prop["id"]}},
                    )
                    n_jobs += (r.modified_count or 0)
            continue
        prop = await _lazy_backfill_from_customer(tid, cid)
        if prop:
            n_props += 1
            # Backfill this customer's jobs onto the new property.
            r = await db.jobs.update_many(
                {"tenant_id": tid, "customer_id": cid,
                  "property_id": {"$in": [None, ""]}},
                {"$set": {"property_id": prop["id"]}},
            )
            n_jobs += (r.modified_count or 0)
    if n_props or n_jobs:
        logger.info(f"[properties] migration seeded {n_props} property row(s), "
                       f"backfilled {n_jobs} job(s)")
    return n_props


# ─── Endpoints ────────────────────────────────────────────────────────

@router.get("/customers/{cid}/properties")
async def list_customer_properties(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-open (admin + tech). Techs see only properties they're
    assigned to via ``assigned_technician_id``. Admin sees all.

    Lazy backfill — if the customer has no properties yet + has an
    address on the customer doc, seed a single "Main" property so the
    UI never renders an empty state on legacy customers.
    """
    role = user.get("role")
    q: dict = {"tenant_id": tenant["id"], "customer_id": cid}
    if role not in ("admin", "super_admin"):
        q["assigned_technician_id"] = user["id"]
    docs = await db.properties.find(q, {"_id": 0}).sort("sort_order", 1).to_list(50)
    if not docs and role in ("admin", "super_admin"):
        seeded = await _lazy_backfill_from_customer(tenant["id"], cid)
        if seeded:
            docs = [seeded]
    return docs


@router.post("/customers/{cid}/properties", status_code=201)
async def create_property(cid: str, body: PropertyIn,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    n = await _active_count(tenant["id"], cid)
    if n >= MAX_PROPERTIES:
        raise HTTPException(400, (
            f"cannot exceed {MAX_PROPERTIES} active properties per "
            f"customer (currently {n})"
        ))
    order = await _next_sort_order(tenant["id"], cid)
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "sort_order": order,
        "active": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        **body.dict(exclude_unset=False),
    }
    # Normalize nested dicts.
    if isinstance(doc.get("address"), _AddressIn):
        doc["address"] = doc["address"].dict()
    # Strip transient alias fields (see _AddressIn model_validator).
    addr = doc.get("address")
    if isinstance(addr, dict):
        addr.pop("address_line1", None)
        addr.pop("address_line2", None)
    await db.properties.insert_one(doc)
    _strip(doc)
    await _emit("property.created", tenant["id"], user, cid, doc)
    return doc


@router.get("/properties/{pid}")
async def get_property(pid: str,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    doc = await db.properties.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Property not found")
    if user.get("role") not in ("admin", "super_admin"):
        if doc.get("assigned_technician_id") != user["id"]:
            raise HTTPException(403, "Not allowed")
    return doc


@router.patch("/properties/{pid}")
async def patch_property(pid: str, body: PropertyPatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    # Strip transient address alias fields (see _AddressIn model_validator).
    addr = updates.get("address")
    if isinstance(addr, dict):
        addr.pop("address_line1", None)
        addr.pop("address_line2", None)
    if not updates:
        return await db.properties.find_one(
            {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
    updates["updated_at"] = now_iso()
    r = await db.properties.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Property not found")
    return await db.properties.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


@router.delete("/properties/{pid}", status_code=200)
async def delete_property(pid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Soft-delete only. Refuses when the property has open jobs so we
    never orphan work in progress."""
    prop = await db.properties.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not prop:
        raise HTTPException(404, "Property not found")
    open_jobs = await db.jobs.count_documents({
        "tenant_id": tenant["id"], "property_id": pid,
        # Feb-2026 tester fix — ``JobIn.status`` defaults to ``"pending"``,
        # not ``"scheduled"``. The old guard missed newly created jobs
        # because it only listed the mid-lifecycle statuses. Include
        # every not-yet-terminal state so the guard actually blocks.
        "status": {"$in": [
            "pending", "created", "scheduled", "assigned",
            "in_progress", "on_the_way", "en_route",
        ]},
    })
    if open_jobs > 0:
        raise HTTPException(400, (
            f"cannot delete — {open_jobs} open job(s) still reference "
            f"this property"
        ))
    await db.properties.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"active": False, "updated_at": now_iso()}},
    )
    await _emit("property.deleted", tenant["id"], user,
                  prop.get("customer_id") or "", prop)
    return {"ok": True, "id": pid, "active": False}


@router.post("/properties/{pid}/duplicate", status_code=201)
async def duplicate_property(pid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    src = await db.properties.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not src:
        raise HTTPException(404, "Property not found")
    cid = src.get("customer_id")
    n = await _active_count(tenant["id"], cid)
    if n >= MAX_PROPERTIES:
        raise HTTPException(400, (
            f"cannot exceed {MAX_PROPERTIES} active properties per customer"
        ))
    order = await _next_sort_order(tenant["id"], cid)
    dup = dict(src)
    dup["id"] = new_id()
    dup["label"] = f"{src.get('label') or 'Property'} (copy)"
    dup["sort_order"] = order
    dup["active"] = True
    dup["created_at"] = now_iso()
    dup["updated_at"] = now_iso()
    dup.pop("backfilled_from_customer", None)
    await db.properties.insert_one(dup)
    _strip(dup)
    await _emit("property.created", tenant["id"], user, cid, dup)
    return dup


@router.post("/properties/reorder")
async def reorder_properties(body: ReorderIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    for i, pid in enumerate(body.ordered_property_ids):
        await db.properties.update_one(
            {"id": pid, "tenant_id": tenant["id"],
              "customer_id": body.customer_id},
            {"$set": {"sort_order": i, "updated_at": now_iso()}},
        )
    return {"ok": True, "count": len(body.ordered_property_ids)}


@router.get("/properties/{pid}/schedule")
async def property_schedule(pid: str,
                              limit: int = Query(50, ge=1, le=200),
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    prop = await db.properties.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1,
                                                       "assigned_technician_id": 1},
    )
    if not prop:
        raise HTTPException(404, "Property not found")
    if user.get("role") not in ("admin", "super_admin"):
        if prop.get("assigned_technician_id") != user["id"]:
            raise HTTPException(403, "Not allowed")
    jobs = await db.jobs.find(
        {"tenant_id": tenant["id"], "property_id": pid},
        {"_id": 0},
    ).sort("scheduled_date", -1).to_list(limit)
    return {"property_id": pid, "count": len(jobs), "jobs": jobs}


@router.patch("/customers/{cid}/master-billing")
async def patch_master_billing(cid: str, body: MasterBillingIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    if body.mode not in _ALLOWED_BILLING_MODES:
        raise HTTPException(400, (
            f"mode must be one of {sorted(_ALLOWED_BILLING_MODES)}"
        ))
    r = await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {
            "master_billing_mode": body.mode,
            "master_billing_contact_email": body.master_billing_contact_email,
            "master_billing_contact_phone": body.master_billing_contact_phone,
            "updated_at": now_iso(),
        }},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    return await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "master_billing_mode": 1,
          "master_billing_contact_email": 1, "master_billing_contact_phone": 1},
    )


def resolve_invoice_recipient(customer: dict, property_doc: Optional[dict]) -> Dict[str, Optional[str]]:
    """Billing routing per Feb-2026 MP1.5 spec:

      * ``off`` (default) — deliver to the property's on-site contact
        primary email/phone. Fallback chain: property.site_contact
        primary → customer's primary email/phone (from ``emails`` /
        ``mobiles`` arrays with the legacy scalar as final fallback).
        If nothing resolves, returns ``send_status_hint=
        "not_sent_missing_recipient"`` so the caller can log + skip.
      * ``consolidated`` — one invoice per customer, aggregated across
        all properties. Delivered to
        ``customer.master_billing_contact_email`` (override) →
        ``primary_email(customer)`` → ``customer.email`` (legacy).
      * ``forward_to_master_contact`` — per-property invoices, but the
        delivery target is the customer's master billing contact
        (same fallback chain as consolidated).

    Returns::

        {
          "email":  Optional[str],
          "phone":  Optional[str],
          "delivery_kind": "per_property" | "consolidated" | "forwarded",
          "send_status_hint": "ready" | "not_sent_missing_recipient",
          "mode": <the resolved mode string>,
        }
    """
    # Local import to avoid a circular boot cycle with customers router.
    try:
        from services.customer_multi_contact import (
            primary_email as _prim_email, primary_mobile as _prim_mobile,
        )
    except Exception:
        def _prim_email(_d):
            return None
        def _prim_mobile(_d):
            return None

    cust = customer or {}
    prop = property_doc or {}
    mode = cust.get("master_billing_mode") or "off"

    cust_primary_email = _prim_email(cust) or cust.get("email") or None
    cust_primary_phone = _prim_mobile(cust) or cust.get("phone") or None

    def _wrap(email: Optional[str], phone: Optional[str], kind: str) -> Dict[str, Optional[str]]:
        return {
            "email": (email or None) or None,
            "phone": (phone or None) or None,
            "delivery_kind": kind,
            "mode": mode,
            "send_status_hint": (
                "ready" if (email or phone) else "not_sent_missing_recipient"
            ),
        }

    if mode == "consolidated":
        email = cust.get("master_billing_contact_email") or cust_primary_email
        phone = cust.get("master_billing_contact_phone") or cust_primary_phone
        return _wrap(email, phone, "consolidated")

    if mode == "forward_to_master_contact":
        email = cust.get("master_billing_contact_email") or cust_primary_email
        phone = cust.get("master_billing_contact_phone") or cust_primary_phone
        return _wrap(email, phone, "forwarded")

    # off — property site contact primary → customer primary fallback.
    site = (prop.get("site_contact") or {})
    site_email = None
    site_phone = None
    for e in (site.get("emails") or []):
        if e.get("is_primary") and e.get("address"):
            site_email = e["address"]
            break
    for m in (site.get("mobiles") or []):
        if m.get("is_primary") and m.get("number_e164"):
            site_phone = m["number_e164"]
            break
    email = site_email or cust_primary_email
    phone = site_phone or cust_primary_phone
    return _wrap(email, phone, "per_property")
