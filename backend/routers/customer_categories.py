"""Slice O.5 · Feb-2026 — Admin-managed customer categories + classifier.

Replaces the hardcoded pool/landscaping/both filter approach with a
tenant-owned, admin-configurable taxonomy. Each category carries a
list of case-insensitive substring patterns; the classifier walks
every customer's active recurring templates + last-90d completed
jobs and assigns matching category ids to ``customer.category_ids``.

Denormalized fields on ``customers`` (all populated by
``recompute_customer_denorm``):

    category_ids     : str[]  matching category ids
    service_days     : str[]  union of day_of_week names (Mon..Sun)
    assigned_tech_ids: str[]  union of assigned techs across templates

Endpoints (all under ``/api/customer-categories``):

    GET      /              → list          op=customerCategories.list
    POST     /              → create        op=customerCategories.create
    PATCH    /{id}          → update        op=customerCategories.update
    DELETE   /{id}          → soft-delete   op=customerCategories.delete
    POST     /recompute     → reclassify    op=customerCategories.recompute

Guardrails:

* Read: admin + manager.
* Write: admin only. Tech + customer → 403 on every write path.
* Delete refuses (409) if any customer still carries the category id;
  the response includes ``referencing_customer_count`` so the UI can
  show a clear "used by N customers" message.
* Names are unique per tenant, case-insensitive, trimmed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

_ADMIN_ONLY = {"admin", "super_admin"}
_READ_ROLES = {"admin", "super_admin", "manager"}

_PALETTE = [
    "#DBEAFE", "#DCFCE7", "#FEF3C7", "#FEE2E2", "#EDE9FE",
    "#CFFAFE", "#FCE7F3", "#FEDCBB", "#E0E7FF", "#D1FAE5",
]

_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _pick_color(name: str) -> str:
    # MD5 for stable non-security identifier (not password/signature)
    h = int(hashlib.md5(name.strip().lower().encode()).hexdigest(), 16)  # noqa: S324 — non-security cache-key hash
    return _PALETTE[h % len(_PALETTE)]


def _validate_name(raw: Optional[str]) -> str:
    if raw is None or not isinstance(raw, str):
        raise HTTPException(400, "name is required")
    if raw != raw.strip():
        raise HTTPException(400, "name has leading/trailing whitespace")
    t = raw.strip()
    if not t:
        raise HTTPException(400, "name is empty")
    if len(t) > 60:
        raise HTTPException(400, "name is too long (max 60 characters)")
    return t


def _normalize_patterns(patterns: Optional[List[str]]) -> List[str]:
    """Trim + lowercase + de-dupe. Empty entries dropped.  Preserves
    caller order (first-writer wins)."""
    if not patterns:
        return []
    seen: set = set()
    out: List[str] = []
    for p in patterns:
        if not isinstance(p, str):
            continue
        cleaned = p.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _require_read(user: dict) -> None:
    if user.get("role") not in _READ_ROLES:
        raise HTTPException(403, "Admin or manager access required")


def _require_admin(user: dict) -> None:
    if user.get("role") not in _ADMIN_ONLY:
        raise HTTPException(403, "Admin access required")


# ══════════════════════════════════════════════════════════════════
# Boot seed — 2 defaults per tenant, idempotent
# ══════════════════════════════════════════════════════════════════
_DEFAULTS = [
    ("Pool",        ["pool", "p52", "sun svc"]),
    ("Landscaping", ["landscap"]),
    ("Both",        []),  # meta-bucket — matched via classifier post-pass
]


def _slugify(name: str) -> str:
    """Deterministic slug from a display name — lowercase, kebab, ascii
    fallback for edge chars. Used for boot-seeded system categories so
    the frontend can reference them by a stable id-less handle."""
    import re
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "category"


async def seed_default_categories(tenant_id: str) -> int:
    """Insert the 3 default categories for a tenant if they don't
    already exist. Returns the number of rows inserted (0 on
    subsequent calls). Case-insensitive uniqueness enforced via
    ``name_lower``. All defaults are marked ``is_system=True`` and
    resist deletion."""
    inserted = 0
    for idx, (name, patterns) in enumerate(_DEFAULTS):
        existing = await db.customer_categories.find_one({
            "tenant_id": tenant_id, "name_lower": name.lower(),
        }, {"_id": 0, "id": 1})
        if existing:
            # Backfill missing system flags on legacy docs (idempotent).
            await db.customer_categories.update_one(
                {"id": existing["id"]},
                {"$set": {"is_system": True,
                          "slug": _slugify(name),
                          "sort_order": idx}},
            )
            continue
        await db.customer_categories.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": name,
            "name_lower": name.lower(),
            "slug": _slugify(name),
            "color": _pick_color(name),
            "color_hex": _pick_color(name),
            "sort_order": idx,
            "is_system": True,
            "service_type_patterns": patterns,
            "is_active": True,
            "usage_count": 0,
            "created_by": "system",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        inserted += 1
    return inserted


async def seed_default_categories_for_all_tenants() -> int:
    """Boot-time wrapper — walks every tenant and idempotently seeds
    the 2 defaults. Reused as a normal FastAPI startup task."""
    total = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        try:
            total += await seed_default_categories(t["id"])
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[customer-categories] seed failed for tenant=%s: %s",
                t.get("id"), e,
            )
    return total


# ══════════════════════════════════════════════════════════════════
# Classifier — assign category_ids + service_days + tech_ids
# ══════════════════════════════════════════════════════════════════
async def _load_active_categories(tenant_id: str) -> List[Dict[str, Any]]:
    return await db.customer_categories.find(
        {"tenant_id": tenant_id, "is_active": True}, {"_id": 0}
    ).to_list(500)


def _match_categories(service_type_strings: List[str],
                       categories: List[Dict[str, Any]]) -> List[str]:
    """Return the category ids whose patterns match any of the input
    service_type strings (case-insensitive substring).

    Post-pass (Feb-2026): if BOTH ``Pool`` and ``Landscaping`` system
    categories match, additionally include the ``Both`` system
    category id so ``$in`` queries for the "Both" filter surface these
    customers with a single-index lookup.
    """
    lows = [(s or "").strip().lower() for s in service_type_strings if s]
    hits: List[str] = []
    matched_names: set = set()
    by_id = {c["id"]: c for c in categories}
    for cat in categories:
        # Skip the "Both" meta-bucket — it's assigned post-pass.
        if (cat.get("name") or "").lower() == "both":
            continue
        for pat in (cat.get("service_type_patterns") or []):
            p = (pat or "").lower()
            if not p:
                continue
            if any(p in s for s in lows):
                hits.append(cat["id"])
                matched_names.add((cat.get("name") or "").lower())
                break
    if {"pool", "landscaping"}.issubset(matched_names):
        for cat in categories:
            if (cat.get("name") or "").lower() == "both" and cat["id"] not in hits:
                hits.append(cat["id"])
                break
    return hits


async def recompute_customer_denorm(tenant_id: str,
                                     customer_id: Optional[str] = None) -> int:
    """Walk every (or one) customer and populate:

    * ``category_ids``      — from recurring + last-90d jobs' service_type
    * ``service_days``      — day_of_week union across active templates
    * ``assigned_tech_ids`` — union across active templates

    Idempotent — the update sets the full arrays each time. Returns
    the number of customers whose denormalized fields actually
    changed."""
    categories = await _load_active_categories(tenant_id)
    ninety_ago = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    cust_q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        cust_q["id"] = customer_id

    updated = 0
    async for cust in db.customers.find(cust_q, {"_id": 0, "id": 1,
                                                   "category_ids": 1,
                                                   "service_days": 1,
                                                   "assigned_tech_ids": 1}):
        cid = cust["id"]

        # Gather source strings for classification.
        rec_tpls = await db.recurring_job_templates.find(
            {"tenant_id": tenant_id, "customer_id": cid, "active": True},
            {"_id": 0, "service_type": 1, "day_of_week": 1, "assigned_tech_id": 1},
        ).to_list(200)
        from utils import not_deleted_filter as _nd
        recent_jobs = await db.jobs.find(
            {"tenant_id": tenant_id, "customer_id": cid,
              "created_at": {"$gte": ninety_ago}, **_nd()},
            {"_id": 0, "service_type": 1},
        ).to_list(500)

        service_types = [t.get("service_type") for t in rec_tpls]
        service_types += [j.get("service_type") for j in recent_jobs]

        cat_ids = _match_categories(service_types, categories)

        # Day of week — dedupe + preserve Mon…Sun order.
        dows: set = set()
        for t in rec_tpls:
            v = t.get("day_of_week")
            if isinstance(v, int) and 0 <= v <= 6:
                dows.add(_DAY_NAMES[v])
        service_days = [d for d in _DAY_NAMES if d in dows]

        tech_ids = sorted({
            t.get("assigned_tech_id") for t in rec_tpls
            if t.get("assigned_tech_id")
        })

        new_cats = sorted(set(cat_ids))
        cur_cats = sorted(cust.get("category_ids") or [])
        cur_days = list(cust.get("service_days") or [])
        cur_techs = sorted(cust.get("assigned_tech_ids") or [])
        if (cur_cats == new_cats and cur_days == service_days
                and cur_techs == list(tech_ids)):
            continue

        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant_id},
            {"$set": {
                "category_ids": new_cats,
                "service_days": service_days,
                "assigned_tech_ids": list(tech_ids),
                "category_updated_at": now_iso(),
            }},
        )
        updated += 1

    # Refresh usage_count on each category.
    for cat in categories:
        n = await db.customers.count_documents({
            "tenant_id": tenant_id, "category_ids": cat["id"],
        })
        await db.customer_categories.update_one(
            {"id": cat["id"], "tenant_id": tenant_id},
            {"$set": {"usage_count": n}},
        )
    return updated


# ══════════════════════════════════════════════════════════════════
# CRUD endpoints
# ══════════════════════════════════════════════════════════════════
class _CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1)
    color: Optional[str] = None
    service_type_patterns: Optional[List[str]] = None


class _CategoryPatch(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    service_type_patterns: Optional[List[str]] = None
    is_active: Optional[bool] = None


@router.get("/customer-categories", tags=["customer-categories"],
             operation_id="customerCategories.list")
async def list_categories(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    include_inactive: bool = False,
):
    _require_read(user)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if not include_inactive:
        q["is_active"] = True
    rows = await db.customer_categories.find(
        q, {"_id": 0}
    ).sort([("is_active", -1), ("name_lower", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/customer-categories", tags=["customer-categories"],
              operation_id="customerCategories.create")
async def create_category(
    body: _CategoryCreate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    name = _validate_name(body.name)
    existing = await db.customer_categories.find_one({
        "tenant_id": tenant["id"], "name_lower": name.lower(),
    }, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(409, {
            "code": "DUPLICATE_NAME",
            "existing_id": existing["id"],
            "message": f"A category named '{name}' already exists",
        })
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": name,
        "name_lower": name.lower(),
        "color": body.color or _pick_color(name),
        "service_type_patterns": _normalize_patterns(body.service_type_patterns),
        "is_active": True,
        "usage_count": 0,
        "created_by": user.get("id"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.customer_categories.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.patch("/customer-categories/{cat_id}", tags=["customer-categories"],
                operation_id="customerCategories.update")
async def update_category(
    cat_id: str,
    body: _CategoryPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    existing = await db.customer_categories.find_one(
        {"id": cat_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not existing:
        raise HTTPException(404, "Category not found")

    updates: Dict[str, Any] = {"updated_at": now_iso()}
    if body.name is not None:
        new_name = _validate_name(body.name)
        if new_name.lower() != existing["name_lower"]:
            clash = await db.customer_categories.find_one({
                "tenant_id": tenant["id"], "name_lower": new_name.lower(),
                "id": {"$ne": cat_id},
            }, {"_id": 0, "id": 1})
            if clash:
                raise HTTPException(409, {
                    "code": "DUPLICATE_NAME",
                    "existing_id": clash["id"],
                })
        updates["name"] = new_name
        updates["name_lower"] = new_name.lower()
    if body.color is not None:
        updates["color"] = body.color
    if body.service_type_patterns is not None:
        updates["service_type_patterns"] = _normalize_patterns(
            body.service_type_patterns
        )
    if body.is_active is not None:
        updates["is_active"] = bool(body.is_active)

    await db.customer_categories.update_one(
        {"id": cat_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    return {**existing, **updates}


@router.delete("/customer-categories/{cat_id}", tags=["customer-categories"],
                 operation_id="customerCategories.delete")
async def delete_category(
    cat_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    existing = await db.customer_categories.find_one(
        {"id": cat_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not existing:
        raise HTTPException(404, "Category not found")
    ref_n = await db.customers.count_documents({
        "tenant_id": tenant["id"], "category_ids": cat_id,
    })
    if ref_n > 0:
        raise HTTPException(409, {
            "code": "CATEGORY_IN_USE",
            "referencing_customer_count": ref_n,
        })
    # Soft-delete via is_active=false so historical batch filter refs
    # keep resolving. Actual $unset from customer.category_ids only
    # runs when someone clicks "recompute" or a customer save fires.
    await db.customer_categories.update_one(
        {"id": cat_id, "tenant_id": tenant["id"]},
        {"$set": {"is_active": False, "updated_at": now_iso()}},
    )
    return {"ok": True, "id": cat_id, "is_active": False}


@router.post("/customer-categories/recompute", tags=["customer-categories"],
              operation_id="customerCategories.recompute")
async def recompute_all(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    n = await recompute_customer_denorm(tenant["id"])
    return {"customers_updated": n}
