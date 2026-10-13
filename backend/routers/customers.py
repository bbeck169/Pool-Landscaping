# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Body
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone, timedelta
import uuid

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, require_admin_or_manager,
                   send_sms, notify_customer, auth_response)
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
    # Feb-2026 · First-access denorm (stamped ONCE on the customer's
    # first completed portal sign-in — never overwritten).
    portal_first_login_at: Optional[str] = None
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
# Feb-2026 hotfix · Shared count/list predicate — the K49b guard.
# ─────────────────────────────────────────────────────────────────
def _valid_customer_id_predicate() -> Dict[str, Any]:
    """Mongo predicate that excludes legacy customer docs missing a
    top-level ``id`` field.

    Applied to ``q`` inside ``list_customers`` BEFORE both the
    ``count_only=true`` branch AND the list branch so the two
    queries never drift. Was previously enforced only Python-side
    (see ``_k49b_kept`` below), which caused the "Never logged in"
    chip (and every other count/list pair reading ``q``) to drift
    by the number of K49b-orphan rows in the tenant. The K49b
    migration seeds ``id = str(_id)`` on boot; this predicate is
    the runtime guard for the window before the migration lands
    and for any future doc that slips in without an ``id``.
    """
    return {"id": {"$exists": True, "$nin": [None, ""]}}


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
# Feb-2026 · Chase Stalled Invites — ``sort=stalest_first`` pipeline.
# Sorts by staleness of the portal invite (oldest first). Primary
# key: ``temp_password_issued_at`` (stamped by the portal-invite
# path in ``portal_admin._upsert_customer_user``). Fallback:
# ``created_at`` (some legacy customers were promoted to has_login
# without a dated invite stamp). Nulls-last: rows with neither
# stamp land at the END (they haven't been chased yet AND have no
# create date — outliers).
#
# Case-insensitive coercion is not needed here — every stamp is an
# ISO-8601 UTC string, so lexicographic ASC == chronological ASC.
# ─────────────────────────────────────────────────────────────────
def _stalest_first_pipeline(
    match: dict,
    *,
    skip: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """Aggregation pipeline for the ``sort=stalest_first`` order.
    See module comment for the primary/fallback/nulls-last rules."""
    stages: List[dict] = [
        {"$match": match},
        {"$addFields": {
            # Coerce every stamp into a string. ``$ifNull`` chain
            # picks the first non-null in [invite, created]. If
            # BOTH are missing/null, we synthesise a far-future
            # sentinel so those docs sort LAST on ASC.
            "_stale_key": {
                "$ifNull": [
                    "$temp_password_issued_at",
                    {"$ifNull": ["$created_at", "9999-12-31T23:59:59Z"]},
                ],
            },
            "_has_stale_key": {
                "$cond": [
                    {"$or": [
                        {"$ifNull": ["$temp_password_issued_at", False]},
                        {"$ifNull": ["$created_at", False]},
                    ]},
                    1, 0,
                ],
            },
        }},
        {"$sort": {
            "_has_stale_key": -1,   # 1 (has any stamp) before 0 (nulls-last)
            "_stale_key": 1,        # ASC → oldest (stalest) first
            "_id": 1,
        }},
    ]
    if skip:
        stages.append({"$skip": int(skip)})
    if limit is not None:
        stages.append({"$limit": int(limit)})
    stages.append({"$project": {
        "_id": 0,
        "_stale_key": 0,
        "_has_stale_key": 0,
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
    # Phase K68 · Feb-2026 — overlapping counts for the 5 tab
    # buckets (active / inactive / muted / waitlist / all). Reflects
    # the same search + city + tag + data-quality + portal-status
    # filter surface the paginated ``total`` uses; the per-tab
    # status predicates (waitlisted / is_active / is_muted) are
    # applied on top of the shared base per bucket.
    counts_by_status: Optional[Dict[str, int]] = None


# ═════════════════════════════════════════════════════════════════════
# Phase P31 · Feb-2026 — Consolidated customer counts endpoint.
#
# Replaces 9 separate ``count_only=true`` fanout calls the customers
# list page previously fired on every scope change + filter toggle.
# One endpoint, one round trip, nine numbers.
#
# Response envelope
# -----------------
# * Tab counts (composed with the caller-provided global chips —
#   the same ``p43Suffix`` the FE assembles from
#   ``missing_email`` / ``missing_phone`` / ``missing_address`` /
#   ``portal_activated`` / ``has_payment_method`` / ``city`` /
#   ``tags``):
#     ``active`` / ``inactive`` / ``muted`` / ``waitlist``
# * Standalone badge counts (STABLE — deliberately NOT composed
#   with the caller's chips so the badges don't jump as the admin
#   narrows the list, matching the pre-P31 "stability" contract
#   for each of these five badges):
#     ``missing_address`` / ``portal_activated`` /
#     ``portal_not_activated`` / ``no_payment_method`` /
#     ``never_logged_in``
#
# The ``muted`` / ``waitlist`` fields are admin-only (matches the
# per-count call gates in the pre-P31 FE) — returned as ``None``
# for tech/customer callers so the FE doesn't need a second call
# to fetch them.
#
# All 9 counts execute via ``asyncio.gather`` so wall-clock ≈
# max(individual count query), not sum. Reuses the exact predicate
# construction from ``list_customers(count_only=True)`` (same
# module, same shared helpers) so byte-for-byte parity with the
# 9-call fanout is guaranteed.
# ═════════════════════════════════════════════════════════════════════
class CustomerCountsResponse(BaseModel):
    active: int
    inactive: int
    muted: Optional[int] = None
    waitlist: Optional[int] = None
    # Feb-2026 · CUS-perf v3 — admin-only ``All`` tab total, added so
    # ``CustomersList.jsx`` can consume ``/customers/counts`` as the
    # SINGLE source of truth for every tab badge (see R2 ruling in
    # the CUS-perf v3 recon).  Defined as ``active + inactive + muted``
    # to mirror the legacy ``counts_by_status.all`` semantics
    # (waitlist rows are a labelling overlay on top of active/inactive
    # rather than an exclusive bucket; the ``all`` total intentionally
    # does NOT include waitlist as a separate summand).  ``None`` for
    # non-admin callers (matches the admin-gate the ``All`` tab
    # already enforces in the FE).
    all: Optional[int] = None
    missing_address: int
    portal_activated: int
    portal_not_activated: int
    no_payment_method: int
    never_logged_in: int


@router.get("/customers/counts", response_model=CustomerCountsResponse,
              summary="Consolidated customer counts",
              tags=["customers"],
              operation_id="customers.counts")
async def customer_counts(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    # Global chips — apply to the tab counts, ignored by the
    # standalone badges (per the pre-P31 stability contract).
    missing_email: Optional[bool] = False,
    missing_phone: Optional[bool] = False,
    missing_address: Optional[bool] = False,
    portal_activated: Optional[bool] = None,
    has_payment_method: Optional[bool] = None,
    city: Optional[str] = None,
    tags: Optional[List[str]] = Query(None),
):
    """Return the nine counts the Customers list page displays, in
    a single envelope. Replaces the pre-P31 nine-call ``count_only``
    fanout.

    Delegates each count to ``list_customers(count_only=True, ...)``
    with the appropriate flag combination so the predicate logic
    is DRY — a future filter tweak in ``list_customers`` propagates
    automatically. All nine counts fire concurrently via
    ``asyncio.gather``.
    """
    import asyncio as _asyncio
    from fastapi.params import Query as _QueryParam
    # Direct-callers (tests bypassing FastAPI's DI) receive the
    # ``Query(None)`` sentinel as the default rather than ``None``.
    # Coerce back so the downstream ``list_customers`` doesn't
    # inherit a Query object where it expects a scalar / list.
    if isinstance(tags, _QueryParam):
        tags = None
    if isinstance(city, _QueryParam):
        city = None
    role = (user.get("role") or "").lower()
    is_admin = role in ("admin", "super_admin", "manager", "owner")

    async def _one(**overrides):
        """Invoke the shared list-customers count branch with the
        caller's global chips + a per-count override. Returns the
        integer count (never raises — a permission failure downstream
        would surface as 403, which we let bubble)."""
        base = {
            "user": user, "tenant": tenant,
            # Explicit ``None`` defaults for every list_customers
            # param that isn't part of the caller's chip surface —
            # keeps direct-call behavior identical to the FastAPI
            # HTTP path.
            "search": None, "tag": None, "tags": tags,
            "city": city,
            "waitlisted": None, "unscheduled": None,
            "is_active": None, "missing_card": None,
            "missing_email": missing_email,
            "missing_phone": missing_phone,
            "missing_address": missing_address,
            "portal_activated": portal_activated,
            "portal_invited": None,
            "first_access": None,
            "portal_status": None,
            "is_muted": None,
            "has_payment_method": has_payment_method,
            "count_only": True,
            "include_deleted": False,
            "include_merged": False,
            "page": None, "page_size": None,
            "sort": "created_desc",
        }
        base.update(overrides)
        res = await list_customers(**base)
        # ``count_only=True`` branch returns ``{"count": N}`` (dict)
        # OR a ``CustomerListCount`` model — coerce to int.
        if hasattr(res, "count"):
            return int(res.count)
        return int((res or {}).get("count", 0))

    async def _stable(**overrides):
        """Standalone-badge count — same as ``_one`` but ignores the
        caller's global chips so the badge number stays stable as
        the admin narrows the list (pre-P31 stability contract)."""
        base = {
            "user": user, "tenant": tenant,
            "search": None, "tag": None, "tags": None,
            "city": None,
            "waitlisted": None, "unscheduled": None,
            "is_active": None, "missing_card": None,
            "missing_email": False, "missing_phone": False,
            "missing_address": False,
            "portal_activated": None,
            "portal_invited": None,
            "first_access": None,
            "portal_status": None,
            "is_muted": None,
            "has_payment_method": None,
            "count_only": True,
            "include_deleted": False,
            "include_merged": False,
            "page": None, "page_size": None,
            "sort": "created_desc",
        }
        base.update(overrides)
        res = await list_customers(**base)
        if hasattr(res, "count"):
            return int(res.count)
        return int((res or {}).get("count", 0))

    # Kick off all counts concurrently. Non-admin skips muted +
    # waitlist (which 403 for tech in the underlying handler).
    tasks = {
        "active": _one(is_active=True),
        "inactive": _one(is_active=False),
        "missing_address": _stable(missing_address=True),
        "portal_activated": _stable(portal_activated=True),
        "portal_not_activated": _stable(portal_activated=False),
        "no_payment_method": _stable(has_payment_method=False),
        "never_logged_in": _stable(first_access="never"),
    }
    if is_admin:
        tasks["muted"] = _one(is_muted=True)
        tasks["waitlist"] = _one(waitlisted=True)

    keys = list(tasks.keys())
    values = await _asyncio.gather(*tasks.values())
    payload = dict(zip(keys, values))

    # Feb-2026 · CUS-perf v3 (R2 ruling) — the ``All`` tab total.
    # Admin-only.  Backend is single source of truth so the FE
    # doesn't need to derive this from the individual buckets.
    # Formula mirrors the pre-refactor ``counts_by_status.all``
    # semantics: waitlist rows overlap active/inactive (a waitlist
    # customer is still active-or-inactive) so we do NOT add
    # waitlist as a separate summand.  The paginated list envelope's
    # ``counts_by_status.all`` (kept as a vestigial alias per R5)
    # uses the same predicate.
    all_total: Optional[int] = None
    if is_admin:
        all_total = (int(payload.get("active", 0))
                       + int(payload.get("inactive", 0))
                       + int(payload.get("muted", 0)))

    return CustomerCountsResponse(
        active=payload["active"],
        inactive=payload["inactive"],
        muted=payload.get("muted"),
        waitlist=payload.get("waitlist"),
        all=all_total,
        missing_address=payload["missing_address"],
        portal_activated=payload["portal_activated"],
        portal_not_activated=payload["portal_not_activated"],
        no_payment_method=payload["no_payment_method"],
        never_logged_in=payload["never_logged_in"],
    )


# ══════════════════════════════════════════════════════════════════
# Feb-2026 · Customers list — Service Category distinct-values.
#
# Powers the Customers-list Category filter dropdown: fetches the
# distinct ``customers.service_category`` values actually in use
# within the caller's tenant, with per-value counts so operators
# see "Pool (142)" style labels instead of a bare option list.
#
# Legacy ``?service_category=`` filter on ``/customers`` is NOT
# touched — its pool∪both / landscaping∪both union semantics
# backing the dashboard-tile deep-links stay verbatim. This
# endpoint is read-only metadata; the dropdown reads it for
# option labels + custom-category discovery.
#
# Tenant-scoped, non-deleted-only. Auth gate matches the companion
# ``list_customers`` endpoint (``get_current_user`` — role filter
# happens inside the search ladder).
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/customers/service-categories",
    summary="Distinct service_category values + counts for the "
             "Customers list filter dropdown",
    tags=["customers"],
    operation_id="customers.service_categories",
)
async def list_customer_service_categories(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the distinct in-use ``service_category`` values for
    the caller's tenant plus a separate ``uncategorized_count`` for
    null / missing / empty-string / whitespace-only buckets.

    Response shape::

        {
          "categories": [
            {"value": "pool",        "count": 142},
            {"value": "landscaping", "count": 38},
            {"value": "both",        "count": 11}
          ],
          "uncategorized_count": 5
        }

    Sort order: count desc, value asc. Soft-deleted customers are
    excluded (``deleted_at`` filter) so the counts align with what
    the operator sees in the list.
    """
    from utils import not_deleted_filter as _nd

    tid = tenant["id"]
    pipeline = [
        {"$match": {"tenant_id": tid, **_nd()}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$or": [
                        {"$eq": [
                            {"$type": "$service_category"}, "missing",
                        ]},
                        {"$eq": ["$service_category", None]},
                        {"$eq": [
                            {"$trim": {"input": {"$ifNull": [
                                "$service_category", ""]}}},
                            "",
                        ]},
                    ]},
                    None,
                    "$service_category",
                ],
            },
            "count": {"$sum": 1},
        }},
    ]
    uncategorized_count = 0
    categories: list[dict] = []
    async for row in db.customers.aggregate(pipeline):
        bucket = row.get("_id")
        count = int(row.get("count") or 0)
        if bucket is None:
            uncategorized_count = count
            continue
        if not isinstance(bucket, str):
            # Defensive — a legacy row may have stashed a non-
            # string value. Coerce to string for the response so
            # the FE renders predictably.
            bucket = str(bucket)
        categories.append({"value": bucket, "count": count})

    categories.sort(key=lambda r: (-r["count"], r["value"].lower()))
    return {
        "categories": categories,
        "uncategorized_count": uncategorized_count,
    }


# ═════════════════════════════════════════════════════════════
# Feb-2026 · Duplicates tab + merge workflow
#
# ``GET /api/customers/duplicates`` powers the new Customers-list
# "Duplicates" tab + the eventual merge dialog.  Detection runs
# through :mod:`services.customers.duplicate_detection` (shared
# normalisation helpers with the PDF-import ladder — same canonical
# name form so the two surfaces agree on "same customer").
#
# Role gate: admin + manager can SEE duplicates (per operator
# ruling); only admin can execute the merge (future commit).
# ═════════════════════════════════════════════════════════════
@router.get(
    "/customers/duplicates",
    summary="Groups of 2+ customers in this tenant sharing a "
             "name / phone / email / fuzzy-name match",
    tags=["customers"],
    operation_id="customers.duplicates",
)
async def list_customer_duplicates(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the duplicate-customer groups for the caller's
    tenant.

    Response shape::

        {
          "groups": [
            {
              "group_id": "<root customer id>",
              "match_reasons": ["email", "name_exact"],
              "customers": [
                {"id": "...", "name": "...", "email": "...",
                 "phone": "...", "status": "active|inactive|muted",
                 "created_at": "..."}
              ]
            }
          ],
          "summary": {
            "group_count": N,
            "customer_count": M
          }
        }

    * Soft-deleted customers are excluded.
    * Active + inactive + muted customers are all considered.
    * Fuzzy-name tier is bounded to tenants with <10K customers
      (see ``_FUZZY_SWEEP_CUSTOMER_CEILING`` on the service);
      above the ceiling the fuzzy sweep is skipped (a WARN is
      logged server-side) and only the exact tiers run.
    """
    from services.customers.duplicate_detection import (
        detect_duplicates,
    )
    groups = await detect_duplicates(db=db, tenant_id=tenant["id"])
    customer_count = sum(len(g.customers) for g in groups)
    return {
        "groups": [
            {
                "group_id": g.group_id,
                "match_reasons": list(g.match_reasons),
                "customers": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "email": c.email,
                        "phone": c.phone,
                        "status": c.status,
                        # Coerce datetime → ISO string for the JSON
                        # response (older rows persisted ``created_at``
                        # as a native BSON date; newer rows as ISO).
                        "created_at": (
                            c.created_at.isoformat()
                            if hasattr(c.created_at, "isoformat")
                            else c.created_at
                        ),
                    }
                    for c in g.customers
                ],
            }
            for g in groups
        ],
        "summary": {
            "group_count": len(groups),
            "customer_count": customer_count,
        },
    }


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
    # Feb-2026 · P43b — "Missing address" data-quality chip. Same
    # ``missing_*`` boolean convention as email/phone. A customer
    # counts as missing an address when BOTH sides of the read-side
    # union used by ``services.google_maps.geocoding._flatten_addr``
    # come up empty: (a) ``service_address`` is null/missing/empty
    # string/whitespace/empty-dict/all-empty-dict, AND (b) every
    # per-field slot (``service_street|street``, ``service_city|city``,
    # ``service_state|state``, ``service_zip|zip``) is also empty.
    # This mirrors the truth used by the P37 geocode backfill so the
    # chip count exactly matches "customers that can't be pinned on
    # the map".
    missing_address: Optional[bool] = False,
    # Feb-2026 · P43c CORRECTED — "Portal status" tri-state filter.
    #   ``portal_activated=true``  → customer has EITHER
    #     ``portal_password_set_at`` set (customer chose their own
    #     password via ``/auth/reset-password`` or in-portal Change
    #     Password) OR ``last_portal_login_at`` set (customer has
    #     actually signed in at least once). Any single positive
    #     signal counts. This is the **customer engagement** signal.
    #   ``portal_activated=false`` → NEITHER signal is present —
    #     the admin may have sent an invite (``has_login=True``)
    #     but the customer has not chosen a password AND has never
    #     signed in. These are the "invited but not onboarded"
    #     customers the chip surfaces.
    #   Omitted (``None``) → no filter, all customers pass.
    # NOTE: ``has_login`` (denorm flipped True by admin invite send)
    # is INTENTIONALLY excluded — it describes admin state, not
    # customer engagement. The previous over-loose definition
    # counted every invited customer as "activated"; the corrected
    # definition matches the "has this customer actually onboarded
    # themselves?" question the operator is asking.
    portal_activated: Optional[bool] = None,
    # ── Feb-2026 · Portal-invited cohort filter ────────────────
    # ``portal_invited=any``  → customer has ``has_login`` truthy
    #   (an admin has issued a portal invite / temp-password —
    #   this is the SAME predicate the
    #   ``/reports/portal-onboarding-health`` "invited" cohort
    #   tallies, so the tile deep-link count equals the filtered
    #   list length verbatim).
    # ``portal_invited=none`` → ``has_login`` is missing / false.
    # Omitted (``None``) → no filter.
    # Composes as intersection with every other filter, incl.
    # ``first_access=never`` (used by the "Chase Stalled Invites"
    # modal to target the invited-but-never-signed-in subset).
    portal_invited: Optional[str] = Query(
        None,
        description=(
            "Feb-2026 — filter by whether the customer has been "
            "issued a portal invite (matches the onboarding-health "
            "``invited`` cohort predicate, ``has_login`` truthy). "
            "Values: ``any`` = invited; ``none`` = not invited."
        ),
    ),
    # ── Feb-2026 · Customer first-access filter ─────────────────
    # ``first_access=never`` → customer has never completed a
    # sign-in (``portal_first_login_at`` is null/missing).
    # ``first_access=any``   → customer has signed in at least once
    # (``portal_first_login_at`` is set). Distinct from
    # ``portal_activated`` because a customer can chose their own
    # password via a reset link WITHOUT ever completing a sign-in —
    # that customer counts as "activated" (portal_password_set_at
    # set) but ``first_access=never``. Admin/manager/tech gate is
    # inherited from the list endpoint.
    first_access: Optional[str] = Query(
        None,
        description=(
            "Feb-2026 — filter by whether the customer has ever "
            "completed a portal sign-in. Values: ``never`` = "
            "``portal_first_login_at`` is null/missing (customer "
            "has never signed in even once); ``any`` = "
            "``portal_first_login_at`` is set. Distinct from "
            "``portal_activated`` (which also counts a chosen "
            "password without a sign-in as activated)."
        ),
    ),
    portal_status: Optional[str] = Query(
        None,
        description=(
            "Phase G4a · Feb-2026 (P43c-corrected) — filter by "
            "customer-portal activation state. Values: ``all`` "
            "(or omit) = no filter; ``activated`` = customer has "
            "``portal_password_set_at`` OR ``last_portal_login_at`` "
            "set (the customer has actually chosen a password or "
            "signed in at least once); ``not_activated`` = neither "
            "signal is present (invited but not onboarded). "
            "``has_login`` is not part of the definition. Composes "
            "as intersection with ``is_active`` / ``is_muted`` / "
            "search / tag filters."
        ),
    ),
    is_muted: Optional[bool] = Query(None, description="Feb-2026 · P28 admin/super_admin only — filter to muted (true) or non-muted (false); absent = no filter"),
    # P2 #6 · Feb-2026 — service-category filter chip.  Accepts
    #   ``pool`` / ``landscaping`` / ``both``   → exact match
    #   ``unset``                                → null OR missing field
    # Omitted / empty → no filter.  Composes as intersection with
    # every other filter (search, is_active, tags, etc.).  Values
    # outside the enum are silently ignored (no 400) to keep the
    # list endpoint tolerant of bookmarked legacy URLs.
    service_category: Optional[str] = Query(
        None,
        description=(
            "P2 #6 · Feb-2026 — filter by customer service category. "
            "Values: ``pool`` / ``landscaping`` / ``both`` for exact "
            "match; ``unset`` for null-or-missing. Values outside this "
            "set are ignored. Composes as intersection with every "
            "other filter."
        ),
    ),
    # Feb-2026 · P44 — "No payment on file" data-quality chip.
    #   ``has_payment_method=false`` → customer has ZERO saved
    #     payment methods (no card AND no us_bank_account). Uses the
    #     same ``customers.saved_payment_methods_count`` denorm the
    #     ``CardOnFileWarningBanner`` reads (maintained by every
    #     Stripe attach + detach code path in
    #     ``services/payments/stripe_charge.py``). Because the denorm
    #     counts ALL payment_methods rows regardless of ``type``, the
    #     filter honours both cards and ACH bank accounts without a
    #     $lookup.
    #   ``has_payment_method=true`` → count > 0 (any card OR ACH).
    #   Omitted (``None``) → no filter.
    # NOTE: banner + filter must agree. If ``has_card_on_file`` is
    # true for a customer, they must NOT match
    # ``has_payment_method=false``.
    has_payment_method: Optional[bool] = None,
    count_only: bool = False,
    include_deleted: bool = Query(False, description="Feb-2026 · P25 super_admin only — include soft-deleted customers"),
    include_merged: bool = Query(False, description="Feb-2026 · Customer Merge — include records whose ``merged_into`` is set. Default false — merged rows are hidden so admins don't see stale duplicates."),
    page: Optional[int] = Query(None, description="Feb-2026 · P35 — 1-indexed page number. Presence of this OR page_size flips the response into a paginated envelope."),
    page_size: Optional[int] = Query(None, description="Feb-2026 · P35 — page size (1..500). Presence of this OR page flips the response into a paginated envelope."),
    # 2026-02 · P0 Stage 3 Step B — reject the ``size`` alias
    # explicitly. Several ad-hoc clients were calling
    # ``GET /api/customers?size=100`` expecting a ``page_size`` alias;
    # FastAPI silently ignored it and returned the full unpaginated
    # legacy list, producing confusing "no pagination" results.
    # Rejecting with the project-standard
    # ``{error_code, detail, message}`` 400 shape teaches callers to
    # migrate to ``page_size``.
    size: Optional[int] = Query(
        None,
        deprecated=True,
        description=(
            "**Not supported.** Use ``page_size`` instead. Passing "
            "``size`` returns a 400 with ``error_code = "
            "unknown_param``."
        ),
    ),
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
    slim: Optional[bool] = Query(
        False,
        description=(
            "Phase 9c · Feb-2026 — opt-in slim projection. When "
            "``slim=1`` the response skips the per-row ``properties_count`` "
            "aggregation + the ``next_scheduled_at`` P45 hydration "
            "(two separate aggregations against db.properties and "
            "db.jobs). Core row fields and all filter/sort/pagination "
            "semantics are unchanged. Used by the customers-list page "
            "to drop sub-second overhead on tenants with 1900+ "
            "customers; non-slim callers (external automations, admin "
            "exports) are unaffected."
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
    # 2026-02 · P0 Stage 3 Step B — unknown ``size`` alias → 400.
    # Caught before RBAC permits the request so even an authenticated
    # admin can't accidentally rely on a silently-ignored param.
    # Shape mirrors the ``page_size`` validator below so the frontend
    # error-handling layer treats both the same way.
    if size is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "unknown_param",
                "detail": "unsupported_query_param",
                "message":
                    "'size' is not a supported query param on this "
                    "endpoint. Use 'page_size' instead.",
                "param": "size",
            },
        )
    # Phase 9c · Feb-2026 — Coerce ``slim`` to a plain bool. When
    # list_customers is called directly from Python (e.g. the
    # ``tests/_f7_loop_fixture.py`` perf-contract suite) the
    # unresolved default is a ``Query(False, ...)`` sentinel object,
    # which is TRUTHY under ``bool()`` — exactly the trap the
    # ``portal_status`` / ``first_access`` params worked around with
    # ``isinstance(x, str)``. Mirror that here so direct-call
    # callers get the documented default behaviour.
    _slim = bool(slim) if isinstance(slim, bool) else False
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
        # Feb-2026 · Diag-Timeout Task 1 — search-haystack fast path.
        # The prior implementation OR'd a case-insensitive
        # ``$regex`` across six fields (``name`` / ``first_name`` /
        # ``last_name`` / ``email`` / ``phone`` / ``address``) —
        # Mongo can't use any index for that shape, so a tenant
        # with 2000 customers scanned the collection six times per
        # request (+ five more times in the K68 ``$facet`` stage
        # below). Prod tenants with 1931 customers were tipping the
        # frontend's 30s ``fetch`` timeout on the ``search=lynn``
        # query the user reported.
        #
        # New shape: match a single ``$regex`` against the
        # pre-computed lowercase ``search_haystack`` field, which
        # concatenates all six columns. Combined with the compound
        # ``(tenant_id, search_haystack)`` index (see
        # ``services.customers_search_haystack``) Mongo streams a
        # small tenant-scoped partition through a **single** regex
        # instead of six. Per-doc work drops 6× and the collection
        # scans in this handler drop from 12+ (find + count + 5
        # facet stages, each with 6 fields) to 12 single-field
        # scans, most of which the (tenant_id, is_active, is_muted)
        # index already narrows.
        #
        # Token semantics unchanged from K49b — split on
        # whitespace, AND across tokens.  Each token becomes a
        # ``$regex`` (case-sensitive, since the haystack is already
        # lowercased) so ``$options`` is elided and the regex
        # engine skips the case-fold work per byte.
        #
        # Legacy fallback: rows created before the backfill
        # migration ran won't have ``search_haystack``, so the
        # per-token predicate also OR's the raw name/email/phone
        # match so those tenants still see hits. The fallback path
        # is only taken for un-backfilled docs — the boot-time
        # migration touches every doc once, so the OR arm is dead
        # code within a minute of a rolling deploy.
        import re as _search_re
        _tokens = [t for t in (search or "").split() if t.strip()]
        if _tokens:
            _search_and = []
            for _tok in _tokens:
                _tok_lc = _tok.lower()
                _hay_rx = {"$regex": _search_re.escape(_tok_lc)}
                _legacy_rx = {"$regex": _search_re.escape(_tok),
                                "$options": "i"}
                _search_and.append({"$or": [
                    {"search_haystack": _hay_rx},
                    # Legacy fallback for un-backfilled rows.
                    {"name": _legacy_rx}, {"first_name": _legacy_rx},
                    {"last_name": _legacy_rx}, {"email": _legacy_rx},
                    {"phone": _legacy_rx}, {"address": _legacy_rx},
                ]})
            q["$and"] = q.get("$and", []) + _search_and
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
    # ═══════════════════════════════════════════════════════════════
    # Phase K68 · Feb-2026 — Snapshot the query BEFORE the status-tab
    # predicates (waitlisted / is_active / is_muted) are compounded
    # in below so we can compute overlapping counts for the 5 tab
    # buckets (active / inactive / muted / waitlist / all) in a
    # single $facet aggregation. The snapshot strips whichever
    # status predicate got applied so each tab count reflects the
    # base search + data-quality filter surface only.
    # Shallow-copy of the dict + list-copy of its ``$and`` is
    # sufficient — individual predicates inside are read-only from
    # here on.
    # ═══════════════════════════════════════════════════════════════
    _k68_base_q: dict = {k: v for k, v in q.items() if k not in ("$and",
                                                                     "waitlisted")}
    if q.get("$and"):
        _k68_base_q["$and"] = list(q["$and"])
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
    # P2 #6 · Feb-2026 — service-category chip.  Normalized to lowercase
    # against the P2 #6 enum.  Values outside the whitelist silently
    # pass through to a no-op (list behavior unchanged) so bookmarked
    # legacy URLs don't 400.
    #
    # Behavior correction (Feb-2026): ``?service_category=pool`` and
    # ``?service_category=landscaping`` BOTH union-include customers
    # tagged ``both`` — same semantic as the companion tile fix at
    # ``routers/dashboard_service_category.py``. Rationale: the Pool
    # dashboard tile deep-links to this list, and mismatched counts
    # (tile says 15, list shows 12) is immediately user-confusing.
    # ``?service_category=both`` continues to return ONLY ``both``-
    # customers; ``?service_category=unset`` continues to return
    # null-or-missing. Legacy clients passing ``?service_category=pool``
    # see a slightly larger result set — that's the semantic
    # correction (not a regression).
    _p26_cat = (service_category or "").strip().lower() if service_category else None
    if _p26_cat == "pool":
        q["service_category"] = {"$in": ["pool", "both"]}
    elif _p26_cat == "landscaping":
        q["service_category"] = {"$in": ["landscaping", "both"]}
    elif _p26_cat == "both":
        q["service_category"] = "both"
    elif _p26_cat == "unset":
        q["$and"] = q.get("$and", []) + [{
            "$or": [{"service_category": None},
                        {"service_category": {"$exists": False}}],
        }]
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
    # Feb-2026 · P43b — "Missing address" data-quality chip. Matches
    # the read-side predicate used by
    # ``services.google_maps.geocoding._flatten_addr``: a customer
    # counts as address-less only when the top-level ``service_address``
    # AND every per-field breakdown slot are empty. Both branches
    # tolerate the historical dict shape (``{street, city, state,
    # postal_code|zip}``) — an empty or all-blank dict qualifies.
    # ``$regex: \S`` (any non-whitespace char) is the canonical
    # "has-content" probe used by the ``$nor`` clause.
    if missing_address:
        _blank = {"$regex": r"\S", "$options": "s"}
        _dict_all_blank = {"$and": [
            {"service_address": {"$type": "object"}},
            {"$nor": [
                {"service_address.street": _blank},
                {"service_address.city": _blank},
                {"service_address.state": _blank},
                {"service_address.postal_code": _blank},
                {"service_address.zip": _blank},
            ]},
        ]}
        q["$and"] = q.get("$and", []) + [{
            "$and": [
                # (a) top-level ``service_address`` is empty in any shape
                {"$or": [
                    {"service_address": None},
                    {"service_address": ""},
                    {"service_address": {"$exists": False}},
                    {"service_address": {"$regex": r"^\s*$"}},
                    _dict_all_blank,
                ]},
                # (b) per-field breakdown is entirely empty (any of the
                # eight slots with non-whitespace content disqualifies)
                {"$nor": [
                    {"service_street": _blank},
                    {"street": _blank},
                    {"service_city": _blank},
                    {"city": _blank},
                    {"service_state": _blank},
                    {"state": _blank},
                    {"service_zip": _blank},
                    {"zip": _blank},
                ]},
            ],
        }]
    # Feb-2026 · P43c CORRECTED — "Portal status" tri-state filter.
    # Positive signals (customer engagement, not admin state):
    #   * ``portal_password_set_at`` set — customer chose their own
    #     password (see ``auth._apply_new_password`` +
    #     ``auth.change_my_password`` for the denorm).
    #   * ``last_portal_login_at`` set — customer has signed in at
    #     least once (see ``auth.login`` / ``auth.login-select``).
    # ``has_login`` (admin-side invite flag) is INTENTIONALLY not
    # part of the definition — see the parameter docstring above.
    if portal_activated is not None:
        _activated_signals = {
            "$or": [
                {"portal_password_set_at": {"$exists": True,
                                              "$nin": [None, ""]}},
                {"last_portal_login_at": {"$exists": True,
                                             "$nin": [None, ""]}},
            ],
        }
        if portal_activated:
            q["$and"] = q.get("$and", []) + [_activated_signals]
        else:
            # Not activated → NEITHER signal is present.
            q["$and"] = q.get("$and", []) + [{
                "$and": [
                    {"$or": [{"portal_password_set_at": {"$exists": False}},
                              {"portal_password_set_at": None},
                              {"portal_password_set_at": ""}]},
                    {"$or": [{"last_portal_login_at": {"$exists": False}},
                              {"last_portal_login_at": None},
                              {"last_portal_login_at": ""}]},
                ],
            }]
    # ── Feb-2026 · Portal-invited cohort filter body ────────────
    # Predicate: ``has_login`` truthy — same as the onboarding-
    # health "invited" cohort in ``profit_report.py``. Unknown
    # values → 400 so typos surface early.
    if isinstance(portal_invited, str) and portal_invited.strip():
        _pi = portal_invited.strip().lower()
        if _pi not in ("any", "none"):
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "invalid_portal_invited",
                    "message": "portal_invited must be one of: any, none",
                    "portal_invited": portal_invited,
                },
            )
        if _pi == "any":
            q["$and"] = q.get("$and", []) + [{"has_login": True}]
        else:  # none
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"has_login": {"$exists": False}},
                    {"has_login": None},
                    {"has_login": False},
                ],
            }]
    # Phase G4a · Feb-2026 — Portal-activation cohort filter (string
    # alias). Uses the same corrected definition as the boolean
    # ``portal_activated`` param above; ``has_login`` is
    # intentionally not part of the definition. Unknown values → 400
    # so typos surface early.
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
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"portal_password_set_at": {"$exists": True,
                                                  "$nin": [None, ""]}},
                    {"last_portal_login_at": {"$exists": True,
                                                 "$nin": [None, ""]}},
                ],
            }]
        elif _ps == "not_activated":
            q["$and"] = q.get("$and", []) + [{
                "$and": [
                    {"$or": [{"portal_password_set_at": {"$exists": False}},
                              {"portal_password_set_at": None},
                              {"portal_password_set_at": ""}]},
                    {"$or": [{"last_portal_login_at": {"$exists": False}},
                              {"last_portal_login_at": None},
                              {"last_portal_login_at": ""}]},
                ],
            }]
        # ``all`` → intentionally no-op.
    # ── Feb-2026 · Customer first-access filter body ────────────
    if isinstance(first_access, str) and first_access.strip():
        _fa = first_access.strip().lower()
        if _fa not in ("never", "any"):
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "invalid_first_access",
                    "message": "first_access must be one of: never, any",
                    "first_access": first_access,
                },
            )
        if _fa == "never":
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"portal_first_login_at": {"$exists": False}},
                    {"portal_first_login_at": None},
                    {"portal_first_login_at": ""},
                ],
            }]
        else:  # any
            q["$and"] = q.get("$and", []) + [{
                "portal_first_login_at": {"$exists": True,
                                             "$nin": [None, ""]},
            }]
    # Feb-2026 · P44 — "No payment on file" filter body. Matches the
    # exact source-of-truth the ``CardOnFileWarningBanner`` reads —
    # ``customers.saved_payment_methods_count`` — so filter and
    # banner never disagree.
    if has_payment_method is not None:
        if has_payment_method:
            q["$and"] = q.get("$and", []) + [{
                "saved_payment_methods_count": {"$gt": 0},
            }]
        else:
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"saved_payment_methods_count": {"$exists": False}},
                    {"saved_payment_methods_count": None},
                    {"saved_payment_methods_count": 0},
                ],
            }]
    # ─────────────────────────────────────────────────────────────
    # Feb-2026 hotfix · Never-logged-in chip off-by-one — keep the
    # count/list/facet branches in lockstep by promoting the K49b
    # "row must carry a top-level ``id``" guard from a Python
    # post-filter (see below) into the Mongo predicate. Before this
    # change, ``count_documents(q)`` matched legacy customer docs
    # without a top-level ``id`` while the list branch dropped them
    # via ``_k49b_kept`` — producing exactly the shape the batch
    # verification caught (badge N, list N-1). The Python guard is
    # kept as a belt-and-braces safety for any doc that slips in
    # AFTER the count query resolves but BEFORE ``.to_list()`` — it
    # becomes a no-op in the common case.
    q["$and"] = q.get("$and", []) + [_valid_customer_id_predicate()]
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
            page_size = 25
        if page < 1:
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_page",
                          "message": "page must be >= 1",
                          "page": page},
            )
        # SEARCH-SPEED · Feb-2026 — Customers list page_size cap
        # dropped from 500 → 100.  ``page_size > 100`` requests are
        # rejected with ``error_code: page_size_too_large``.  The
        # cap keeps the payload size + fanout cost bounded and
        # matches the FE list-card render budget (25-100 rows).
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "page_size_too_large",
                          "detail": "invalid_page_size",
                          "message":
                            "page_size must be between 1 and 100",
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
        # Feb-2026 · Chase Stalled Invites ship — sort by staleness of
        # the portal invite (oldest ``temp_password_issued_at`` first,
        # falling back to ``created_at`` for docs that never got a
        # dated invite stamp). Nulls-last is enforced via the
        # dedicated ``_stalest_first_pipeline`` aggregation branch;
        # this map entry is a fallback for the fast-path enum guard
        # only.
        "stalest_first": [("temp_password_issued_at", 1), ("_id", 1)],
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
    # Feb-2026 · Chase Stalled Invites — same nulls-last requirement
    # for the ``temp_password_issued_at``-driven staleness sort.
    _use_stalest_pipeline = _sort_key == "stalest_first"

    if _paginated and not _needs_python_postfilter:
        # Fast path — DB-side pagination.
        total = await db.customers.count_documents(q)
        skip = (page - 1) * page_size
        if _use_lastname_pipeline:
            docs = await db.customers.aggregate(
                _k49_lastname_pipeline(q, skip=skip, limit=page_size),
            ).to_list(page_size)
        elif _use_stalest_pipeline:
            docs = await db.customers.aggregate(
                _stalest_first_pipeline(q, skip=skip, limit=page_size),
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
        elif _use_stalest_pipeline:
            docs = await db.customers.aggregate(
                _stalest_first_pipeline(q),
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
        elif _use_stalest_pipeline:
            docs = await db.customers.aggregate(
                _stalest_first_pipeline(q, limit=2000),
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

    # K49b · Feb-2026 — drop legacy customer docs missing a top-level
    # ``id`` field BEFORE they reach the response.  ``CustomerListItem``
    # declares ``id: str`` (required), so a missing-id doc would 500 the
    # endpoint at Pydantic response-validation time — even after the
    # downstream ``d.get("id")`` guards prevent the earlier ``KeyError``.
    # The ``k49b_customer_id_backfill`` migration populates
    # ``id = str(_id)`` on boot; this filter is the transient guard
    # for the window before the migration lands and for any future
    # doc that slips in without an ``id``.  Emit one ``warning``
    # per dropped row (breadcrumbs for the backfill audit — ``_id``
    # is projected out on both the ``find()`` and aggregation paths,
    # so identify by tenant + name shape).
    _k49b_kept: List[dict] = []
    for _d in docs:
        if _d.get("id"):
            _k49b_kept.append(_d)
        else:
            logger.warning(
                "[k49b] dropping customer row missing top-level 'id' "
                "(tenant=%s name=%r first=%r last=%r); backfill "
                "migration will repair on next boot",
                _d.get("tenant_id"),
                _d.get("name"),
                _d.get("first_name"),
                _d.get("last_name"),
            )
    docs = _k49b_kept

    # If unscheduled=true, filter out customers who have any non-completed/cancelled job.
    if unscheduled:
        from utils import not_deleted_filter as _nd
        scheduled_ids = set(
            [d["customer_id"] async for d in db.jobs.find(
                {"tenant_id": tenant["id"], "status": {"$nin": ["completed", "cancelled"]}, **_nd()},
                {"customer_id": 1, "_id": 0},
            )]
        )
        docs = [d for d in docs if d.get("id") and d["id"] not in scheduled_ids]
    # K49b · Feb-2026 — every downstream hydration block in this
    # handler indexes ``d["id"]``.  A single legacy customer doc
    # created without a top-level ``id`` field (mirrored ``_id`` but
    # never populated) 500's the whole ``GET /api/customers``
    # response with ``KeyError: 'id'`` on line 768 — including K49's
    # new ``sort=last_name_asc`` path.  Guard once here, then reuse
    # ``cust_ids`` (a de-duplicated list of valid customer ids)
    # everywhere below so no downstream lookup can crash.
    # The ``k49b_customer_id_backfill`` migration seeds
    # ``id = str(_id)`` for these docs on boot; this guard keeps the
    # endpoint safe in the window BEFORE the migration lands and
    # for any future doc that slips in without an ``id``.
    cust_ids = [d["id"] for d in docs if isinstance(d, dict) and d.get("id")]
    # Feb-2026 MP2 UI — augment each customer row with a
    # ``properties_count`` (active properties only) so the list can
    # render a chip without an N+1 fetch. Batched aggregation keeps
    # this cheap for tenants with thousands of customers.
    #
    # Phase 9c · Feb-2026 — guarded by ``slim``. The customers list
    # page passes ``slim=1`` and consumes neither hydration (the
    # chip is rendered from the base-row saved_payment_methods_count
    # denorm + a cheap FE lookup). External/admin callers that need
    # these fields leave ``slim`` unset.
    if docs and not _slim:
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
            d["properties_count"] = counts.get(d.get("id"), 0)

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
    #
    # Phase 9c · Feb-2026 — guarded by ``slim``. The P45 hydration
    # issues a second aggregation against db.jobs; dropping it under
    # slim halves per-page latency on the hot path.
    # ─────────────────────────────────────────────────────────────
    if docs and not _slim:
        from datetime import datetime as _p45_dt, timezone as _p45_tz
        from utils import not_deleted_filter as _p45_nd
        today_utc_iso = _p45_dt.now(_p45_tz.utc).strftime("%Y-%m-%d")
        try:
            p45_pipeline = [
                {"$match": {
                    "tenant_id": tenant["id"],
                    # K49b · Feb-2026 — reuse the guarded ``cust_ids``
                    # so a doc with no top-level ``id`` never crashes
                    # this hydration.
                    "customer_id": {"$in": cust_ids},
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
            d["next_scheduled_at"] = next_map.get(d.get("id"))

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
        # ═══════════════════════════════════════════════════════════
        # Phase K68 · Feb-2026 — counts_by_status (CUS-perf v3 refactor).
        #
        # Prior implementation ran a single ``$facet`` aggregation
        # over the base query, producing 5 overlapping tab counts in
        # one Mongo round trip.  While cheaper than the pre-K68
        # 5-round-trip fanout, ``$facet`` still routed every bucket
        # through a Python-side response validation stage and could
        # not use the ``customers_dashboard_active_inactive_idx``
        # compound cleanly — the aggregation planner tends to prefer
        # a partition-only scan when a non-tenant-leading facet is
        # present.
        #
        # Feb-2026 CUS-perf v3 replaces the ``$facet`` with 5
        # concurrent ``count_documents`` calls via ``asyncio.gather``.
        # Wall-clock cost is now ``max(bucket)`` — every bucket runs
        # in parallel against Mongo's connection pool.  The
        # per-bucket predicates preserve the exact same semantics
        # (search + city + tags + data-quality + portal filters on
        # the base + per-tab predicate on top) so byte-for-byte
        # numerical parity with ``$facet`` is guaranteed.
        #
        # Bucket definitions (unchanged from K68):
        #   * active   — is_active∈{true, missing} AND is_muted!=true
        #   * inactive — is_active=false AND is_muted!=true
        #   * muted    — is_muted=true
        #   * waitlist — waitlisted=true
        #   * all      — the base query verbatim
        #
        # ``unscheduled`` and ``missing_card`` still run in Python
        # post-filter so their exclusion isn't reflected in the tab
        # counts — those tabs are advisory (their totals may
        # over-count vs the visible page).
        #
        # ─── VESTIGIAL ALIAS ──────────────────────────────────────
        # ``counts_by_status`` is kept in the response envelope for
        # 1 release cycle to survive the deploy-order gap where BE
        # ships before FE.  Frontend as of the CUS-perf v3 commit
        # reads ``/customers/counts`` (extended with the ``all``
        # bucket) as single source of truth.  Drop this alias in
        # the follow-up per
        # ``memory/FOLLOWUP_CUS_PERF_V3_ENVELOPE_DEPRECATION.md``.
        # No extra query cost — the alias is populated from the
        # same 5 parallel counts already fetched below.
        # ═══════════════════════════════════════════════════════════
        import asyncio as _cus_perf_v3_asyncio
        _cbs_not_muted = {"$or": [{"is_muted": {"$ne": True}},
                                     {"is_muted": {"$exists": False}}]}
        # Per-bucket filter shape: ``$and`` of base + per-tab
        # predicate(s).  Nested ``$and`` inside an outer ``$and``
        # is optimized flat by the Mongo planner.
        _cbs_active_q = {"$and": [
            _k68_base_q,
            {"$or": [{"is_active": True},
                       {"is_active": {"$exists": False}}]},
            _cbs_not_muted,
        ]}
        _cbs_inactive_q = {"$and": [
            _k68_base_q, {"is_active": False}, _cbs_not_muted,
        ]}
        _cbs_muted_q = {"$and": [_k68_base_q, {"is_muted": True}]}
        _cbs_waitlist_q = {"$and": [_k68_base_q, {"waitlisted": True}]}
        _cbs_all_q = _k68_base_q
        try:
            _cbs_active, _cbs_inactive, _cbs_muted, _cbs_waitlist, _cbs_all = (
                await _cus_perf_v3_asyncio.gather(
                    db.customers.count_documents(_cbs_active_q),
                    db.customers.count_documents(_cbs_inactive_q),
                    db.customers.count_documents(_cbs_muted_q),
                    db.customers.count_documents(_cbs_waitlist_q),
                    db.customers.count_documents(_cbs_all_q),
                )
            )
            counts_by_status = {
                "active": int(_cbs_active or 0),
                "inactive": int(_cbs_inactive or 0),
                "muted": int(_cbs_muted or 0),
                "waitlist": int(_cbs_waitlist or 0),
                "all": int(_cbs_all or 0),
            }
        except Exception as _cbs_exc:  # noqa: BLE001
            logger.warning(
                "[cus-perf-v3] counts_by_status gather failed: %s",
                _cbs_exc,
            )
            counts_by_status = {
                "active": 0, "inactive": 0, "muted": 0,
                "waitlist": 0, "all": 0,
            }
        return {
            "items": docs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": _total_pages,
            "counts_by_status": counts_by_status,
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
    # Feb-2026 · Diag-Timeout Task 1 — write ``search_haystack`` on
    # create so the customers-list fast path works without waiting
    # for the boot-time backfill migration to catch up.
    from services.customers_search_haystack import apply_haystack as _apply_hay
    _apply_hay(doc)
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
    # Feb-2026 · Auto-geocode phase — stamp ``geocode_address_hash``
    # up-front so a follow-up PUT with an unchanged address
    # short-circuits without a second Google round-trip.
    try:
        import asyncio as _a17
        from services.google_maps.geocoding import (
            geocode_and_persist_customer as _gp17,
            resolve_customer_address as _resolve_addr17,
        )
        from routers.admin_customer_geocode_backfill import (
            address_hash as _addr_hash17,
        )
        _resolved_create = _resolve_addr17(doc)
        _hash_create = _addr_hash17(_resolved_create)
        if _hash_create:
            await db.customers.update_one(
                {"id": doc["id"], "tenant_id": tenant["id"]},
                {"$set": {"geocode_address_hash": _hash_create}},
            )
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


# ─── Feb-2026 · Manual customer re-geocode (UI escape hatch) ─────────
# Phase 17 (Feb-2026) already auto-geocodes on customer create + on
# address-field update inside the update endpoint. This endpoint is
# NOT a second automation — it's the "Re-geocode" button on the
# customer profile page for when the address is technically valid
# but Google returned ZERO_RESULTS on the async path, when a rooftop
# lookup improved after the fact, or when a tenant admin just wants
# to force a fresh fix without editing the address.
#
# ``force=true`` clears the 30-day ``geocoded_at`` short-circuit
# inside ``geocode_and_persist_customer`` so the helper actually
# re-hits Google. Without ``force`` a customer that was geocoded
# less than 30 days ago no-ops (returns ``ok=false, reason=fresh``).
# RBAC: admin + super_admin + owner + manager (mirrors the geocode-
# backfill endpoint in dispatch_board.py).
_MANUAL_GEOCODE_ROLES = {"admin", "super_admin", "owner", "manager"}


@router.post("/customers/{cid}/geocode", tags=["customers"],
             operation_id="customers.manualGeocode")
async def customer_manual_geocode(
    cid: str,
    force: bool = Query(False, description="Clear the 30-day cache short-circuit and force a fresh Google lookup."),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Synchronous per-customer re-geocode. Not fire-and-forget — the
    caller is waiting on a UI button. Returns the resulting lat/lng
    on success, ``ok=false`` + ``reason`` otherwise. Never raises on
    provider failure; the customer save is not affected."""
    role = (user.get("role") or "").lower()
    if role not in _MANUAL_GEOCODE_ROLES:
        raise HTTPException(403, "Manual geocode is admin/manager only")

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "tenant_id": 1, "deleted_at": 1,
         "service_address": 1, "service_street": 1, "street": 1,
         "service_city": 1, "city": 1, "service_state": 1, "state": 1,
         "service_zip": 1, "zip": 1, "geocoded_at": 1,
         "latitude": 1, "longitude": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    if doc.get("deleted_at"):
        raise HTTPException(404, "Customer not found")

    # ``force`` clears the 30-day cache short-circuit inside the helper.
    if force:
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$unset": {"geocoded_at": ""}},
        )

    try:
        from services.google_maps.geocoding import (
            geocode_and_persist_customer as _gp,
        )
        did = await _gp(cid, tenant["id"])
    except Exception as exc:
        logger.warning("[manual-geocode] customer=%s err=%s", cid, exc)
        return {"ok": False, "reason": "provider_error", "error": str(exc)}

    if not did:
        # Re-read to distinguish "fresh cache" (already geocoded < 30d,
        # no ``force``) from "no address" from "ZERO_RESULTS".
        after = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"_id": 0, "latitude": 1, "longitude": 1, "geocoded_at": 1},
        ) or {}
        # If the doc already has coords + a stamp, we hit the 30-day
        # cache. If it has neither, either the address was empty or
        # Google returned ZERO_RESULTS.
        if after.get("geocoded_at") and after.get("latitude") is not None:
            return {
                "ok": False, "reason": "fresh_cache",
                "lat": after.get("latitude"), "lng": after.get("longitude"),
                "geocoded_at": after.get("geocoded_at"),
            }
        # Distinguish empty-address from ZERO_RESULTS.
        # Feb-2026 · Fix — Re-geocode button reported "no address"
        # even when ``customer.address`` was populated because the
        # old fallback only checked ``service_address`` + structured
        # legacy fields. ``resolve_customer_address`` now walks the
        # canonical fallback chain (mirrors the geocode path).
        from services.google_maps.geocoding import (
            resolve_customer_address as _resolve_addr,
        )
        addr = _resolve_addr(doc)
        if not addr:
            return {"ok": False, "reason": "no_address"}
        return {"ok": False, "reason": "not_found",
                "error": "Google returned ZERO_RESULTS for the address"}

    after = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "latitude": 1, "longitude": 1, "geocoded_at": 1},
    ) or {}
    return {
        "ok": True,
        "lat": after.get("latitude"), "lng": after.get("longitude"),
        "geocoded_at": after.get("geocoded_at"),
    }


@router.get("/customers/{cid}")
async def get_customer(cid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant),
                       slim: Optional[bool] = Query(
                           False,
                           description=(
                               "Phase 9d · Feb-2026 — opt-in slim "
                               "projection. When ``slim=1`` the response "
                               "SKIPS the embedded ``jobs`` array (up to "
                               "200 slim-photo'd job rows). The customer "
                               "profile page fetches its jobs list "
                               "separately via "
                               "``GET /jobs?customer_id=...&limit=50`` "
                               "and never consumes the embedded array; "
                               "the slim path saves one jobs find+sort "
                               "+ SR-photo-id enrichment per profile "
                               "open. Non-slim callers (external "
                               "automations, legacy admin tooling) are "
                               "unaffected."
                           ),
                       )):
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
    # Phase 9d · Feb-2026 — Coerce ``slim`` to a plain bool. When
    # called directly from Python the unresolved default is a
    # ``Query(False, ...)`` sentinel object (truthy under ``bool()``).
    # Mirror the ``list_customers`` _slim coercion.
    _slim_profile = bool(slim) if isinstance(slim, bool) else False
    # PERF-AUDIT-B/C · Feb-2026 — Phase A balance denorm.  Ensures
    # ``balance_due`` / ``past_due`` / ``credit_balance_cents`` /
    # ``overdue_count`` + ``balance_recomputed_at`` are present on
    # the response doc.  Lazy-backfills on stale/missing values so
    # the profile tiles can render straight from the Phase A payload
    # without a second KPI round-trip.  Common case (fresh denorm)
    # is a no-op field read; cold path (stale/absent) triggers the
    # shared aggregation + persists back.  Admins + managers only
    # (techs don't see the balance tiles on the profile UI).
    _role_pa = (user.get("role") or "").lower()
    if _role_pa in ("admin", "super_admin", "manager", "owner"):
        try:
            from services.customer_balance import (
                ensure_fresh_balance_denorm as _efbd,
            )
            fresh = await _efbd(db, tenant["id"], cid, cust_doc=doc)
            # Merge the fresh (or already-cached) denorm fields
            # back onto the response doc.  ``as_of`` → stamp.
            doc["balance_due"] = fresh["balance_due"]
            doc["past_due"] = fresh["past_due"]
            doc["credit_balance_cents"] = fresh["credit_balance_cents"]
            doc["overdue_count"] = fresh["overdue_count"]
            doc["balance_recomputed_at"] = fresh.get("as_of")
        except Exception as _efbd_exc:                                # noqa: BLE001
            logger.warning(
                "[get_customer] Phase A balance backfill failed "
                "cid=%s: %s", cid, _efbd_exc,
            )
    from utils import not_deleted_filter as _nd_cust
    # Phase 9d · Feb-2026 — the embedded ``jobs`` array is a legacy
    # convenience payload the current frontend never consumes
    # (``CustomerDetail.jsx`` calls ``GET /jobs?customer_id=`` with
    # its own ``limit=50`` pagination). ``slim=1`` skips the second
    # find + SR-photo-id enrichment + slim-photos pass, cutting the
    # profile endpoint from a bimodal ~300ms-3s to a stable sub-100ms
    # on tenants with 50+ jobs per customer. The field is OMITTED
    # entirely under slim rather than set to an empty list so the
    # response shape is unambiguous.
    if _slim_profile:
        # Phase 12 · Feb 2026 — derive card-on-file fields at read time.
        doc.update(_compute_card_fields(
            doc, bool(tenant.get("require_card_on_file_default", True))))
        if user.get("role") == "technician":
            doc.pop("stripe_customer_id", None)
            doc.pop("stripe_default_payment_method_id", None)
        return doc
    # Phase P31 · Feb-2026 — apply ``JOBS_LIST_PROJECTION`` at Mongo
    # query time so photo base64 blobs never cross the wire between
    # Mongo and the API process. The historic ``{"_id": 0}`` shape
    # would pull every ``photos[].data`` (base64, ~500KB per photo)
    # for every job on the customer's timeline — a customer with 50
    # completed jobs × 5 photos each shipped ~125 MB per profile
    # load. Post-fetch ``slim_photos_on_rows`` still emits
    # ``photo_count`` + ``photo_ids`` from the surviving photo
    # sub-docs (id / label / created_at); the FE consumes only
    # ``id`` / ``title`` / ``scheduled_date`` / ``technician_name``
    # / ``status`` on this timeline surface (grep
    # ``frontend/src/pages/customers/CustomerDetail.jsx`` lines
    # 898-930), so the projection preserves every field the UI
    # actually renders.
    from services.jobs_slim_photos import (
        JOBS_LIST_PROJECTION,
        slim_photos_on_rows,
        enrich_docs_with_sr_photo_ids,
    )
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tenant["id"], **_nd_cust()},
        JOBS_LIST_PROJECTION,
    ).sort("scheduled_date", -1).to_list(200)
    # Feb-2026 · Slim-photos follow-up — the customer-detail embedded
    # jobs list previously shipped every job's full ``photos`` array
    # (base64 blobs). On customers with ~50 completed jobs × ~10 photos
    # each, that duplicated the same wire-payload problem the earlier
    # ``/api/jobs`` slim-photos ship (Feb-2026) solved. Drop ``photos``,
    # emit ``photo_count`` + ``photo_ids`` — matches the /api/jobs
    # slim shape verbatim so downstream consumers use one contract.
    # No ``include_photos`` opt-in here: the customer-detail endpoint
    # takes no query params for its embedded lists — callers that
    # need full photos fetch ``GET /jobs/{id}`` per row.
    # See /app/memory/PERF_SLIM_PHOTOS_WORKSTREAM_AND_CUSTOMER.md.
    #
    # Task L+P · Feb-2026 — batched SR photo-id pre-fetch (same
    # pattern as ``routers/jobs.py::list_jobs``).  Runs BEFORE
    # ``slim_photos_on_rows`` so a single ``$in`` query widens
    # ``photo_ids[]`` to include service_reports.photos ids on
    # every embedded-jobs row.
    await enrich_docs_with_sr_photo_ids(db, jobs, tenant["id"])
    slim_photos_on_rows(jobs, include_photos=False)
    doc["jobs"] = jobs
    # Phase 12 · Feb 2026 — derive card-on-file fields at read time.
    doc.update(_compute_card_fields(
        doc, bool(tenant.get("require_card_on_file_default", True))))
    # Phase 12B · Feb 2026 — techs never see the Stripe customer id.
    if user.get("role") == "technician":
        doc.pop("stripe_customer_id", None)
        doc.pop("stripe_default_payment_method_id", None)
    return doc


# ─── Phase 9d · Feb-2026 · Customer profile counts summary ─────────────
# ``GET /api/customers/{cid}/summary`` returns a cheap, parallelized
# count snapshot across the seven collections that back the customer
# profile tabs: jobs, invoices (quotes doc_type=invoice), quotes
# (quotes doc_type=quote), customer_tasks, service_reports,
# customer_notes_history (via submitted service reports with any
# note populated — approximated via service_reports count),
# properties (active).
#
# Shape:
#   {
#     "jobs_count":            int,
#     "invoices_count":        int,
#     "quotes_count":          int,
#     "tasks_count":           int,
#     "service_reports_count": int,
#     "notes_count":           int,
#     "properties_count":      int,
#     "open_invoices_count":   int,
#   }
#
# Semantics:
#   * All counts tenant-scoped + customer-scoped.
#   * Soft-deleted jobs / quotes / reports are excluded via
#     ``not_deleted_filter()`` (matches the FE tab lists).
#   * ``open_invoices_count`` = invoices with status in
#     {"draft", "pending", "sent", "overdue"} (anything not fully
#     paid or cancelled).
#   * Runs all 8 counts in parallel via ``asyncio.gather``.
#   * Returns 404 if the customer isn't found (or is soft-deleted
#     and the caller isn't super_admin — same gate as get_customer).
#
# Called by ``CustomerDetail.jsx`` alongside the ``?slim=1`` profile
# fetch so tab-badges can render from a lightweight response before
# the user clicks any individual tab (lazy tab fetch still owns
# full tab data).
@router.get("/customers/{cid}/summary")
async def get_customer_summary(cid: str,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    # Same 404/409 gate as the base profile endpoint — a missing or
    # soft-deleted customer must not leak counts.
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    if cust.get("deleted_at"):
        role = (user.get("role") or "").lower()
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "customer_soft_deleted",
                          "message": "Customer is soft-deleted; restore first."},
            )
        raise HTTPException(404, "Customer not found")

    import asyncio as _summary_asyncio
    from utils import not_deleted_filter as _summary_nd

    _tid = tenant["id"]
    _cust_scope = {"tenant_id": _tid, "customer_id": cid}
    _nd = _summary_nd()

    # Per-collection match predicates. Each is a plain dict (not a
    # pipeline) so each count_documents call uses the compound
    # (tenant_id, customer_id, ...) indexes created by the existing
    # per-collection ensure_indexes routines.
    _jobs_q = {**_cust_scope, **_nd}
    _invoices_q = {**_cust_scope, "doc_type": "invoice", **_nd}
    _quotes_q = {**_cust_scope, "doc_type": "quote", **_nd}
    _tasks_q = {**_cust_scope}
    _reports_q = {**_cust_scope, **_nd}
    _notes_q = {**_cust_scope, "notes": {"$exists": True, "$nin": [None, ""]},
                **_nd}
    _properties_q = {**_cust_scope, "active": {"$ne": False}}
    _open_inv_q = {
        **_cust_scope, "doc_type": "invoice", **_nd,
        "status": {"$in": ["draft", "pending", "sent", "overdue"]},
    }

    try:
        results = await _summary_asyncio.gather(
            db.jobs.count_documents(_jobs_q),
            db.quotes.count_documents(_invoices_q),
            db.quotes.count_documents(_quotes_q),
            db.customer_tasks.count_documents(_tasks_q),
            db.service_reports.count_documents(_reports_q),
            db.service_reports.count_documents(_notes_q),
            db.properties.count_documents(_properties_q),
            db.quotes.count_documents(_open_inv_q),
            return_exceptions=True,
        )
    except Exception as _summary_exc:  # noqa: BLE001
        logger.warning(
            "[customer_summary] gather failed cid=%s: %s",
            cid, _summary_exc,
        )
        results = [0] * 8

    def _coerce(v):
        if isinstance(v, Exception) or v is None:
            return 0
        try:
            return int(v)
        except Exception:                                        # noqa: BLE001
            return 0

    return {
        "customer_id": cid,
        "jobs_count":            _coerce(results[0]),
        "invoices_count":        _coerce(results[1]),
        "quotes_count":          _coerce(results[2]),
        "tasks_count":           _coerce(results[3]),
        "service_reports_count": _coerce(results[4]),
        "notes_count":           _coerce(results[5]),
        "properties_count":      _coerce(results[6]),
        "open_invoices_count":   _coerce(results[7]),
    }


@router.get("/customers/{cid}/kpi-summary")
async def get_customer_kpi_summary(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase 27 · Feb-2026 — admin KPI tile data for CustomerDetail.

    Returns the six KPI tile values rendered atop the admin
    customer profile::

        {
            "customer_id":              cid,
            "balance_due_cents":        int,
            "past_due_cents":           int,
            "credit_cents":             int,
            "overdue_count":            int,
            "pending_estimates_count":  int,
            "unread_messages_count":    int,
        }

    Admin-role gated.  Tenant-scoped.  Returns 404 on missing or
    cross-tenant customer; 409 on super-admin peek of a soft-deleted
    row (same semantics as ``/customers/{cid}/summary``).

    Dollar-denominated balance figures returned in **cents** to
    match the credits endpoint shape — the frontend formats them
    for display and conditions the red/green tile backgrounds on
    the integer-cents value (``> 0``).
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "insufficient_role_for_kpi_summary")

    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    if cust.get("deleted_at"):
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "customer_soft_deleted",
                          "message": "Customer is soft-deleted; restore first."},
            )
        raise HTTPException(404, "Customer not found")

    import asyncio as _kpi_asyncio
    from utils import not_deleted_filter as _kpi_nd

    tid = tenant["id"]
    nd = _kpi_nd()
    today_iso = datetime.now(timezone.utc).date().isoformat()

    # ── Balance due + past due + overdue count — aggregated in
    # one pass over open invoices.  Open = payment_status in the
    # three unpaid buckets.  Past-due = open AND due_date before
    # today (string-compare safe because dates are ISO).
    _open_match = {
        "tenant_id": tid, "customer_id": cid, "doc_type": "invoice",
        "payment_status": {"$in": ["unpaid", "partial", "partially_paid"]},
        **nd,
    }

    async def _agg_balance():
        pipeline = [
            {"$match": _open_match},
            {"$project": {
                "balance": {"$subtract": [
                    {"$ifNull": ["$total", 0]},
                    {"$ifNull": ["$amount_paid", 0]},
                ]},
                "is_past_due": {
                    "$and": [
                        {"$ne": [{"$ifNull": ["$due_date", None]}, None]},
                        {"$lt": ["$due_date", today_iso]},
                    ]},
            }},
            {"$group": {
                "_id": None,
                "balance_due": {"$sum": "$balance"},
                "past_due": {
                    "$sum": {"$cond": ["$is_past_due", "$balance", 0]}},
                "overdue_count": {
                    "$sum": {"$cond": ["$is_past_due", 1, 0]}},
            }},
        ]
        cur = db.quotes.aggregate(pipeline)
        rows = await cur.to_list(1)
        return rows[0] if rows else {}

    _pending_est_q = {
        "tenant_id": tid, "customer_id": cid,
        "doc_type": {"$in": ["quote", "estimate"]},
        "status": {"$in": ["draft", "sent", "pending", "viewed"]},
        **nd,
    }
    # Unread messages — inbound (customer→staff) that no admin has
    # marked read yet.  ``db.messages.read_by_staff`` is set to
    # True on the first admin open; absent/False counts as unread.
    _unread_msg_q = {
        "tenant_id": tid, "customer_id": cid,
        "sender": "customer",
        "$or": [
            {"read_by_staff": {"$exists": False}},
            {"read_by_staff": False},
            {"read_by_staff": None},
        ],
    }

    async def _credit_cents():
        row = await db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1, "balance": 1},
        ) or {}
        return int(
            row.get("balance_cents")
            or int(float(row.get("balance") or 0) * 100))

    try:
        agg, pending_est, unread_msg, credit_cents = await _kpi_asyncio.gather(
            _agg_balance(),
            db.quotes.count_documents(_pending_est_q),
            db.messages.count_documents(_unread_msg_q),
            _credit_cents(),
            return_exceptions=True,
        )
    except Exception as _kpi_exc:                                    # noqa: BLE001
        logger.warning(
            "[customer_kpi_summary] gather failed cid=%s: %s",
            cid, _kpi_exc,
        )
        agg, pending_est, unread_msg, credit_cents = {}, 0, 0, 0

    def _coerce_int(v):
        if isinstance(v, Exception) or v is None:
            return 0
        try:
            return int(v)
        except Exception:                                            # noqa: BLE001
            return 0

    def _dollars_to_cents(v):
        if isinstance(v, Exception) or v is None:
            return 0
        try:
            return int(round(float(v) * 100))
        except Exception:                                            # noqa: BLE001
            return 0

    agg_dict = agg if isinstance(agg, dict) else {}
    return {
        "customer_id":             cid,
        "balance_due_cents":       _dollars_to_cents(agg_dict.get("balance_due")),
        "past_due_cents":          _dollars_to_cents(agg_dict.get("past_due")),
        "credit_cents":            _coerce_int(credit_cents),
        "overdue_count":           _coerce_int(agg_dict.get("overdue_count")),
        "pending_estimates_count": _coerce_int(pending_est),
        "unread_messages_count":   _coerce_int(unread_msg),
    }


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


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · Multi-Contact Phase 1 · Automations-mute PATCH.
# Deliberately parallel to the existing ``/mute`` + ``/unmute``
# endpoints (which flip ``is_muted`` for auto-scheduling /
# route-suggest). This endpoint flips ``automations_muted`` — a
# distinct field that ONLY gates comms fan-out. Two fields,
# two toggles, accepted trade-off per user decision 1B.
# ─────────────────────────────────────────────────────────────────
@router.patch("/customers/{cid}/mute-automations")
async def mute_automations(
    cid: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Toggle the automations-mute state on a customer.

    Body: ``{muted: bool, reason?: str, channel?: "all"|"email"|"sms"}``

    Muted=true stamps the audit trail
    (``automations_muted_reason``, ``automations_muted_at``,
    ``automations_muted_by``, ``automations_muted_channel``);
    muted=false clears the four audit fields. Admin+ only.
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403,
                              detail={"detail": "role_not_permitted",
                                       "message": "Only admin or super_admin can mute automations."})
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be an object.")
    muted = bool(body.get("muted"))
    reason = body.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            raise HTTPException(400, "reason must be a string.")
        reason = reason.strip()[:500] or None
    channel = body.get("channel") or "all"
    if channel not in ("all", "email", "sms"):
        raise HTTPException(400, "channel must be all, email, or sms.")

    from utils import not_deleted_filter as _nd
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd()},
        {"_id": 0, "id": 1, "automations_muted": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")

    if muted:
        upd = {
            "$set": {
                "automations_muted": True,
                "automations_muted_reason": reason,
                "automations_muted_at": now_iso(),
                "automations_muted_by": user.get("id"),
                "automations_muted_channel": channel,
            },
        }
    else:
        upd = {
            "$set": {
                "automations_muted": False,
                "automations_muted_reason": None,
                "automations_muted_at": None,
                "automations_muted_by": None,
                "automations_muted_channel": "all",
            },
        }
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, upd,
    )
    # Audit trail.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "customer.automations_mute" if muted
                       else "customer.automations_unmute",
            "target_type": "customer",
            "target_id": cid,
            "metadata": {"reason": reason, "channel": channel},
            "created_at": now_iso(),
        })
    except Exception as exc:
        logger.warning("[multi-contact-mute] audit log soft-fail: %s", exc)
    logger.info(
        "[multi-contact-mute] cid=%s muted=%s actor=%s reason=%r channel=%s",
        cid, muted, user.get("email"), reason, channel,
    )
    return {
        "customer_id": cid,
        "automations_muted": muted,
        "automations_muted_reason": reason if muted else None,
        "automations_muted_at": (upd["$set"].get("automations_muted_at")
                                    if muted else None),
        "automations_muted_by": user.get("id") if muted else None,
        "automations_muted_channel": channel if muted else "all",
    }


# ═══════════════════════════════════════════════════════════════════
# CUSTOMER-DETAIL-NEXT-SERVICE · Feb-2026 — admin "Next Service" tile.
# ═══════════════════════════════════════════════════════════════════
# Mirrors the Phase P47 portal next-service query shape verbatim so
# the admin tile on ``CustomerDetail.jsx`` and the customer-facing
# tile on PortalHome stay in sync forever.  Query shape (lifted from
# ``routers/customer_portal.py`` lines 191-227):
#
#   status ∈ {scheduled, active, pending, requested}
#   AND deleted_at ∈ {null, missing}
#   AND (
#       scheduled_start >= now_iso                  (rung 1)
#       OR
#       scheduled_start ∈ {null, "", missing}       (rung 2)
#         AND scheduled_date >= today_ymd
#   )
#   sort: scheduled_start ASC, scheduled_date ASC
#   limit: 1
#
# Rung-2 catches rows that only carry a bare ``YYYY-MM-DD``.  The P47
# commit (``customer_portal.py``) documents why the pre-P47 single-
# sort + Python-post-filter path failed on BSON null-sort-first
# ordering — DO NOT regress to a Python post-filter here.
#
# Response: ``{"next_service": <job doc> | None}``.  Full canonical
# job object (``{_id: 0}`` only) so the FE tile reuses the existing
# ``<StatusPill status={job.status}>`` shape and the ``/jobs/:id``
# link path from ``TodaySchedule.jsx``.  Admin-role gated + tenant-
# scoped identically to ``/kpi-summary``.
# ═══════════════════════════════════════════════════════════════════
@router.get("/customers/{cid}/next-service")
async def get_customer_next_service(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "insufficient_role_for_next_service")

    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    if cust.get("deleted_at"):
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "customer_soft_deleted",
                          "message": "Customer is soft-deleted; restore first."},
            )
        raise HTTPException(404, "Customer not found")

    now_iso_ts = datetime.now(timezone.utc).isoformat()
    today_ymd = datetime.now(timezone.utc).date().isoformat()

    doc = await db.jobs.find_one(
        {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "status": {"$in": ["scheduled", "active", "pending",
                                 "requested"]},
            "$and": [
                {"$or": [
                    {"deleted_at": None},
                    {"deleted_at": {"$exists": False}},
                ]},
                {"$or": [
                    # Rung 1 — has a real scheduled_start ≥ now.
                    {"scheduled_start": {"$gte": now_iso_ts}},
                    # Rung 2 — no scheduled_start; date ≥ today.
                    {"$and": [
                        {"$or": [
                            {"scheduled_start": None},
                            {"scheduled_start": ""},
                            {"scheduled_start": {"$exists": False}},
                        ]},
                        {"scheduled_date": {"$gte": today_ymd}},
                    ]},
                ]},
            ],
        },
        {"_id": 0},
        sort=[("scheduled_start", 1), ("scheduled_date", 1)],
    )
    return {"next_service": doc}



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
    (cancel future jobs, pause recurring templates, log event, notify
    admins).

    Returns (cancelled_job_count, deactivated_recurring_count,
             paused_template_count).

    INACTIVE-CUSTOMER-CASCADE · Feb-2026 — gap-closing addition.  The
    original Phase-34f cascade only mutated materialised instances in
    ``db.jobs`` (filtered by ``auto_recurring: true``).  The underlying
    ``db.recurring_job_templates`` rows were LEFT ACTIVE, so the
    nightly generator (``_generate_from_template``) would silently
    rematerialise visits every night and the cascade effectively
    reverted within 24h.

    Phase B closes that gap by piggy-backing on the existing P18
    pause side-effect contract (``_cancel_future_visits_on_pause`` in
    ``routers.recurring_jobs``) — flip each template's ``is_active``
    + ``active`` to False, stamp provenance fields
    (``stopped_at``, ``stopped_by_customer_cascade=true``), then fire
    the P18 helper so templates + their visits cancel through the
    SAME code path.  Prevents drift between the customer-cascade and
    the template-cascade: there is now exactly one place the visit-
    cancel semantics live.

    Idempotency: templates that are ALREADY ``is_active=false`` are
    SKIPPED — the fresh filter (``is_active: True``) ensures the
    ``stopped_by_customer_cascade`` provenance is only stamped the
    first time, and a manually-paused template never gets our
    provenance stamp mis-attributed.
    """
    cancelled_job_count = 0
    deactivated_recurring_count = 0
    paused_template_count = 0
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

        # ─────────── INACTIVE-CUSTOMER-CASCADE · template pause.
        # Scope filter targets ONLY currently-active templates for this
        # customer.  Manually-paused templates (``is_active=false``) are
        # left alone so their original ``stopped_at`` / reason provenance
        # survives.  Legacy ``active`` field is also written for parity
        # with the ``_generate_from_template`` short-circuit at
        # ``routers/recurring_jobs.py:2004-2007`` which checks either
        # field.
        try:
            _now = now_iso()
            active_tpls = await db.recurring_job_templates.find(
                {"tenant_id": tenant_id, "customer_id": cid,
                 "is_active": True},
                {"_id": 0, "id": 1},
            ).to_list(1000)
            if active_tpls:
                tpl_ids = [t["id"] for t in active_tpls]
                tpl_upd = await db.recurring_job_templates.update_many(
                    {"tenant_id": tenant_id, "id": {"$in": tpl_ids},
                     "is_active": True},
                    {"$set": {
                        "is_active": False,
                        "active": False,
                        "stopped_at": _now,
                        "stopped_by_customer_cascade": True,
                        "updated_at": _now,
                    }},
                )
                paused_template_count = int(tpl_upd.modified_count or 0)
                # Fire the shared P18 visit-cancel helper per template.
                # Best-effort — a per-template cancel failure is logged
                # but doesn't abort the broader cascade.  The helper is
                # idempotent on its own (its filter requires
                # ``status in [pending, scheduled]``) so a retry is
                # safe.
                from routers.recurring_jobs import (
                    _cancel_future_visits_on_pause,
                )
                for tpl_id in tpl_ids:
                    try:
                        await _cancel_future_visits_on_pause(
                            tenant_id=tenant_id, tpl_id=tpl_id,
                            actor=user,
                        )
                    except Exception as _p18_exc:
                        logger.warning(
                            "[inactive-cascade] visit-cancel failed "
                            "tpl=%s err=%s", tpl_id, _p18_exc,
                        )
        except Exception as _tpl_exc:  # pragma: no cover - defensive
            logger.warning(
                "[inactive-cascade] template pause failed cid=%s err=%s",
                cid, _tpl_exc,
            )

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
            # INACTIVE-CUSTOMER-CASCADE · Feb-2026 — audit the number
            # of recurring_job_templates paused by this cascade.
            "paused_template_count": paused_template_count,
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
    return (cancelled_job_count, deactivated_recurring_count,
             paused_template_count)


async def _mirror_address_to_primary_property(
    cid: str, tenant_id: str, customer_merged: Dict[str, Any],
) -> None:
    """Feb-2026 · Customer profile display bugfix.

    The customer detail page reads the primary address from
    ``db.properties`` (via ``getPrimaryPropertyAddress`` in
    ``CustomerDetail.jsx``), NOT from the customer doc directly. When
    an admin edits the customer's address, the customer PUT handler
    persists to ``db.customers`` but leaves the property row stale —
    causing "save appears to not persist" reports.

    This helper is called AFTER the customer $set has landed, from
    the same PUT handler. It resolves the customer's primary
    property (``is_primary`` OR ``sort_order == 0`` OR
    ``label == 'Main'``) and mirrors the freshly-normalised address
    fields onto it. Idempotent + non-blocking (caller wraps in a
    try/except).

    Resolution priority for the property's address fields:
    1. Structured customer fields (``address_line1``, ``city``,
       ``state``, ``postal_code``) when present.
    2. ``service_address`` object shape when it's a dict.
    3. Fallback to parsing the free-form ``address`` string via the
       same rules the FE ``_parseAddress`` helper uses.

    Zero-property customers are skipped — the lazy backfill in
    ``list_customer_properties`` will seed a fresh property from the
    updated customer doc on the next GET.
    """
    line1 = ""
    city = ""
    state = ""
    postal = ""

    # Feb-2026 · Parse the free-form ``address`` string FIRST — the
    # ``CustomerIn`` API model exposes only the flat ``address``
    # field, so the structured legacy fields on the merged doc
    # (``address_line1`` etc.) may be stale relative to what the
    # caller just PUT. Match the frontend ``_parseAddress`` rules:
    # split on commas, first chunk is street, last chunk is
    # "STATE ZIP", middle chunks join as the city.
    raw = customer_merged.get("address")
    if isinstance(raw, str) and raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            line1 = parts[0]
            if len(parts) >= 2:
                import re as _re
                m = _re.match(
                    r"^([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$",
                    parts[-1],
                )
                if m:
                    state = m.group(1).upper()
                    postal = m.group(2)
                    if len(parts) >= 3:
                        city = ", ".join(parts[1:-1])
                else:
                    # Support 4-part shape ``street, city, STATE, ZIP``
                    # where state + zip live in separate comma
                    # segments (a variation the frontend produced in
                    # earlier phases).
                    zip_m = _re.match(r"^\d{5}(?:-\d{4})?$", parts[-1])
                    state_m = (
                        _re.match(r"^[A-Za-z]{2}$", parts[-2])
                        if len(parts) >= 2 else None
                    )
                    if zip_m and state_m and len(parts) >= 3:
                        postal = parts[-1]
                        state = parts[-2].upper()
                        city = ", ".join(parts[1:-2])
                    else:
                        # No trailing state/zip chunk — treat
                        # everything after the street as the city.
                        city = ", ".join(parts[1:])

    # Structured fields fill in gaps left by the parser (e.g. the
    # caller sent a bare street with no comma).
    line1 = line1 or (customer_merged.get("address_line1") or "").strip()
    city = city or (customer_merged.get("city") or "").strip()
    state = state or (customer_merged.get("state") or "").strip()
    postal = postal or (customer_merged.get("postal_code")
                          or customer_merged.get("zip") or "").strip()

    # Nested service_address object — third-tier fallback.
    sa = customer_merged.get("service_address")
    if isinstance(sa, dict):
        line1 = line1 or (sa.get("street")
                          or sa.get("line1")
                          or sa.get("address_line1") or "").strip()
        city = city or (sa.get("city") or "").strip()
        state = state or (sa.get("state") or "").strip()
        postal = postal or (sa.get("postal_code")
                            or sa.get("zip") or "").strip()

    if not any([line1, city, state, postal]):
        return  # nothing to mirror

    # Find the primary property. Prefer explicit ``is_primary``,
    # fall back to lowest ``sort_order``. Case-insensitive
    # ``label='Main'`` is a third-tier fallback for legacy tenants.
    prop = await db.properties.find_one(
        {"tenant_id": tenant_id, "customer_id": cid,
         "is_primary": True},
        {"_id": 0, "id": 1, "address": 1},
    )
    if not prop:
        prop = await db.properties.find_one(
            {"tenant_id": tenant_id, "customer_id": cid,
             "active": {"$ne": False}},
            {"_id": 0, "id": 1, "address": 1},
            sort=[("sort_order", 1)],
        )
    if not prop:
        return  # zero-property customer — lazy backfill will seed

    updates: Dict[str, Any] = {}
    if line1:
        updates["address.line1"] = line1
    if city:
        updates["address.city"] = city
    if state:
        updates["address.state"] = state
    if postal:
        updates["address.postal_code"] = postal
    if not updates:
        return
    updates["updated_at"] = now_iso()
    await db.properties.update_one(
        {"id": prop["id"], "tenant_id": tenant_id},
        {"$set": updates},
    )


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
    # Feb-2026 · Diag-Timeout Task 1 — rebuild ``search_haystack``
    # whenever the write may have mutated any of the six searchable
    # columns. Cheap; keeps the fast-path index accurate without a
    # follow-up backfill.
    from services.customers_search_haystack import (
        build_haystack as _build_hay,
    )
    _merged = {**existing, **payload}
    payload["search_haystack"] = _build_hay(_merged)
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
    # Feb-2026 · Auto-geocode phase — expanded to walk EVERY field
    # ``resolve_customer_address`` reads (free-form + structured +
    # legacy variants) + idempotency-guarded via
    # ``geocode_address_hash`` so an update that mutates only, say,
    # notes doesn't re-fire the geocode.
    from services.google_maps.geocoding import (
        resolve_customer_address as _resolve_addr,
    )
    from routers.admin_customer_geocode_backfill import (
        address_hash as _addr_hash,
    )
    _merged_after = {**existing, **payload}
    _new_addr = _resolve_addr(_merged_after)
    _old_addr = _resolve_addr(existing)
    _new_hash = _addr_hash(_new_addr)
    _old_hash = existing.get("geocode_address_hash") or _addr_hash(_old_addr)
    _addr_changed = _new_addr != _old_addr or _new_hash != _old_hash
    if _addr_changed and _new_addr:
        try:
            import asyncio as _a17
            from services.google_maps.geocoding import (
                geocode_and_persist_customer as _gp17,
            )
            await db.customers.update_one(
                {"id": cid, "tenant_id": tenant["id"]},
                {"$unset": {"geocoded_at": ""},
                 "$set": {"geocode_address_hash": _new_hash}},
            )
            _a17.create_task(_gp17(cid, tenant["id"]))
        except Exception:
            pass

    # Feb-2026 · Customer profile detail bugfix — the customer detail
    # page renders its primary address from ``db.properties`` (see
    # ``getPrimaryPropertyAddress`` in the FE). When an admin edits
    # the customer address, we MUST mirror the write to the primary
    # property row too — otherwise the save appears to no-op on the
    # detail card even though the customer doc updated cleanly.
    #
    # We independently check the flat ``address`` string change too
    # because ``CustomerIn`` strips ``service_address`` / ``address_line1``
    # (see models.py) — that means ``resolve_customer_address`` may
    # still pick the stale nested value on the merged doc, making
    # ``_addr_changed`` falsely False when the ONLY thing the caller
    # sent was a new flat ``address`` string.
    _flat_before = (existing.get("address") or "").strip()
    _flat_after = (payload.get("address") or "").strip()
    _mirror_trigger = _addr_changed or _flat_before != _flat_after
    if _mirror_trigger:
        try:
            await _mirror_address_to_primary_property(cid, tenant["id"],
                                                        _merged_after)
        except Exception as _pm_exc:
            logger.warning(
                "[customer.update] primary property address mirror "
                f"failed cid={cid}: {_pm_exc}"
            )

    (cancelled_job_count,
     deactivated_recurring_count,
     paused_template_count) = await _apply_activation_cascade(
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
        # INACTIVE-CUSTOMER-CASCADE · Feb-2026 — expose template-pause
        # count on the PUT response envelope so the ``ActivationControl``
        # confirm-toast surface can read it alongside the existing
        # job-cancel count.
        doc["paused_template_count"] = paused_template_count
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

    (cancelled_job_count,
     deactivated_recurring_count,
     paused_template_count) = await _apply_activation_cascade(
        cid, tenant["id"], user, was_active, now_active, existing.get("name")
    )

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if was_active is True and now_active is False:
        doc["cancelled_job_count"] = cancelled_job_count
        doc["deactivated_recurring_count"] = deactivated_recurring_count
        # INACTIVE-CUSTOMER-CASCADE · Feb-2026 — parity with PUT path.
        doc["paused_template_count"] = paused_template_count
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
    # Feb-2026 · Customer-Attachments (Option D) — optional list of
    # ``marketing_media.id`` values. Empty list and unset field are
    # equivalent; both skip the attachment path entirely.
    attachments: Optional[List[str]] = None


# BUG F · Feb 2026 — customer-direct SMS body. Mirrors the email
# payload so the frontend composer can flip channels without a body
# schema change.
class _SendSmsBody(BaseModel):
    to: str
    body: str
    customer_id: Optional[str] = None
    # Feb-2026 · Customer-Attachments (Option D) — optional list of
    # ``marketing_media.id`` values. Each resolves to a signed public
    # download URL appended to the SMS body.
    attachments: Optional[List[str]] = None


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


# ═══════════════════════════════════════════════════════════════════════════
# Phase P7 · Feb-2026 · Send-email attachment hardening (Option B).
# ═══════════════════════════════════════════════════════════════════════════
# Applies email-only tighter caps on top of Option D. The library-side
# upload endpoint (``POST /api/marketing/media/upload``) keeps its more
# permissive per-type caps (image 5 MB / PDF 15 MB / doc 10 MB / SVG
# 200 KB) — those are for library storage, not send-time. This gate is
# strictly additive: every 422 code introduced here fires BEFORE the
# resolver's own 404/413/502 branches, so pre-P7 client contracts on
# ``file_not_found`` / ``attachment_too_large_*`` / ``storage_unavailable``
# remain intact for any other consumer.
_EMAIL_ATTACHMENTS_MAX_COUNT = 5                       # per-send cap
_EMAIL_ATTACHMENT_MAX_BYTES  = 10 * 1024 * 1024        # 10 MB per file

# Content-type whitelist (email side). Anything else → 422
# ``attachment_type_disallowed``.
_EMAIL_ATTACHMENT_TYPE_WHITELIST = frozenset({
    # Images
    "image/jpeg", "image/png", "image/webp",
    "image/heic", "image/heif",
    # PDF
    "application/pdf",
    # Office docs
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
})

# Extension → MIME fallback used when the media row's ``mime_type`` is
# ``application/octet-stream`` (i.e. the upload path couldn't sniff it
# and python-magic isn't installed in this pod).
_EMAIL_ATTACHMENT_EXT_TO_MIME = {
    ".jpg":  "image/jpeg", ".jpeg": "image/jpeg",
    ".png":  "image/png",  ".webp": "image/webp",
    ".heic": "image/heic", ".heif": "image/heif",
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv":  "text/csv",
}


def _mime_from_filename(filename: Optional[str]) -> str:
    """Best-effort MIME fallback keyed off the filename extension.
    Returns ``""`` when the extension isn't in the whitelist map so
    the caller's ``not in _EMAIL_ATTACHMENT_TYPE_WHITELIST`` check
    fires deterministically. Never raises."""
    if not filename:
        return ""
    lower = filename.lower()
    dot = lower.rfind(".")
    if dot < 0:
        return ""
    return _EMAIL_ATTACHMENT_EXT_TO_MIME.get(lower[dot:], "")


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

    # Feb-2026 · Customer-Attachments (Option D). Resolve file IDs into
    # base64 attachment dicts. Cross-tenant, size, and storage errors
    # all abort the send with a targeted 4xx/5xx so the frontend can
    # render an actionable red toast — never a half-attached email.
    attachment_ids = body.attachments or []
    email_attachments: List[Dict[str, Any]] = []
    if attachment_ids:
        # ── Phase P7 · Feb-2026 · Send-email email-only hardening ──
        # 1. Per-send cap of 5 attachments. Pre-check on the payload
        #    BEFORE any Mongo I/O so a bad client can't force us into
        #    an expensive resolver batch. 422 (not 4xx via resolver)
        #    with a stable error code the UI can key off.
        # 2. Content-type whitelist (email-specific). Option D's
        #    resolver accepts any type the media library persisted;
        #    tighter caller here rejects everything outside the
        #    whitelisted image/PDF/office/CSV set. Falls back to the
        #    filename extension when the row's ``mime_type`` is
        #    ``application/octet-stream`` (unknown) because
        #    python-magic isn't a dep in this pod — flagged in the
        #    wrap-up. See ``_EMAIL_ATTACHMENT_TYPE_WHITELIST`` /
        #    ``_EMAIL_ATTACHMENT_EXT_TO_MIME`` below.
        # 3. Per-file 10 MB cap enforced on the row's stored
        #    ``size_bytes`` at the email gate. The library's own
        #    per-type caps (5 MB img / 15 MB PDF / 10 MB doc / 200
        #    KB SVG) stay intact for other consumers; the resolver's
        #    413 ``file_too_large`` is now unreachable for the email
        #    path (this gate fires first at 10 MB, matching what the
        #    resolver would enforce anyway) but stays as a defensive
        #    net for any bytes-drift edge case.
        # 4. Tenant scoping continues to happen inside the resolver
        #    (``_fetch_row`` filters by ``tenant_id``), so a
        #    cross-tenant id still surfaces as 404 file_not_found.
        if len(attachment_ids) > _EMAIL_ATTACHMENTS_MAX_COUNT:
            raise HTTPException(
                422,
                detail={
                    "code": "attachments_cap_exceeded",
                    "count": len(attachment_ids),
                    "limit": _EMAIL_ATTACHMENTS_MAX_COUNT,
                },
            )
        # Single Mongo find covers the whole batch — cheaper than N
        # sequential ``_fetch_row`` calls the resolver would make.
        _rows = await db.marketing_media.find(
            {"id":         {"$in": attachment_ids},
             "tenant_id":  tenant["id"],
             "deleted_at": None},
            {"_id": 0, "id": 1, "file_name": 1,
             "mime_type": 1, "size_bytes": 1},
        ).to_list(length=len(attachment_ids) + 1)
        _rows_by_id = {r["id"]: r for r in _rows}
        for fid in attachment_ids:
            row = _rows_by_id.get(fid)
            if row is None:
                # Let the resolver's 404 branch handle unknown ids
                # for a consistent error shape with the pre-P7 path.
                continue
            _fn = row.get("file_name") or fid
            _size = int(row.get("size_bytes") or 0)
            if _size > _EMAIL_ATTACHMENT_MAX_BYTES:
                raise HTTPException(
                    422,
                    detail={
                        "code":        "attachment_too_large",
                        "filename":    _fn,
                        "size_bytes":  _size,
                        "limit_bytes": _EMAIL_ATTACHMENT_MAX_BYTES,
                    },
                )
            _mime = (row.get("mime_type") or "").lower().strip()
            if _mime and _mime != "application/octet-stream":
                _resolved = _mime
            else:
                _resolved = _mime_from_filename(_fn)
            if _resolved not in _EMAIL_ATTACHMENT_TYPE_WHITELIST:
                raise HTTPException(
                    422,
                    detail={
                        "code":         "attachment_type_disallowed",
                        "filename":     _fn,
                        "content_type": _resolved or "unknown",
                    },
                )
        from services.marketing_media.attachments import (
            AttachmentTooLarge, MediaFileNotFound,
            resolve_email_attachments,
        )
        from services.marketing_media.storage_client import StorageUnavailable
        try:
            email_attachments = await resolve_email_attachments(
                tenant["id"], attachment_ids,
            )
        except MediaFileNotFound as exc:
            raise HTTPException(
                404,
                detail={"code": "file_not_found", "file_id": exc.file_id},
            )
        except AttachmentTooLarge as exc:
            raise HTTPException(
                413,
                detail={
                    "code":         exc.code,
                    "file_id":      exc.file_id,
                    "size_bytes":   exc.size_bytes,
                    "limit_bytes":  exc.limit_bytes,
                },
            )
        except StorageUnavailable as exc:
            raise HTTPException(
                502, detail={"code": "storage_unavailable",
                              "message": str(exc)[:200]},
            )

    from services.comms_email_adapter import send_email
    from services.comms_env_guard import CommsContext
    res = await send_email(
        tenant["id"], to,
        subject=body.subject.strip() or "Message",
        html=f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{body.body}</pre>",
        attachments=email_attachments or None,
        context=CommsContext.SYSTEM,
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
                                "sent_by": user.get("id"),
                                "attachment_ids": attachment_ids or None},
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

    # Feb-2026 · Customer-Attachments (Option D) — resolve file IDs
    # to signed public URLs and append them to the outgoing body.
    # SMS carries no attachment bytes so the trust model is the same
    # HMAC-signed marketing_media link already used for image
    # thumbnails in delivered emails.
    sms_body = body.body
    attachment_ids = body.attachments or []
    if attachment_ids:
        # Phase P1.2 · Feb 2026 — signed URLs now embed an ``exp``
        # claim. SMS gets the shorter 72-hour TTL since it's a
        # more replay-prone surface (forwarded texts / screenshots).
        from routers.marketing_media import (
            _signed_download_url, MEDIA_URL_TTL_SMS_SECONDS,
        )
        from services.marketing_media.attachments import (
            MediaFileNotFound, format_sms_attachments_suffix,
            resolve_sms_public_urls,
        )
        try:
            urls = await resolve_sms_public_urls(
                tenant["id"], attachment_ids,
                build_signed_url=_signed_download_url,
                ttl_seconds=MEDIA_URL_TTL_SMS_SECONDS,
            )
        except MediaFileNotFound as exc:
            raise HTTPException(
                404,
                detail={"code": "file_not_found", "file_id": exc.file_id},
            )
        sms_body = sms_body.rstrip() + format_sms_attachments_suffix(urls)
        if len(sms_body) > 480:
            logger.warning(
                "[customer-attachments] SMS body %d chars > 480 "
                "(will segment across %d parts) tenant=%s customer=%s",
                len(sms_body), (len(sms_body) + 159) // 160,
                tenant["id"], cid,
            )

    from services.sms.rc_adapter import send as _sms_send
    res = await _sms_send(
        to=to_raw,
        body=sms_body,
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
            "body": sms_body,
            "delivery_status": res.get("provider_status") or "unknown",
            "provider": res.get("provider") or "ringcentral",
            "provider_response_id": res.get("provider_response_id"),
            "trigger_entity": {"kind": "customer_direct_message",
                                "customer_id": cid,
                                "sent_by": user.get("id"),
                                "attachment_ids": attachment_ids or None},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"[bug-f] failed to persist customer sms comms_log row: {e}")

    status = res.get("provider_status")
    # Phase I1.7.e · Fix A · Feb-2026 — guard-block statuses are NOT
    # infrastructure failures. Each of the pre-flight gates in
    # ``rc_adapter.send`` (marketing suppression, K31 consent gate,
    # comm-allowlist gate, K72 kill switch, ``guard_outbound`` preview
    # dry-run, tenant-BYO cap) intentionally returns a distinct
    # ``provider_status`` other than ``"sent"``. They mean "the safety
    # system fired and no live send occurred" — the caller should get
    # 200 OK with the envelope so the UI can surface the reason,
    # not a 502 that implies a transport-level failure.
    #
    # Cap-exceeded is a real business signal (tenant hit their monthly
    # cap) so it surfaces as HTTP 429 — the same shape every other
    # transactional cap-exceeded callsite uses.
    from services.messaging.byo_passthrough import raise_if_cap_exceeded
    raise_if_cap_exceeded(res,
                           detail="Monthly SMS cap exceeded for this tenant")
    if status == "failed" or not status:
        raise HTTPException(
            502,
            f"send failed: {res.get('error') or status or 'unknown'}",
        )
    return {"ok": True, **res}



# ═══════════════════════════════════════════════════════════════════════════
# Task 6 · Feb 2026 · "Send service records link" (Customer admin page).
#
# Admin dispatches a portal auto-login magic URL to the customer via
# Email or SMS. The URL redeems into a customer-scoped session and
# drops the customer on ``/portal/service-reports`` (the existing
# portal list surface — NO new portal view was invented). Rate
# limited to 5 sends per hour per customer. Consent is hard-enforced
# — a customer whose ``channel_opt_in.email_marketing`` or
# ``channel_opt_in.sms_marketing`` is explicitly False cannot be
# targeted; the 403 error surfaces the reason so the admin UI can
# render a tooltip explaining the block.
# ═══════════════════════════════════════════════════════════════════════════
class _ServiceRecordsLinkSendBody(BaseModel):
    channel: str = Field(..., pattern="^(email|sms)$")
    recipient: Optional[str] = None  # optional override — falls back
    # to the customer's primary email/phone. When supplied it MUST
    # match one of the customer's mirrored contacts (same allow-list
    # rule as ``send-email`` / ``send-sms``).


_SR_LINK_RATE_LIMIT_PER_HOUR = 5
_SR_LINK_TTL_HOURS = 168  # 7 days


def _sr_link_has_consent(customer: dict, channel: str) -> bool:
    """Task 6 consent gate. Absent field OR True = allow; explicit
    False = block. Muted customers are always blocked regardless of
    channel_opt_in. Transactional-only opt-in (email_transactional
    /sms_transactional) is NOT sufficient — the service-records link
    is treated as marketing-adjacent for this compliance surface per
    the Task 6 spec.
    """
    if customer.get("is_muted"):
        return False
    channel_opt_in = customer.get("channel_opt_in") or {}
    key = "email_marketing" if channel == "email" else "sms_marketing"
    return channel_opt_in.get(key) is not False


def _sr_link_default_recipient(customer: dict, channel: str) -> Optional[str]:
    if channel == "email":
        for e in (customer.get("emails") or []):
            addr = (e.get("address") or "").strip()
            if addr:
                return addr
        return (customer.get("email") or "").strip() or None
    # sms
    for m in (customer.get("mobiles") or []):
        n = (m.get("number_e164") or "").strip()
        if n:
            return n
    return (customer.get("phone") or "").strip() or None


def _sr_link_recipient_matches(customer: dict, channel: str, recipient: str) -> bool:
    """Verify the supplied recipient is one of the customer's mirrored
    contacts on that channel. Prevents an admin from redirecting the
    link to an arbitrary address/phone.
    """
    r = (recipient or "").strip()
    if not r:
        return False
    if channel == "email":
        r_lc = r.lower()
        addrs = {(e.get("address") or "").strip().lower()
                  for e in (customer.get("emails") or [])}
        addrs.add((customer.get("email") or "").strip().lower())
        addrs.discard("")
        return r_lc in addrs

    def _digits(s: str) -> str:
        return "".join(ch for ch in (s or "") if ch.isdigit())

    def _norm(d: str) -> str:
        return d[-10:] if len(d) > 10 else d

    r_digits = _digits(r)
    allowed: set[str] = set()
    for m in (customer.get("mobiles") or []):
        n = _digits(m.get("number_e164") or "")
        if n:
            allowed.add(n)
    for k in ("phone", "mobile_phone", "phone_number"):
        n = _digits(customer.get(k) or "")
        if n:
            allowed.add(n)
    return _norm(r_digits) in {_norm(a) for a in allowed}


def _sr_link_hash(url: str) -> str:
    """Legacy — Feb-2026 Task 6 originally hashed the built URL. The
    revoke ship (Task 6b) switched to hashing the raw JWT so the
    denylist lookup on redemption is stable across URL rebuilds.
    Kept for any historical caller — new code MUST use
    ``services.service_records_link.hash_token``.
    """
    import hashlib
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@router.post("/customers/{cid}/send-service-records-link",
              operation_id="customers.sendServiceRecordsLink")
async def send_service_records_link(cid: str,
                                       body: _ServiceRecordsLinkSendBody,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    """Admin action from the Customer detail page — dispatches a
    portal auto-login magic URL that opens directly on the customer's
    service records list.

    Body:
      * ``channel`` — ``"email"`` or ``"sms"``.
      * ``recipient`` — optional override (defaults to the customer's
        primary email/phone). When supplied it MUST match one of the
        customer's mirrored contacts on that channel.

    Response:
      * ``ok`` — True on success.
      * ``url`` — the generated auto-login URL. The frontend renders
        a Copy button so the admin can share the URL manually as a
        fallback when delivery hasn't landed yet.
      * ``recipient`` — the final target address/phone.
      * ``channel`` — echoed back.
      * ``ttl_hours`` — 168 (7 days).
      * ``expires_at`` — ISO timestamp for the link expiry.

    Errors:
      * 403 ``consent_blocked`` — customer has ``channel_opt_in``
        False for the requested channel (or is muted). Admin
        CANNOT bypass. Surfaces ``reason`` = ``sms_consent_off`` /
        ``email_consent_off`` / ``muted``.
      * 400 ``no_recipient`` — no contact on file for the channel
        AND no ``recipient`` override was supplied.
      * 400 ``recipient_not_allowed`` — the supplied override is
        NOT one of the customer's mirrored contacts.
      * 429 ``rate_limited`` — customer has hit the 5-sends-per-hour
        cap. Response body includes ``retry_after_seconds``.
      * 502 — email/SMS adapter failed (not a customer-visible
        error — the admin can retry).
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    import os as _os

    channel = (body.channel or "").strip().lower()
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    # 1) Consent gate — hard-block. Admin cannot override.
    if customer.get("is_muted"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "consent_blocked",
                      "reason": "muted",
                      "message": "This customer is muted — outbound comms are disabled."},
        )
    if not _sr_link_has_consent(customer, channel):
        reason = "sms_consent_off" if channel == "sms" else "email_consent_off"
        friendly = ("SMS opt-in is off for this customer."
                     if channel == "sms"
                     else "Email opt-in is off for this customer.")
        raise HTTPException(
            status_code=403,
            detail={"detail": "consent_blocked",
                      "reason": reason,
                      "message": friendly},
        )

    # 2) Recipient resolution.
    recipient = (body.recipient or "").strip()
    if recipient:
        if not _sr_link_recipient_matches(customer, channel, recipient):
            raise HTTPException(
                status_code=400,
                detail={"detail": "recipient_not_allowed",
                          "message": (
                              "Recipient must match one of the "
                              "customer's mirrored contacts."
                          )},
            )
    else:
        recipient = _sr_link_default_recipient(customer, channel) or ""
    if not recipient:
        raise HTTPException(
            status_code=400,
            detail={"detail": "no_recipient",
                      "message": (
                          f"No {channel} on file for this customer."
                      )},
        )

    # 3) Rate limit — 5 sends per hour per customer, across BOTH channels.
    now = _dt.now(_tz.utc)
    window_start = now - _td(hours=1)
    recent = await db.customer_link_sends.count_documents({
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "created_at": {"$gte": window_start.isoformat()},
    })
    if recent >= _SR_LINK_RATE_LIMIT_PER_HOUR:
        # Compute retry-after = seconds until the oldest hit in-window falls off.
        oldest = await db.customer_link_sends.find_one(
            {"tenant_id": tenant["id"], "customer_id": cid,
             "created_at": {"$gte": window_start.isoformat()}},
            sort=[("created_at", 1)],
        )
        retry_after = 3600
        if oldest and oldest.get("created_at"):
            try:
                oldest_dt = _dt.fromisoformat(oldest["created_at"])
                retry_after = max(60, int(3600 - (now - oldest_dt).total_seconds()))
            except Exception:
                pass
        raise HTTPException(
            status_code=429,
            detail={"detail": "rate_limited",
                      "message": (
                          f"Rate limit hit — max "
                          f"{_SR_LINK_RATE_LIMIT_PER_HOUR} sends per hour "
                          "per customer."
                      ),
                      "retry_after_seconds": retry_after,
                      "limit_per_hour": _SR_LINK_RATE_LIMIT_PER_HOUR},
        )

    # 4) Mint the token + URL.
    from services.service_records_link import (
        build_service_records_url_and_token, hash_token,
    )
    base = _os.environ.get("APP_PUBLIC_URL", "") or ""
    if not base:
        # Fall back to the tenant's configured portal URL if APP_PUBLIC_URL
        # isn't set (common in dev). This keeps the URL clickable in the
        # local box; production always sets APP_PUBLIC_URL.
        base = (tenant.get("portal_url") or tenant.get("portal_link") or "").rstrip("/")
    if not base:
        raise HTTPException(
            status_code=500,
            detail={"detail": "public_url_unset",
                      "message": "APP_PUBLIC_URL is not configured — cannot build the link."},
        )
    url, raw_token = build_service_records_url_and_token(
        base, cid, tenant["id"], ttl_hours=_SR_LINK_TTL_HOURS,
    )
    token_hash = hash_token(raw_token)
    expires_at = (now + _td(hours=_SR_LINK_TTL_HOURS)).isoformat()

    # 5) Dispatch on the requested channel.
    company_name = tenant.get("name") or "your service"
    subject = f"Your service records — {company_name}"
    if channel == "email":
        greeting_name = (customer.get("first_name")
                          or (customer.get("name") or "").split(" ", 1)[0]
                          or "there")
        html = (
            f"<div style=\"font-family:-apple-system,Segoe UI,Roboto,"
            f"Helvetica,Arial,sans-serif;color:#222;line-height:1.5;\">"
            f"<p>Hi {greeting_name},</p>"
            f"<p>Here are your service records with {company_name}. "
            f"Click the button below to view your history — no "
            f"password needed.</p>"
            f"<p style=\"margin:24px 0;\">"
            f"<a href=\"{url}\" style=\"display:inline-block;"
            f"background:#0f6ed1;color:#fff;padding:12px 24px;"
            f"text-decoration:none;border-radius:6px;font-weight:600;\">"
            f"View service records</a></p>"
            f"<p style=\"color:#555;font-size:13px;\">Or paste this link "
            f"in your browser:<br/>"
            f"<a href=\"{url}\">{url}</a></p>"
            f"<p style=\"color:#8a8a8a;font-size:12px;margin-top:32px;\">"
            f"This link expires in 7 days.</p>"
            f"</div>"
        )
        from services.comms_email_adapter import send_email
        from services.comms_env_guard import CommsContext
        res = await send_email(
            tenant["id"], recipient,
            subject=subject, html=html,
            context=CommsContext.SYSTEM,
        )
        provider = "resend"
        provider_status = res.get("status") or "unknown"
        provider_id = res.get("provider_id")
        if provider_status not in ("sent", "queued", "mocked", "skipped_opted_out"):
            raise HTTPException(
                502,
                f"send failed: {res.get('error') or provider_status}",
            )
    else:  # sms
        # SMS body — keep tight for deliverability. Under ~160 chars
        # when company name is short. No shortener helper exists in
        # this codebase (per spec: skip if adds complexity); a longer
        # URL is fine since providers segment cleanly.
        sms_body = f"{company_name}: view your service records — {url} (expires in 7 days)"
        from services.sms.rc_adapter import send as _sms_send
        res = await _sms_send(
            to=recipient,
            body=sms_body,
            category="transactional",
            tenant_id=tenant["id"],
            customer_id=cid,
        )
        provider = res.get("provider") or "ringcentral"
        provider_status = res.get("provider_status") or "unknown"
        provider_id = res.get("provider_response_id")
        # Reuse the cap-exceeded 429 branch the sibling ``send-sms``
        # endpoint uses so tenant SMS caps get the same treatment.
        from services.messaging.byo_passthrough import raise_if_cap_exceeded
        raise_if_cap_exceeded(
            res, detail="Monthly SMS cap exceeded for this tenant",
        )
        if provider_status == "failed" or not provider_status:
            raise HTTPException(
                502,
                f"send failed: {res.get('error') or provider_status}",
            )

    # 6) Audit row — powers the 5/hour rate limit AND appears on the
    # customer's activity timeline. Best-effort persistence of the
    # comms_log row so the admin timeline surfaces the send even if
    # the audit-insert path fails somehow.
    try:
        await db.customer_link_sends.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": channel,
            "recipient": recipient,
            "sent_by": user.get("id"),
            "sent_by_email": user.get("email"),
            "provider": provider,
            "provider_status": provider_status,
            "provider_response_id": provider_id,
            "token_hash": token_hash,
            "ttl_hours": _SR_LINK_TTL_HOURS,
            "expires_at": expires_at,
            "revoked_at": None,
            "revoked_by": None,
            "created_at": now.isoformat(),
        })
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[task6] audit insert failed cid=%s: %s", cid, _exc)

    try:
        await db.communications_log.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": channel,
            "direction": "outbound",
            "recipient": recipient,
            "subject": subject if channel == "email" else None,
            "body": ("Service records link sent" if channel == "email"
                     else "Service records SMS link sent"),
            "delivery_status": provider_status,
            "provider": provider,
            "provider_response_id": provider_id,
            "trigger_entity": {"kind": "service_records_link",
                                "customer_id": cid,
                                "sent_by": user.get("id")},
            "created_at": now.isoformat(),
        })
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[task6] comms_log insert failed cid=%s: %s", cid, _exc)

    return {
        "ok": True,
        "url": url,
        "recipient": recipient,
        "channel": channel,
        "ttl_hours": _SR_LINK_TTL_HOURS,
        "expires_at": expires_at,
        "provider_status": provider_status,
    }


@router.get("/customers/{cid}/service-records-link-status",
              operation_id="customers.getServiceRecordsLinkStatus")
async def get_service_records_link_status(cid: str,
                                             user: dict = Depends(require_admin),
                                             tenant: dict = Depends(get_current_tenant)):
    """Task 6 · Feb 2026 — light read surface for the modal. Returns:

    * ``sends_last_hour`` — count of successful sends in the past hour.
    * ``rate_limit`` — the 5-per-hour ceiling (exposed so the UI
      doesn't hardcode the number).
    * ``rate_limited`` — True when ``sends_last_hour >= rate_limit``.
    * ``retry_after_seconds`` — seconds until the oldest send falls
      out of the rolling window (only set when rate_limited).
    * ``last_send_at`` — ISO timestamp of the most recent send.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    # Confirm the customer exists + tenant-scoped.
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    now = _dt.now(_tz.utc)
    window_start = now - _td(hours=1)
    q = {"tenant_id": tenant["id"], "customer_id": cid,
          "created_at": {"$gte": window_start.isoformat()}}
    count = await db.customer_link_sends.count_documents(q)
    last = await db.customer_link_sends.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid},
        sort=[("created_at", -1)],
    )
    rate_limited = count >= _SR_LINK_RATE_LIMIT_PER_HOUR
    retry_after: Optional[int] = None
    if rate_limited:
        oldest = await db.customer_link_sends.find_one(
            q, sort=[("created_at", 1)],
        )
        if oldest and oldest.get("created_at"):
            try:
                oldest_dt = _dt.fromisoformat(oldest["created_at"])
                retry_after = max(
                    60,
                    int(3600 - (now - oldest_dt).total_seconds()),
                )
            except Exception:
                retry_after = 3600
        else:
            retry_after = 3600
    return {
        "sends_last_hour": count,
        "rate_limit": _SR_LINK_RATE_LIMIT_PER_HOUR,
        "rate_limited": rate_limited,
        "retry_after_seconds": retry_after,
        "last_send_at": (last or {}).get("created_at"),
    }


# ── Task 6b · Feb 2026 · Revoke a sent service-records link ──────────
class _ServiceRecordsLinkListItem(BaseModel):
    id: str
    channel: str
    recipient: str
    sent_by_email: Optional[str] = None
    provider_status: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by_email: Optional[str] = None


@router.get(
    "/customers/{cid}/service-records-links",
    operation_id="customers.listServiceRecordsLinks",
)
async def list_service_records_links(cid: str,
                                        limit: int = 5,
                                        user: dict = Depends(require_admin),
                                        tenant: dict = Depends(get_current_tenant)):
    """Return the most-recent sent service-records links for a
    customer — powers the "Recent sends" list in the send modal so
    an admin can revoke a specific link. Default limit = 5; hard
    cap at 25.
    """
    limit = max(1, min(int(limit or 5), 25))
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")
    cursor = db.customer_link_sends.find(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0, "id": 1, "channel": 1, "recipient": 1,
         "sent_by_email": 1, "provider_status": 1,
         "created_at": 1, "expires_at": 1,
         "revoked_at": 1, "revoked_by_email": 1},
    ).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    return {"sends": rows, "limit": limit}


@router.post(
    "/customers/{cid}/service-records-links/{token_id}/revoke",
    operation_id="customers.revokeServiceRecordsLink",
)
async def revoke_service_records_link(cid: str, token_id: str,
                                         user: dict = Depends(require_admin),
                                         tenant: dict = Depends(get_current_tenant)):
    """Mark a single sent service-records link as revoked.

    Behavioural contract:
      * Scope is a SINGLE ``token_id`` — no other outstanding links
        for this customer (or any other customer) are affected.
      * Idempotent — revoking an already-revoked link returns 200
        with the original ``revoked_at`` timestamp preserved.
      * A ``customer_link_sends`` doc's ``revoked_at`` stamp is
        checked at ``/api/portal/auto-login`` redemption time; a
        revoked token 302s to ``/portal/login?reason=link_revoked``
        with the friendly "This link has been revoked" copy.
      * Writes an audit row into ``communications_log`` with
        ``trigger_entity.kind = "service_records_link_revoked"`` so
        the customer timeline shows the revocation event.
    """
    from datetime import datetime as _dt, timezone as _tz

    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    row = await db.customer_link_sends.find_one(
        {"id": token_id, "customer_id": cid, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Link not found")

    if row.get("revoked_at"):
        # Idempotent — return the existing revocation stamp.
        return {"ok": True, "already_revoked": True,
                "id": row["id"],
                "revoked_at": row["revoked_at"],
                "revoked_by_email": row.get("revoked_by_email")}

    now = _dt.now(_tz.utc).isoformat()
    await db.customer_link_sends.update_one(
        {"id": token_id, "customer_id": cid, "tenant_id": tenant["id"]},
        {"$set": {"revoked_at": now,
                    "revoked_by": user.get("id"),
                    "revoked_by_email": user.get("email")}},
    )

    try:
        await db.communications_log.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": row.get("channel") or "system",
            "direction": "outbound",
            "recipient": row.get("recipient") or "",
            "subject": None,
            "body": (
                f"Service records link revoked by "
                f"{user.get('email') or 'admin'} — originally sent "
                f"{row.get('created_at') or ''}"
            ),
            "delivery_status": "revoked",
            "provider": row.get("provider") or "",
            "provider_response_id": None,
            "trigger_entity": {"kind": "service_records_link_revoked",
                                "customer_id": cid,
                                "sent_by": row.get("sent_by"),
                                "revoked_by": user.get("id"),
                                "link_id": token_id},
            "created_at": now,
        })
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[task6b] comms_log insert failed cid=%s tok=%s: %s",
                        cid, token_id, _exc)

    return {"ok": True,
            "already_revoked": False,
            "id": token_id,
            "revoked_at": now,
            "revoked_by_email": user.get("email")}


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


# ─── P2 #6 · Feb-2026 — Service-category PATCH ────────────────────
_P2_6_VALID_CATEGORIES = ("pool", "landscaping", "both")


class _ServiceCategoryPatch(BaseModel):
    """Body for ``PATCH /api/customers/{cid}/service-category``.

    Whitelisted to ``pool`` / ``landscaping`` / ``both``.  ``None``
    explicitly clears the field (customer category is "unset").
    """
    service_category: Optional[str] = None


@router.patch("/customers/{cid}/service-category")
async def patch_customer_service_category(
    cid: str, body: _ServiceCategoryPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """P2 #6 · Feb-2026 — set / clear the customer's service category.

    Admin-only (``require_admin`` dep).  Values are lowercased before
    validation so a casual ``"Pool"`` from a legacy client still lands.
    Emits exactly one ``audit_logs`` row
    ``event="customer.service_category_changed"`` on each transition;
    no-op PATCH requests (same value in and out) are silent — matches
    the audit contract used on the sibling P2 #4 ticket.
    """
    raw = body.service_category
    if raw is not None:
        normalized = (raw or "").strip().lower() or None
        if normalized is not None and normalized not in _P2_6_VALID_CATEGORIES:
            raise HTTPException(400, (
                f"service_category must be one of {_P2_6_VALID_CATEGORIES} "
                "or null to clear"
            ))
    else:
        normalized = None
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not existing:
        raise HTTPException(404, "Customer not found")
    before = existing.get("service_category")
    if before == normalized:
        return existing  # idempotent — no audit, no write
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"service_category": normalized}},
    )
    try:
        await db.audit_logs.insert_one({
            "event": "customer.service_category_changed",
            "entity_kind": "customer",
            "entity_id": cid,
            "customer_id": cid,
            "from": before,
            "to": normalized,
            "actor_user_id": user.get("id"),
            "tenant_id": tenant["id"],
            "created_at": now_iso(),
        })
    except Exception as _e:  # noqa: BLE001
        logger.warning(
            "customer.service_category_changed audit_logs insert failed: %s",
            _e,
        )
    return await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


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


# ─── Phase D5 · Feb-2026 — Customer locale patch ───────────────────
class _LocalePatch(BaseModel):
    """Body for ``PATCH /api/customers/{cid}/locale``.

    Whitelisted to the D5 locale set (``en`` / ``es`` / ``fr``).
    Passing ``None`` explicitly clears the field so the tenant
    default (or the ultimate ``en`` fallback) takes over.
    """
    locale: Optional[str] = None


@router.patch("/customers/{cid}/locale")
async def patch_customer_locale(cid: str, body: _LocalePatch,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Phase D5 · Feb-2026 — set / clear the customer's outbound
    notification locale.

    Locale drives every customer-facing email + SMS body's language
    (see :mod:`services.i18n_notifications`). Admin scope only —
    customers should NOT be able to change their own locale via the
    portal until we've hardened the resolver's fallback chain in a
    later phase.
    """
    from services.i18n_notifications import SUPPORTED_LOCALES
    raw = body.locale
    if raw is not None:
        loc = str(raw).strip().lower()
        if loc not in SUPPORTED_LOCALES:
            raise HTTPException(422, detail={
                "code": "invalid_locale",
                "supported": sorted(SUPPORTED_LOCALES),
                "received": raw,
            })
        new_value = loc
    else:
        new_value = None
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not existing:
        raise HTTPException(404, "Customer not found")
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"locale": new_value, "updated_at": now_iso()}},
    )
    return {"customer_id": cid, "locale": new_value}





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
    from services.add_card_links import ensure_rate_limit
    from services.marketing.merge_tags import render_context, render_template

    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(404, "Customer not found")
    # 1/5min rate limit (raises 429).
    ensure_rate_limit(cid)

    # Phase P30 · Feb-2026 — Direct Stripe Checkout Session (mode="setup").
    # Was: build a JWT self-hosted magic link to ``/portal/add-card`` and
    # render our own SetupIntent Elements form. That flow required us to
    # own the PCI-scoped page + explain a two-hop UX to customers.
    # Now: mint a Stripe-hosted Checkout Session, drop the ``session.url``
    # straight into email + SMS. Stripe carries the PCI scope; our
    # frontend only needs to render ``/portal/setup-success`` after the
    # redirect. Zero self-hosted UI in the critical path.
    base_url = (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or (tenant.get("brand") or {}).get("public_origin")
        or "https://app.plofv.com"   # P30 · production default (was preview)
    ).strip().rstrip("/")

    # Ensure the customer has a Stripe Customer id BEFORE creating the
    # Checkout Session (Stripe requires the ``customer`` field on
    # setup-mode sessions). Reuses the same idempotency + metadata
    # shape as ``create_setup_intent`` — a single canonical helper.
    from services.payments.stripe_charge import (
        ensure_stripe_customer, create_card_setup_checkout_session,
    )
    try:
        stripe_customer_id = await ensure_stripe_customer(
            tenant_id=tenant["id"], customer_id=cid,
        )
    except ValueError as _vexc:
        raise HTTPException(404, str(_vexc))

    try:
        link = await create_card_setup_checkout_session(
            customer_id=cid,
            tenant_id=tenant["id"],
            stripe_customer_id=stripe_customer_id,
            # ``{CHECKOUT_SESSION_ID}`` is a Stripe-side placeholder —
            # the double-braces are LITERAL, don't escape.
            success_url=(
                f"{base_url}/portal/setup-success"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{base_url}/portal/setup-cancelled",
            metadata={"trigger_source": "send_card_add_link"},
        )
    except Exception as _sxc:
        logger.error(
            "[p30] create_setup_checkout_session failed cid=%s "
            "tenant=%s: %s",
            cid, tenant["id"], _sxc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "STRIPE_SESSION_ERROR",
                "message": (
                    "Could not create Stripe Checkout Session. "
                    "Check Stripe API keys + logs."
                ),
            },
        )

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
    # Feb-2026 · Add-Card magic-link truthfulness — track the exact
    # per-channel outcome so the FE toast never lies about success.
    # ``email_status`` mirrors the ``send_email`` status enum so ops
    # can filter deliveries by reason without tailing logs.
    email_status: str | None = None
    sms_status: str | None = None
    email_error: str | None = None
    sms_error: str | None = None
    trigger_id = f"add_card_request:{cid}:{new_id()[:8]}"

    if email_tpl:
        # Feb-2026 · Multi-Contact Phase 1 · canary fan-out.
        # Route through ``active_email_recipients`` so every enabled
        # address on the customer gets the magic link — honors
        # ``automations_muted`` (context="automation" → muted
        # customers receive zero emails).
        from services.customer_multi_contact import active_email_recipients
        _recipients = active_email_recipients(customer, context="automation")
        if _recipients:
            subject_r, _ = render_template(email_tpl.get("subject") or "", ctx)
            body_r, _ = render_template(email_tpl.get("body") or "", ctx)
            per_addr_ok: list[bool] = []
            for _addr in _recipients:
                email_provider_id: str | None = None
                _addr_status: str | None = None
                _addr_error:  str | None = None
                try:
                    from services.comms_email_adapter import send_email
                    import asyncio as _asyncio
                    res = await _asyncio.wait_for(send_email(
                        tenant_id=tenant["id"], to_email=_addr,
                        subject=subject_r, html=body_r,
                        from_name=(tenant.get("name") or None),
                    ), timeout=8.0)
                    _addr_status = (res or {}).get("status")
                    email_provider_id = (res or {}).get("provider_id")
                    _addr_ok = _addr_status in ("sent", "sent_no_provider_id")
                    if not _addr_ok:
                        _addr_error = (res or {}).get("error") or _addr_status
                except Exception as exc:
                    _addr_status = "exception"
                    _addr_error = f"{type(exc).__name__}: {exc}"[:200]
                    _addr_ok = False
                    logger.warning(
                        "[phase12] add-card email send exception cid=%s addr=%s: %s",
                        cid, _addr, _addr_error,
                    )
                per_addr_ok.append(_addr_ok)
                # Reflect the FIRST attempt's status into the
                # legacy scalar fields so existing wire consumers
                # (FE toast, ops dashboards) keep reading a single
                # status; per-recipient rows below carry the truth.
                if email_status is None:
                    email_status = _addr_status
                    email_error = _addr_error
                # Per-recipient ledger row.
                await db.marketing_deliveries.insert_one({
                    "id": new_id(), "tenant_id": tenant["id"],
                    "customer_id": cid,
                    "channel": "email", "kind": "transactional",
                    "recipient": _addr,
                    "subject": subject_r, "body": body_r,
                    "trigger_entity": {"kind": "add_card_request", "id": cid},
                    "trigger_id": trigger_id,
                    "delivered": _addr_ok,
                    "accepted_by_provider": _addr_ok,
                    "terminal_delivered": None,
                    "provider_status": _addr_status,
                    "accepted_status": _addr_status,
                    "accepted_status_at": now_iso(),
                    "provider_id": email_provider_id,
                    "error": _addr_error,
                    "created_at": now_iso(),
                    # Feb-2026 · Multi-Contact Phase 1 · fan-out marker
                    "fanned_out": True,
                    "fanout_recipient_count": len(_recipients),
                })
            sent_email = any(per_addr_ok)
        elif customer.get("automations_muted"):
            # Muted → deliberately zero-recipient. Stamp a status so
            # ops can see WHY nothing was sent.
            email_status = "skipped_muted"
            sent_email = False
        else:
            email_status = "no_recipients"
            sent_email = False
        # Feb-2026 · Multi-Contact Phase 2 · suppressed-by-mute audit.
        # Only stamp when the reason was "muted" (not "no template"
        # / "no recipient on file") so ops can slice mute suppressions
        # cleanly from routine misses.
        if customer.get("automations_muted"):
            from services.customer_multi_contact import log_mute_suppressed
            await log_mute_suppressed(
                tenant_id=tenant["id"], customer_id=cid,
                channel="email", cluster="add_card_link_email",
                context="automation",
            )
    else:
        # Template missing → status stamp for FE toast + ops slicing.
        email_status = "template_missing"
        sent_email = False

    if sms_tpl and customer.get("phone"):
        body_r, _ = render_template(sms_tpl.get("body") or "", ctx)
        sms_provider_id: str | None = None
        try:
            # Feb-2026 · SMS parity fix — call the async RC adapter
            # DIRECTLY so we can inspect the full response envelope
            # (``provider``, ``provider_status``,
            # ``provider_response_id``). The legacy sync wrapper
            # ``send_sms`` returns bool only, which is why the old
            # code silently marked ``sent_sms=True`` even when RC
            # returned ``provider="mock"`` (BYO unconfigured) or the
            # comms gate downgraded to ``dry_run``.
            from services.sms.rc_adapter import send as _rc_send
            import asyncio as _asyncio
            res = await _asyncio.wait_for(
                _rc_send(
                    to=customer["phone"], body=body_r,
                    category="transactional",
                    tenant_id=tenant["id"],
                ),
                timeout=8.0,
            )
            provider = (res or {}).get("provider")
            provider_status = (res or {}).get("provider_status")
            sms_provider_id = (res or {}).get("provider_response_id")
            # Truthful outcome — only a live RC accept counts as
            # sent. Everything else (mock provider, dry_run gate,
            # explicit failure) is surfaced with a distinct status
            # so ops / the FE toast never lie about success.
            if provider == "ringcentral" and provider_status in (
                "queued", "sent", "delivered", "accepted"
            ):
                sent_sms = True
                sms_status = provider_status
            elif provider == "mock":
                sms_status = "sms_not_configured"
                sms_error = (
                    "RingCentral BYO credentials missing on this "
                    "tenant — SMS silently mocked. Configure "
                    "RC_CLIENT_ID / RC_JWT_TOKEN (or the per-tenant "
                    "RC overrides) to enable live SMS."
                )
            elif provider_status == "dry_run":
                sms_status = "gate_dry_run"
                sms_error = (
                    "Comms env-guard downgraded the send to dry-run "
                    "(recipient not allowlisted for this "
                    "environment)."
                )
            else:
                sms_status = provider_status or "provider_rejected"
                sms_error = (res or {}).get("error") or str(res)[:200]
        except Exception as exc:
            sms_status = "exception"
            sms_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning(
                "[phase12] add-card sms send exception cid=%s: %s",
                cid, sms_error,
            )
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "sms", "kind": "transactional",
            "recipient": customer["phone"],
            "subject": None, "body": body_r,
            "trigger_entity": {"kind": "add_card_request", "id": cid},
            "trigger_id": trigger_id,
            # Feb-2026 · Same ledger-honesty split as the email row —
            # ``delivered``/``accepted_by_provider`` = "RC accepted",
            # ``terminal_delivered`` = null (SMS terminal state is
            # a follow-up — RC delivery webhooks are not yet wired
            # for this pod), ``provider_terminal_status`` = null
            # until the RC delivery-status webhook lands.
            "delivered": sent_sms,
            "accepted_by_provider": sent_sms,
            "terminal_delivered": None,
            "provider_status": sms_status,
            "provider_terminal_status": None,
            "provider_response_id": sms_provider_id,
            "error": sms_error,
            "created_at": now_iso(),
        })
    elif not customer.get("phone"):
        sms_status = "no_recipient_on_file"
    elif not sms_tpl:
        sms_status = "template_missing"

    # Feb-2026 · P1 diagnostic follow-up — if nothing left the pod on
    # either channel, DO NOT return 200 with a false "success" flag.
    # Surface the exact reason so the FE toast can tell the operator
    # what to fix.
    if not sent_email and not sent_sms:
        outcome = "nothing_sent"
        reasons = {"email": email_status, "sms": sms_status}
        # Distinguish the two most-common actionable buckets so the FE
        # can render user-friendly copy without parsing status strings.
        if (email_status == "no_recipient_on_file"
                and sms_status == "no_recipient_on_file"):
            detail = {
                "code": "NO_CONTACT_ON_FILE",
                "message": "Customer has no email or phone on file. Add contact info and try again.",
                "reasons": reasons,
            }
            raise HTTPException(status_code=400, detail=detail)
        if (email_status in ("template_missing", None)
                and sms_status in ("template_missing", None)):
            detail = {
                "code": "TEMPLATE_MISSING",
                "message": "Add-card email/SMS templates aren't set up for this tenant.",
                "reasons": reasons,
            }
            raise HTTPException(status_code=409, detail=detail)
        # Provider-level failure (Resend/RC returned a non-sent
        # status or the SDK raised). Return 502 so the FE surfaces a
        # distinct "provider failure" state and ops can chase it.
        detail = {
            "code": "PROVIDER_FAILURE",
            "message": "Provider rejected the send. Check ops logs.",
            "reasons": reasons,
            "errors": {"email": email_error, "sms": sms_error},
        }
        raise HTTPException(status_code=502, detail=detail)

    return {
        "ok": True,
        "sent_email": sent_email,
        "sent_sms": sent_sms,
        "email_recipient": customer.get("email") if sent_email else None,
        "sms_recipient": customer.get("phone") if sent_sms else None,
        # Feb-2026 · Persist the per-channel outcome on the response
        # so the FE toast + any future consumer can distinguish
        # partial success (e.g., email sent, SMS skipped for lack of
        # phone) from full success.
        "outcome": "sent" if (sent_email and sent_sms) else "partial",
        "channels": {
            "email": {"sent": sent_email, "status": email_status,
                        "error": email_error},
            "sms":   {"sent": sent_sms,   "status": sms_status,
                        "error": sms_error},
        },
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
                or "https://app.plofv.com"   # P30.2 · flipped from preview host
            ).strip().rstrip("/")
            link = build_add_card_link(base_url, cid, tenant["id"])
            subject = "Please verify your bank account"
            html = (
                f"<p>Hi {cust.get('name') or 'there'},</p>"
                f"<p>Please complete your ACH bank verification so we can process your recurring payments:</p>"
                f'<p><a href="{link}">Verify bank account</a></p>'
                f"<p>This link is valid for 7 days.</p>"
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


# ─── Task N Round 2 · Phase N.6 · Feb-2026 — Customer Notes History ────
# Per-customer read of submitted service-report notes.  Same
# aggregation shape as ``GET /api/service-reports/archive``; the only
# difference is a ``customer_id`` constraint on the joined
# ``job_doc.customer_id``.  Shared builder lives at
# ``services/notes/archive_query.build_archive_pipeline`` so shape
# drift lands in one file.  Admin-gated + tenant-scoped.
from services.notes.archive_query import (
    NOTES_ARCHIVE_MAX_PAGE_SIZE as _NOTES_HIST_MAX_PAGE_SIZE,
    build_archive_pipeline as _build_notes_history_pipeline,
    normalise_row as _normalise_notes_history_row,
)


@router.get("/customers/{cid}/notes-history")
async def customer_notes_history(
    cid: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return submitted service reports with any note field populated
    for a single customer, newest-first.

    Response shape mirrors ``/service-reports/archive`` verbatim so
    the shared ``<NotesHistoryList/>`` frontend component renders
    either one identically.
    """
    if page_size > _NOTES_HIST_MAX_PAGE_SIZE:
        raise HTTPException(
            400,
            {"error": "page_size_too_large",
             "max": _NOTES_HIST_MAX_PAGE_SIZE},
        )
    # Verify customer exists in this tenant (404 vs quietly-empty
    # rows — the frontend surfaces "customer not found" distinctly
    # from "customer has no notes yet").
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "notes": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")

    pipeline = _build_notes_history_pipeline(
        tenant_id=tenant["id"], page=page, page_size=page_size,
        customer_id=cid,
    )
    if pipeline is None:  # pragma: no cover — no industry filter here
        return {"rows": [], "total_count": 0, "page": page,
                 "page_size": page_size,
                 "customer": {"id": cid,
                               "name": cust.get("name") or "",
                               "notes": cust.get("notes") or ""}}

    cursor = db.service_reports.aggregate(pipeline)
    facet_result = await cursor.to_list(1)
    facet = facet_result[0] if facet_result else {"rows": [], "total_count": []}
    rows_out = [_normalise_notes_history_row(r) for r in (facet.get("rows") or [])]
    total_count = 0
    _tc = facet.get("total_count") or []
    if _tc:
        total_count = int(_tc[0].get("n") or 0)
    return {
        "rows": rows_out,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        # ``customer`` block carries the customer-level free-text
        # ``notes`` string (the persisted, edited-via-CustomerForm
        # field) so the frontend can render it above the SR list
        # in the CustomerDetail "Notes" tab per Phase N.5 §E halt.
        "customer": {
            "id": cid,
            "name": cust.get("name") or "",
            "notes": cust.get("notes") or "",
        },
    }



# ═════════════════════════════════════════════════════════════════════════
# CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026
#
# A customer can be flagged as an "Account Correction" to exclude the
# record from retention / churn analytics (test accounts, bookkeeping
# duplicates, mis-entered rows the office doesn't want to count against
# their numbers). The exclusion is retroactive — flipping the flag ON
# removes the customer from every past, present, and future tile count
# on the retention report (predicate: ``{account_correction: {$ne: true}}``
# — sparse-safe, so unflagged rows and legacy rows both pass through).
#
# Role gate matches the DOC-DATE-EDITING-PUT-GATE widening shipped this
# session: admin / super_admin / manager / owner. Reuses
# ``require_admin_or_manager`` from utils.py; no new dep code.
#
# Audit shape (``db.customer_account_correction_audit``):
#   {id, event:"toggle", customer_id, tenant_id, from_state, to_state,
#    actor_user_id, actor_role, note, at}
# ═════════════════════════════════════════════════════════════════════════
class AccountCorrectionBody(BaseModel):
    """Body for ``POST /customers/{cid}/account-correction``.

    ``active`` is the desired post-call state (true = toggle ON, false =
    toggle OFF).  ``note`` is a free-form reason captured on the audit
    row for review; the field is optional with no length validation
    (CUSTOMER-RETENTION-ACCOUNT-CORRECTION G4).
    """
    active: bool
    note: Optional[str] = None


@router.post("/customers/{cid}/account-correction")
async def toggle_customer_account_correction(
    cid: str,
    body: AccountCorrectionBody,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Toggle the per-customer ``account_correction`` flag.

    * Idempotent: toggling ON when already ON is a no-op (returns
      ``no_change=true``) but still writes nothing to the audit log —
      only genuine state transitions emit a row.
    * Sets ``account_correction_at`` + ``account_correction_by`` on
      transition ON; clears ``account_correction_at`` / ``_by`` /
      ``_note`` on transition OFF so stale audit metadata doesn't
      survive a re-toggle.
    * The retroactive exclusion in retention tiles / drill-downs is
      live-computed off the current flag — no cache invalidation step.
    """
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    from_state = bool(cust.get("account_correction") or False)
    to_state = bool(body.active)
    if from_state == to_state:
        return {
            "ok": True, "no_change": True, "customer_id": cid,
            "account_correction": to_state,
        }
    _now = now_iso()
    if to_state:
        patch = {
            "account_correction": True,
            "account_correction_at": _now,
            "account_correction_by": user.get("id"),
            "account_correction_note": body.note,
        }
        unset: dict = {}
    else:
        # Transition OFF — unset the metadata so a future OFF→ON
        # transition writes a fresh timestamp instead of a stale
        # one from the prior ON cycle.
        patch = {"account_correction": False}
        unset = {
            "account_correction_at": "",
            "account_correction_by": "",
            "account_correction_note": "",
        }
    update_op: dict = {"$set": patch}
    if unset:
        update_op["$unset"] = unset
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, update_op,
    )
    await db.customer_account_correction_audit.insert_one({
        "id": new_id(),
        "event": "toggle",
        "customer_id": cid,
        "tenant_id": tenant["id"],
        "from_state": from_state,
        "to_state": to_state,
        "actor_user_id": user.get("id"),
        "actor_role": (user.get("role") or "").lower(),
        "note": body.note,
        "at": _now,
    })
    return {
        "ok": True,
        "no_change": False,
        "customer_id": cid,
        "account_correction": to_state,
        "account_correction_at": _now if to_state else None,
        "account_correction_by": user.get("id") if to_state else None,
    }


@router.get("/customers/{cid}/account-correction/history")
async def get_customer_account_correction_history(
    cid: str,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(20, ge=1, le=200),
):
    """Return the N most recent audit entries for a customer's flag.

    Supports the "why was this flipped" trail on the profile toggle
    panel. Scoped to tenant for cross-tenant leak safety.
    """
    rows = await db.customer_account_correction_audit.find(
        {"customer_id": cid, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("at", -1).to_list(length=limit)
    return {"items": rows, "count": len(rows)}

