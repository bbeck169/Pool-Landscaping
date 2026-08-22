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
import logging
from typing import List, Optional

logger = logging.getLogger("pool_crm")

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso, not_deleted_filter
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
                       created_by: str, *, auto_created: bool = False) -> dict:
    """Idempotent single-tag upsert. Case-insensitive uniqueness on
    ``name_lower``. Returns the persisted doc (existing or new).

    Feb-2026 · P33 — ``auto_created`` stamps the origin when the tag
    was born by side-effect (customer create/update path) vs the
    admin explicitly adding it via the tag admin. Existing rows are
    left untouched — we never rewrite the flag once set.

    Feb-2026 · P36 — Explicit archived-row no-op branch (P29b
    muted-reasons parity contract). When ``name_lower`` matches an
    existing row with ``is_active=False``, this helper returns the
    archived row AS-IS: no ``$set is_active=true``, no re-insert, no
    metadata touch. The customer's ``tags`` array still carries the
    label as a free-text snapshot; the admin's intentional archive
    is respected. The only way to re-activate an archived tag is the
    admin explicit ``POST /customer-tags/{id}/restore`` endpoint."""
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
        "auto_created": bool(auto_created),
        # P36 — every new row is active by default; archive is an
        # explicit admin action via DELETE or PATCH is_active=false.
        "is_active": True,
        "sort_order": 0,
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
# ═════════════════════════════════════════════════════════════════
# Feb-2026 · P33h — Lazy self-heal top-up.
# The customers list "All tags" filter renders from GET /customer-tags.
# On any tenant where the P33 seed migration was skipped (e.g. prod
# redeploy before ops ran ``task_p33_seed_customer_tags_catalog``)
# the catalog stays empty except for the two system-tag rows, so the
# dropdown looks broken even though the customers themselves carry
# tag strings. Self-heal: on each GET, aggregate the distinct tag
# strings on ``customers.tags`` and upsert any that are missing from
# the catalog. Rate-limited to once per tenant per ``_SELF_HEAL_TTL_S``
# seconds so a customers-list page load doesn't hammer the DB.
# ═════════════════════════════════════════════════════════════════
import time as _p33h_time
_SELF_HEAL_TTL_S = 300  # 5 minutes per tenant
_SELF_HEAL_LAST: dict[str, float] = {}
_SELF_HEAL_COUNTER: dict[str, int] = {}  # test hook — counts aggregate calls


async def _self_heal_catalog(tenant_id: str) -> None:
    """Best-effort top-up. Wrapped by the caller in try/except; any
    failure here is swallowed by the caller."""
    now = _p33h_time.time()
    last = _SELF_HEAL_LAST.get(tenant_id, 0.0)
    if now - last < _SELF_HEAL_TTL_S:
        return
    _SELF_HEAL_LAST[tenant_id] = now
    _SELF_HEAL_COUNTER[tenant_id] = _SELF_HEAL_COUNTER.get(tenant_id, 0) + 1

    # Aggregate distinct tag strings on this tenant's customers.
    distinct = await db.customers.distinct(
        "tags", {"tenant_id": tenant_id, "tags": {"$exists": True, "$ne": []}},
    )
    if not distinct:
        return
    # Filter + normalize.
    cleaned: list[str] = []
    for raw in distinct:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        try:
            cleaned.append(_validate_name(s))
        except HTTPException:
            continue
    if not cleaned:
        return
    # De-dup case-insensitively on the incoming set first.
    seen_norm: dict[str, str] = {}
    for label in cleaned:
        seen_norm.setdefault(label.lower(), label)

    # Check the catalog for existing rows (active OR archived).
    existing = await db.customer_tags.find(
        {"tenant_id": tenant_id,
          "name_lower": {"$in": list(seen_norm.keys())}},
        {"_id": 0, "name_lower": 1},
    ).to_list(len(seen_norm) + 10)
    have = {r["name_lower"] for r in existing}
    to_insert = [
        {"label": v, "norm": k}
        for k, v in seen_norm.items() if k not in have
    ]
    if not to_insert:
        return
    # Compute next sort_order once.
    last_sort = 0
    last_row = await db.customer_tags.find(
        {"tenant_id": tenant_id}, {"_id": 0, "sort_order": 1},
    ).sort("sort_order", -1).limit(1).to_list(1)
    if last_row:
        try:
            last_sort = int(last_row[0].get("sort_order") or 0)
        except Exception:
            last_sort = 0
    now_stamp = now_iso()
    docs = []
    for i, item in enumerate(to_insert, start=1):
        docs.append({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": item["label"],
            "name_lower": item["norm"],
            "color": _pick_color(item["label"]),
            "is_system": False,
            "created_by": "self_heal",
            "created_at": now_stamp,
            "usage_count": 0,
            "auto_created": True,
            "is_active": True,
            "sort_order": last_sort + (i * 10),
        })
    if docs:
        await db.customer_tags.insert_many(docs)
        logger.info("[p33h] self-heal top-up tenant=%s inserted=%s",
                        tenant_id, len(docs))


