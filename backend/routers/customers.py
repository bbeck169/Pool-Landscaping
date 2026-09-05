# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Body
from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone, timedelta
import uuid

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import (
    CreateLoginRequest,
    CustomerBulkAction,
    CustomerIn,
    CustomerProfileUpdate,
)

router = APIRouter()


# ─── Response models for OpenAPI docs (Feb-2026 AE1 T4 fix) ────────────
# These document the visible fields on customer + list endpoints so
# generated clients / docs sites see a populated schema instead of
# ``"schema": {}``. Extra keys are allowed (``extra="allow"``) so
# existing UI callers reading dynamic legacy fields don't regress.

class CustomerListItem(BaseModel):
    """Row shape returned by ``GET /api/customers``."""
    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: Optional[str] = None
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None
    has_login: Optional[bool] = None
    customer_since: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    notes: Optional[str] = None
    # Feb-2026 MP2 UI addition — active property count for the row's
    # "N properties" chip. Zero when the customer has no properties.
    properties_count: int = 0
    # Multi-contact arrays (Feb-2026 customer detail additions).
    emails: Optional[List[Dict[str, Any]]] = None
    mobiles: Optional[List[Dict[str, Any]]] = None
    # Service notes cards (Pool / Landscape).
    service_notes: Optional[Dict[str, Any]] = None
    # VIP toggle + last portal login stamps (Feb-2026 Portal Access ship).
    is_vip: Optional[bool] = None
    last_portal_login_at: Optional[str] = None
    last_portal_login_ip: Optional[str] = None
    # Master billing (MP1 / MP1.5).
    master_billing_mode: Optional[str] = None
    master_billing_contact_email: Optional[str] = None
    master_billing_contact_phone: Optional[str] = None
    # Phase 12 · Feb 2026 — "Require card on file" toggle. Derived at
    # read-time from tenant default + per-customer override so tenant
    # flips propagate without a customer-doc write.
    require_card_on_file_override: Optional[bool] = None
    effective_require_card_on_file: Optional[bool] = None
    has_card_on_file: Optional[bool] = None
    saved_payment_methods_count: Optional[int] = None


def _compute_card_fields(customer: dict, tenant_default: bool) -> dict:
    """Phase 12 · Feb 2026 — Return the derived ``effective_*`` and
    ``has_card_on_file`` fields for a customer row. Never mutates
    ``customer`` — callers spread the result into their response dict."""
    override = customer.get("require_card_on_file_override")
    effective = (bool(override) if override is not None
                    else bool(tenant_default))
    pm_count = int(customer.get("saved_payment_methods_count") or 0)
    return {
        "require_card_on_file_override": override,
        "effective_require_card_on_file": effective,
        "has_card_on_file": pm_count > 0,
        "saved_payment_methods_count": pm_count,
    }


def _sync_customer_names(doc: dict) -> dict:
    """Phase 56.3.A — Bidirectional first/last/name sync.

    Callers may send:
      • `first_name` + `last_name`  → we recompose `name` from them.
      • `name` only (legacy)        → we split on the first whitespace and
                                       populate first/last.
      • all three                   → first/last win; `name` is rebuilt.
    Ensures the stored document always has a coherent triple so display
    code can prefer `{first_name} {last_name}` with `name` as fallback.
    Idempotent — safe to call on every write.
    """
    first = (doc.get("first_name") or "").strip()
    last = (doc.get("last_name") or "").strip()
    name = (doc.get("name") or "").strip()
    if first or last:
        doc["first_name"] = first
        doc["last_name"] = last
        composed = " ".join(p for p in (first, last) if p)
        doc["name"] = composed or name
    elif name:
        parts = name.split(None, 1)
        doc["first_name"] = parts[0] if parts else ""
        doc["last_name"] = parts[1] if len(parts) > 1 else ""
        doc["name"] = name
    return doc


def _apply_multi_contact(doc: dict) -> dict:
    """Feb-2026 Customer Detail Additions — normalize the ``mobiles`` /
    ``emails`` arrays, enforce caps + primary invariants, and sync the
    legacy ``phone`` / ``email`` scalars back to the primary entries.
    Idempotent — safe to call on every write. See
    :mod:`services.customer_multi_contact` for the full rules."""
    from services.customer_multi_contact import apply_multi_contact
    return apply_multi_contact(doc)


async def _k31_audit_phone_collision(doc: dict, tenant_id: str,
                                        current_id: Optional[str] = None) -> None:
    """K31 · Feb-2026 — post-write drift guard. If the customer being
    written shares a phone (scalar OR any ``mobiles[].number_e164``)
    with any OTHER customer in the same tenant, insert a non-blocking
    ``audit_events`` row with ``event_type="customer_phone_collision"``
    listing the sharing customer ids.

    Non-blocking: any exception is swallowed so the customer write
    never fails on this defensive check.  Grew out of the K31 SMS
    misrouting RCA — a shared phone across two customer records will
    silently deliver a completion SMS to the wrong recipient.  Surfacing
    the collision proactively means ops sees the drift in the
    communication timeline the moment it lands.
    """
    try:
        phones: set[str] = set()
        p = (doc.get("phone") or "").strip()
        if p:
            phones.add(p)
        for m in (doc.get("mobiles") or []):
            n = (m.get("number_e164") or "").strip()
            if n:
                phones.add(n)
        if not phones:
            return
        q_or = [{"phone": {"$in": list(phones)}},
                {"mobiles.number_e164": {"$in": list(phones)}}]
        q: Dict[str, Any] = {"tenant_id": tenant_id, "$or": q_or}
        if current_id:
            q["id"] = {"$ne": current_id}
        collisions: List[Dict[str, Any]] = []
        async for other in db.customers.find(
            q, {"_id": 0, "id": 1, "name": 1, "phone": 1},
        ).limit(10):
            collisions.append(other)
        if not collisions:
            return
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "customer_phone_collision",
            "tenant_id": tenant_id,
            "timestamp": now_iso(),
            "payload": {
                "customer_id": current_id or doc.get("id"),
                "customer_name": doc.get("name"),
                "phones": sorted(phones),
                "colliding_customer_ids": [c.get("id") for c in collisions],
                "colliding_customer_names": [c.get("name") for c in collisions],
            },
        })
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[k31] phone collision audit failed cid=%s: %s",
                        current_id or doc.get("id"), _exc)


def _apply_vip_stamp(doc: dict, existing: Optional[dict] = None) -> dict:
    """Auto-stamp ``vip_since`` when ``is_vip`` transitions to True;
    clear it when transitioning to False. Preserves ``vip_note`` across
    the toggle so admins can see historical notes even after un-VIP."""
    was_vip = bool((existing or {}).get("is_vip"))
    now_vip = bool(doc.get("is_vip"))
    if now_vip and not was_vip:
        doc["vip_since"] = doc.get("vip_since") or now_iso()
    elif not now_vip and was_vip:
        doc["vip_since"] = None
    return doc


