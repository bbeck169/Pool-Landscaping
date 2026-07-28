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
    reloads. Uses a stable md5 hash mod palette length."""
    # MD5 for stable non-security identifier (not password/signature)
    h = int(hashlib.md5(name.strip().lower().encode()).hexdigest(), 16)
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
    tag = await _upsert_tag(
        tenant["id"], body.name, body.color, user.get("id", ""),
    )
    # Recompute in case the tag already existed and got orphaned
    # customers pre-registry.
    await _recompute_usage(tenant["id"], tag["name"])
    return tag


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