# Feb-2026 · P33h — internal test/support helper. Clears the per-tenant
# self-heal window so the next GET re-runs the aggregate. Admin only.
class _P33hReset(BaseModel):
    tenant_id: Optional[str] = None


@router.post("/internal/customer-tags/reset-self-heal",
                tags=["customer-tags"])
async def reset_self_heal_cache(
    body: _P33hReset,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    tid = body.tenant_id or tenant["id"]
    _SELF_HEAL_LAST.pop(tid, None)
    _SELF_HEAL_COUNTER.pop(tid, None)
    return {"ok": True, "tenant_id": tid}


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · P44 — Used-tag distinct cache. Per-tenant, 60s TTL. The
# customers.tags distinct set is authoritative — the stored per-row
# ``usage_count`` may drift (spec). Cached because the customers-list
# page hits ``GET /customer-tags?only_used=true`` on every mount and
# tab switch. Reset via ``POST /internal/customer-tags/reset-usage-
# cache`` (test hook, parallels the P38 dupe-cache reset).
# ═════════════════════════════════════════════════════════════════════
import time as _p44_time

_USED_TAG_CACHE_TTL_S = 60
_TAG_USAGE_CACHE: dict[str, tuple[float, set[str]]] = {}


async def _get_used_tag_names_lower(tenant_id: str) -> set[str]:
    hit = _TAG_USAGE_CACHE.get(tenant_id)
    if hit and hit[0] > _p44_time.time():
        return hit[1]
    raw = await db.customers.distinct(
        "tags",
        {"tenant_id": tenant_id, **not_deleted_filter()},
    )
    used: set[str] = set()
    for v in raw or []:
        if isinstance(v, str):
            trimmed = v.strip().lower()
            if trimmed:  # whitespace-only strings don't count as usage
                used.add(trimmed)
    _TAG_USAGE_CACHE[tenant_id] = (
        _p44_time.time() + _USED_TAG_CACHE_TTL_S, used)
    return used


@router.post("/internal/customer-tags/reset-usage-cache",
                tags=["customer-tags"])
async def reset_usage_cache(
    body: _P33hReset,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Test/support helper — clears the P44 used-tag distinct cache
    for a tenant so a subsequent GET rebuilds fresh. Same RBAC as the
    sibling reset endpoints."""
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    tid = body.tenant_id or tenant["id"]
    _TAG_USAGE_CACHE.pop(tid, None)
    return {"ok": True, "tenant_id": tid}


@router.get("/customer-tags", tags=["customer-tags"],
             operation_id="customerTags.list")
async def list_customer_tags(
    include_inactive: bool = False,
    only_used: bool = False,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Feb-2026 · P33 — any authenticated staff can READ the registry
    # so the customer-form tag picker + list-page "All tags" filter
    # can populate for techs too. Writes (POST / PATCH / DELETE) stay
    # admin-or-manager gated below.
    if user.get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")

    # Feb-2026 · P33h — lazy self-heal top-up. Silent on failure so a
    # bug here never 500s the customers-list page.
    try:
        await _self_heal_catalog(tenant["id"])
    except Exception as _e:  # noqa: BLE001
        logger.warning("[p33h] self-heal error tenant=%s: %s",
                          tenant.get("id"), _e)

    # Feb-2026 · P36 — hide archived (is_active=False) rows by default.
    # Rows created before P36 have no ``is_active`` field and are
    # treated as active (matches the migration's default).
    q: dict = {"tenant_id": tenant["id"]}
    if not include_inactive:
        q["$or"] = [{"is_active": {"$ne": False}},
                       {"is_active": {"$exists": False}}]
    rows = await db.customer_tags.find(q, {"_id": 0}).sort(
        [("sort_order", 1), ("usage_count", -1), ("name_lower", 1)],
    ).to_list(500)

    # Feb-2026 · P44 — hide zero-usage tags from the customers-list
    # "All tags" dropdown. Trust the distinct set on ``customers.tags``
    # (stored ``usage_count`` may be stale — spec).
    if only_used:
        used_lower = await _get_used_tag_names_lower(tenant["id"])
        rows = [r for r in rows if (r.get("name_lower") or "").strip()
                    in used_lower]

    return {"items": rows, "total": len(rows)}


# Feb-2026 · P33 — Best-effort auto-persist hook used by the customer
# POST + PUT paths. Iterates every tag string on the incoming payload
# and idempotently upserts it into the tenant catalog. Wrapped by the
# caller in try/except so any failure never blocks the customer save.
# Existing rows are respected (no reactivation of admin-archived tags —
# the current schema doesn't archive, but the ``auto_created`` flag on
# net-new rows lets the settings page distinguish origin later).
async def auto_persist_customer_tags(
    tenant_id: str, actor_id: str, tags: Optional[List[str]],
) -> int:
    """Returns the count of NEW catalog rows inserted (0 if all
    incoming tags were already present)."""
    if not tags:
        return 0
    inserted = 0
    for raw in tags:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        # Validate loosely — reuse the existing 40-char cap but
        # swallow validation errors rather than blowing up the save.
        try:
            trimmed = _validate_name(s)
        except HTTPException:
            continue
        existed = await db.customer_tags.find_one(
            {"tenant_id": tenant_id, "name_lower": trimmed.lower()},
            {"_id": 0, "id": 1},
        )
        if existed:
            continue
        try:
            await _upsert_tag(
                tenant_id, trimmed, None, actor_id or "system",
                auto_created=True,
            )
            inserted += 1
        except Exception:
            # Best-effort — never break the customer write.
            continue
    return inserted


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
    # Feb-2026 · P36 — admins may toggle archive/active via PATCH as
    # an alternative to DELETE / POST /restore. Same RBAC applies.
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


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
    if body.sort_order is not None:
        upd["sort_order"] = int(body.sort_order)
    # Feb-2026 · P36 — PATCH archive/restore alias for the settings page.
    if body.is_active is not None:
        if row.get("is_system") and body.is_active is False:
            raise HTTPException(400, "system_tag_readonly")
        upd["is_active"] = bool(body.is_active)
        if body.is_active is False:
            upd["archived_at"] = now_iso()
            upd["archived_by"] = user.get("id")
        else:
            upd["archived_at"] = None
            upd["archived_by"] = None
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
# DELETE /customer-tags/{tag_id} — soft-archive (P36)
# ─────────────────────────────────────────────────────────────────
# Feb-2026 · P36 — DELETE is now a soft-deactivate. The catalog row
# is flipped to ``is_active=False`` + ``archived_at/by`` stamped;
# ``customers.tags`` snapshots are LEFT INTACT (immutable, matches
# the P29b muted-reasons contract). To rewrite existing customer
# references, use the merge endpoint below. To reactivate an
# archived tag, POST /customer-tags/{id}/restore.
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
    await db.customer_tags.update_one(
        {"id": tag_id, "tenant_id": tenant["id"]},
        {"$set": {"is_active": False,
                    "archived_at": now_iso(),
                    "archived_by": user.get("id"),
                    "updated_at": now_iso()}},
    )
    return {"ok": True, "archived": True, "id": tag_id}


# ═════════════════════════════════════════════════════════════════
# POST /customer-tags/{tag_id}/restore — reactivate an archived tag
# ═════════════════════════════════════════════════════════════════
@router.post("/customer-tags/{tag_id}/restore", tags=["customer-tags"],
                operation_id="customerTags.restore")
async def restore_customer_tag(
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
    await db.customer_tags.update_one(
        {"id": tag_id, "tenant_id": tenant["id"]},
        {"$set": {"is_active": True,
                    "archived_at": None,
                    "archived_by": None,
                    "updated_at": now_iso()}},
    )
    return {"ok": True, "restored": True, "id": tag_id}


# ═════════════════════════════════════════════════════════════════
# POST /customer-tags/merge — collapse victim tags into a canonical
# ─────────────────────────────────────────────────────────────────
# Feb-2026 · P36 — merges N victim tag labels into a canonical tag.
# For every customer that carries any victim label, the label is
# rewritten to the canonical label (deduplicated case-insensitively
# in the array). Victims are archived (soft-deactivate). Idempotent
# on re-run — if victims are already archived and no customer
# references them, returns 200 with ``customers_updated=0``.
# ═════════════════════════════════════════════════════════════════
class _TagMerge(BaseModel):
    canonical_id: str
    victim_ids: List[str] = Field(default_factory=list, min_items=1)


@router.post("/customer-tags/merge", tags=["customer-tags"],
                operation_id="customerTags.merge")
async def merge_customer_tags(
    body: _TagMerge,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_manager(user)

    if body.canonical_id in body.victim_ids:
        raise HTTPException(400, "canonical_cannot_be_victim")

    canonical = await db.customer_tags.find_one(
        {"id": body.canonical_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not canonical:
        raise HTTPException(404, "canonical_tag_not_found")

    victims: List[dict] = []
    for vid in body.victim_ids:
        v = await db.customer_tags.find_one(
            {"id": vid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not v:
            raise HTTPException(404, f"victim_tag_not_found: {vid}")
        if v.get("is_system"):
            raise HTTPException(400, "system_tag_readonly")
        victims.append(v)

    canonical_name = canonical["name"]
    victim_names = [v["name"] for v in victims]

    # Rewrite every customer that carries at least one victim label.
    # Do it customer-by-customer so we can dedup case-insensitively
    # against any existing canonical membership.
    q_touch = {"tenant_id": tenant["id"],
                 "tags": {"$in": victim_names}}
    affected_ids: List[str] = []
    async for c in db.customers.find(
        q_touch, {"_id": 0, "id": 1, "tags": 1},
    ):
        existing_tags: List[str] = list(c.get("tags") or [])
        # Remove any victim labels; keep everything else.
        remaining = [t for t in existing_tags if t not in victim_names]
        # Add canonical if not already present (case-insensitive).
        has_canon = any((isinstance(t, str) and t.lower() == canonical_name.lower())
                            for t in remaining)
        if not has_canon:
            remaining.append(canonical_name)
        await db.customers.update_one(
            {"id": c["id"], "tenant_id": tenant["id"]},
            {"$set": {"tags": remaining, "updated_at": now_iso()}},
        )
        affected_ids.append(c["id"])

    # Archive each victim tag (soft-deactivate). Skip already-archived
    # to keep the operation idempotent.
    victims_archived_now: List[str] = []
    for v in victims:
        if v.get("is_active") is False:
            continue
        await db.customer_tags.update_one(
            {"id": v["id"], "tenant_id": tenant["id"]},
            {"$set": {"is_active": False,
                        "archived_at": now_iso(),
                        "archived_by": user.get("id"),
                        "updated_at": now_iso(),
                        "merged_into_id": canonical["id"],
                        "merged_into_name": canonical_name}},
        )
        victims_archived_now.append(v["id"])

    # Usage-count refresh on canonical (victims are archived so their
    # counts stop mattering).
    await _recompute_usage(tenant["id"], canonical_name)

    # Audit log — full before/after payload for the merge.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_id": user.get("id"), "actor_email": user.get("email"),
            "event": "customer_tag_merge",
            "at": now_iso(),
            "payload": {
                "canonical_id": canonical["id"],
                "canonical_name": canonical_name,
                "victim_ids": body.victim_ids,
                "victim_names": victim_names,
                "customers_updated": affected_ids,
                "victims_archived_now": victims_archived_now,
            },
        })
    except Exception:
        # Best-effort audit; never block the merge.
        pass

    return {
        "ok": True,
        "canonical_id": canonical["id"],
        "canonical_label": canonical_name,
        "merged_victims": len(victims),
        "victims_archived_now": len(victims_archived_now),
        "customers_updated": len(affected_ids),
    }


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


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · P38 — AI-suggested duplicate tags (pure-Python fuzzy).
# ═════════════════════════════════════════════════════════════════════
import difflib as _difflib
import time as _time

_DUPE_RATIO_THRESHOLD = 0.8
_DUPE_CACHE_TTL_S = 60
# In-memory per-tenant cache. Keyed on tenant_id; value is
# (expires_at_epoch, payload_dict). The cache is a UX optimization
# for admin refreshes; it's fine if it evicts on process restart.
_DUPE_CACHE: dict[str, tuple[float, dict]] = {}


def _dupe_cluster_signature(labels: list[str]) -> str:
    return "|".join(sorted(l.lower() for l in labels))


@router.post("/internal/customer-tags/reset-dupe-cache",
                tags=["customer-tags"])
async def reset_dupe_cache(
    body: _P33hReset,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Test/support helper — clears the server-side suggest-duplicates
    cache for a tenant so a subsequent GET rebuilds fresh. Same RBAC
    as the sibling self-heal reset."""
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    tid = body.tenant_id or tenant["id"]
    _DUPE_CACHE.pop(tid, None)
    return {"ok": True, "tenant_id": tid}


@router.get("/customer-tags/suggest-duplicates", tags=["customer-tags"])
async def suggest_duplicate_tags(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return clusters of near-duplicate tag labels.

    Uses ``difflib.SequenceMatcher`` (Python stdlib — deterministic,
    no LLM cost) with a 0.8 ratio threshold. Exact case-variant
    duplicates ("pool" vs "Pool") always cluster because their
    ``name_lower`` compare identically (ratio 1.0).

    Suggested canonical selection:
        1. Highest ``usage_count`` (most-tagged wins)
        2. Tie-break: longest label ("Landscaping" over "Landscape")
        3. Tie-break 2: alphabetically first
    """
    _require_admin_or_manager(user)
    tid = tenant["id"]

    # Cache hit?
    hit = _DUPE_CACHE.get(tid)
    if hit and hit[0] > _time.time():
        return hit[1]

    # Load active tags for the tenant.
    tags = await db.customer_tags.find(
        {"tenant_id": tid, "is_active": True},
        {"_id": 0},
    ).to_list(length=None)

    # Build clusters via union-find over pairs meeting the ratio threshold.
    n = len(tags)
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        li = (tags[i].get("name_lower") or (tags[i].get("name") or "").lower())
        for j in range(i + 1, n):
            lj = (tags[j].get("name_lower")
                     or (tags[j].get("name") or "").lower())
            if not li or not lj:
                continue
            ratio = _difflib.SequenceMatcher(None, li, lj).ratio()
            if ratio >= _DUPE_RATIO_THRESHOLD:
                _union(i, j)

    # Group tags by root.
    buckets: dict[int, list[dict]] = {}
    for i in range(n):
        buckets.setdefault(_find(i), []).append(tags[i])

    clusters: list[dict] = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        # Suggested-canonical heuristic.
        group_sorted = sorted(
            group,
            key=lambda t: (
                -int(t.get("usage_count") or 0),
                -len(t.get("name") or ""),
                (t.get("name") or "").lower(),
            ),
        )
        canonical = group_sorted[0]
        # Confidence = MAX pairwise ratio inside the cluster (the
        # strongest evidence of similarity in the group). Min-pair
        # ratio would under-report tri-clusters where two labels
        # differ pairwise but both closely match a third.
        pair_ratios: list[float] = []
        labels_lower = [(t.get("name_lower")
                           or (t.get("name") or "").lower()) for t in group]
        for a in range(len(labels_lower)):
            for b in range(a + 1, len(labels_lower)):
                pair_ratios.append(_difflib.SequenceMatcher(
                    None, labels_lower[a], labels_lower[b]).ratio())
        confidence = round(max(pair_ratios), 2) if pair_ratios else 1.0
        clusters.append({
            "tag_ids": [t["id"] for t in group_sorted],
            "labels": [t.get("name") or "" for t in group_sorted],
            "suggested_canonical": canonical.get("name") or "",
            "suggested_canonical_id": canonical.get("id"),
            "confidence": confidence,
            "signature": _dupe_cluster_signature(
                [t.get("name") or "" for t in group]),
        })

    # Deterministic cluster order — highest confidence first, then
    # alphabetical on canonical label.
    clusters.sort(key=lambda c: (-c["confidence"],
                                       c["suggested_canonical"].lower()))

    payload = {
        "ok": True,
        "clusters": clusters,
        "ratio_threshold": _DUPE_RATIO_THRESHOLD,
    }
    _DUPE_CACHE[tid] = (_time.time() + _DUPE_CACHE_TTL_S, payload)
    return payload