async def migrate_customer_names_split(tenant_filter: Optional[dict] = None) -> int:
    """Phase 56.3.A — one-shot idempotent backfill. Populates
    `first_name` / `last_name` on any customer doc that has `name` but
    no first/last yet. Splits on the first whitespace. Safe to run on
    every startup (skipped for docs already migrated). Returns the
    number of docs actually mutated."""
    q = tenant_filter or {}
    q = {
        **q,
        "$or": [
            {"first_name": {"$exists": False}},
            {"first_name": ""},
            {"first_name": None},
        ],
        "name": {"$exists": True, "$ne": ""},
    }
    n = 0
    async for doc in db.customers.find(q, {"_id": 0, "id": 1, "name": 1, "tenant_id": 1}):
        parts = str(doc.get("name") or "").split(None, 1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
        if not first and not last:
            continue
        await db.customers.update_one(
            {"id": doc["id"], "tenant_id": doc.get("tenant_id")},
            {"$set": {"first_name": first, "last_name": last}},
        )
        n += 1
    if n:
        logger.info(f"[phase56.3.A] customer name-split migration touched {n} doc(s)")
    return n


# ----------------------- Customers -----------------------
@router.get("/me")
async def get_my_profile(user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    doc = await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Profile not found")
    return doc


@router.put("/me")
async def update_my_profile(body: CustomerProfileUpdate,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if update:
        await db.customers.update_one(
            {"id": user["customer_id"], "tenant_id": tenant["id"]},
            {"$set": update},
        )
        # keep the login user's display name/avatar in sync
        user_patch = {k: update[k] for k in ("name", "avatar") if k in update}
        if user_patch:
            await db.users.update_one(
                {"id": user["id"], "tenant_id": tenant["id"]},
                {"$set": user_patch},
            )
    return await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )


class CustomerListCount(BaseModel):
    """Compact ``count_only=true`` response for ``GET /api/customers``."""
    count: int


# ─────────────────────────────────────────────────────────────────
# K49 · Feb-2026 — Customers list Last-Name-A→Z aggregation.
# ─────────────────────────────────────────────────────────────────
def _k49_lastname_pipeline(
    match: dict,
    *,
    skip: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """Build the ``$last_name ASC`` aggregation pipeline for the K49
    Customers-list sort. Handles:

    * Primary key: ``last_name`` when non-empty.
    * Fallback: substring after the LAST space in ``name``
      (``Jane Doe`` → ``Doe``, ``Cher`` → ``Cher``).
    * Nulls-last: rows with no derivable last name (both fields
      empty / missing) land at the end.
    * Compound tie-breaker: ``first_name`` ASC → ``_id`` ASC.

    Case-insensitive: normalises the sort key to lower-case so
    ``Adams`` and ``adams`` collate together.
    """
    # ``$split`` on a missing / non-string field would error; the
    # ``$ifNull`` + ``$toLower`` chain coerces every doc into a
    # non-null string first.
    stages: List[dict] = [
        {"$match": match},
        {"$addFields": {
            "_k49_last_name_norm": {"$toLower": {
                "$ifNull": ["$last_name", ""],
            }},
            "_k49_name_norm": {"$toLower": {
                "$ifNull": ["$name", ""],
            }},
        }},
        {"$addFields": {
            "_k49_last_from_name": {
                "$let": {
                    "vars": {
                        "parts": {"$split": [
                            {"$trim": {"input": "$_k49_name_norm"}},
                            " ",
                        ]},
                    },
                    "in": {"$cond": [
                        {"$gt": [{"$size": "$$parts"}, 0]},
                        {"$arrayElemAt": [
                            "$$parts",
                            {"$subtract": [
                                {"$size": "$$parts"}, 1,
                            ]},
                        ]},
                        "",
                    ]},
                },
            },
        }},
        {"$addFields": {
            "_k49_sort_key": {"$cond": [
                {"$gt": [
                    {"$strLenCP": "$_k49_last_name_norm"}, 0,
                ]},
                "$_k49_last_name_norm",
                "$_k49_last_from_name",
            ]},
        }},
        {"$addFields": {
            # 1 = has a real key → sort BEFORE the empty bucket
            # (nulls-last).
            "_k49_has_key": {"$cond": [
                {"$gt": [
                    {"$strLenCP": "$_k49_sort_key"}, 0,
                ]},
                1,
                0,
            ]},
        }},
        {"$sort": {
            "_k49_has_key": -1,
            "_k49_sort_key": 1,
            "first_name": 1,
            "_id": 1,
        }},
    ]
    if skip:
        stages.append({"$skip": int(skip)})
    if limit is not None:
        stages.append({"$limit": int(limit)})
    # Strip the synthetic sort keys + the raw ``_id`` before the
    # doc leaves the DB layer so downstream ``clean_customer_doc``
    # sees the same shape it does for the ``find()`` path.
    stages.append({"$project": {
        "_id": 0,
        "_k49_last_name_norm": 0,
        "_k49_name_norm": 0,
        "_k49_last_from_name": 0,
        "_k49_sort_key": 0,
        "_k49_has_key": 0,
    }})
    return stages


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · P35 — pagination response shape (opt-in).
# The endpoint keeps returning a bare ``List[CustomerListItem]``
# when neither ``page`` nor ``page_size`` is supplied so the 20+
# existing bare-array callers (jobs, comms, quotes, estimator,
# workstream, warranties, invoices, reviews, tracking, D2D, AI
# tools, finance) stay untouched. When either query param is
# present, the endpoint returns the paginated envelope below.
# ─────────────────────────────────────────────────────────────────
class CustomerListPage(BaseModel):
    items: List[CustomerListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/customers",
    response_model=Union[List[CustomerListItem], CustomerListCount,
                            CustomerListPage],
    summary="List customers",
    responses={200: {"description": (
        "Customer rows scoped to the caller's tenant. Each row includes "
        "the standard customer fields plus a Feb-2026 MP2 UI addition:\n\n"
        "- ``properties_count`` (int) — number of active properties for "
        "the customer. Zero when none exist. Used by the customers list "
        "to render a `N properties` chip when ≥2.\n\n"
        "When ``count_only=true``, the response is a compact "
        "``{\"count\": int}`` object instead of the row array.\n\n"
        "**Feb-2026 · P35 pagination (opt-in).** When either ``page`` "
        "or ``page_size`` is supplied, the response becomes a paginated "
        "envelope: ``{items, total, page, page_size, total_pages}``. "
        "Callers that do not pass either param continue to receive the "
        "legacy bare-array response verbatim."
    )}})
async def list_customers(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    search: Optional[str] = None,
    tag: Optional[str] = None,
    # Feb-2026 · P46 — multi-tag AND filter (spec: repeatable/CSV).
    # When BOTH plural and singular are supplied, plural takes
    # precedence (see composition below). Backwards-compat is
    # preserved for the 20+ existing single-tag callers.
    tags: Optional[List[str]] = Query(None),
    city: Optional[str] = None,
    waitlisted: Optional[bool] = None,
    unscheduled: Optional[bool] = None,
    is_active: Optional[bool] = None,
    missing_card: Optional[bool] = None,
    # Feb-2026 · P43 — data-quality filters. Both compose as AND when
    # active together. Whitespace-only fields are treated as missing.
    missing_email: Optional[bool] = False,
    missing_phone: Optional[bool] = False,
    portal_status: Optional[str] = Query(
        None,
        description=(
            "Phase G4a · Feb-2026 — filter by customer-portal "
            "activation state. Values: ``all`` (or omit) = no filter; "
            "``activated`` = customer has an active portal login "
            "(``customers.has_login == True`` — denorm stamped when "
            "``POST /customers/{cid}/portal-invite`` provisions the "
            "``users`` doc); ``not_activated`` = no portal login "
            "(missing or false). Composes as intersection with "
            "``is_active`` / ``is_muted`` / search / tag filters."
        ),
    ),
    is_muted: Optional[bool] = Query(None, description="Feb-2026 · P28 admin/super_admin only — filter to muted (true) or non-muted (false); absent = no filter"),
    count_only: bool = False,
    include_deleted: bool = Query(False, description="Feb-2026 · P25 super_admin only — include soft-deleted customers"),
    include_merged: bool = Query(False, description="Feb-2026 · Customer Merge — include records whose ``merged_into`` is set. Default false — merged rows are hidden so admins don't see stale duplicates."),
    page: Optional[int] = Query(None, description="Feb-2026 · P35 — 1-indexed page number. Presence of this OR page_size flips the response into a paginated envelope."),
    page_size: Optional[int] = Query(None, description="Feb-2026 · P35 — page size (1..500). Presence of this OR page flips the response into a paginated envelope."),
    sort: Optional[str] = Query(
        "created_desc",
        description=(
            "Feb-2026 · Customers list sort order. Supported values: "
            "``created_desc`` (default — newest → oldest), "
            "``created_asc`` (oldest → newest), ``name_asc`` "
            "(alphabetical A → Z), ``name_desc`` (alphabetical Z → A), "
            "``last_name_asc`` (K49 · Feb-2026 — last name A → Z with "
            "``first_name`` tie-breaker; docs missing ``last_name`` "
            "fall back to the substring after the LAST space of "
            "``name`` (``Jane Doe`` → ``Doe``, ``Cher`` → ``Cher``); "
            "rows with no derivable last name sort LAST). "
            "Unknown values fall back to ``created_desc``. When the "
            "sort is by creation time and a legacy doc lacks "
            "``created_at``, the compound sort falls back to the "
            "Mongo-generated ``_id`` (which encodes creation time in "
            "its ObjectId prefix) so those rows still land in the "
            "correct chronological bucket."
        ),
    ),
):
    # RBAC: only staff (admin/manager/technician/super_admin) may list
    # customer records. Customers use /me.
    # Feb-2026 · P46 — manager was previously omitted from this allow-
    # list even though downstream checks (missing_card, is_muted) treat
    # manager as allowed. That inconsistency shipped as a 403 for
    # every manager list request. Fix: fold manager in.
    if user.get("role") not in ("admin", "manager", "technician",
                                     "super_admin"):
        raise HTTPException(403, "Not allowed")
    # Phase 12 · Feb 2026 — the ``missing_card`` filter is admin/manager
    # only. Technicians see the plain list.
    if missing_card and user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Not allowed")
    # Feb-2026 · P28 — the muted saved view is admin/manager/super_admin
    # only. Technicians never see the Muted tab.
    if is_muted is not None and user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Not allowed")
    # Feb-2026 · P25 — soft-delete read-filter. Mirror the P4/P4.5 job
    # list pattern: default filters out ``deleted_at`` (both null and
    # missing key); ``?include_deleted=true`` is admin-tier only (admin
    # / super_admin / owner — widened from super_admin-only by the
    # Customer Delete UX overhaul so the admin restore path can list
    # soft-deleted rows). P11b anonymized customers also carry
    # ``deleted_at`` so they're hidden too. Lower roles passing
    # ``include_deleted=true`` are rejected rather than silently
    # ignored, so the UI catches accidental use.
    q: dict = {"tenant_id": tenant["id"]}
    role_lc = (user.get("role") or "").lower()
    is_admin_tier = role_lc in ("admin", "super_admin", "owner")
    if include_deleted and not is_admin_tier:
        raise HTTPException(
            403,
            "Only admin, super_admin, or owner can include soft-deleted customers",
        )
    if not include_deleted:
        from utils import not_deleted_filter as _nd_cust
        q.update(_nd_cust())
    # Feb-2026 · Customer Merge — hide records that have been merged
    # into a primary. Default off so the customers list never shows
    # stale duplicates. ``include_merged=true`` surfaces them (used
    # by the Merge Audit view + reversal tooling once shipped).
    if not include_merged:
        q["$and"] = q.get("$and", []) + [{
            "$or": [{"merged_into": None},
                     {"merged_into": {"$exists": False}}],
        }]
    if search:
        rx = {"$regex": search, "$options": "i"}
        q["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}, {"address": rx}]
    if tag:
        q["tags"] = tag
    # Feb-2026 · P46 — multi-tag AND filter. When both singular and
    # plural are supplied, plural wins (spec). Empty / whitespace-only
    # values are stripped so a URL like ``?tags=&tags=Pool`` behaves
    # correctly.
    tags_clean = [t.strip() for t in (tags or []) if (t or "").strip()]
    if tags_clean:
        q["tags"] = {"$all": tags_clean}
    # Feb-2026 · P46 — case-insensitive city match across the three
    # address surfaces (P41-imported structured columns + legacy free-
    # form ``address``). ``re.escape`` neutralizes user-typed regex
    # metacharacters so a period or asterisk in a city name is safe.
    if city and city.strip():
        import re as _p46_re
        rx = {"$regex": _p46_re.escape(city.strip()), "$options": "i"}
        q["$and"] = q.get("$and", []) + [{
            "$or": [{"service_city": rx},
                        {"billing_city": rx},
                        {"address": rx}],
        }]
    if waitlisted is not None:
        q["waitlisted"] = bool(waitlisted)
    # Phase 56.2 — active/inactive cohort filter. Rows created before the
    # `is_active` field existed default to active per Phase 34f semantics,
    # so a `True` filter must match {is_active: True} OR field-absent.
    #
    # Feb-2026 · P32 — Muted-tab exclusivity. Muted rows are stamped
    # ``is_active=False`` by the P27 mute path, so without an explicit
    # ``is_muted != true`` guard they leak into the Inactive tab (and
    # its count). Fix: the ``is_active`` cohort filters MUST also
    # exclude muted rows. Muted lives in its own tab; Active + Inactive
    # cover the non-muted world.
    _NOT_MUTED = {"$or": [{"is_muted": {"$ne": True}},
                             {"is_muted": {"$exists": False}}]}
    if is_active is True:
        q["$and"] = q.get("$and", []) + [
            {"$or": [{"is_active": True}, {"is_active": {"$exists": False}}]},
            _NOT_MUTED,
        ]
    elif is_active is False:
        q["$and"] = q.get("$and", []) + [
            {"is_active": False},
            _NOT_MUTED,
        ]
    # Feb-2026 · P28 — muted saved view. Absent = no filter. True =
    # only muted rows. False = non-muted (both explicit-False and
    # legacy field-missing, since P27 only stamps ``is_muted`` on
    # mute — non-muted rows have no such field).
    if is_muted is True:
        q["is_muted"] = True
    elif is_muted is False:
        q["$and"] = q.get("$and", []) + [
            {"$or": [{"is_muted": {"$ne": True}}, {"is_muted": {"$exists": False}}]}
        ]
    # Feb-2026 · P43 — "No email" / "No phone number" data-quality
    # chips. Null, missing key, empty string, and whitespace-only all
    # count as missing. Predicates compose into ``$and`` so they
    # honor both the list branch AND ``count_only=true`` (P40
    # unified-predicate contract).
    if missing_email:
        q["$and"] = q.get("$and", []) + [{
            "$or": [
                {"email": None},
                {"email": ""},
                {"email": {"$exists": False}},
                {"email": {"$regex": r"^\s*$"}},
            ],
        }]
    if missing_phone:
        q["$and"] = q.get("$and", []) + [{
            "$or": [
                {"phone": None},
                {"phone": ""},
                {"phone": {"$exists": False}},
                {"phone": {"$regex": r"^\s*$"}},
            ],
        }]
    # Phase G4a · Feb-2026 — Portal-activation cohort filter. Uses the
    # ``customers.has_login`` denorm (set to True on
    # ``portal-invite``, False on ``portal-revoke``) for O(index)
    # perf. ``activated`` = denorm True; ``not_activated`` = missing,
    # false, or null. Unknown values → 400 so typos surface early.
    #
    # NB: ``isinstance(portal_status, str)`` — direct callers (e.g.
    # tests that bypass FastAPI's DI) leave FastAPI ``Query(None,
    # ...)`` sentinel as the raw default, which is neither ``None``
    # nor a string. Checking for str-ness cleanly filters both the
    # HTTP-omit path AND the direct-call default path.
    if isinstance(portal_status, str) and portal_status.strip():
        _ps = portal_status.strip().lower()
        if _ps not in ("all", "activated", "not_activated"):
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "invalid_portal_status",
                    "message": (
                        "portal_status must be one of: all, activated, "
                        "not_activated"
                    ),
                    "portal_status": portal_status,
                },
            )
        if _ps == "activated":
            q["$and"] = q.get("$and", []) + [{"has_login": True}]
        elif _ps == "not_activated":
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"has_login": {"$ne": True}},
                    {"has_login": {"$exists": False}},
                ],
            }]
        # ``all`` → intentionally no-op.
    if count_only:
        return {"count": await db.customers.count_documents(q)}

    # ─────────────────────────────────────────────────────────────
    # Feb-2026 · P35 — pagination. Opt-in via ``page`` or ``page_size``.
    # Validation is manual so we can raise 400 (rather than FastAPI's
    # default 422) with a clear, machine-readable ``detail`` code.
    # ─────────────────────────────────────────────────────────────
    _paginated = (page is not None) or (page_size is not None)
    if _paginated:
        if page is None:
            page = 1
        if page_size is None:
            page_size = 100
        if page < 1:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_page",
                          "message": "page must be >= 1",
                          "page": page},
            )
        if page_size < 1 or page_size > 500:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_page_size",
                          "message": "page_size must be between 1 and 500",
                          "page_size": page_size},
            )

    # The ``unscheduled`` and ``missing_card`` filters run in Python
    # AFTER the Mongo query (see below), so paginating at the DB layer
    # would produce wrong totals when either is set. We branch: the
    # common case (no Python post-filter) uses Mongo-side skip/limit
    # + count_documents (efficient); the rarer case pulls the full
    # filtered set and slices in Python (correct).
    _needs_python_postfilter = bool(unscheduled) or bool(missing_card)

    # Feb 2026 · Resolve the caller's sort preference into a Mongo
    # sort spec. ``created_desc`` (default) is the "newest first" UX
    # the Customers list surfaces via its Sort dropdown. Unknown /
    # missing values fall back to the default rather than 400 so a
    # stale bookmark / rolled-back client never breaks the list.
    # Compound sort trails ``_id`` so legacy docs without
    # ``created_at`` still order by ObjectId creation time — same
    # tiebreaker the pagination path relies on for stable slices.
    _SORT_MAP = {
        "created_desc": [("created_at", -1), ("_id", -1)],
        "created_asc": [("created_at", 1), ("_id", 1)],
        "name_asc": [("name", 1), ("_id", 1)],
        "name_desc": [("name", -1), ("_id", -1)],
        # K49 · Feb-2026 — kept in the map for parity with the fast
        # path enum guard even though ``last_name_asc`` routes
        # through the dedicated aggregation branch below (needed for
        # the last-space fallback + nulls-last ordering that plain
        # ``$sort`` can't express).
        "last_name_asc": [("last_name", 1), ("first_name", 1),
                            ("_id", 1)],
    }
    _sort_key = sort or ""
    _sort_spec = _SORT_MAP.get(_sort_key, _SORT_MAP["created_desc"])

    # K49 · Feb-2026 — dedicated pipeline for the Last-Name-A→Z sort.
    # Mongo's plain ``$sort`` puts nulls-first on ASC; we want
    # nulls-last per the K49 spec. We also need the last-space
    # fallback for legacy docs whose backfill hasn't run yet (they
    # have ``name`` but no ``last_name``). Both requirements collapse
    # into a single aggregation stage.
    _use_lastname_pipeline = _sort_key == "last_name_asc"

    if _paginated and not _needs_python_postfilter:
        # Fast path — DB-side pagination.
        total = await db.customers.count_documents(q)
        skip = (page - 1) * page_size
        if _use_lastname_pipeline:
            docs = await db.customers.aggregate(
                _k49_lastname_pipeline(q, skip=skip, limit=page_size),
            ).to_list(page_size)
        else:
            docs = await (db.customers.find(q, {"_id": 0})
                              .sort(_sort_spec)
                              .skip(skip).limit(page_size)
                              .to_list(page_size))
    elif _paginated and _needs_python_postfilter:
        # Correct-but-slower path — Python-side slice after post-filters.
        # Uncapped fetch so ``total`` reflects the true filtered count
        # for tenants past the legacy 2000-row ceiling. The skip/limit
        # is applied AFTER unscheduled / missing_card below.
        if _use_lastname_pipeline:
            docs = await db.customers.aggregate(
                _k49_lastname_pipeline(q),
            ).to_list(length=None)
        else:
            docs = await (db.customers.find(q, {"_id": 0})
                              .sort(_sort_spec)
                              .to_list(length=None))
    else:
        # Legacy path — no pagination requested. Keep the 2000-row
        # ceiling to preserve exact backwards-compat with all bare-array
        # callers (they've been living with this cap since Phase 34f).
        if _use_lastname_pipeline:
            docs = await db.customers.aggregate(
                _k49_lastname_pipeline(q, limit=2000),
            ).to_list(2000)
        else:
            docs = await db.customers.find(q, {"_id": 0}).sort(_sort_spec).to_list(2000)

    # Feb-2026 · P0 hotfix — legacy prod docs occasionally store BSON
    # ``datetime`` values in fields declared as ``Optional[str]`` on
    # ``CustomerListItem`` (``created_at`` / ``updated_at`` /
    # ``last_portal_login_at`` / ``customer_since``). Pydantic v2's
    # union-discriminator on the response_model can't coerce a bare
    # datetime into ``str`` and 500s the whole list. Coerce here so
    # the response validates cleanly regardless of what shape the
    # underlying Mongo doc has. Idempotent — string values pass
    # through, ``None`` stays ``None``.
    from datetime import datetime as _dt_hotfix
    for _d in docs:
        for _k, _v in list(_d.items()):
            if isinstance(_v, _dt_hotfix):
                _d[_k] = _v.isoformat()
    # If unscheduled=true, filter out customers who have any non-completed/cancelled job.
    if unscheduled:
        from utils import not_deleted_filter as _nd
        scheduled_ids = set(
            [d["customer_id"] async for d in db.jobs.find(
                {"tenant_id": tenant["id"], "status": {"$nin": ["completed", "cancelled"]}, **_nd()},
                {"customer_id": 1, "_id": 0},
            )]
        )
        docs = [d for d in docs if d["id"] not in scheduled_ids]
    # Feb-2026 MP2 UI — augment each customer row with a
    # ``properties_count`` (active properties only) so the list can
    # render a chip without an N+1 fetch. Batched aggregation keeps
    # this cheap for tenants with thousands of customers.
    if docs:
        cust_ids = [d["id"] for d in docs]
        try:
            pipeline = [
                {"$match": {"tenant_id": tenant["id"],
                              "customer_id": {"$in": cust_ids},
                              "active": {"$ne": False}}},
                {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}},
            ]
            counts = {row["_id"]: int(row.get("n") or 0)
                        async for row in db.properties.aggregate(pipeline)}
        except Exception:
            counts = {}
        for d in docs:
            d["properties_count"] = counts.get(d["id"], 0)

    # ─────────────────────────────────────────────────────────────
    # Feb-2026 · P45 — hydrate ``next_scheduled_at`` (earliest upcoming
    # job's ``scheduled_date``) per row via a single batched aggregate.
    # Consumed by the customers-list "Next visit" column. Rules:
    #   • status ∈ {"pending", "scheduled"} — inclusion whitelist so
    #     future terminal variants (cancelled, canceled, no_show,
    #     missed, skipped, could_not_service, completed) can't leak in.
    #   • scheduled_date ≥ today's UTC date at 00:00Z (inclusive of
    #     today).
    #   • soft-deleted jobs excluded via ``not_deleted_filter()``.
    #   • tenant-scoped.
    # ISO strings sort lexicographically for both full-ISO
    # ("2026-08-23T09:00:00+00:00") and date-only ("2026-09-01")
    # shapes because both lead with Y-M-D, so ``$sort`` +
    # ``$first`` returns the correct earliest either way.
    # NOT applied on the ``count_only=true`` branch (returned above).
    # ─────────────────────────────────────────────────────────────
    if docs:
        from datetime import datetime as _p45_dt, timezone as _p45_tz
        from utils import not_deleted_filter as _p45_nd
        today_utc_iso = _p45_dt.now(_p45_tz.utc).strftime("%Y-%m-%d")
        try:
            p45_pipeline = [
                {"$match": {
                    "tenant_id": tenant["id"],
                    "customer_id": {"$in": [d["id"] for d in docs]},
                    "status": {"$in": ["pending", "scheduled"]},
                    "scheduled_date": {"$gte": today_utc_iso},
                    **_p45_nd(),
                }},
                {"$sort": {"scheduled_date": 1}},
                {"$group": {
                    "_id": "$customer_id",
                    "next_scheduled_at": {"$first": "$scheduled_date"},
                }},
            ]
            next_map = {
                row["_id"]: row.get("next_scheduled_at")
                async for row in db.jobs.aggregate(p45_pipeline)
            }
        except Exception as _p45_exc:  # noqa: BLE001
            logger.warning("[p45] next_scheduled hydrate failed: %s",
                              _p45_exc)
            next_map = {}
        for d in docs:
            d["next_scheduled_at"] = next_map.get(d["id"])

    # Phase 12 · Feb 2026 — augment each row with the derived card fields.
    tenant_default_require = bool(tenant.get("require_card_on_file_default", True))
    for d in docs:
        d.update(_compute_card_fields(d, tenant_default_require))
        # Phase 12B · Feb 2026 — techs must never see Stripe identifiers.
        if user.get("role") == "technician":
            d.pop("stripe_customer_id", None)
            d.pop("stripe_default_payment_method_id", None)

    # Phase 12 · Feb 2026 — apply missing_card filter AFTER derived
    # fields are computed (server-authoritative — the filter never
    # trusts client-side reasoning about "effective").
    if missing_card:
        docs = [d for d in docs
                if d.get("effective_require_card_on_file")
                and not d.get("has_card_on_file")]

    # Feb-2026 · P35 — pagination response assembly. The paginated
    # envelope is only produced when the caller opted in via the
    # ``page`` / ``page_size`` query params; every other caller gets
    # the legacy bare-array response verbatim.
    if _paginated:
        if _needs_python_postfilter:
            # Total reflects the count AFTER unscheduled/missing_card
            # post-filters (i.e. the count the pager should paginate).
            total = len(docs)
            skip = (page - 1) * page_size
            docs = docs[skip: skip + page_size]
        # else: ``total`` was already computed via count_documents
        # above; ``docs`` was already sliced by skip/limit at the DB.
        _total_pages = 0 if total == 0 else (
            (total + page_size - 1) // page_size)
        return {
            "items": docs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": _total_pages,
        }
    return docs


@router.post("/customers/bulk")
async def customers_bulk(body: CustomerBulkAction,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Bulk-update or bulk-delete a selection of customers (tenant-scoped)."""
    if not body.ids:
        return {"ok": True, "updated": 0}
    q = {"id": {"$in": body.ids}, "tenant_id": tenant["id"]}
    if body.action == "delete":
        # Feb-2026 · Customer Delete UX overhaul — the legacy
        # ``POST /customers/bulk`` action=delete path is a HARD
        # ``delete_many`` with NO audit trail and NO locked-check.
        # Frontends have already migrated to the soft-delete
        # ``POST /customers/bulk-delete`` endpoint in ``bulk_crm.py``
        # (audit-logged, locked-checked). This path stays working
        # for one release so any lingering caller doesn't 404, but
        # emits a structured WARN so ops can trace and cutover, and
        # advertises the retirement date in the response.
        logger.warning(
            "customers.bulk_delete.deprecated actor=%s email=%s "
            "called=%d deprecated_until=2026-05-01 "
            "use_instead=POST /customers/bulk-delete",
            user.get("id"), user.get("email"), len(body.ids),
        )
        # Feb-2026 · Phase F3 — even the deprecated path must NOT
        # create orphan-customer refs. Block if ANY selected id is
        # referenced by an active job.
        referencing_count = await db.jobs.count_documents({
            "customer_id": {"$in": body.ids},
            "tenant_id": tenant["id"],
            "status": {"$nin": ["deleted"]},
            "$or": [{"deleted_at": None},
                    {"deleted_at": {"$exists": False}}],
        })
        if referencing_count > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "has_referencing_jobs",
                    "message": (
                        f"{referencing_count} active job(s) reference "
                        "one or more of the selected customers — "
                        "soft-delete or reassign those jobs first."
                    ),
                    "job_count": referencing_count,
                    "resolution": (
                        "soft-delete or reassign the affected jobs first"
                    ),
                },
            )
        res = await db.customers.delete_many(q)
        return {
            "ok": True,
            "deleted": res.deleted_count,
            "deprecated": True,
            "deprecated_until": "2026-05-01",
            "use_instead": "POST /customers/bulk-delete (soft-delete + audit)",
        }
    if body.action in ("add_tag", "remove_tag"):
        if not body.tag:
            raise HTTPException(400, "tag is required")
        op = "$addToSet" if body.action == "add_tag" else "$pull"
        res = await db.customers.update_many(q, {op: {"tags": body.tag}})
        return {"ok": True, "updated": res.modified_count}
    if body.action in ("add_waitlist", "remove_waitlist"):
        res = await db.customers.update_many(
            q, {"$set": {"waitlisted": body.action == "add_waitlist"}}
        )
        return {"ok": True, "updated": res.modified_count}
    raise HTTPException(400, f"Unknown action: {body.action}")


# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · Bulk status change (Customers list floating action bar).
# Small, generic-shaped endpoint that today only permits
# ``target_status == "inactive"`` — the enum-widening is a future
# concern and is guarded by an explicit 400.
# ─────────────────────────────────────────────────────────────────────
class CustomerBulkStatusIn(BaseModel):
    customer_ids: List[str]
    target_status: str  # today only "inactive" is accepted; see TODO.


# Roles allowed to bulk-change customer status. Tighter than
# ``require_admin`` (which permits ``owner``) — dispatch says only
# super_admin / admin / manager can drive this. ``owner`` is
# excluded on purpose so the endpoint's blast radius matches the
# ops org chart.
_BULK_STATUS_ROLES = {"super_admin", "admin", "manager"}
_BULK_STATUS_MAX_IDS = 500


@router.patch("/customers/bulk-status")
async def customers_bulk_status(body: CustomerBulkStatusIn,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Bulk-mark a selection of customers as inactive.

    Idempotent: setting ``inactive`` on customers that are already
    inactive is a no-op — the response reports ``matched`` vs
    ``modified`` so the UI can show the right toast without erroring.
    Tenant-scoped by construction (every query includes
    ``tenant_id``). Homeworks-imported customers retain their
    ``imported_from`` / ``original_id`` fields — only ``is_active``
    + ``status`` + ``updated_at`` change here.
    """
    role = (user or {}).get("role")
    if role not in _BULK_STATUS_ROLES:
        raise HTTPException(403, "bulk_status_change_requires_admin_or_manager")

    ids = list(body.customer_ids or [])
    if not ids:
        return {"matched": 0, "modified": 0, "requested": 0}
    if len(ids) > _BULK_STATUS_MAX_IDS:
        raise HTTPException(
            400,
            f"too_many_ids: max_{_BULK_STATUS_MAX_IDS}_per_request",
        )

    # TODO(Feb-2026 · Phase 34+): widen this to accept any customer
    # status enum value once the product surface has a UI for
    # transitions other than "→ inactive" (e.g. reactivate, mark VIP).
    # Keep the 400 as-is until then so we don't ship a footgun.
    if body.target_status != "inactive":
        raise HTTPException(
            400,
            "unsupported_target_status: only 'inactive' is permitted in this release",
        )

    now = now_iso()
    # Feb-2026 · Route through the central helper so the Active/
    # Inactive system tags stay in sync with the status flip.
    from routers.customer_tags import apply_customer_status
    result = await apply_customer_status(
        tenant_id=tenant["id"],
        customer_ids=ids,
        target_status="inactive",
        actor_id=(user or {}).get("id"),
    )
    matched_count = result["matched"]
    modified_count = result["modified"]

    # Simulate the old `res` shape so the audit-log block below is
    # untouched.
    class _R:
        pass
    res = _R()
    res.matched_count = matched_count
    res.modified_count = modified_count

    # One audit-log entry per bulk operation (not per customer).
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": "bulk_status_change",
            "target_status": "inactive",
            "count": int(matched_count),
            "requested_count": len(ids),
            "modified_count": int(res.modified_count),
            "actor_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "actor_role": role,
            # Log only the first 100 ids to keep the doc bounded even
            # on 500-id batches (5x compression at the cap).
            "customer_ids": ids[:100],
            "customer_ids_truncated": len(ids) > 100,
            "created_at": now,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bulk_status] audit insert failed: %s", exc)

    return {
        "matched": int(matched_count),
        "modified": int(res.modified_count),
        "requested": len(ids),
    }


@router.post("/customers")
async def create_customer(body: CustomerIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    # Feb-2026 · P42 — never set ``customer_since`` at create time.
    # Only the lifecycle helper is allowed to write this field.
    doc.pop("customer_since", None)
    _sync_customer_names(doc)
    _apply_multi_contact(doc)
    _apply_vip_stamp(doc, existing=None)
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "created_at": now_iso()})
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    # K31 · Feb-2026 — flag any phone collision with another customer
    # in the same tenant.  Non-blocking.
    await _k31_audit_phone_collision(doc, tenant["id"], current_id=doc.get("id"))
    # Feb-2026 · P33 — auto-persist any novel tag strings on the
    # newly-created customer into the tenant catalog. Best-effort:
    # any failure is swallowed so the customer create never fails
    # over tag-catalog plumbing.
    try:
        from routers.customer_tags import auto_persist_customer_tags as _p33
        await _p33(tenant["id"], user.get("id") or "", doc.get("tags") or [])
    except Exception as _e33:
        logger.warning("[P33] customer.create tag auto-persist failed: %s", _e33)
    # Phase 17 · Feb 2026 — fire-and-forget geocode of the new
    # customer's address so it lands on the Dispatch Board without
    # waiting for the next boot backfill pass. Non-blocking — the
    # helper silently no-ops when the API key isn't configured.
    try:
        import asyncio as _a17
        from services.google_maps.geocoding import geocode_and_persist_customer as _gp17
        _a17.create_task(_gp17(doc["id"], tenant["id"]))
    except Exception:
        pass
    # Comms Phase 3 — fire customer.created automation. Never blocks.
    try:
        from services.automation_engine import emit as _emit
        await _emit(
            "customer.created",
            {"customer": doc},
            tenant_id=tenant["id"],
            entity_kind="customer", entity_id=doc["id"],
            customer_id=doc["id"],
        )
    except Exception:
        pass
    # Feb-2026 · Marketing Slice M5c — drip event bus (customer_created).
    try:
        from services.marketing.drip_events import on_event as _drip_on_event
        await _drip_on_event("customer_created", tenant["id"], doc["id"])
    except Exception:
        pass
    # Marketing M1 — mirror the new customer into the subscribers
    # collection with source="crm_customer" (already-consented).
    try:
        from services.marketing_subscribers import mirror_customer_created
        await mirror_customer_created(tenant["id"], doc)
    except Exception:
        pass

    # Batch 12C · Feb 2026 — add-card-on-create hook. Fires only if
    # ALL of the following are true:
    #   * ``tenant.auto_send_card_add_on_create == True`` (default OFF).
    #   * Effective card-on-file requirement is on for this customer.
    #   * The customer has no saved PMs yet (brand new → always true).
    #   * The customer has EITHER an email OR a phone.
    # Respects the existing 1/5-min per-customer rate limit inside
    # ``send_card_add_link`` — brand-new customers pass trivially.
    try:
        if bool(tenant.get("auto_send_card_add_on_create", False)):
            card_fields = _compute_card_fields(
                doc, bool(tenant.get("require_card_on_file_default", True)),
            )
            has_contact = bool(doc.get("email") or doc.get("phone"))
            if (card_fields["effective_require_card_on_file"]
                    and not card_fields["has_card_on_file"]
                    and has_contact):
                await send_card_add_link(doc["id"], user=user, tenant=tenant)
            elif not has_contact and card_fields["effective_require_card_on_file"]:
                logger.warning(
                    f"[phase12c-auto-send] tenant={tenant['id']} "
                    f"customer={doc['id']} skipped=no_contact_info"
                )
    except HTTPException:
        # send_card_add_link raises 429 on repeat sends; a brand-new
        # customer can't trip it. Any other HTTPException is not
        # worth blowing up customer creation for.
        pass
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            f"[phase12c-auto-send] tenant={tenant['id']} "
            f"customer={doc['id']} error={exc}"
        )
    return doc


