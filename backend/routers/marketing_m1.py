"""Marketing Subsystem · Phase M1 — Foundation backend.

Namespace: ``/api/marketing/*``. Coexists with the legacy
``routers/marketing.py`` (forms + placeholder campaigns) — new M1
endpoints use non-colliding paths.

M1 surface:

* Subscribers   — CRUD + unsubscribe + bulk-tag
* Lists         — CRUD + membership add/remove/list
* Segments      — CRUD + preview (matched-count + sample) + materialize
* Settings      — GET/PUT double-opt-in default + attribution window
* Public        — signup-form/{slug}/subscribe + confirm

All admin surfaces require the admin or super_admin role. Public
signup + confirm endpoints are unauthenticated and resolve the tenant
from the form document + ``X-Tenant-Slug`` header + custom domain.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, EmailStr

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant, _ensure_default_tenant
from services.marketing_segments import compile_rules, compile_to_filter
from services.marketing_subscribers import (
    sign_confirmation, verify_confirmation, send_confirmation_email,
)


router = APIRouter(tags=["Marketing (M1)"])


# ─── constants ────────────────────────────────────────────────────────

_SUB_STATUS = {"pending_confirmation", "subscribed", "unsubscribed", "bounced"}
_SUB_SOURCES = {"public_form", "crm_customer", "manual", "api_import", "instaquote"}
_LIST_TYPES = {"static", "dynamic"}


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


def _clean(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return d
    out = dict(d)
    out.pop("_id", None)
    return out


async def _resolve_public_tenant(request: Request,
                                  form: Optional[dict] = None) -> Optional[dict]:
    """Public endpoints: prefer form's tenant_id → X-Tenant-Slug header →
    custom domain → default tenant. Returns the full tenant document."""
    tid = None
    if form and form.get("tenant_id"):
        tid = form["tenant_id"]
        t = await db.tenants.find_one({"id": tid, "active": True}, {"_id": 0})
        if t:
            return t
    slug = request.headers.get("x-tenant-slug")
    if slug:
        t = await db.tenants.find_one({"slug": slug, "active": True}, {"_id": 0})
        if t:
            return t
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host:
        t = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
        if t:
            return t
    return await _ensure_default_tenant()


async def _ensure_default_seeds(tenant_id: str) -> None:
    """Idempotent per-tenant seed: default list + default segment + VIP.
    Called lazily whenever a tenant hits its first M1 admin endpoint so
    every tenant has a working "everyone" audience out of the box."""
    seg = await db.marketing_segments.find_one(
        {"tenant_id": tenant_id, "slug": "active-subscribers"}, {"_id": 0})
    if not seg:
        await db.marketing_segments.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "slug": "active-subscribers",
            "name": "Active Subscribers",
            "description": "Everyone who has confirmed and not opted out.",
            "rules": {"combinator": "and", "rules": [
                {"field": "status", "op": "eq", "value": "subscribed"},
            ]},
            "is_system_default": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    # Feb-2026 Customer Detail Additions — auto-seeded "VIP Customers"
    # segment. Resolves against subscribers mirrored from the customers
    # collection where ``is_vip=True``.
    vip_seg = await db.marketing_segments.find_one(
        {"tenant_id": tenant_id, "slug": "vip-customers"}, {"_id": 0})
    if not vip_seg:
        await db.marketing_segments.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "slug": "vip-customers",
            "name": "VIP Customers",
            "description": "Customers flagged VIP on their profile.",
            "rules": {"combinator": "and", "rules": [
                {"field": "is_vip", "op": "eq", "value": True},
                {"field": "status", "op": "eq", "value": "subscribed"},
            ]},
            "is_system_default": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    lst = await db.marketing_lists.find_one(
        {"tenant_id": tenant_id, "slug": "all-subscribers"}, {"_id": 0})
    if not lst:
        await db.marketing_lists.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "slug": "all-subscribers",
            "name": "All Subscribers",
            "description": "Static list containing every subscriber in this tenant.",
            "type": "static",
            "segment_id": None,
            "is_system_default": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })


# ═════════════════════════════════════════════════════════════════════
# Pydantic bodies
# ═════════════════════════════════════════════════════════════════════

class SubscriberIn(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    source: Optional[str] = "manual"
    status: Optional[str] = "subscribed"
    tags: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None
    customer_id: Optional[str] = None


class SubscriberPatch(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None


class MailingListIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: Optional[str] = None
    description: Optional[str] = ""
    type: str = Field(
        "static",
        description="List type: 'static' (manual membership) or 'dynamic' (auto-resolves via segment_id).",
    )
    segment_id: Optional[str] = None


class MailingListPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    segment_id: Optional[str] = None


class SegmentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: Optional[str] = None
    description: Optional[str] = ""
    rules: Dict[str, Any] = Field(default_factory=dict)


class SegmentPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[Dict[str, Any]] = None


class MarketingSettingsIn(BaseModel):
    require_double_optin: Optional[bool] = None
    revenue_attribution_days: Optional[int] = Field(None, ge=1, le=365)


class MembershipIn(BaseModel):
    subscriber_ids: List[str] = Field(..., min_length=1, max_length=1000)


class PublicSubscribeIn(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    values: Optional[Dict[str, Any]] = None  # extra form fields → attributes
    honeypot: Optional[str] = None
    model_config = {"extra": "allow"}


class PublicConfirmIn(BaseModel):
    tenant_id: str
    email: EmailStr
    token: str


# ═════════════════════════════════════════════════════════════════════
# Subscribers
# ═════════════════════════════════════════════════════════════════════

@router.get("/marketing/subscribers")
async def list_subscribers(
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
    q: Optional[str] = Query(None, description="Search email/phone/name"),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        query["status"] = status
    if source:
        query["source"] = source
    if tag:
        query["tags"] = tag
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [{"email": rx}, {"phone": rx},
                         {"first_name": rx}, {"last_name": rx}]
    rows = await db.subscribers.find(query, {"_id": 0}) \
                                 .sort("created_at", -1) \
                                 .to_list(limit)
    return {"count": len(rows), "subscribers": rows}


@router.post("/marketing/subscribers", status_code=201)
async def create_subscriber(body: SubscriberIn,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    if not body.email and not body.phone:
        raise HTTPException(422, "email or phone is required")
    if body.status and body.status not in _SUB_STATUS:
        raise HTTPException(422, f"status must be one of {sorted(_SUB_STATUS)}")
    if body.source and body.source not in _SUB_SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(_SUB_SOURCES)}")
    email = (body.email or "").lower() if body.email else None
    key: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if email:
        key["email"] = email
    else:
        key["phone"] = body.phone
    existing = await db.subscribers.find_one(key, {"_id": 0})
    if existing:
        raise HTTPException(409, "subscriber already exists for this tenant")
    now = now_iso()
    status = body.status or "subscribed"
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "email": email,
        "phone": body.phone or None,
        "first_name": body.first_name or "",
        "last_name": body.last_name or "",
        "status": status,
        "source": body.source or "manual",
        "customer_id": body.customer_id,
        "tags": list(body.tags or []),
        "attributes": dict(body.attributes or {}),
        "consent_at": now if status == "subscribed" else None,
        "confirmed_at": now if status == "subscribed" else None,
        "unsubscribed_at": None,
        "confirmation_token": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.subscribers.insert_one(doc)
    return _clean(doc)


@router.get("/marketing/subscribers/{sid}")
async def get_subscriber(sid: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = await db.subscribers.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.patch("/marketing/subscribers/{sid}")
async def patch_subscriber(sid: str, body: SubscriberPatch,
                            user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    existing = await db.subscribers.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    upd: Dict[str, Any] = {}
    if body.email is not None:
        upd["email"] = body.email.lower()
    if body.phone is not None:
        upd["phone"] = body.phone or None
    if body.first_name is not None:
        upd["first_name"] = body.first_name
    if body.last_name is not None:
        upd["last_name"] = body.last_name
    if body.status is not None:
        if body.status not in _SUB_STATUS:
            raise HTTPException(422, f"status must be one of {sorted(_SUB_STATUS)}")
        upd["status"] = body.status
        if body.status == "unsubscribed":
            upd["unsubscribed_at"] = now_iso()
        if body.status == "subscribed" and not existing.get("confirmed_at"):
            upd["confirmed_at"] = now_iso()
    if body.tags is not None:
        upd["tags"] = list(body.tags)
    if body.attributes is not None:
        upd["attributes"] = dict(body.attributes)
    if not upd:
        return existing
    upd["updated_at"] = now_iso()
    await db.subscribers.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": upd})
    doc = await db.subscribers.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    return doc


@router.delete("/marketing/subscribers/{sid}", status_code=204)
async def delete_subscriber(sid: str,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    r = await db.subscribers.delete_one(
        {"id": sid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "Not found")
    # Cascade: purge memberships pointing at this subscriber.
    await db.marketing_list_memberships.delete_many(
        {"tenant_id": tenant["id"], "subscriber_id": sid})
    return None


@router.post("/marketing/subscribers/{sid}/unsubscribe")
async def admin_unsubscribe(sid: str,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    existing = await db.subscribers.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    await db.subscribers.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"status": "unsubscribed",
                  "unsubscribed_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# Mailing lists
# ═════════════════════════════════════════════════════════════════════

def _slugify(name: str) -> str:
    s = "".join(c if c.isalnum() or c in ("-", " ") else "" for c in (name or "")).strip()
    s = s.lower().replace(" ", "-")
    return s or f"list-{new_id()[:8]}"


@router.get("/marketing/lists")
async def list_lists(user: dict = Depends(_require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    await _ensure_default_seeds(tenant["id"])
    rows = await db.marketing_lists.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)
    # Enrich with member count (static: memberships collection; dynamic: segment eval)
    out = []
    for lst in rows:
        if lst.get("type") == "dynamic" and lst.get("segment_id"):
            seg = await db.marketing_segments.find_one(
                {"id": lst["segment_id"], "tenant_id": tenant["id"]},
                {"_id": 0})
            n = 0
            if seg:
                try:
                    flt = compile_to_filter(tenant["id"], seg.get("rules") or {})
                    n = await db.subscribers.count_documents(flt)
                except Exception:
                    n = 0
            lst["member_count"] = n
        else:
            lst["member_count"] = await db.marketing_list_memberships \
                .count_documents({"tenant_id": tenant["id"],
                                   "list_id": lst["id"]})
        out.append(lst)
    return {"count": len(out), "lists": out}


@router.post("/marketing/lists", status_code=201)
async def create_list(body: MailingListIn,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    if body.type not in _LIST_TYPES:
        raise HTTPException(422, f"type must be one of {sorted(_LIST_TYPES)}")
    if body.type == "dynamic" and not body.segment_id:
        raise HTTPException(422, "dynamic list requires segment_id")
    slug = body.slug or _slugify(body.name)
    if await db.marketing_lists.find_one(
            {"tenant_id": tenant["id"], "slug": slug}, {"_id": 0}):
        raise HTTPException(409, "slug already exists for this tenant")
    if body.segment_id:
        seg = await db.marketing_segments.find_one(
            {"id": body.segment_id, "tenant_id": tenant["id"]}, {"_id": 0})
        if not seg:
            raise HTTPException(422, "segment_id does not exist for this tenant")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "slug": slug,
        "name": body.name,
        "description": body.description or "",
        "type": body.type,
        "segment_id": body.segment_id,
        "is_system_default": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.marketing_lists.insert_one(doc)
    return _clean(doc)


@router.get("/marketing/lists/{lid}")
async def get_list(lid: str,
                    user: dict = Depends(_require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.patch("/marketing/lists/{lid}")
async def patch_list(lid: str, body: MailingListPatch,
                      user: dict = Depends(_require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    existing = await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    upd = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not upd:
        return existing
    upd["updated_at"] = now_iso()
    await db.marketing_lists.update_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/marketing/lists/{lid}", status_code=204)
async def delete_list(lid: str,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    existing = await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    if existing.get("is_system_default"):
        raise HTTPException(400, "system default list cannot be deleted")
    await db.marketing_lists.delete_one(
        {"id": lid, "tenant_id": tenant["id"]})
    await db.marketing_list_memberships.delete_many(
        {"tenant_id": tenant["id"], "list_id": lid})
    return None


@router.get("/marketing/lists/{lid}/members")
async def list_list_members(lid: str,
                              user: dict = Depends(_require_admin),
                              tenant: dict = Depends(get_current_tenant),
                              limit: int = Query(500, ge=1, le=5000)):
    lst = await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not lst:
        raise HTTPException(404, "list not found")
    if lst.get("type") == "dynamic" and lst.get("segment_id"):
        seg = await db.marketing_segments.find_one(
            {"id": lst["segment_id"], "tenant_id": tenant["id"]}, {"_id": 0})
        if not seg:
            return {"count": 0, "subscribers": []}
        flt = compile_to_filter(tenant["id"], seg.get("rules") or {})
        rows = await db.subscribers.find(flt, {"_id": 0}) \
                                     .sort("created_at", -1).to_list(limit)
        return {"count": len(rows), "subscribers": rows}
    # Static list.
    memberships = await db.marketing_list_memberships.find(
        {"tenant_id": tenant["id"], "list_id": lid}, {"_id": 0}
    ).to_list(limit)
    sub_ids = [m["subscriber_id"] for m in memberships]
    subs = await db.subscribers.find(
        {"tenant_id": tenant["id"], "id": {"$in": sub_ids}}, {"_id": 0}
    ).to_list(limit)
    return {"count": len(subs), "subscribers": subs}


@router.post("/marketing/lists/{lid}/members", status_code=201)
async def add_list_members(lid: str, body: MembershipIn,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    lst = await db.marketing_lists.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not lst:
        raise HTTPException(404, "list not found")
    if lst.get("type") == "dynamic":
        raise HTTPException(400, "dynamic lists cannot accept manual members")
    # Verify subscribers exist in this tenant.
    subs = await db.subscribers.find(
        {"tenant_id": tenant["id"], "id": {"$in": body.subscriber_ids}},
        {"_id": 0, "id": 1}).to_list(len(body.subscriber_ids))
    valid_ids = {s["id"] for s in subs}
    added = 0
    for sid in body.subscriber_ids:
        if sid not in valid_ids:
            continue
        r = await db.marketing_list_memberships.update_one(
            {"tenant_id": tenant["id"], "list_id": lid,
             "subscriber_id": sid},
            {"$setOnInsert": {"id": new_id(),
                              "tenant_id": tenant["id"],
                              "list_id": lid,
                              "subscriber_id": sid,
                              "added_at": now_iso()}},
            upsert=True,
        )
        if r.upserted_id is not None:
            added += 1
    return {"ok": True, "added": added,
            "requested": len(body.subscriber_ids),
            "invalid": len(body.subscriber_ids) - len(valid_ids)}


@router.delete("/marketing/lists/{lid}/members/{sid}", status_code=204)
async def remove_list_member(lid: str, sid: str,
                               user: dict = Depends(_require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_list_memberships.delete_one(
        {"tenant_id": tenant["id"], "list_id": lid, "subscriber_id": sid})
    if not r.deleted_count:
        raise HTTPException(404, "membership not found")
    return None


# ═════════════════════════════════════════════════════════════════════
# Segments
# ═════════════════════════════════════════════════════════════════════

@router.get("/marketing/segments")
async def list_segments(user: dict = Depends(_require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_default_seeds(tenant["id"])
    rows = await db.marketing_segments.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return {"count": len(rows), "segments": rows}


@router.post("/marketing/segments", status_code=201)
async def create_segment(body: SegmentIn,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    try:
        compile_rules(body.rules or {})
    except ValueError as e:
        raise HTTPException(422, f"invalid rules: {e}")
    slug = body.slug or _slugify(body.name)
    if await db.marketing_segments.find_one(
            {"tenant_id": tenant["id"], "slug": slug}, {"_id": 0}):
        raise HTTPException(409, "slug already exists for this tenant")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "slug": slug,
        "name": body.name,
        "description": body.description or "",
        "rules": body.rules or {},
        "is_system_default": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.marketing_segments.insert_one(doc)
    return _clean(doc)


@router.get("/marketing/segments/{sid}")
async def get_segment(sid: str,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.patch("/marketing/segments/{sid}")
async def patch_segment(sid: str, body: SegmentPatch,
                         user: dict = Depends(_require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    existing = await db.marketing_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    upd: Dict[str, Any] = {}
    if body.name is not None:
        upd["name"] = body.name
    if body.description is not None:
        upd["description"] = body.description
    if body.rules is not None:
        try:
            compile_rules(body.rules)
        except ValueError as e:
            raise HTTPException(422, f"invalid rules: {e}")
        upd["rules"] = body.rules
    if not upd:
        return existing
    upd["updated_at"] = now_iso()
    await db.marketing_segments.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.marketing_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/marketing/segments/{sid}", status_code=204)
async def delete_segment(sid: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    existing = await db.marketing_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    if existing.get("is_system_default"):
        raise HTTPException(400, "system default segment cannot be deleted")
    # Reject if any dynamic list references this segment.
    dep = await db.marketing_lists.find_one(
        {"tenant_id": tenant["id"], "segment_id": sid}, {"_id": 0})
    if dep:
        raise HTTPException(400, f"segment is referenced by list {dep.get('slug')}")
    await db.marketing_segments.delete_one(
        {"id": sid, "tenant_id": tenant["id"]})
    return None


@router.post("/marketing/segments/{sid}/preview")
async def preview_segment(sid: str,
                            user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant),
                            limit: int = Query(20, ge=1, le=200)):
    seg = await db.marketing_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not seg:
        raise HTTPException(404, "Not found")
    try:
        flt = compile_to_filter(tenant["id"], seg.get("rules") or {})
    except ValueError as e:
        raise HTTPException(422, f"invalid rules: {e}")
    total = await db.subscribers.count_documents(flt)
    sample = await db.subscribers.find(flt, {"_id": 0}) \
                                    .sort("created_at", -1) \
                                    .to_list(limit)
    return {"matched_count": total, "sample": sample, "sample_size": len(sample)}


@router.post("/marketing/segments/preview")
async def preview_segment_adhoc(body: SegmentIn,
                                  user: dict = Depends(_require_admin),
                                  tenant: dict = Depends(get_current_tenant),
                                  limit: int = Query(20, ge=1, le=200)):
    """Ad-hoc preview without saving — used by the segment builder UI
    to show live counts while the admin edits rules."""
    try:
        flt = compile_to_filter(tenant["id"], body.rules or {})
    except ValueError as e:
        raise HTTPException(422, f"invalid rules: {e}")
    total = await db.subscribers.count_documents(flt)
    sample = await db.subscribers.find(flt, {"_id": 0}) \
                                    .sort("created_at", -1) \
                                    .to_list(limit)
    return {"matched_count": total, "sample": sample, "sample_size": len(sample)}


# ═════════════════════════════════════════════════════════════════════
# Marketing settings (tenant-scoped)
# ═════════════════════════════════════════════════════════════════════

MARKETING_SETTINGS_DEFAULTS = {
    "require_double_optin": True,
    "revenue_attribution_days": 30,
}


@router.get("/marketing/settings")
async def get_marketing_settings(user: dict = Depends(_require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return {
        "tenant_id": tenant["id"],
        "require_double_optin": bool(
            (fresh or {}).get("require_double_optin",
                              MARKETING_SETTINGS_DEFAULTS["require_double_optin"])
        ),
        "revenue_attribution_days": int(
            (fresh or {}).get("revenue_attribution_days",
                              MARKETING_SETTINGS_DEFAULTS["revenue_attribution_days"])
        ),
    }


@router.put("/marketing/settings")
async def put_marketing_settings(body: MarketingSettingsIn,
                                   user: dict = Depends(_require_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    upd: Dict[str, Any] = {}
    if body.require_double_optin is not None:
        upd["require_double_optin"] = bool(body.require_double_optin)
    if body.revenue_attribution_days is not None:
        upd["revenue_attribution_days"] = int(body.revenue_attribution_days)
    if upd:
        upd["updated_at"] = now_iso()
        await db.tenants.update_one({"id": tenant["id"]}, {"$set": upd})
    return await get_marketing_settings(user=user, tenant=tenant)


# ═════════════════════════════════════════════════════════════════════
# Public signup-form + double-opt-in confirmation
# ═════════════════════════════════════════════════════════════════════

@router.post("/marketing/public/signup-form/{form_slug}/subscribe")
async def public_signup(form_slug: str, body: PublicSubscribeIn,
                          request: Request):
    """Public unauthenticated endpoint. Resolves the tenant from the
    form document, honors an optional honeypot field, then creates a
    subscribers row. If tenant-level ``require_double_optin=true`` and
    the form doesn't override, subscriber lands in
    ``status=pending_confirmation`` and a confirmation email is queued.
    Otherwise subscriber is created as ``status=subscribed``."""
    form = await db.forms.find_one({"slug": form_slug}, {"_id": 0})
    if not form:
        raise HTTPException(404, "form not found")
    if form.get("status") and form["status"] != "published":
        raise HTTPException(400, "form is not published")
    # Honeypot: if the caller filled the trap field (or the form declared
    # one and it came back non-empty in the values map), reject silently
    # with 200. Bots hitting this endpoint get a soft-success.
    honeypot_field = form.get("honeypot_field") or "hp_field"
    hp_val = (body.honeypot or "").strip()
    values = dict(body.values or {})
    if honeypot_field in values and str(values.get(honeypot_field) or "").strip():
        hp_val = str(values.get(honeypot_field))
    if hp_val:
        return {"ok": True, "status": "ignored"}
    values.pop(honeypot_field, None)

    tenant = await _resolve_public_tenant(request, form)
    if not tenant:
        raise HTTPException(500, "unable to resolve tenant")
    tenant_id = tenant["id"]

    email = (body.email or "").strip().lower() or None
    phone = (body.phone or "").strip() or None
    if not email and not phone:
        raise HTTPException(422, "email or phone is required")

    # Effective double-opt-in setting: tenant default unless form overrides.
    tenant_require = bool(tenant.get("require_double_optin",
                                       MARKETING_SETTINGS_DEFAULTS["require_double_optin"]))
    form_override = form.get("double_opt_in")
    require_confirm = tenant_require if form_override is None else bool(form_override)

    key: Dict[str, Any] = {"tenant_id": tenant_id}
    if email:
        key["email"] = email
    else:
        key["phone"] = phone
    existing = await db.subscribers.find_one(key, {"_id": 0})

    now = now_iso()
    if existing:
        # Already-subscribed row: refresh attributes, re-confirm if needed.
        merged_attrs = dict(existing.get("attributes") or {})
        merged_attrs.update(values)
        upd = {
            "first_name": body.first_name or existing.get("first_name") or "",
            "last_name": body.last_name or existing.get("last_name") or "",
            "attributes": merged_attrs,
            "updated_at": now,
        }
        # Re-subscribing a previously unsubscribed row: put back into
        # pending_confirmation (if DOI) or subscribed.
        if existing.get("status") == "unsubscribed":
            upd["status"] = "pending_confirmation" if require_confirm else "subscribed"
            if not require_confirm:
                upd["confirmed_at"] = now
                upd["consent_at"] = now
            upd["unsubscribed_at"] = None
        await db.subscribers.update_one(
            {"id": existing["id"]}, {"$set": upd})
        subscriber = await db.subscribers.find_one(
            {"id": existing["id"]}, {"_id": 0})
    else:
        status = "pending_confirmation" if require_confirm else "subscribed"
        subscriber = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "email": email,
            "phone": phone,
            "first_name": body.first_name or "",
            "last_name": body.last_name or "",
            "status": status,
            "source": "public_form",
            "customer_id": None,
            "tags": list(form.get("bound_tags") or []),
            "attributes": values,
            "consent_at": None if require_confirm else now,
            "confirmed_at": None if require_confirm else now,
            "unsubscribed_at": None,
            "confirmation_token": sign_confirmation(tenant_id, email) if email else None,
            "form_slug": form_slug,
            "created_at": now,
            "updated_at": now,
        }
        await db.subscribers.insert_one(subscriber)

    # If confirmed immediately (no DOI), attach to bound_list_ids.
    bound_list_ids = list(form.get("bound_list_ids") or [])
    if subscriber.get("status") == "subscribed" and bound_list_ids:
        for lid in bound_list_ids:
            await db.marketing_list_memberships.update_one(
                {"tenant_id": tenant_id, "list_id": lid,
                 "subscriber_id": subscriber["id"]},
                {"$setOnInsert": {"id": new_id(),
                                  "tenant_id": tenant_id,
                                  "list_id": lid,
                                  "subscriber_id": subscriber["id"],
                                  "added_at": now}},
                upsert=True,
            )

    # Confirmation email — best-effort, never blocks.
    email_status = None
    if subscriber.get("status") == "pending_confirmation" and email:
        try:
            r = await send_confirmation_email(
                tenant=tenant, subscriber=subscriber)
            email_status = r.get("status")
        except Exception as e:
            logger.warning(f"[marketing] confirmation email failed: {e}")
            email_status = "failed"

    return {
        "ok": True,
        "subscriber_id": subscriber["id"],
        "status": subscriber["status"],
        "require_confirm": bool(require_confirm),
        "confirmation_email_status": email_status,
        "redirect_url": form.get("redirect_url"),
    }


@router.post("/marketing/public/confirm")
async def public_confirm(body: PublicConfirmIn):
    """Public unauthenticated endpoint. Verifies the HMAC-signed
    confirmation token minted at signup time, then flips the subscriber
    to ``status=subscribed`` and applies bound list memberships from
    the originating form (if any)."""
    email = body.email.lower()
    if not verify_confirmation(body.tenant_id, email, body.token):
        raise HTTPException(403, "invalid or expired confirmation token")
    sub = await db.subscribers.find_one(
        {"tenant_id": body.tenant_id, "email": email}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "subscriber not found")
    now = now_iso()
    if sub.get("status") != "subscribed":
        await db.subscribers.update_one(
            {"id": sub["id"]},
            {"$set": {"status": "subscribed",
                      "confirmed_at": now,
                      "consent_at": sub.get("consent_at") or now,
                      "unsubscribed_at": None,
                      "updated_at": now}},
        )
    # Apply bound_list_ids from the originating form if we have it.
    form_slug = sub.get("form_slug")
    if form_slug:
        form = await db.forms.find_one(
            {"slug": form_slug, "tenant_id": body.tenant_id}, {"_id": 0})
        for lid in list((form or {}).get("bound_list_ids") or []):
            await db.marketing_list_memberships.update_one(
                {"tenant_id": body.tenant_id, "list_id": lid,
                 "subscriber_id": sub["id"]},
                {"$setOnInsert": {"id": new_id(),
                                  "tenant_id": body.tenant_id,
                                  "list_id": lid,
                                  "subscriber_id": sub["id"],
                                  "added_at": now}},
                upsert=True,
            )
    fresh = await db.subscribers.find_one(
        {"id": sub["id"]}, {"_id": 0})
    return {"ok": True, "subscriber": fresh}
