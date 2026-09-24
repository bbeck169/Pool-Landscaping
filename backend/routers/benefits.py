"""Task D · Feb-2026 — Employee Benefits router.

Tenant-managed CRUD catalog for the "Benefits" surface that lets
admins publish external-URL perks (e.g. Perks at Work) to their
whole workforce. Read is open to every authenticated user;
mutations require ``admin`` or ``super_admin``.

Contract highlights:
  * Canonical path:      ``/api/benefits`` for GET/POST/PATCH/DELETE.
  * Icon field:          string, holds a Lucide kebab-case name.
                         The 12-name allowlist is enforced at the
                         pydantic layer so bad names fail at 400,
                         not at frontend-render time.
  * Delete:              soft — sets ``deleted_at`` timestamp.
  * Seed:                on first GET, when the tenant has ZERO
                         rows (including tombstoned rows) we
                         upsert the ``Perks at Work`` starter
                         via ``update_one(..., upsert=True)`` so
                         two concurrent GETs on a fresh tenant
                         race safely.
  * Tenant isolation:    P57/P58 pattern — every find/update
                         filter includes ``tenant_id`` alongside
                         the row id. P57-style ValueError guard
                         on empty/whitespace tenant_id.
  * Audit trail:         POST/PATCH/DELETE each write an
                         ``audit_log`` row stamped with
                         ``tenant_id`` and ``resource_type="benefit"``.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from config import db
from utils import get_current_user, require_admin, new_id, now_iso


logger = logging.getLogger(__name__)
router = APIRouter()


# 12 curated Lucide icon names (kebab-case). Admin dialog exposes
# these as a preset picker; anything outside this set is rejected
# at the pydantic layer so bad data never lands in Mongo.
BENEFIT_ICON_ALLOWLIST: frozenset[str] = frozenset({
    "gift", "heart", "building", "briefcase", "coffee",
    "graduation-cap", "shield", "smile", "sparkles",
    "book", "dumbbell", "piggy-bank",
})


# Reject non-http(s) external URLs at the pydantic layer.
# ``javascript:``, ``data:``, ``file:``, ``mailto:`` etc. all fail
# this regex.  Kept permissive on the host component so localhost
# / IP / port variants still work in dev seed data.
_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


class BenefitBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=1000)
    external_url: str = Field(..., max_length=2048)
    icon: str = Field(..., min_length=1, max_length=64)
    is_active: bool = True
    sort_order: int = 0

    @validator("external_url")
    def _validate_url(cls, v: str) -> str:  # noqa: N805
        trimmed = (v or "").strip()
        if not _URL_RE.match(trimmed):
            raise ValueError(
                "external_url must be an http:// or https:// URL"
            )
        return trimmed

    @validator("icon")
    def _validate_icon(cls, v: str) -> str:  # noqa: N805
        name = (v or "").strip().lower()
        if name not in BENEFIT_ICON_ALLOWLIST:
            raise ValueError(
                f"icon must be one of: "
                f"{', '.join(sorted(BENEFIT_ICON_ALLOWLIST))}"
            )
        return name

    @validator("title")
    def _validate_title(cls, v: str) -> str:  # noqa: N805
        trimmed = (v or "").strip()
        if not trimmed:
            raise ValueError("title cannot be empty or whitespace")
        return trimmed


class BenefitCreate(BenefitBase):
    pass


class BenefitPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    external_url: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

    @validator("external_url")
    def _validate_url(cls, v):  # noqa: N805
        if v is None:
            return v
        trimmed = (v or "").strip()
        if not _URL_RE.match(trimmed):
            raise ValueError(
                "external_url must be an http:// or https:// URL"
            )
        return trimmed

    @validator("icon")
    def _validate_icon(cls, v):  # noqa: N805
        if v is None:
            return v
        name = (v or "").strip().lower()
        if name not in BENEFIT_ICON_ALLOWLIST:
            raise ValueError(
                f"icon must be one of: "
                f"{', '.join(sorted(BENEFIT_ICON_ALLOWLIST))}"
            )
        return name

    @validator("title")
    def _validate_title(cls, v):  # noqa: N805
        if v is None:
            return v
        trimmed = (v or "").strip()
        if not trimmed:
            raise ValueError("title cannot be empty or whitespace")
        return trimmed


# ─────────────────────────── seed helper ───────────────────────────

_SEED_TITLE = "Perks at Work"
_SEED_ROW = {
    "title": _SEED_TITLE,
    "description": (
        "Discounts and rewards on 30,000+ brands. Log in with your "
        "work email to unlock exclusive savings."
    ),
    "external_url": "https://www.perksatwork.com/login",
    "icon": "gift",
    "is_active": True,
    "sort_order": 0,
}


def _require_tenant_id(user: dict) -> str:
    """P57/P58 pattern — every mutation must resolve a non-empty
    tenant_id from the caller. Empty / whitespace / None raises
    immediately instead of silently collapsing the tenant filter.
    """
    tid = user.get("tenant_id")
    if not isinstance(tid, str) or not tid.strip():
        raise ValueError(
            "benefits endpoint requires a non-empty tenant_id on the caller"
        )
    return tid


async def _ensure_default_benefit(tenant_id: str) -> None:
    """Seed the ``Perks at Work`` starter row on first GET for a
    tenant that has ZERO rows (counting tombstoned rows too, so
    admins who delete the seed don't see it come back).

    Race safety: the ``count_documents == 0`` check + ``insert_one``
    are not atomic. Two concurrent first-GETs on a fresh tenant
    could both pass the check and both insert. Wrap the insert in
    ``update_one(..., upsert=True)`` on the compound
    ``{tenant_id, title="Perks at Work"}`` filter so Mongo enforces
    the uniqueness atomically. Even with no explicit unique index,
    the upsert semantic never creates duplicates because the
    filter is exact-match on both fields.
    """
    total = await db.benefits.count_documents({"tenant_id": tenant_id})
    if total > 0:
        return
    now = now_iso()
    doc = {
        **_SEED_ROW,
        "id": new_id(),
        "tenant_id": tenant_id,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    # Race-safe idempotent seed. Filter is exact-match on
    # ``(tenant_id, title)`` so a concurrent GET that also passed
    # the count check will hit the upsert as an update (setOnInsert
    # is a no-op if the row exists).
    await db.benefits.update_one(
        {"tenant_id": tenant_id, "title": _SEED_TITLE},
        {"$setOnInsert": doc},
        upsert=True,
    )


# ─────────────────────────── audit helper ──────────────────────────

async def _audit(tenant_id: str, user: dict, action: str, bid: str,
                   fields: Optional[list[str]] = None) -> None:
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": action,
            "resource_type": "benefit",
            "resource_id": bid,
            "changed_fields": sorted(fields) if fields else None,
            "at": now_iso(),
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"benefits.audit ({action}) failed: {e}")


# ────────────────────────────── routes ─────────────────────────────

def _project(row: dict) -> dict:
    """Strip Mongo ``_id`` and internal-only fields on the way out."""
    row.pop("_id", None)
    return row


@router.get("/benefits")
async def list_benefits(user: dict = Depends(get_current_user)):
    tenant_id = _require_tenant_id(user)
    await _ensure_default_benefit(tenant_id)
    rows = await db.benefits.find(
        {"tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0},
    ).sort([("sort_order", 1), ("title", 1)]).to_list(500)
    return {"items": [_project(r) for r in rows], "count": len(rows)}


@router.post("/benefits", status_code=201)
async def create_benefit(body: BenefitCreate,
                            user: dict = Depends(require_admin)):
    tenant_id = _require_tenant_id(user)
    now = now_iso()
    doc = {
        **body.dict(),
        "id": new_id(),
        "tenant_id": tenant_id,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.benefits.insert_one(doc)
    await _audit(tenant_id, user, "benefit.create", doc["id"],
                    sorted(body.dict(exclude_none=True).keys()))
    return _project({**doc})


@router.patch("/benefits/{bid}")
async def patch_benefit(bid: str, body: BenefitPatch,
                           user: dict = Depends(require_admin)):
    tenant_id = _require_tenant_id(user)
    upd = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not upd:
        raise HTTPException(400, "No fields to update")
    row = await db.benefits.find_one(
        {"id": bid, "tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0, "id": 1},
    )
    if not row:
        raise HTTPException(404, "Benefit not found")
    upd["updated_at"] = now_iso()
    await db.benefits.update_one(
        {"id": bid, "tenant_id": tenant_id},
        {"$set": upd},
    )
    await _audit(tenant_id, user, "benefit.patch", bid, list(upd.keys()))
    return _project(await db.benefits.find_one(
        {"id": bid, "tenant_id": tenant_id}, {"_id": 0},
    ))


@router.delete("/benefits/{bid}")
async def delete_benefit(bid: str,
                            user: dict = Depends(require_admin)):
    tenant_id = _require_tenant_id(user)
    row = await db.benefits.find_one(
        {"id": bid, "tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0, "id": 1},
    )
    if not row:
        raise HTTPException(404, "Benefit not found")
    now = now_iso()
    await db.benefits.update_one(
        {"id": bid, "tenant_id": tenant_id},
        {"$set": {"deleted_at": now, "updated_at": now}},
    )
    await _audit(tenant_id, user, "benefit.delete", bid, ["deleted_at"])
    return {"ok": True, "deleted": True, "benefit_id": bid}