@router.post("/customers/{cid}/create-login")
async def create_customer_login(cid: str, body: CreateLoginRequest,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(404, "Customer not found")
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "An account with this email already exists")
    new_user = {
        "id": new_id(), "name": customer["name"], "email": email,
        "password_hash": hash_password(body.password), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": cid,
        "tenant_id": tenant["id"],
    }
    await db.users.insert_one(new_user)
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"email": email, "has_login": True}},
    )
    return {"ok": True, "email": email}


@router.get("/customers/{cid}")
async def get_customer(cid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    # Feb-2026 · P25 — mirror the P4.5 soft-delete two-branch check
    # from ``get_job``. Super_admin sees a 409 (so restore tooling
    # knows the row still exists); every other role gets a 404 so
    # the mere existence of a soft-deleted customer doesn't leak.
    # Covers both admin-driven bulk soft-deletes and P11b account-
    # anonymization (both stamp ``deleted_at``).
    if doc.get("deleted_at"):
        role = (user.get("role") or "").lower()
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "customer_soft_deleted",
                          "message": "Customer is soft-deleted; restore first."},
            )
        raise HTTPException(404, "Customer not found")
    from utils import not_deleted_filter as _nd_cust
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tenant["id"], **_nd_cust()}, {"_id": 0}
    ).sort("scheduled_date", -1).to_list(200)
    doc["jobs"] = jobs
    # Phase 12 · Feb 2026 — derive card-on-file fields at read time.
    doc.update(_compute_card_fields(
        doc, bool(tenant.get("require_card_on_file_default", True))))
    # Phase 12B · Feb 2026 — techs never see the Stripe customer id.
    if user.get("role") == "technician":
        doc.pop("stripe_customer_id", None)
        doc.pop("stripe_default_payment_method_id", None)
    return doc


# ─── P26 · Feb-2026 · Super_admin customer restore ──────────────────────

