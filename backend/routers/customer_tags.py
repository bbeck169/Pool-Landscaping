"""Phase 15b · Feb-2026 — Tenant-scoped customer tag registry.

Complements the existing free-form ``customers.tags: str[]`` field
with a dedicated ``customer_tags`` collection so the picker on the
customer detail page can:

* Suggest previously-used labels.
* Show usage counts.
* Auto-assign a color chip from a rotating palette.

Registry rules:

* **Idempotent create** — inserting a duplicate name (case-insensitive,
  trimmed) returns the existing row and increments its `usage_count`.
* **Validation** — 1-40 chars, no leading/trailing whitespace,
  no leading whitespace on save. Whitespace-only is rejected.
* **RBAC** — admin + manager read/write. Everything else 403.
* **Auto-create on PATCH** — ``PATCH /api/customers/{cid}/tags``
  walks the incoming list; any name not yet in the registry is
  inserted through the same idempotent path.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

# Rotating color palette used when the caller doesn't specify one.
# Colors chosen from an accessibility-tested set of pastels; enough
# variation that adjacent tags don't visually collide.
_PALETTE = [
    "#DBEAFE", "#FEE2E2", "#DCFCE7", "#FEF3C7", "#EDE9FE",
    "#CFFAFE", "#FCE7F3", "#FEDCBB", "#E0E7FF", "#D1FAE5",
]


def _require_admin_or_manager(user: dict) -> dict:
    if user.get("role") not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Admin or manager access required")
    return user


def _pick_color(name: str) -> str:
    """Deterministic palette pick — same name → same color across
    reloads. Uses a stable SHA-256 hash mod palette length."""
    # SHA-256 for stable non-security identifier (not password/signature)
    h = int(hashlib.sha256(name.strip().lower().encode()).hexdigest(), 16)  # non-security: stable name→color slot
    return _PALETTE[h % len(_PALETTE)]


def _validate_name(raw: Optional[str]) -> str:
    """Trim + validate. Raises 400 on any rule violation.
    Returns the trimmed name."""
    if raw is None:
        raise HTTPException(400, "name is required")
    if not isinstance(raw, str):
        raise HTTPException(400, "name must be a string")
    if raw != raw.strip():
        # Reject leading/trailing whitespace outright — matches the
        # user's spec verbatim ("no leading/trailing whitespace").
        raise HTTPException(400, "name has leading/trailing whitespace")
    trimmed = raw.strip()
    if not trimmed:
        raise HTTPException(400, "name is empty")
    if len(trimmed) > 40:
        raise HTTPException(400, "name is too long (max 40 characters)")
    return trimmed


async def _upsert_tag(tenant_id: str, name: str, color: Optional[str],
                       created_by: str) -> dict:
    """Idempotent single-tag upsert. Case-insensitive uniqueness on
    ``name_lower``. Returns the persisted doc (existing or new)."""
    trimmed = _validate_name(name)
    name_lower = trimmed.lower()
    existing = await db.customer_tags.find_one(
        {"tenant_id": tenant_id, "name_lower": name_lower}, {"_id": 0},
    )
    if existing:
        return existing
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "name": trimmed,
        "name_lower": name_lower,
        "color": color or _pick_color(trimmed),
        "created_by": created_by,
        "created_at": now_iso(),
        "usage_count": 0,
    }
    await db.customer_tags.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _recompute_usage(tenant_id: str, name: str) -> None:
    """Recount how many customers currently carry this tag; write it
    back to the registry. Cheap enough on a per-write basis and avoids
    drift when tags are removed from customers directly."""
    n = await db.customers.count_documents({
        "tenant_id": tenant_id,
        "tags": name,
    })
    await db.customer_tags.update_one(
        {"tenant_id": tenant_id, "name": name},
        {"$set": {"usage_count": n}},
    )


# ═════════════════════════════════════════════════════════════════
# Feb-2026 · System tag scaffolding
# ═════════════════════════════════════════════════════════════════
# Two tenant-scoped system tags — Active / Inactive — auto-applied to
# customers based on ``status``. Editable / deletable via UI is
# blocked at the router; the seed itself is idempotent (safe to run
# from a startup pipe or a migration script).
SYSTEM_TAG_ACTIVE = "Active"
SYSTEM_TAG_INACTIVE = "Inactive"
_SYSTEM_TAG_COLORS = {
    SYSTEM_TAG_ACTIVE: "#22c55e",   # green
    SYSTEM_TAG_INACTIVE: "#94a3b8",  # slate
}
_SYSTEM_TAG_NAMES_LOWER = {n.lower() for n in _SYSTEM_TAG_COLORS.keys()}


async def ensure_system_tags(tenant_id: str) -> dict:
    """Idempotently seed the two system tags for a tenant. Returns
    ``{active_tag_id, inactive_tag_id, created_count}``. Cheap enough
    to call at startup and inline before any status-driven auto-tag
    sync."""
    created = 0
    ids: dict = {}
    for name, color in _SYSTEM_TAG_COLORS.items():
        existing = await db.customer_tags.find_one(
            {"tenant_id": tenant_id, "name_lower": name.lower()},
            {"_id": 0, "id": 1, "is_system": 1},
        )
        if existing:
            if not existing.get("is_system"):
                # Prior user-created tag with the same name — promote
                # to system so the UI locks it. Preserves usage.
                await db.customer_tags.update_one(
                    {"tenant_id": tenant_id, "name_lower": name.lower()},
                    {"$set": {"is_system": True, "color": color,
                                "name": name}},
                )
            ids[name] = existing["id"]
            continue
        tag_id = new_id()
        await db.customer_tags.insert_one({
            "id": tag_id, "tenant_id": tenant_id,
            "name": name, "name_lower": name.lower(),
            "color": color, "is_system": True,
            "created_by": "system", "created_at": now_iso(),
            "usage_count": 0,
        })
        ids[name] = tag_id
        created += 1
    return {"active_tag_id": ids[SYSTEM_TAG_ACTIVE],
              "inactive_tag_id": ids[SYSTEM_TAG_INACTIVE],
              "created_count": created}


async def _apply_status_tag_membership(
    tenant_id: str, customer_ids: list[str],
    target_status: str,
) -> None:
    """Ensure customers carry the Active-or-Inactive system tag that
    matches ``target_status`` and NOT the opposite. Preserves all
    other tags on the customer (Homeworks-imported, user-added, etc.)."""
    if not customer_ids:
        return
    await ensure_system_tags(tenant_id)
    if target_status == "active":
        add_tag, remove_tag = SYSTEM_TAG_ACTIVE, SYSTEM_TAG_INACTIVE
    elif target_status == "inactive":
        add_tag, remove_tag = SYSTEM_TAG_INACTIVE, SYSTEM_TAG_ACTIVE
    else:
        return  # unrecognized status → don't touch tags

    q = {"tenant_id": tenant_id, "id": {"$in": customer_ids}}
    # 1. Remove the opposite tag from every listed customer (idempotent).
    await db.customers.update_many(q,
        {"$pull": {"tags": remove_tag}})
    # 2. Add the target tag only where missing.
    await db.customers.update_many(
        {**q, "tags": {"$ne": add_tag}},
        {"$addToSet": {"tags": add_tag}},
    )
    # 3. Recompute usage counts on both system tags.
    await _recompute_usage(tenant_id, add_tag)
    await _recompute_usage(tenant_id, remove_tag)


async def apply_customer_status(*, tenant_id: str,
                                    customer_ids: list[str],
                                    target_status: str,
                                    actor_id: str | None = None) -> dict:
    """Single write path for customer status changes. Sets
    ``is_active`` + ``status`` + ``updated_at`` on every matched row
    AND ensures the corresponding Active/Inactive system tag is
    correctly attached. Returns ``{matched, modified}``.

    Retrofit target — every existing status-mutation route SHOULD
    ultimately funnel through here. The bulk-status endpoint is the
    first caller; more will follow.
    """
    if not customer_ids:
        return {"matched": 0, "modified": 0}
    now = now_iso()
    q_all = {"tenant_id": tenant_id, "id": {"$in": customer_ids}}
    matched = await db.customers.count_documents(q_all)
    q_change = {
        **q_all,
        "$or": [
            {"is_active": {"$ne": (target_status == "active")}},
            {"status": {"$ne": target_status}},
        ],
    }
    r = await db.customers.update_many(q_change, {"$set": {
        "is_active": (target_status == "active"),
        "status": target_status,
        "updated_at": now,
    }})
    await _apply_status_tag_membership(
        tenant_id, customer_ids, target_status)
    return {"matched": int(matched), "modified": int(r.modified_count)}


# ═════════════════════════════════════════════════════════════════
# GET /customer-tags — list registry
# ═════════════════════════════════════════════════════════════════
@router.get("/customer-tags", tags=["customer-tags"],
             operation_id="customerTags.list")
async def list_customer_tags(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)
    rows = await db.customer_tags.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort([("usage_count", -1), ("name_lower", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


# ═════════════════════════════════════════════════════════════════
# POST /customer-tags — idempotent create
# ═════════════════════════════════════════════════════════════════
class _TagCreate(BaseModel):
    # Length is validated by our own `_validate_name` — leaving
    # pydantic's max_length open ensures every rejection returns 400
    # (rather than pydantic's 422 for one specific case).
    name: str = Field(..., min_length=1)
    color: Optional[str] = None


@router.post("/customer-tags", tags=["customer-tags"],
              operation_id="customerTags.create")
async def create_customer_tag(
    body: _TagCreate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)
    # Feb-2026 · Reject user attempts to create tags shadowing the
    # two system tag names (case-insensitive). System tags are seeded
    # via ``ensure_system_tags`` and users must not be able to
    # sneak-create a look-alike that races the seeder.
    trimmed = _validate_name(body.name)
    if trimmed.lower() in _SYSTEM_TAG_NAMES_LOWER:
        raise HTTPException(
            409, "duplicate_tag_name: reserved system tag name")
    tag = await _upsert_tag(
        tenant["id"], trimmed, body.color, user.get("id", ""),
    )
    await _recompute_usage(tenant["id"], tag["name"])
    return tag


# ═════════════════════════════════════════════════════════════════
# PATCH /customer-tags/{tag_id} — rename / recolor
# System tags are locked (400 system_tag_readonly).
# ═════════════════════════════════════════════════════════════════
class _TagPatch(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


@router.patch("/customer-tags/{tag_id}", tags=["customer-tags"],
                operation_id="customerTags.update")
async def update_customer_tag(
    tag_id: str,
    body: _TagPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)
    row = await db.customer_tags.find_one(
        {"id": tag_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Tag not found")
    if row.get("is_system"):
        raise HTTPException(400, "system_tag_readonly")

    upd: dict = {}
    old_name = row["name"]
    new_name = old_name
    if body.name is not None:
        new_name = _validate_name(body.name)
        # Reject renaming to shadow a system tag name.
        if new_name.lower() in _SYSTEM_TAG_NAMES_LOWER:
            raise HTTPException(
                409, "duplicate_tag_name: reserved system tag name")
        # Reject collision with existing tag (case-insensitive).
        if new_name.lower() != row["name_lower"]:
            existing = await db.customer_tags.find_one(
                {"tenant_id": tenant["id"], "name_lower": new_name.lower(),
                 "id": {"$ne": tag_id}},
                {"_id": 0, "id": 1},
            )
            if existing:
                raise HTTPException(409, "duplicate_tag_name")
        upd["name"] = new_name
        upd["name_lower"] = new_name.lower()
    if body.color is not None:
        upd["color"] = body.color
    if not upd:
        return row
    upd["updated_at"] = now_iso()
    await db.customer_tags.update_one(
        {"id": tag_id, "tenant_id": tenant["id"]}, {"$set": upd})

    # If the name changed, migrate it on every customer that carries
    # the old name — otherwise the registry row and the customer's
    # tags field drift out of sync.
    if body.name is not None and new_name != old_name:
        await db.customers.update_many(
            {"tenant_id": tenant["id"], "tags": old_name},
            {"$addToSet": {"tags": new_name}})
        await db.customers.update_many(
            {"tenant_id": tenant["id"], "tags": old_name},
            {"$pull": {"tags": old_name}})
        await _recompute_usage(tenant["id"], new_name)
    else:
        await _recompute_usage(tenant["id"], old_name)

    return await db.customer_tags.find_one(
        {"id": tag_id, "tenant_id": tenant["id"]}, {"_id": 0})


# ═════════════════════════════════════════════════════════════════
# DELETE /customer-tags/{tag_id}
# System tags are locked. Deleting cascades: the tag string is
# removed from every customer that carries it.
# ═════════════════════════════════════════════════════════════════
@router.delete("/customer-tags/{tag_id}", tags=["customer-tags"],
                 operation_id="customerTags.delete")
async def delete_customer_tag(
    tag_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)
    row = await db.customer_tags.find_one(
        {"id": tag_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Tag not found")
    if row.get("is_system"):
        raise HTTPException(400, "system_tag_readonly")
    name = row["name"]
    # Cascade: strip the tag from every customer that carries it.
    await db.customers.update_many(
        {"tenant_id": tenant["id"], "tags": name},
        {"$pull": {"tags": name}})
    await db.customer_tags.delete_one(
        {"id": tag_id, "tenant_id": tenant["id"]})
    return {"ok": True, "removed_from_customers": True}


# ═════════════════════════════════════════════════════════════════
# PATCH /customers/{cid}/tags — set customer tag list
# ═════════════════════════════════════════════════════════════════
class _CustomerTagsSet(BaseModel):
    tags: List[str] = Field(default_factory=list, max_items=50)


@router.patch("/customers/{cid}/tags", tags=["customers"],
                operation_id="customers.setTags")
async def set_customer_tags(
    cid: str,
    body: _CustomerTagsSet,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "tags": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")

    # Validate + trim every incoming tag. Deduplicate case-insensitively
    # while preserving the caller's ordering.
    seen: set = set()
    cleaned: List[str] = []
    for raw in body.tags:
        t = _validate_name(raw)
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(t)

    # Auto-create any tag missing from the registry.
    for t in cleaned:
        await _upsert_tag(tenant["id"], t, None, user.get("id", ""))

    # Diff old vs new so we can recompute usage on both sides.
    old_tags = list(cust.get("tags") or [])
    changed = set(old_tags) ^ set(cleaned)

    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"tags": cleaned}},
    )

    # Best-effort usage recount on every touched name.
    for name in changed:
        await _recompute_usage(tenant["id"], name)

    return {"ok": True, "tags": cleaned}