@router.patch("/customers/{cid}/restore")
async def restore_customer(
    cid: str,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · P26 — Admin-tier restore surface for soft-deleted
    customers (companion to the P25 read-filter). Clears ``deleted_at``
    and — if the row was P11b-anonymized — ``anonymized_at`` as well.

    Idempotent: restoring a live customer is a 200 with
    ``restored=false, reason=not_soft_deleted`` (not a 400) so the UI
    can safely retry. A restored anonymized customer surfaces the
    ``was_anonymized=true`` flag so the caller can warn the operator
    the PII fields (name/email/phone/address) were already scrubbed
    and will NOT come back — P11b anonymization is one-way.

    Auth: admin / super_admin / owner (Feb-2026 · Customer Delete UX
    overhaul widened from super_admin-only). Every other role → 403
    role_not_permitted.
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "owner"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin, super_admin, or owner can restore a customer."},
        )
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1, "anonymized_at": 1, "name": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    # Idempotent branch — the UI can safely retry a Restore click.
    if not doc.get("deleted_at"):
        return {
            "restored": False,
            "reason": "not_soft_deleted",
            "customer_id": cid,
            "was_anonymized": bool(doc.get("anonymized_at")),
        }
    was_anonymized = bool(doc.get("anonymized_at"))
    unset: dict = {"deleted_at": ""}
    if was_anonymized:
        unset["anonymized_at"] = ""
    restored_at = datetime.now(timezone.utc).isoformat()
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$unset": unset, "$set": {"restored_at": restored_at}},
    )
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": "customer_restore",
            "customer_id": cid,
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": role,
            "was_anonymized": was_anonymized,
            "ip": _p26_client_ip(request),
            "user_agent": (request.headers.get("user-agent") or "")[:400],
            "restored_at": restored_at,
            "created_at": restored_at,
        })
    except Exception:
        logger.exception("[P26] audit log insert failed for restore of %s", cid)
    logger.info(
        "[P26] customer_restore actor=%s cid=%s was_anonymized=%s",
        user.get("email"), cid, was_anonymized,
    )
    return {
        "restored": True,
        "customer_id": cid,
        "was_anonymized": was_anonymized,
        "restored_at": restored_at,
    }


def _p26_client_ip(request) -> str:
    try:
        from services._shared.http import client_ip as _shared_ip
        return _shared_ip(request)
    except Exception:
        try:
            xff = (request.headers.get("x-forwarded-for") or "").split(",")
            if xff and xff[0].strip():
                return xff[0].strip()[:64]
            return (getattr(request.client, "host", "") or "")[:64]
        except Exception:
            return ""


# ─── P27 · Feb-2026 · Mute / Unmute customer ──────────────────────────
# Muted = full silent-mode. Marketing drips, seasonal reminders,
# reactivation campaigns, autobilling, route optimization, and P18
# lead alerts all check ``is_muted`` and skip the customer. Mute is
# reversible; the underlying doc is NOT soft-deleted (see P25/P26 for
# that surface). Muted rows carry ``is_active=False`` too so every
# existing "active only" query naturally excludes them without a
# code change.
#
# Permissions:
#   * mute   — admin OR super_admin (tech + customer → 403)
#   * unmute — admin OR super_admin (tech + customer → 403)  [P27 addendum]


async def _p27_write_audit(
    *, event: str, cid: str, tenant_id: str, user: dict, request: Request,
    extra: Optional[dict] = None,
) -> None:
    entry = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "event": event,
        "customer_id": cid,
        "actor_id": user.get("id"),
        "actor_email": user.get("email"),
        "actor_role": (user.get("role") or "").lower(),
        "ip": _p26_client_ip(request),
        "user_agent": (request.headers.get("user-agent") or "")[:400],
        "created_at": now_iso(),
    }
    if extra:
        entry.update(extra)
    try:
        await db.audit_logs.insert_one(entry)
    except Exception:
        logger.exception("[P27] audit log insert failed event=%s cid=%s",
                            event, cid)


@router.patch("/customers/{cid}/mute")
async def mute_customer(
    cid: str,
    request: Request,
    body: Optional[Dict[str, Any]] = Body(default=None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · P27 (+ P29 muted_reason snapshot) — Mute a customer.
    Full silent-mode. Idempotent. Auth: admin OR super_admin.

    P29: optional ``muted_reason`` free-text snapshot (<=500 chars,
    trimmed; empty → null). NOT a foreign key to ``muted_reasons`` —
    renaming a reason must not retroactively change historical rows.
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin or super_admin can mute a customer."},
        )
    from utils import not_deleted_filter as _nd_cust
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd_cust()},
        {"_id": 0, "id": 1, "is_muted": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    # P29 — normalise reason (trim; empty/whitespace → None; cap 500).
    raw_reason = (body or {}).get("muted_reason") if isinstance(body, dict) else None
    reason: Optional[str] = None
    if isinstance(raw_reason, str):
        s = raw_reason.strip()
        if s:
            reason = s[:500]
    if doc.get("is_muted"):
        return {"muted": False, "reason": "already_muted", "customer_id": cid}
    muted_at = now_iso()
    set_fields = {
        "is_muted": True,
        "muted_at": muted_at,
        "muted_by": user.get("id"),
        "is_active": False,
    }
    if reason is not None:
        set_fields["muted_reason"] = reason
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": set_fields},
    )
    await _p27_write_audit(event="customer_mute", cid=cid,
                              tenant_id=tenant["id"], user=user, request=request,
                              extra=({"muted_reason": reason} if reason else None))
    logger.info("[P27] customer_mute actor=%s cid=%s reason=%s",
                    user.get("email"), cid, (reason or "-"))
    # Feb-2026 · P32 — best-effort auto-persist of a novel custom reason
    # into ``muted_reasons`` so it appears in the picker next time.
    # Rules (see phase brief):
    #   * Case-insensitive dedup via ``label_norm`` across active +
    #     archived rows for this tenant.
    #   * If the label matches an ACTIVE row → no-op.
    #   * If it matches an ARCHIVED row → do NOT reactivate. Respect
    #     the admin's intentional archive; the customer.muted_reason
    #     snapshot on the row already captures the label.
    #   * If missing → insert a new active row with next sort_order +
    #     an ``auto_created=true`` breadcrumb, and audit-log it.
    # A failure here MUST NEVER block the mute — swallowed + logged.
    if reason:
        try:
            await _p32_auto_persist_reason(reason, tenant["id"], user, request)
        except Exception as e:
            logger.warning("[P32] muted_reason auto-persist failed cid=%s: %s",
                              cid, e)
    return {"muted": True, "customer_id": cid, "muted_at": muted_at,
             "muted_reason": reason}


async def _p32_auto_persist_reason(reason: str, tenant_id: str,
                                       user: dict, request: Request) -> None:
    """Feb-2026 · P32 — Idempotent auto-persist of a mute reason into
    ``muted_reasons``. See ``mute_customer`` for the full contract.
    Kept as a private helper so the mute path stays terse and the
    audit-log call is co-located with the insert."""
    label = reason.strip()
    if not label:
        return
    norm = label.lower()
    existing = await db.muted_reasons.find_one(
        {"tenant_id": tenant_id, "label_norm": norm},
        {"_id": 0, "id": 1, "is_active": 1},
    )
    if existing is not None:
        # Matches an active or archived row — either way, do nothing.
        # Archived-match intentionally does not reactivate.
        return
    last = await db.muted_reasons.find(
        {"tenant_id": tenant_id}, {"_id": 0, "sort_order": 1},
    ).sort("sort_order", -1).limit(1).to_list(1)
    next_sort = int((last[0].get("sort_order") if last else 0) or 0) + 10
    now = now_iso()
    new_row = {
        "id": new_id(), "tenant_id": tenant_id, "label": label[:120],
        "label_norm": norm[:120],
        "is_active": True, "sort_order": next_sort,
        "auto_created": True,
        "created_at": now, "created_by": user.get("id"),
        "updated_at": now, "updated_by": user.get("id"),
    }
    await db.muted_reasons.insert_one(new_row)
    await _p27_write_audit(event="muted_reason_auto_created",
                              cid=new_row["id"], tenant_id=tenant_id,
                              user=user, request=request,
                              extra={"label": label[:120]})
    logger.info("[P32] muted_reason auto-created tenant=%s label=%r",
                    tenant_id, label[:120])


@router.patch("/customers/{cid}/unmute")
async def unmute_customer(
    cid: str,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · P27 (+ addendum) — Unmute a customer. Restores
    ``is_active=True`` and clears the muted-at breadcrumb. Idempotent.

    Auth: admin OR super_admin (tech + customer → 403). The P27
    addendum widened this from super_admin-only.
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin or super_admin can unmute a customer."},
        )
    from utils import not_deleted_filter as _nd_cust
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd_cust()},
        {"_id": 0, "id": 1, "is_muted": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    if not doc.get("is_muted"):
        return {"unmuted": False, "reason": "not_muted", "customer_id": cid}
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_active": True},
         "$unset": {"is_muted": "", "muted_at": "", "muted_by": "",
                      "muted_reason": ""}},
    )
    await _p27_write_audit(event="customer_unmute", cid=cid,
                              tenant_id=tenant["id"], user=user, request=request)
    logger.info("[P27] customer_unmute actor=%s cid=%s", user.get("email"), cid)
    return {"unmuted": True, "customer_id": cid}




@router.get("/customers/{cid}/deactivation-preview")
async def deactivation_preview(cid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Phase 34f — dry-run for the Active/Inactive toggle confirm dialog.
    Returns the counts that WOULD be affected if the caller flipped
    `is_active` from true → false right now. Does not mutate anything."""
    # Feb-2026 · P25 — hide soft-deleted / P11b-anonymized customers.
    from utils import not_deleted_filter as _nd_cust
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd_cust()}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future_q = {
        "customer_id": cid,
        "tenant_id": tenant["id"],
        "scheduled_date": {"$gte": today_iso},
        "status": {"$in": ["scheduled", "pending", "confirmed"]},
    }
    future_count = await db.jobs.count_documents(future_q)
    recurring_count = await db.jobs.count_documents(
        {**future_q, "auto_recurring": True}
    )
    return {
        "future_job_count": future_count,
        "recurring_template_count": recurring_count,
    }


async def _apply_activation_cascade(cid: str, tenant_id: str, user: dict,
                                     was_active: bool, now_active: bool,
                                     doc_name: Optional[str]):
    """Phase 34f/56.2 — Shared cascade + audit + notification helper.

    Called from both `PUT /customers/{cid}` (bulk edit) and
    `PATCH /customers/{cid}/activation` (list-row / detail-header toggle).
    Kept in one place so we can never drift: any change to the cascade
    ripples through both surfaces.

    Assumes the caller has ALREADY persisted the new `is_active` value on
    the customer document — this helper only handles the side-effects
    (cancel future jobs, log event, notify admins).

    Returns (cancelled_job_count, deactivated_recurring_count).
    """
    cancelled_job_count = 0
    deactivated_recurring_count = 0
    deactivating = was_active is True and now_active is False
    reactivating = was_active is False and now_active is True

    if deactivating:
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q = {
            "customer_id": cid,
            "tenant_id": tenant_id,
            "scheduled_date": {"$gte": today_iso},
            "status": {"$in": ["scheduled", "pending", "confirmed"]},
        }
        # Count recurring instances BEFORE the update so we can report both
        # totals honestly. `auto_recurring` is the flag Phase 20 attached to
        # jobs created by `create_recurring_maintenance`.
        deactivated_recurring_count = await db.jobs.count_documents(
            {**q, "auto_recurring": True}
        )
        upd = await db.jobs.update_many(
            q,
            {"$set": {
                "status": "cancelled",
                "cancellation_reason": "Customer marked inactive",
                "cancelled_at": now_iso(),
                "cancelled_by_user_id": user["id"],
                "auto_recurring": False,
            }},
        )
        cancelled_job_count = int(upd.modified_count or 0)

    if deactivating or reactivating:
        await db.customer_activation_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "customer_id": cid,
            "from_status": "active" if deactivating else "inactive",
            "to_status": "inactive" if deactivating else "active",
            "changed_at": now_iso(),
            "changed_by_user_id": user["id"],
            "cancelled_job_count": cancelled_job_count,
            "deactivated_recurring_count": deactivated_recurring_count,
        })
        try:
            from services.notifications import emit as notify_emit, KIND_LABELS
            admins = await db.users.find(
                {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]},
                 "id": {"$ne": user.get("id")}},
                {"_id": 0, "id": 1},
            ).to_list(200)
            aids = [a["id"] for a in admins if a.get("id")]
            if aids:
                kind = "system_alert" if "system_alert" in KIND_LABELS else "system"
                verb = "inactive" if deactivating else "active"
                who = user.get("name") or user.get("email") or "Admin"
                body_txt = (
                    f"{who} marked {doc_name or 'customer'} inactive. "
                    f"{cancelled_job_count} upcoming job(s) auto-cancelled."
                    if deactivating
                    else f"{who} reactivated {doc_name or 'customer'}."
                )
                await notify_emit(
                    aids, kind=kind,
                    title=f"Customer {doc_name or ''} marked {verb}",
                    body=body_txt,
                    href=f"/customers/{cid}",
                    tenant_id=tenant_id, audience="internal",
                    source_ref={"kind": "customer_activation", "id": cid},
                    customer_id=cid,
                )
        except Exception:
            pass
    # Feb-2026 · P42 — on inactive → active flips, stamp
    # ``customer_since`` if this is the customer's first crossing of
    # the "converted" threshold AND they already have ≥1 job. Safe
    # no-op otherwise (immutable once set, requires ≥1 job).
    if reactivating:
        try:
            from services.customer_lifecycle import stamp_customer_since
            await stamp_customer_since(cid, tenant_id)
        except Exception as _p42_exc:  # pragma: no cover — best-effort
            logger.warning("[p42] cascade stamp failed cid=%s err=%s",
                              cid, _p42_exc)
    return cancelled_job_count, deactivated_recurring_count


@router.put("/customers/{cid}")
async def update_customer(cid: str, body: CustomerIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")

    # Phase 34f — Active/inactive lifecycle detection. Missing field on the
    # existing doc defaults to True (all legacy customers were implicitly
    # active). New value defaults to True on the input model.
    was_active = existing.get("is_active", True)
    now_active = bool(body.is_active) if body.is_active is not None else True

    payload = body.dict()
    _sync_customer_names(payload)
    # Feb-2026 · P42 — ``customer_since`` is immutable on the write
    # path. Existing stamps are preserved; blank-out attempts are
    # rejected here by never letting the payload touch the field.
    payload.pop("customer_since", None)
    # Feb-2026 Customer Detail Additions — normalize arrays + sync
    # scalars + auto-stamp VIP transitions BEFORE persisting.
    _apply_multi_contact(payload)
    _apply_vip_stamp(payload, existing=existing)
    vip_flipped_on = bool(payload.get("is_vip")) and not bool(existing.get("is_vip"))
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": payload}
    )
    # K31 · Feb-2026 — flag any phone collision with another customer
    # in the same tenant.  Non-blocking.
    await _k31_audit_phone_collision(payload, tenant["id"], current_id=cid)
    # Feb-2026 · P33 — auto-persist any novel tag strings from the
    # incoming PUT into the tenant catalog. Best-effort (never blocks).
    try:
        from routers.customer_tags import auto_persist_customer_tags as _p33
        await _p33(tenant["id"], user.get("id") or "", payload.get("tags") or [])
    except Exception as _e33:
        logger.warning("[P33] customer.update tag auto-persist failed: %s", _e33)

    # Phase 17 · Feb 2026 — re-geocode if the service address (either
    # free-form or any structured field) actually changed. Clears the
    # ``geocoded_at`` stamp so the helper doesn't short-circuit on the
    # cache and picks up new coordinates immediately.
    _addr_keys = (
        "service_address", "service_street", "street",
        "service_city", "city", "service_state", "state",
        "service_zip", "zip",
    )
    _addr_changed = any(
        (payload.get(k) or "") != (existing.get(k) or "")
        for k in _addr_keys
    )
    if _addr_changed:
        try:
            import asyncio as _a17
            from services.google_maps.geocoding import (
                geocode_and_persist_customer as _gp17,
            )
            await db.customers.update_one(
                {"id": cid, "tenant_id": tenant["id"]},
                {"$unset": {"geocoded_at": ""}},
            )
            _a17.create_task(_gp17(cid, tenant["id"]))
        except Exception:
            pass

    cancelled_job_count, deactivated_recurring_count = await _apply_activation_cascade(
        cid, tenant["id"], user, was_active, now_active, existing.get("name")
    )

    # Feb-2026 Customer Detail Additions — if this PUT flipped VIP on,
    # mirror to subscribers + emit ``customer.vip_flagged`` notification
    # so the auto-seeded "VIP Customers" segment updates immediately.
    if vip_flipped_on:
        try:
            from services.marketing_subscribers import mirror_customer_updated
            fresh = await db.customers.find_one(
                {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
            )
            if fresh:
                await mirror_customer_updated(tenant["id"], fresh)
                await _emit_vip_flagged(tenant["id"], user, fresh)
        except Exception:
            pass

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if was_active is True and now_active is False:
        doc["cancelled_job_count"] = cancelled_job_count
        doc["deactivated_recurring_count"] = deactivated_recurring_count
    return doc


@router.patch("/customers/{cid}/activation")
async def patch_customer_activation(cid: str, body: dict,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    """Phase 56.2 — lightweight activation toggle for the list-row and
    detail-header switches. Only mutates `is_active`; all other fields
    are preserved verbatim (unlike PUT /customers/{cid} which expects a
    full CustomerIn body). Reuses the Phase 34f cascade helper so
    behavior is identical to a full-body update that flips the flag."""
    if "is_active" not in body:
        raise HTTPException(400, "is_active is required")
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")

    was_active = existing.get("is_active", True)
    now_active = bool(body.get("is_active"))

    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_active": now_active}},
    )

    cancelled_job_count, deactivated_recurring_count = await _apply_activation_cascade(
        cid, tenant["id"], user, was_active, now_active, existing.get("name")
    )

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if was_active is True and now_active is False:
        doc["cancelled_job_count"] = cancelled_job_count
        doc["deactivated_recurring_count"] = deactivated_recurring_count
    return doc


@router.delete("/customers/{cid}")
async def delete_customer(
    cid: str,
    request: Request,
    mode: str = Query(
        "soft",
        description=(
            "Feb-2026 · Customer Delete UX overhaul — ``soft`` (default) "
            "stamps ``deleted_at`` (recoverable via "
            "``PATCH /customers/{cid}/restore``); ``hard`` removes the "
            "customer row from ``db.customers`` and writes a rich "
            "pre-delete snapshot to ``db.deletion_audit`` + a "
            "``customer.hard_delete`` row to ``db.audit_logs``. Hard-"
            "delete never cascades — jobs/invoices/service reports/"
            "recurring templates keep a dangling ``customer_id`` and "
            "reads render 'Unknown Customer' gracefully. Hard-delete "
            "is blocked with 409 if the customer has any unpaid "
            "invoice (soft is not blocked — soft is recoverable)."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Delete a customer. Defaults to ``soft`` for safety — any legacy
    caller that doesn't pass ``?mode=`` gets the safe path.

    Response shape::

        soft: { ok: true, mode: "soft", customer_id, deleted_at,
                already_deleted? }
        hard: { ok: true, mode: "hard", customer_id, deleted_at }
        409 : { detail: "customer_has_unpaid_invoices",
                invoice_ids: [...], invoice_count: N }
    """
    mode = (mode or "soft").lower()
    if mode not in ("soft", "hard"):
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "invalid_mode",
                "message": "mode must be 'soft' or 'hard'",
                "received": mode,
            },
        )

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")

    now = now_iso()

    if mode == "soft":
        # Idempotent — already soft-deleted returns 200 so the UI can
        # safely retry a Soft-Delete click. Matches the P26 restore
        # endpoint's idempotent contract.
        if doc.get("deleted_at"):
            return {
                "ok": True, "mode": "soft", "customer_id": cid,
                "already_deleted": True,
                "deleted_at": doc.get("deleted_at"),
            }
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {"deleted_at": now,
                      "deleted_by_user_id": user.get("id")}},
        )
        # Symmetric audit — single-row soft-delete writes the same
        # ``customer.soft_delete`` event that ``bulk_crm.py`` writes
        # for the bulk path, so downstream forensic tooling can't
        # tell single vs bulk apart.
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "event": "customer.soft_delete",
                "customer_id": cid,
                "actor_id": user.get("id"),
                "actor_email": user.get("email"),
                "actor_role": (user.get("role") or "").lower(),
                "ip": _p26_client_ip(request),
                "user_agent": (request.headers.get("user-agent") or "")[:400],
                "deleted_at": now,
                "created_at": now,
            })
        except Exception:                                          # noqa: BLE001
            logger.exception(
                "[customer.delete] soft-delete audit insert failed for %s", cid,
            )
        logger.info(
            "[customer.delete] soft actor=%s cid=%s",
            user.get("email"), cid,
        )
        return {
            "ok": True, "mode": "soft", "customer_id": cid,
            "deleted_at": now,
        }

    # ── mode == "hard" ────────────────────────────────────────────────
    # Locked-check: any unpaid invoice blocks the hard delete. Soft-
    # delete is NOT blocked (soft is recoverable, so no risk of
    # losing the invoice → customer link if the operator later
    # restores). Match the bulk-soft-delete pipeline query shape so
    # the two locked-checks stay semantically identical.
    unpaid_cursor = db.quotes.find(
        {"tenant_id": tenant["id"],
         "customer_id": cid,
         "doc_type": "invoice",
         "payment_status": {"$ne": "paid"},
         "$or": [{"deleted_at": None},
                 {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "invoice_number": 1, "total": 1,
         "payment_status": 1, "title": 1},
    )
    unpaid = await unpaid_cursor.to_list(200)
    if unpaid:
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "customer_has_unpaid_invoices",
                "message": (
                    f"Customer has {len(unpaid)} unpaid invoice(s) — "
                    "resolve or soft-delete first."
                ),
                "invoice_count": len(unpaid),
                "invoice_ids": [i["id"] for i in unpaid],
                # First 20 invoice summaries help the UI render a
                # "resolve these first" toast without a follow-up
                # fetch. Capped so a customer with 5000 unpaid
                # invoices doesn't OOM the response body.
                "invoices": [
                    {"id": i["id"],
                     "invoice_number": i.get("invoice_number"),
                     "title": i.get("title"),
                     "total": i.get("total"),
                     "payment_status": i.get("payment_status")}
                    for i in unpaid[:20]
                ],
            },
        )

    # Feb-2026 · Phase F3 — cascade/block on referencing jobs. F2
    # shipped the manual repair path; F3 closes the barn door at
    # the source so new orphan-customer refs never accumulate.
    # Matches the same "$or deleted_at null/absent" shape used by
    # the unpaid-invoice guardrail above. Only ACTIVE jobs block;
    # already-soft-deleted jobs are fine (they carry a snapshot).
    referencing_jobs_count = await db.jobs.count_documents({
        "customer_id": cid,
        "tenant_id": tenant["id"],
        "status": {"$nin": ["deleted"]},
        "$or": [{"deleted_at": None},
                {"deleted_at": {"$exists": False}}],
    })
    if referencing_jobs_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "has_referencing_jobs",
                "detail": "customer_has_referencing_jobs",
                "message": (
                    f"Customer is referenced by {referencing_jobs_count} "
                    "active job(s) — soft-delete or reassign those jobs "
                    "first."
                ),
                "job_count": referencing_jobs_count,
                "resolution": (
                    "soft-delete or reassign the affected jobs first"
                ),
            },
        )

    # Pre-delete snapshot for the deletion_audit collection.
    # Excludes ``password_hash`` and ``password_reset_token`` — the
    # collection is super_admin-gated but scrubbing sensitive fields
    # is still the right posture (defence in depth).
    snapshot = {
        k: v for k, v in doc.items()
        if k not in ("password_hash", "password_reset_token", "_id")
    }

    # Rich forensic audit — deletion_audit collection (super_admin-
    # readable via GET /admin/audit/deletions).
    try:
        from routers.deletion_audit import write_deletion_audit_entry
        await write_deletion_audit_entry(
            tenant_id=tenant["id"],
            resource_type="customer",
            resource_id=cid,
            user=user,
            snapshot=snapshot,
            cascade_deleted_ids=[],  # NEVER cascade — spec.
            deletion_reason=None,
        )
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[customer.delete] deletion_audit insert failed for %s", cid,
        )

    # Symmetric ``customer.hard_delete`` event in audit_logs so the
    # legacy audit consumers see a per-row row too.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": "customer.hard_delete",
            "customer_id": cid,
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": (user.get("role") or "").lower(),
            "ip": _p26_client_ip(request),
            "user_agent": (request.headers.get("user-agent") or "")[:400],
            # Denormalised name/email so a quick ``audit_logs`` scan
            # doesn't require a cross-collection lookup into
            # deletion_audit for the operator-visible summary.
            "customer_snapshot_name": doc.get("name") or "",
            "customer_snapshot_email": doc.get("email") or "",
            "deleted_at": now,
            "created_at": now,
        })
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[customer.delete] hard-delete audit_logs insert failed for %s",
            cid,
        )

    # Finally — the actual destructive op. Customer row ONLY.
    # No cascade to jobs / invoices / service_reports /
    # recurring_job_templates / customer_equipment_photos /
    # customer_communications_log / customer_tasks / csat_surveys /
    # customer_reviews / leads / churn_signals /
    # marketing_review_requests. Orphan child rows keep their
    # snapshot ``customer_name`` — frontend renders "Unknown
    # Customer" via ``formatCustomerName()`` if the snapshot is
    # missing.
    await db.customers.delete_one({"id": cid, "tenant_id": tenant["id"]})

    logger.info(
        "[customer.delete] hard actor=%s cid=%s name=%r",
        user.get("email"), cid, doc.get("name"),
    )
    return {
        "ok": True, "mode": "hard", "customer_id": cid,
        "deleted_at": now,
    }


# ─── Feb-2026 Customer Detail Additions ──────────────────────────────
# VIP toggle + multi-contact endpoints. These are lightweight PATCH
# endpoints so the detail-page UI can flip flags without POSTing the
# full CustomerIn body.

class _VipToggle(BaseModel):
    is_vip: bool
    vip_note: Optional[str] = None


class _MobilesUpdate(BaseModel):
    mobiles: List[dict]


class _EmailsUpdate(BaseModel):
    emails: List[dict]


class _SendEmailBody(BaseModel):
    to: str
    subject: str
    body: str
    customer_id: Optional[str] = None


# BUG F · Feb 2026 — customer-direct SMS body. Mirrors the email
# payload so the frontend composer can flip channels without a body
# schema change.
class _SendSmsBody(BaseModel):
    to: str
    body: str
    customer_id: Optional[str] = None


# Phase 29 · Feb 2026 — customer contact composer preview body.
class _PreviewMessageBody(BaseModel):
    channel: str                     # "email" | "sms"
    subject: Optional[str] = ""
    body: str = ""


# ─── Feb-2026 service-notes ship ──────────────────────────────────────
class _ServiceNotesPatch(BaseModel):
    """Partial update — omit a key to leave that side untouched. Send
    ``null`` to explicitly clear a note."""
    pool: Optional[str] = None
    landscape: Optional[str] = None


# ─── Feb-2026 · Service-notes classifier vocabulary ───────────────────
# Widened Feb-2026 (F8 · schedule notes classifier ship) so techs
# don't hit "why doesn't pool notes show on my Filter Clean job?" —
# any service_type whose lowercase form contains one of these tokens
# is treated as pool/landscape respectively.  Tokens are substrings,
# NOT exact words, so "landscap" catches both "Landscape" and
# "Landscaping"; "chemical" catches "Chemical Balance"; etc.
#
# Precedence: LANDSCAPE checked FIRST.  Rationale — the pool set
# includes the generic "clean" token which appears verbatim in
# common landscape service names ("Yard Cleanup", "Landscape
# Cleanup").  Landscape tokens (yard/tree/hedge/mow/lawn) are all
# strongly landscape-signal, so checking them first eliminates the
# false-positive pool routing without ever masking a real pool job.
# Pool tokens that would false-positive under landscape-first (e.g.
# a "Pool Cleaning" that also contains a landscape word) are so rare
# in real service_type strings that we tolerate the edge case in
# favor of the common one.  See test_f8_service_type_classifier.py
# for the locked semantics.
_POOL_KEYWORDS = (
    "pool", "chemical", "filter", "clean", "shock", "backwash", "algae",
)
_LANDSCAPE_KEYWORDS = (
    "landscap", "lawn", "yard", "tree", "trim", "mow", "hedge", "irrigation",
)


def _classify_service_type(service_type: Optional[str]) -> Optional[str]:
    """Return "pool" | "landscape" | None based on a substring match
    against the widened keyword vocab.  Landscape checked first
    (see module comment for rationale).  ``None`` when the input is
    empty or matches neither group — caller must decide fallback."""
    stype = (service_type or "").strip().lower()
    if not stype:
        return None
    for kw in _LANDSCAPE_KEYWORDS:
        if kw in stype:
            return "landscape"
    for kw in _POOL_KEYWORDS:
        if kw in stype:
            return "pool"
    return None


def _resolve_service_note(customer: dict, service_type: Optional[str],
                            user: Optional[dict] = None) -> Optional[str]:
    """Return the relevant note text for a schedule/job view.

    Priority:
      1. Widened substring classifier (``_classify_service_type``) →
         return matching key's note if present.
      2. Direct key hit (legacy path — ``service_type`` was literally
         "pool" or "landscape").  Kept for backward-compat.
      3. Fallback to the tech's ``specialties[0]``.
      4. Return ``None`` when nothing resolves.
    """
    notes = (customer or {}).get("service_notes") or {}
    if not notes:
        return None
    # 1) Widened classifier — the primary path (Feb-2026 F8).
    group = _classify_service_type(service_type)
    if group and notes.get(group):
        return notes[group]
    # 2) Legacy exact-key path — kept so callers that pass a literal
    #    "pool" / "landscape" string still hit.  Redundant with the
    #    classifier above but harmless.
    stype = (service_type or "").strip().lower()
    if stype and stype in notes and notes.get(stype):
        return notes[stype]
    # 3) Tech specialty fallback.
    specialties = ((user or {}).get("specialties") or [])
    for spec in specialties:
        key = (spec or "").strip().lower()
        if key in notes and notes.get(key):
            return notes[key]
    return None


@router.get("/customers/{cid}/service-notes-for-schedule")
async def get_service_note_for_schedule(cid: str, service_type: str = Query(...),
                                          user: dict = Depends(get_current_user),
                                          tenant: dict = Depends(get_current_tenant)):
    """Cheap read used by mobile tech schedule + web route map. Returns
    just the note text for a single service type so tech clients don't
    fetch the whole customer doc.

    Accessible to techs (they can only see notes for their own visits;
    RBAC on the tenant is already enforced by the dependency). Admins
    see everything."""
    # Feb-2026 · P25 — hide soft-deleted / P11b-anonymized customers.
    from utils import not_deleted_filter as _nd_cust
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd_cust()},
        {"_id": 0, "id": 1, "service_notes": 1, "name": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    stype = (service_type or "").strip().lower()
    if stype not in ("pool", "landscape"):
        raise HTTPException(400, "service_type must be 'pool' or 'landscape'")
    note = ((doc.get("service_notes") or {}).get(stype)) or None
    return {"customer_id": cid, "service_type": stype, "note": note}


@router.patch("/customers/{cid}/service-notes")
async def patch_service_notes(cid: str, body: _ServiceNotesPatch,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Partial update — omitted keys are preserved. Explicit ``null``
    clears. Admin-only per user directive; techs read but never write."""
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "service_notes": 1},
    )
    # Feb-2026 tester fix — an empty projected dict ``{}`` (customer
    # exists but has no ``service_notes`` field yet) is falsy, so the
    # old ``if not existing:`` guard raised 404 on every FIRST write.
    # Use an explicit ``is None`` check + include ``id`` in the
    # projection so the match always returns at least the id.
    if existing is None:
        raise HTTPException(404, "Customer not found")
    current = existing.get("service_notes") or {}
    patch = body.dict(exclude_unset=True)
    for k in ("pool", "landscape"):
        if k in patch:
            v = patch[k]
            if v is None:
                current[k] = None
            else:
                v = str(v).strip()
                current[k] = v if v else None
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": {"service_notes": current}},
    )
    return {"customer_id": cid, "service_notes": current}


@router.post("/customers/{cid}/send-email")
async def customer_send_email(cid: str, body: _SendEmailBody,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    """Send an ad-hoc email to a customer contact address. Thin
    passthrough into the existing ``send_email`` adapter so the
    Customer detail Send ▼ Email option can compose freely without a
    template. Validates that the target address is one of the
    customer's mirrored emails so we don't accidentally leak.

    BUG F · Feb 2026 — persist a ``communications_log`` row with
    ``trigger_entity.kind="customer_direct_message"`` so the customer's
    activity timeline surfaces the send. Raises the underlying adapter
    error status on failure so the frontend can render a red toast
    instead of pretending we sent.
    """
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    to = body.to.strip().lower()
    allowed = {(e.get("address") or "").strip().lower()
                for e in (doc.get("emails") or [])}
    allowed.add((doc.get("email") or "").strip().lower())
    allowed.discard("")
    if to not in allowed:
        raise HTTPException(400, "recipient not among the customer's emails")
    if not body.body.strip():
        raise HTTPException(422, "empty message")
    from services.comms_email_adapter import send_email
    res = await send_email(
        tenant["id"], to,
        subject=body.subject.strip() or "Message",
        html=f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{body.body}</pre>",
    )

    # BUG F — persist the send so it shows on the customer activity
    # timeline + downstream analytics. Best-effort: a failure here
    # never masks the send outcome.
    try:
        await db.communications_log.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "email",
            "direction": "outbound",
            "recipient": to,
            "subject": body.subject.strip() or "Message",
            "body": body.body,
            "delivery_status": res.get("status") or "unknown",
            "provider": "resend",
            "provider_response_id": res.get("provider_id"),
            "trigger_entity": {"kind": "customer_direct_message",
                                "customer_id": cid,
                                "sent_by": user.get("id")},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"[bug-f] failed to persist customer email comms_log row: {e}")

    if res.get("status") not in ("sent", "queued", "mocked", "skipped_opted_out"):
        raise HTTPException(
            502,
            f"send failed: {res.get('error') or res.get('status') or 'unknown'}",
        )
    return {"ok": True, **res}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 29 · Feb 2026 · Customer contact composer — preview endpoint.
# Renders a subject + body pair against THIS customer's merge context so
# the composer can show "what will actually go out" before the operator
# hits Send. Reuses the exact same UPPERCASE + legacy Mustache passes the
# marketing templates preview endpoint uses, so behaviour is identical to
# the send path. No PII is leaked — only the caller's own tenant scope is
# queried and the response is returned to that same caller.
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/customers/{cid}/preview-message",
              operation_id="customers.previewMessage")
async def customer_preview_message(cid: str, body: _PreviewMessageBody,
                                        user: dict = Depends(require_admin),
                                        tenant: dict = Depends(get_current_tenant)):
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    channel = (body.channel or "email").lower()
    if channel not in ("email", "sms"):
        raise HTTPException(422, "channel must be 'email' or 'sms'")

    # Reuse the marketing renderer stack so ``{{CUSTOMER_FIRST_NAME}}``
    # etc. resolve identically in the composer preview and at send time.
    from services.marketing.merge_tags import (
        render_template as render_uppercase_tags,
        render_context as build_merge_ctx,
    )
    from services.marketing.render import render_subject_and_body, strip_html

    first_name = doc.get("first_name") or (doc.get("name") or "").split(" ")[0]
    last_name = doc.get("last_name") or " ".join((doc.get("name") or "").split(" ")[1:])
    customer_ctx = {
        "name": doc.get("name") or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "email": (doc.get("emails") or [{}])[0].get("address")
                    if doc.get("emails") else doc.get("email"),
        "phone": (doc.get("phones") or [{}])[0].get("number")
                    if doc.get("phones") else doc.get("phone"),
        "address": doc.get("address") or doc.get("address_line_1") or "",
        "address_line_1": doc.get("address_line_1") or doc.get("address") or "",
        "city": doc.get("city") or "",
        "state": doc.get("state") or "",
        "zip": doc.get("zip") or doc.get("postal_code") or "",
        "open_balance": doc.get("balance_due", 0),
    }
    demo_ctx = build_merge_ctx(
        customer=customer_ctx,
        tenant={"name": tenant.get("name"),
                  "phone": tenant.get("phone"),
                  "email": tenant.get("email")},
    )
    pre_subject, sub_missing = render_uppercase_tags(body.subject or "", demo_ctx)
    pre_body, body_missing = render_uppercase_tags(body.body or "", demo_ctx)
    unresolved = sorted(set(list(sub_missing) + list(body_missing)))

    # Legacy dotted-token render pass — same pipeline the send code uses.
    ctx_dotted = {"customer": customer_ctx,
                    "tenant": {"name": tenant.get("name") or "",
                                 "phone": tenant.get("phone") or "",
                                 "email": tenant.get("email") or ""}}
    try:
        subject_rendered, body_rendered, _missing = render_subject_and_body(
            pre_subject, pre_body, ctx_dotted,
        )
    except Exception:                                    # noqa: BLE001
        # Second pass is best-effort — fall back to the uppercase-only
        # render so the preview always returns something usable.
        subject_rendered, body_rendered = pre_subject, pre_body

    if channel == "sms":
        body_rendered = strip_html(body_rendered or "")
        subject_rendered = None                          # SMS has no subject

    return {
        "channel": channel,
        "subject_rendered": subject_rendered,
        "body_rendered": body_rendered,
        "unresolved_tokens": unresolved,
    }


# BUG F · Feb 2026 — customer-direct SMS. Thin wrapper over the
# RingCentral adapter so the Customer Contact composer's SMS button
# stops 404-ing on the retired ``POST /api/sms/send`` path. Validates
# that the target phone matches one of the customer's mirrored
# numbers so we never leak an SMS to an arbitrary recipient.
@router.post("/customers/{cid}/send-sms",
              operation_id="customers.sendSms")
async def customer_send_sms(cid: str, body: _SendSmsBody,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Customer not found")

    # Recipient allow-list — normalise to digits so "(602) 555-1234"
    # matches "+16025551234" on the customer record.
    def _digits(s: str) -> str:
        return "".join(ch for ch in (s or "") if ch.isdigit())
    to_raw = (body.to or "").strip()
    to_digits = _digits(to_raw)
    allowed_digits = set()
    for p in (doc.get("phones") or []):
        n = _digits(p.get("number") or "")
        if n:
            allowed_digits.add(n)
    for k in ("phone", "mobile_phone", "phone_number"):
        n = _digits(doc.get(k) or "")
        if n:
            allowed_digits.add(n)

    def _norm(d: str) -> str:
        return d[-10:] if len(d) > 10 else d
    if _norm(to_digits) not in {_norm(a) for a in allowed_digits}:
        raise HTTPException(400, "recipient not among the customer's phone numbers")
    if not (body.body or "").strip():
        raise HTTPException(422, "empty message")

    from services.sms.rc_adapter import send as _sms_send
    res = await _sms_send(
        to=to_raw,
        body=body.body,
        category="transactional",
        tenant_id=tenant["id"],
        customer_id=cid,
    )

    try:
        await db.communications_log.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "sms",
            "direction": "outbound",
            "recipient": to_raw,
            "body": body.body,
            "delivery_status": res.get("provider_status") or "unknown",
            "provider": res.get("provider") or "ringcentral",
            "provider_response_id": res.get("provider_response_id"),
            "trigger_entity": {"kind": "customer_direct_message",
                                "customer_id": cid,
                                "sent_by": user.get("id")},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"[bug-f] failed to persist customer sms comms_log row: {e}")

    status = res.get("provider_status")
    if status not in ("sent", "queued", "mocked", "suppressed"):
        raise HTTPException(
            502,
            f"send failed: {res.get('error') or status or 'unknown'}",
        )
    return {"ok": True, **res}



async def _emit_vip_flagged(tenant_id: str, actor: dict, customer: dict) -> None:
    """Emit ``customer.vip_flagged`` to tenant admins (excluding the
    actor who just toggled it). Push defaults OFF for this kind — admins
    can opt in via /settings/notifications."""
    try:
        from services.notifications import emit as notify_emit
        admins = await db.users.find(
            {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]},
             "id": {"$ne": actor.get("id")}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        aids = [a["id"] for a in admins if a.get("id")]
        if not aids:
            return
        who = actor.get("name") or actor.get("email") or "Admin"
        cname = customer.get("name") or "customer"
        note = (customer.get("vip_note") or "").strip()
        body_txt = f"{who} flagged {cname} as VIP."
        if note:
            body_txt = f"{body_txt} Note: {note[:200]}"
        await notify_emit(
            aids, kind="customer.vip_flagged",
            title=f"{cname} is now a VIP",
            body=body_txt,
            href=f"/customers/{customer.get('id')}",
            tenant_id=tenant_id, audience="internal",
            source_ref={"kind": "customer", "id": customer.get("id")},
            customer_id=customer.get("id"),
        )
    except Exception as e:
        logger.warning(f"[customers] vip notification failed: {e}")


@router.patch("/customers/{cid}/vip")
async def patch_customer_vip(cid: str, body: _VipToggle,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Flip the VIP flag on a customer. Auto-stamps ``vip_since`` on ON,
    clears it on OFF, preserves ``vip_note`` across toggles, mirrors the
    change to the ``subscribers`` collection so the VIP Customers
    segment stays in sync, and fires the ``customer.vip_flagged``
    notification when transitioning to True."""
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")

    was_vip = bool(existing.get("is_vip"))
    now_vip = bool(body.is_vip)
    updates: dict = {"is_vip": now_vip}
    if now_vip and not was_vip:
        updates["vip_since"] = now_iso()
    elif not now_vip and was_vip:
        updates["vip_since"] = None
    if body.vip_note is not None:
        updates["vip_note"] = body.vip_note.strip() or None

    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": updates}
    )
    fresh = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    # Sync subscribers + notify on transition to VIP.
    try:
        from services.marketing_subscribers import mirror_customer_updated
        await mirror_customer_updated(tenant["id"], fresh or {})
    except Exception:
        pass
    if now_vip and not was_vip:
        await _emit_vip_flagged(tenant["id"], user, fresh or {})
    return fresh


@router.patch("/customers/{cid}/mobiles")
async def patch_customer_mobiles(cid: str, body: _MobilesUpdate,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    """Replace the ``mobiles`` array. Enforces the 2-entry cap (via
    :mod:`services.customer_multi_contact`) and keeps the scalar
    ``phone`` field synced to the primary entry."""
    from services.customer_multi_contact import normalize_mobiles, MAX_MOBILES, sync_scalars_from_arrays
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")
    if len(body.mobiles or []) > MAX_MOBILES:
        raise HTTPException(400, f"maximum {MAX_MOBILES} mobiles allowed per customer")
    normalized = normalize_mobiles(body.mobiles or [], existing.get("phone"))
    patch = {"mobiles": normalized}
    # Mirror to legacy scalar so RC matcher, invoices, comm-tokens keep working.
    tmp = {"mobiles": normalized, "phone": existing.get("phone")}
    sync_scalars_from_arrays(tmp)
    patch["phone"] = tmp["phone"]
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": patch}
    )
    return await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.patch("/customers/{cid}/emails")
async def patch_customer_emails(cid: str, body: _EmailsUpdate,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Replace the ``emails`` array. Enforces the 3-entry cap and keeps
    the scalar ``email`` field synced to the primary entry."""
    from services.customer_multi_contact import normalize_emails, MAX_EMAILS, sync_scalars_from_arrays
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")
    if len(body.emails or []) > MAX_EMAILS:
        raise HTTPException(400, f"maximum {MAX_EMAILS} emails allowed per customer")
    normalized = normalize_emails(body.emails or [], existing.get("email"))
    patch = {"emails": normalized}
    tmp = {"emails": normalized, "email": existing.get("email")}
    sync_scalars_from_arrays(tmp)
    patch["email"] = tmp["email"]
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": patch}
    )
    return await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


# ─── Phase 12 · Feb 2026 — "Require card on file" override ───────────
class _RequireCardOverridePatch(BaseModel):
    """Body for ``PATCH /api/customers/{cid}`` used exclusively for the
    Phase 12 tri-state override.

    Field is Optional[bool] with a sentinel: passing ``None`` clears
    the override (falls back to the tenant default). Any non-bool /
    non-null value gets a 422 from FastAPI's type coercion — no extra
    validation needed here.
    """
    model_config = ConfigDict(extra="forbid")
    require_card_on_file_override: Optional[bool] = None


@router.patch("/customers/{cid}",
    summary="PATCH customer — Phase 12 partial update (card-on-file override)",
    responses={200: {"description": (
        "Currently only accepts ``require_card_on_file_override`` "
        "(``true`` | ``false`` | ``null``). Admin + manager only. "
        "Returns the freshly-loaded customer with derived "
        "``effective_require_card_on_file`` + ``has_card_on_file`` "
        "recomputed against the tenant default."
    )}})
async def patch_customer(cid: str,
                          body: _RequireCardOverridePatch,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin or manager access required")
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")
    # Distinguish "field present with null value" from "field absent"
    # — Pydantic collapses both to None; we treat the endpoint as a
    # dedicated override setter and always write the value verbatim.
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"require_card_on_file_override": body.require_card_on_file_override,
                    "updated_at": now_iso()}},
    )
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    doc.update(_compute_card_fields(
        doc, bool(tenant.get("require_card_on_file_default", True))))
    return doc


@router.post("/customers/{cid}/send-card-add-link", tags=["customers"],
              operation_id="customers.sendCardAddLink")
async def send_card_add_link(cid: str,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    """Trigger transactional email + SMS with a 30-day SetupIntent
    magic link. Admin + manager only. Rate-limited to 1 request per
    5 minutes per customer."""
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin or manager access required")
    from services.add_card_links import (
        build_add_card_link, ensure_rate_limit,
    )
    from services.marketing.merge_tags import render_context, render_template

    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(404, "Customer not found")
    # 1/5min rate limit (raises 429).
    ensure_rate_limit(cid)

    # Base URL for the magic link — served from the tenant's public
    # domain if configured, else the caller's ``x-forwarded-host`` /
    # env FRONTEND_ORIGIN fallback.
    base_url = (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or (tenant.get("brand") or {}).get("public_origin")
        or ""
    ).strip()
    if not base_url:
        # Last-resort fallback — the app's dev preview host. Still
        # produces a working link when env is unset.
        base_url = "https://poolscape-audit.preview.emergentagent.com"
    link = build_add_card_link(base_url, cid, tenant["id"])

    ctx = render_context(customer=customer, tenant=tenant,
                          add_card_link=link)

    email_tpl = await db.marketing_templates.find_one(
        {"tenant_id": tenant["id"], "code": "add_card_request_email"},
        {"_id": 0},
    )
    sms_tpl = await db.marketing_templates.find_one(
        {"tenant_id": tenant["id"], "code": "add_card_request_sms"},
        {"_id": 0},
    )

    sent_email = False
    sent_sms = False
    trigger_id = f"add_card_request:{cid}:{new_id()[:8]}"

    if email_tpl and customer.get("email"):
        subject_r, _ = render_template(email_tpl.get("subject") or "", ctx)
        body_r, _ = render_template(email_tpl.get("body") or "", ctx)
        try:
            from services.comms_email_adapter import send_email
            import asyncio as _asyncio
            res = await _asyncio.wait_for(send_email(
                tenant_id=tenant["id"], to_email=customer["email"],
                subject=subject_r, html=body_r,
                from_name=(tenant.get("name") or None),
            ), timeout=8.0)
            sent_email = (res or {}).get("status") == "sent" or \
                            (res or {}).get("status") == "sent_no_provider_id"
        except Exception as exc:
            logger.warning(f"[phase12] add-card email send failed: {exc}")
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "email", "kind": "transactional",
            "recipient": customer["email"],
            "subject": subject_r, "body": body_r,
            "trigger_entity": {"kind": "add_card_request", "id": cid},
            "trigger_id": trigger_id,
            "delivered": sent_email,
            "created_at": now_iso(),
        })

    if sms_tpl and customer.get("phone"):
        body_r, _ = render_template(sms_tpl.get("body") or "", ctx)
        try:
            import asyncio as _asyncio
            # Phase G2 · Feb-2026 (TD-G1-1) — plumb tenant_id so the
            # RC adapter honours ``tenants.rc_sms_from_number`` for
            # the add-card send. Positional args + kwarg matches the
            # ``send_sms(to, body, *, tenant_id=None)`` signature.
            await _asyncio.wait_for(
                _asyncio.to_thread(
                    send_sms, customer["phone"], body_r,
                    tenant_id=tenant["id"],
                ),
                timeout=8.0,
            )
            sent_sms = True
        except Exception as exc:
            logger.warning(f"[phase12] add-card sms send failed: {exc}")
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "sms", "kind": "transactional",
            "recipient": customer["phone"],
            "subject": None, "body": body_r,
            "trigger_entity": {"kind": "add_card_request", "id": cid},
            "trigger_id": trigger_id,
            "delivered": sent_sms,
            "created_at": now_iso(),
        })

    return {
        "ok": True,
        "sent_email": sent_email,
        "sent_sms": sent_sms,
        "email_recipient": customer.get("email"),
        "sms_recipient": customer.get("phone"),
    }


# ─── Public add-card magic-link endpoints (no auth) ──────────────────
from fastapi import Body  # noqa: E402
import os  # noqa: E402


@router.get("/customers/add-card/{token}")
async def public_add_card_context(token: str):
    """Public: validate a Phase-12 magic link and return the minimum
    metadata the SetupIntent page needs. NEVER expose full email or
    phone here — a link leak shouldn't reveal PII.

    Feb-2026 · BUG 2 fix — the 404 path here is now structured. The
    most common cause of a valid-JWT-but-missing-customer is a stale
    link minted before a database reseed (typical on preview) or a
    hard-deleted customer. Distinguish those cases from a genuine
    misroute so the frontend can render helpful copy instead of the
    raw "Customer not found" banner.
    """
    from services.add_card_links import decode_add_card_token
    payload = decode_add_card_token(token)
    customer = await db.customers.find_one(
        {"id": payload["customer_id"], "tenant_id": payload["tenant_id"]},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1},
    )
    if not customer:
        # Tenant sanity-probe so we can tell the difference between
        # "customer got hard-deleted" and "token from a completely
        # different env / reseeded DB".
        tenant_exists = bool(await db.tenants.find_one(
            {"id": payload["tenant_id"]}, {"_id": 0, "id": 1}
        ))
        logger.warning(
            "[phase12] add-card token points at unknown customer "
            "customer_id=%s tenant_id=%s tenant_exists=%s",
            payload["customer_id"], payload["tenant_id"], tenant_exists,
        )
        raise HTTPException(
            status_code=404,
            detail={
                "code": "stale_add_card_link",
                "message": (
                    "This add-card link is no longer valid. Please contact "
                    "your service provider to send a fresh link."
                ),
                "tenant_exists": tenant_exists,
            },
        )
    tenant = await db.tenants.find_one(
        {"id": payload["tenant_id"]},
        {"_id": 0, "name": 1, "brand": 1, "support_phone": 1, "phone": 1},
    ) or {}
    # Mask the customer name — first name + last-initial only.
    first = (customer.get("first_name")
              or (customer.get("name") or "").split(" ", 1)[0]
              or "")
    last = (customer.get("last_name") or "")
    masked = first + (f" {last[0]}." if last else "")
    return {
        "customer_name_masked": masked or "Customer",
        "tenant_name": tenant.get("name") or "",
        "tenant_support_phone": (tenant.get("support_phone")
                                    or tenant.get("phone") or ""),
        "stripe_publishable_key": os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
    }


@router.post("/customers/add-card/{token}/setup-intent")
async def public_add_card_setup_intent(token: str):
    """Phase 47c · Feb 2026 — RESTORED after the Phase LZ4 retirement.
    Direct Stripe SetupIntent flow (no Lumino / Zapier) so the customer
    can attach a card via the public magic-link page.

    Auth: JWT-only (no bearer). ``sub="add_card"`` scope verified by
    :func:`services.add_card_links.decode_add_card_token`.
    """
    from services.add_card_links import decode_add_card_token
    from services.payments import stripe_charge as stripe_svc
    payload = decode_add_card_token(token)
    try:
        out = await stripe_svc.create_setup_intent(
            tenant_id=payload["tenant_id"],
            customer_id=payload["customer_id"],
            actor_user_id=None,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.warning("[phase47c] public setup_intent failed: %s", exc)
        raise HTTPException(502, "payment_setup_unavailable")
    # Never expose the internal Stripe customer id via the magic link
    # payload — the frontend only needs the client_secret + pk.
    return {
        "client_secret": out.get("client_secret"),
        "setup_intent_id": out.get("setup_intent_id"),
        "publishable_key": out.get("publishable_key")
                                or os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
        "mode": out.get("mode"),
    }


@router.post("/customers/add-card/{token}/attach")
async def public_add_card_attach(token: str, body: dict = Body(...)):
    """Phase 47c · Feb 2026 — companion attach endpoint for the public
    magic-link flow. Called by the browser once ``stripe.confirmSetup``
    returns a ``payment_method`` id. Mirrors the PM into
    ``db.payment_methods`` via the same helper the authenticated flow uses.
    """
    from services.add_card_links import decode_add_card_token
    from services.payments import stripe_charge as stripe_svc
    payload = decode_add_card_token(token)
    pm_id = (body or {}).get("payment_method_id") or ""
    if not pm_id:
        raise HTTPException(422, "payment_method_id required")
    set_default = bool((body or {}).get("set_default", True))
    try:
        row = await stripe_svc.attach_payment_method(
            tenant_id=payload["tenant_id"],
            customer_id=payload["customer_id"],
            payment_method_id=pm_id,
            set_default=set_default,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.warning("[phase47c] public attach failed: %s", exc)
        raise HTTPException(502, "attach_failed")
    # Return only the safe subset (last4 / brand / expiry) — no Stripe ids.
    return {
        "last4": row.get("last4") or "",
        "brand": row.get("brand") or "",
        "exp_month": row.get("exp_month"),
        "exp_year": row.get("exp_year"),
        "is_default": bool(row.get("is_default")),
    }


# ═════════════════════════════════════════════════════════════════════
# Phase K43 · Feb-2026 — Admin bank-account verify actions.
#
# Two entrypoints on the customer-detail admin surface:
#
#   * ``verify-microdeposits`` — admin enters the two cent-amount
#     descriptors Stripe sent to the customer's account.  Calls
#     ``stripe.PaymentMethod.verify_microdeposits`` and syncs the
#     mirror row's ``verification_status``.
#   * ``re-verify``           — Hector's case: unverified PM with
#     no live SetupIntent.  Mints a fresh SetupIntent that will
#     drive the Financial Connections modal on the customer's next
#     portal visit AND emails them the magic add-card link so they
#     can complete it out-of-band.
# ═════════════════════════════════════════════════════════════════════

class _VerifyMicroDepositsBody(BaseModel):
    """Body for the admin micro-deposit verify action.

    Stripe accepts EITHER an ``amounts`` array (two ints, in the
    account's smallest currency unit — cents for USD) OR a
    ``descriptor_code`` (the six-digit code Stripe includes on the
    single $0.01 verification deposit).  The frontend picks one.
    """
    amounts_cents: Optional[List[int]] = None
    descriptor_code: Optional[str] = None


@router.post(
    "/customers/{cid}/bank-accounts/{pm_id}/verify-microdeposits",
    tags=["customers", "payments"],
)
async def admin_verify_bank_microdeposits(
    cid: str,
    pm_id: str,
    body: _VerifyMicroDepositsBody = Body(...),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """K43 · Admin action — verify a customer's ACH bank via micro-deposits.

    Admin + super only (``require_admin`` already blocks non-admin roles).
    Delegates to ``stripe.PaymentMethod.verify_microdeposits`` then
    stamps the local mirror row's ``verification_status`` so the K38
    bulk modal + autobilling filter recognise the bank as chargeable.
    """
    row = await db.payment_methods.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid,
         "provider_payment_method_id": pm_id, "provider": "stripe"},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "bank_account_not_found")
    if (row.get("type") or "") != "us_bank_account":
        raise HTTPException(422, "not_a_bank_account")

    if not body.amounts_cents and not body.descriptor_code:
        raise HTTPException(422, "amounts_cents_or_descriptor_code_required")
    if body.amounts_cents is not None:
        if (not isinstance(body.amounts_cents, list)
                or len(body.amounts_cents) != 2
                or not all(isinstance(a, int) and 0 < a < 100
                           for a in body.amounts_cents)):
            raise HTTPException(
                422,
                "amounts_cents must be two integers between 1 and 99",
            )

    from services.payments import stripe_charge as stripe_svc
    stripe_svc._init_api_key()
    kwargs: Dict[str, Any] = {}
    if body.amounts_cents:
        kwargs["amounts"] = body.amounts_cents
    if body.descriptor_code:
        kwargs["descriptor_code"] = body.descriptor_code
    try:
        pm_obj = await stripe_svc._to_thread(
            stripe_svc._stripe.PaymentMethod.verify_microdeposits,
            pm_id,
            **kwargs,
        )
    except Exception as exc:
        code = getattr(getattr(exc, "error", None), "code", None) or ""
        msg = str(exc)
        logger.warning(
            "[k43] microdeposit verify failed cid=%s pm=%s code=%s: %s",
            cid, pm_id, code, msg,
        )
        if code in ("payment_method_microdeposit_verification_amounts_mismatch",
                     "payment_method_microdeposit_verification_amounts_invalid",
                     "payment_method_microdeposit_verification_attempts_exceeded",
                     "payment_method_microdeposit_verification_descriptor_code_mismatch",
                     "payment_method_microdeposit_failed"):
            raise HTTPException(400, code)
        raise HTTPException(502, "stripe_error")

    # Sync the mirror row so downstream filters see the new status.
    pm_dict = stripe_svc._asdict(pm_obj) if pm_obj else {}
    new_status = "verified"
    await db.payment_methods.update_one(
        {"tenant_id": tenant["id"], "customer_id": cid,
         "provider_payment_method_id": pm_id, "provider": "stripe"},
        {"$set": {"verification_status": new_status,
                   "verified_at": now_iso(),
                   "verified_by_user_id": user.get("id") or ""}},
    )
    # Audit trail so ops can see who cleared the backlog + when.
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "bank_verification_completed",
            "actor_id": user.get("id") or "",
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "payment_method_id": pm_id,
            "method": "microdeposit_amounts" if body.amounts_cents else "microdeposit_descriptor",
            "timestamp": now_iso(),
            "source": "admin_customer_detail",
        })
    except Exception:  # pragma: no cover
        pass
    return {"ok": True, "verification_status": new_status,
            "payment_method_id": pm_id}


@router.post(
    "/customers/{cid}/bank-accounts/{pm_id}/re-verify",
    tags=["customers", "payments"],
)
async def admin_reverify_bank(
    cid: str,
    pm_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """K43 · Admin action — re-open the ACH verification flow for a
    bank that's unverified but has no live SetupIntent.

    Behaviour:
      1. Mint a fresh ``us_bank_account`` SetupIntent (Financial
         Connections-forced by the K43 SetupIntent options).  This
         returns a ``client_secret`` the frontend can use to open
         the in-portal Financial Connections modal.
      2. Send the customer the standard 30-day magic add-card email
         so they can complete verification from their inbox if
         they'd rather not log into the portal right now.
      3. Mirror-row is stamped ``pending_reverification`` so the
         admin UI reflects the new state without waiting for a webhook.
    """
    row = await db.payment_methods.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid,
         "provider_payment_method_id": pm_id, "provider": "stripe"},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "bank_account_not_found")
    if (row.get("type") or "") != "us_bank_account":
        raise HTTPException(422, "not_a_bank_account")

    from services.payments import stripe_charge as stripe_svc
    try:
        setup = await stripe_svc.create_setup_intent(
            tenant_id=tenant["id"],
            customer_id=cid,
            actor_user_id=user.get("id"),
            payment_method_types=["us_bank_account"],
        )
    except Exception as exc:
        logger.warning("[k43] re-verify SetupIntent failed cid=%s: %s", cid, exc)
        raise HTTPException(502, "stripe_setupintent_failed")

    # Fire the transactional email if the customer has one on file.
    # Reuses the same magic-link email machinery as the admin
    # "Send add-card link" action — best-effort, never blocks the
    # SetupIntent return.  We call the endpoint's underlying helper
    # by lazy-importing the send_email path directly.
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "email": 1, "name": 1},
    ) or {}
    email_sent = False
    if cust.get("email"):
        try:
            from services.add_card_links import build_add_card_link
            from services.comms_email_adapter import send_email
            import asyncio as _asyncio
            base_url = (
                os.environ.get("PUBLIC_FRONTEND_ORIGIN")
                or (tenant.get("brand") or {}).get("public_origin")
                or "https://poolscape-audit.preview.emergentagent.com"
            ).strip()
            link = build_add_card_link(base_url, cid, tenant["id"])
            subject = "Please verify your bank account"
            html = (
                f"<p>Hi {cust.get('name') or 'there'},</p>"
                f"<p>Please complete your ACH bank verification so we can process your recurring payments:</p>"
                f'<p><a href="{link}">Verify bank account</a></p>'
                f"<p>This link is valid for 30 days.</p>"
            )
            res = await _asyncio.wait_for(send_email(
                tenant_id=tenant["id"], to_email=cust["email"],
                subject=subject, html=html,
                from_name=(tenant.get("name") or None),
            ), timeout=8.0)
            email_sent = (res or {}).get("status", "").startswith("sent")
        except Exception as exc:  # pragma: no cover — email best-effort
            logger.info(
                "[k43] re-verify email skipped for cid=%s: %s", cid, exc,
            )

    await db.payment_methods.update_one(
        {"tenant_id": tenant["id"], "customer_id": cid,
         "provider_payment_method_id": pm_id, "provider": "stripe"},
        {"$set": {"verification_status": "pending_reverification",
                   "reverify_setup_intent_id": setup.get("setup_intent_id") or "",
                   "reverify_requested_at": now_iso(),
                   "reverify_requested_by_user_id": user.get("id") or ""}},
    )
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "bank_reverification_requested",
            "actor_id": user.get("id") or "",
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "payment_method_id": pm_id,
            "setup_intent_id": setup.get("setup_intent_id") or "",
            "email_sent_to": cust.get("email") or "",
            "email_sent": email_sent,
            "timestamp": now_iso(),
            "source": "admin_customer_detail",
        })
    except Exception:  # pragma: no cover
        pass
    return {
        "ok": True,
        "verification_status": "pending_reverification",
        "setup_intent_id": setup.get("setup_intent_id"),
        "client_secret": setup.get("client_secret"),
        "publishable_key": setup.get("publishable_key"),
        "email_sent": email_sent,
    }


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · P41 — CSV import for customers (web-only, admin/manager).
# ─────────────────────────────────────────────────────────────────────
# Import contract (locked with user):
#   * 12 fields, header row required, case/space/underscore tolerant.
#   * User picks Active OR Inactive per import; every row lands with
#     that ``is_active`` flag.
#   * Duplicates by email OR phone (against non-soft-deleted rows in
#     the same tenant) are SKIPPED — no update, no create.
#   * Required per-row: First Name + Last Name + Service Address.
#   * Empty billing address → falls back to service address.
#   * Batch cap 5000. Reject BEFORE any insert.
#   * Geocoding is queued as a fire-and-forget BackgroundTask with a
#     5-concurrent-request throttle.
#   * Single ``customer_csv_import`` audit-log entry per call.
# ═════════════════════════════════════════════════════════════════════
from fastapi import UploadFile, File, Form, BackgroundTasks
import csv as _p41_csv
import io as _p41_io
import re as _p41_re

from utils import not_deleted_filter as _p41_not_deleted

_P41_REQUIRED_HEADERS = (
    "first_name", "last_name", "service_address", "service_city",
    "service_state", "service_zip_code", "billing_address", "billing_city",
    "billing_state", "billing_zip_code", "email", "phone_number",
)
_P41_ROW_REQUIRED = ("first_name", "last_name", "service_address")
_P41_MAX_ROWS = 5000
_P41_GEOCODE_CONCURRENCY = 5
# The 10 non-name customer fields eligible for fill-in-blanks merge.
# Names are handled separately (only filled when BOTH first + last are
# blank on the existing row).
_P41_MERGE_FIELDS = (
    ("service_address", "service_address"),
    ("service_city",    "service_city"),
    ("service_state",   "service_state"),
    ("service_zip",     "service_zip_code"),
    ("billing_address", "billing_address"),
    ("billing_city",    "billing_city"),
    ("billing_state",   "billing_state"),
    ("billing_zip",     "billing_zip_code"),
    ("email",           "email"),
    ("phone",           "phone_number"),
)


def _p41_is_blank(value) -> bool:
    """Field-is-missing helper. ``None`` / missing / empty / whitespace
    are blank. ``False`` and ``0`` are populated (spec)."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _p41_normalize_header(raw: str) -> str:
    """Header normalizer: strip, lower, whitespace→underscore.
    ``First Name`` → ``first_name``; ``FIRST_NAME`` → ``first_name``."""
    return _p41_re.sub(r"\s+", "_", (raw or "").strip().lower())


def _p41_normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _p41_normalize_phone(raw: str) -> str:
    """Strip everything except digits and an optional leading ``+``.
    Empty string stays empty."""
    s = (raw or "").strip()
    if not s:
        return ""
    has_plus = s.startswith("+")
    digits = _p41_re.sub(r"\D", "", s)
    return ("+" + digits) if has_plus else digits


_P41_EMAIL_RE = _p41_re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _p41_run_geocode(customer_id: str, tenant_id: str,
                             sem) -> None:
    try:
        from services.google_maps.geocoding import (
            geocode_and_persist_customer as _gp,
        )
        async with sem:
            await _gp(customer_id, tenant_id)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("[P41] geocode failed customer=%s err=%s",
                          customer_id, exc)


async def _p41_geocode_batch(customer_ids: List[str], tenant_id: str) -> None:
    """Background driver — throttles concurrent geocodes to 5."""
    import asyncio as _a
    sem = _a.Semaphore(_P41_GEOCODE_CONCURRENCY)
    await _a.gather(*[
        _p41_run_geocode(cid, tenant_id, sem) for cid in customer_ids
    ])


@router.post("/customers/import-csv", tags=["customers"],
                operation_id="customers.importCsv")
async def import_customers_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_status: str = Form(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # RBAC — super_admin + admin + manager. Tech 403.
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "owner", "manager"):
        raise HTTPException(403, "Admin or manager access required")

    ts = (target_status or "").strip().lower()
    if ts not in ("active", "inactive"):
        raise HTTPException(400, "target_status must be 'active' or 'inactive'")
    is_active_target = ts == "active"

    # Decode + parse CSV.
    try:
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "empty_file")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                raise HTTPException(400, "unsupported_file_type")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "unsupported_file_type")

    # Header sniff — accept CSV only. A completely non-CSV upload will
    # either fail here or produce a row-count of 0 with a missing-header
    # error, so both surface a clear 400.
    reader = _p41_csv.DictReader(_p41_io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, {"error": "unsupported_file_type",
                                       "detail": "no_header_row"})
    fieldmap = {_p41_normalize_header(fn): fn for fn in reader.fieldnames}
    missing = [h for h in _P41_REQUIRED_HEADERS if h not in fieldmap]
    if missing:
        raise HTTPException(400, {"error": "missing_headers",
                                       "missing_headers": missing})

    # Stream all rows into memory FIRST so we can enforce the 5000 cap
    # before doing any writes (spec: never partial-import beyond cap).
    rows: List[dict] = []
    for r in reader:
        rows.append(r)
        if len(rows) > _P41_MAX_ROWS:
            raise HTTPException(400, {"error": "too_many_rows",
                                           "max_rows": _P41_MAX_ROWS})

    tenant_id = tenant["id"]
    actor_id = user.get("id") or ""

    def _pick(row: dict, key: str) -> str:
        src = fieldmap.get(key)
        if not src:
            return ""
        return (row.get(src) or "").strip()

    created_ids: List[str] = []
    updated_count = 0
    skipped_no_new_data = 0
    merges_sample: List[dict] = []
    row_errors: List[dict] = []

    for idx, row in enumerate(rows, start=2):  # header = row 1
        try:
            first_name = _pick(row, "first_name")
            last_name = _pick(row, "last_name")
            service_address = _pick(row, "service_address")

            if not (first_name and last_name and service_address):
                row_errors.append({"row": idx, "reason": "missing_required"})
                continue

            email_norm = _p41_normalize_email(_pick(row, "email"))
            if email_norm and not _P41_EMAIL_RE.match(email_norm):
                row_errors.append({"row": idx, "reason": "invalid_email"})
                continue

            phone_norm = _p41_normalize_phone(_pick(row, "phone_number"))
            if phone_norm and len(_p41_re.sub(r"\D", "", phone_norm)) < 7:
                row_errors.append({"row": idx, "reason": "invalid_phone"})
                continue

            # Billing-address fallback applies to the CSV row BEFORE the
            # merge check (per spec) so the filled billing_address
            # participates in the fill-in-blanks pass normally.
            b_addr = _pick(row, "billing_address")
            if not b_addr:
                b_addr = service_address
                b_city = _pick(row, "service_city")
                b_state = _pick(row, "service_state")
                b_zip = _pick(row, "service_zip_code")
            else:
                b_city = _pick(row, "billing_city")
                b_state = _pick(row, "billing_state")
                b_zip = _pick(row, "billing_zip_code")

            s_city = _pick(row, "service_city")
            s_state = _pick(row, "service_state")
            s_zip = _pick(row, "service_zip_code")

            # ── Match candidate selection ──────────────────────────
            # ``not_deleted_filter()`` scopes the match to live rows so
            # a CSV row matching only a soft-deleted customer creates
            # a NEW row (spec).
            matched_by_email = None
            matched_by_phone = None
            if email_norm:
                matched_by_email = await db.customers.find_one({
                    "tenant_id": tenant_id, **_p41_not_deleted(),
                    "email": email_norm,
                }, {"_id": 0})
            if phone_norm:
                matched_by_phone = await db.customers.find_one({
                    "tenant_id": tenant_id, **_p41_not_deleted(),
                    "phone": phone_norm,
                }, {"_id": 0})

            # Ambiguous: email hits one customer, phone hits a
            # different customer. Do NOT auto-pick.
            if (matched_by_email and matched_by_phone
                    and matched_by_email.get("id")
                        != matched_by_phone.get("id")):
                row_errors.append({
                    "row": idx, "reason": "ambiguous_duplicate",
                    "detail": (f"matches customer {matched_by_email['id']} "
                                  f"by email and customer "
                                  f"{matched_by_phone['id']} by phone"),
                })
                continue

            existing = matched_by_email or matched_by_phone

            if existing:
                # ── Cross-status flag ──────────────────────────────
                # If the row matches a customer whose is_active differs
                # from the requested target list, emit a
                # ``matched_in_other_status`` row-flag so the admin
                # sees in the post-import report that the row did
                # NOT move to the target list. The merge itself still
                # proceeds normally (spec: is_active is never flipped).
                existing_is_active = bool(existing.get("is_active", True))
                if existing_is_active != is_active_target:
                    if existing_is_active:
                        _msg = ("Customer exists in Active list; row "
                                    "will not be moved to Inactive. Fields "
                                    "merged in place.")
                    else:
                        _msg = ("Customer exists in Inactive list; row "
                                    "will not be moved to Active. Fields "
                                    "merged in place.")
                    row_errors.append({
                        "row": idx,
                        "reason": "matched_in_other_status",
                        "detail": _msg,
                    })

                # ── Fill-in-blanks merge ───────────────────────────
                csv_field_values = {
                    "service_address": service_address,
                    "service_city":    s_city,
                    "service_state":   s_state,
                    "service_zip":     s_zip,
                    "billing_address": b_addr,
                    "billing_city":    b_city,
                    "billing_state":   b_state,
                    "billing_zip":     b_zip,
                    "email":           email_norm,
                    "phone":           phone_norm,
                }
                to_set: dict = {}
                for db_key, _csv_key in _P41_MERGE_FIELDS:
                    incoming = csv_field_values.get(db_key) or ""
                    if not incoming:
                        continue
                    if _p41_is_blank(existing.get(db_key)):
                        to_set[db_key] = incoming
                # Names — fill only when BOTH existing first + last
                # are blank (avoid partial-name overwrites, spec).
                if (_p41_is_blank(existing.get("first_name"))
                        and _p41_is_blank(existing.get("last_name"))):
                    to_set["first_name"] = first_name
                    to_set["last_name"] = last_name
                    to_set["name"] = f"{first_name} {last_name}".strip()

                if not to_set:
                    skipped_no_new_data += 1
                    continue

                # NEVER flip is_active on merge (spec).
                to_set["updated_at"] = now_iso()
                await db.customers.update_one(
                    {"id": existing["id"], "tenant_id": tenant_id},
                    {"$set": to_set},
                )
                updated_count += 1
                if len(merges_sample) < 20:
                    merges_sample.append({
                        "row": idx,
                        "customer_id": existing["id"],
                        "fields_filled": [k for k in to_set
                                              if k != "updated_at"],
                    })
                continue

            # ── No match — insert a brand-new customer ─────────────
            composed_name = f"{first_name} {last_name}".strip()
            doc = {
                "id": new_id(),
                "tenant_id": tenant_id,
                "first_name": first_name,
                "last_name": last_name,
                "name": composed_name,
                "email": email_norm,
                "phone": phone_norm,
                "address": ", ".join(p for p in [
                    service_address, s_city,
                    f"{s_state} {s_zip}".strip() if (s_state or s_zip) else "",
                ] if p),
                "service_address": service_address,
                "service_city": s_city,
                "service_state": s_state,
                "service_zip": s_zip,
                "billing_address": b_addr,
                "billing_city": b_city,
                "billing_state": b_state,
                "billing_zip": b_zip,
                "tags": [],
                "is_active": is_active_target,
                "status": "active" if is_active_target else "inactive",
                "is_muted": False,
                "created_at": now_iso(),
                "created_by": actor_id,
                "imported_at": now_iso(),
                "import_source": "csv",
            }
            _sync_customer_names(doc)
            await db.customers.insert_one(doc)
            created_ids.append(doc["id"])
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            row_errors.append({
                "row": idx, "reason": "unknown_error",
                "detail": str(exc)[:200],
            })

    # ``matched_in_other_status`` is an INFO row-flag, not an error.
    # Exclude it from the ``errored`` count while keeping the entry
    # in ``row_errors`` for admin visibility (spec).
    _errored_count = sum(
        1 for e in row_errors
        if e.get("reason") != "matched_in_other_status")

    # Audit log — single summary entry per import.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "actor_id": actor_id, "actor_email": user.get("email"),
            "event": "customer_csv_import", "at": now_iso(),
            "payload": {
                "target_status": ts,
                "total_rows": len(rows),
                "created": len(created_ids),
                "updated": updated_count,
                "skipped_no_new_data": skipped_no_new_data,
                "errored": _errored_count,
                "row_errors_sample": row_errors[:20],
                "merges_sample": merges_sample,
                # Observable from any process — the number of newly-
                # created customer ids queued for background geocoding.
                # Merged rows are intentionally NOT re-geocoded.
                "geocode_queued": len(created_ids),
            },
        })
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("[P41] audit insert failed: %s", exc)

    # Queue background geocoding — only for NEW customers. Merged rows
    # keep whatever geocoding state the existing customer already has
    # (spec: don't re-geocode).
    if created_ids:
        background_tasks.add_task(
            _p41_geocode_batch, list(created_ids), tenant_id)

    return {
        "ok": True,
        "created": len(created_ids),
        "updated": updated_count,
        "skipped_no_new_data": skipped_no_new_data,
        "errored": _errored_count,
        "row_errors": row_errors,
    }
