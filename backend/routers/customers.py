# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *  # noqa: F403,F405

router = APIRouter()


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


@router.get("/customers")
async def list_customers(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    search: Optional[str] = None,
    tag: Optional[str] = None,
    waitlisted: Optional[bool] = None,
    unscheduled: Optional[bool] = None,
    is_active: Optional[bool] = None,
    count_only: bool = False,
):
    # RBAC: only staff (admin/technician/super_admin) may list customer records. Customers use /me.
    if user.get("role") not in ("admin", "technician", "super_admin"):
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if search:
        rx = {"$regex": search, "$options": "i"}
        q["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}, {"address": rx}]
    if tag:
        q["tags"] = tag
    if waitlisted is not None:
        q["waitlisted"] = bool(waitlisted)
    # Phase 56.2 — active/inactive cohort filter. Rows created before the
    # `is_active` field existed default to active per Phase 34f semantics,
    # so a `True` filter must match {is_active: True} OR field-absent.
    if is_active is True:
        q["$and"] = q.get("$and", []) + [{"$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}]
    elif is_active is False:
        q["is_active"] = False
    if count_only:
        return {"count": await db.customers.count_documents(q)}
    docs = await db.customers.find(q, {"_id": 0}).sort("name", 1).to_list(2000)
    # If unscheduled=true, filter out customers who have any non-completed/cancelled job.
    if unscheduled:
        scheduled_ids = set(
            [d["customer_id"] async for d in db.jobs.find(
                {"tenant_id": tenant["id"], "status": {"$nin": ["completed", "cancelled"]}},
                {"customer_id": 1, "_id": 0},
            )]
        )
        docs = [d for d in docs if d["id"] not in scheduled_ids]
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
        res = await db.customers.delete_many(q)
        return {"ok": True, "deleted": res.deleted_count}
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


@router.post("/customers")
async def create_customer(body: CustomerIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    _sync_customer_names(doc)
    _apply_multi_contact(doc)
    _apply_vip_stamp(doc, existing=None)
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "created_at": now_iso()})
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
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
    # Marketing M1 — mirror the new customer into the subscribers
    # collection with source="crm_customer" (already-consented).
    try:
        from services.marketing_subscribers import mirror_customer_created
        await mirror_customer_created(tenant["id"], doc)
    except Exception:
        pass
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
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("scheduled_date", -1).to_list(200)
    doc["jobs"] = jobs
    return doc


@router.get("/customers/{cid}/deactivation-preview")
async def deactivation_preview(cid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Phase 34f — dry-run for the Active/Inactive toggle confirm dialog.
    Returns the counts that WOULD be affected if the caller flipped
    `is_active` from true → false right now. Does not mutate anything."""
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
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
    # Feb-2026 Customer Detail Additions — normalize arrays + sync
    # scalars + auto-stamp VIP transitions BEFORE persisting.
    _apply_multi_contact(payload)
    _apply_vip_stamp(payload, existing=existing)
    vip_flipped_on = bool(payload.get("is_vip")) and not bool(existing.get("is_vip"))
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": payload}
    )

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
async def delete_customer(cid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.customers.delete_one({"id": cid, "tenant_id": tenant["id"]})
    return {"ok": True}


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


# ─── Feb-2026 service-notes ship ──────────────────────────────────────
class _ServiceNotesPatch(BaseModel):
    """Partial update — omit a key to leave that side untouched. Send
    ``null`` to explicitly clear a note."""
    pool: Optional[str] = None
    landscape: Optional[str] = None


def _resolve_service_note(customer: dict, service_type: Optional[str],
                            user: Optional[dict] = None) -> Optional[str]:
    """Return the relevant note text for a schedule/job view.

    ``service_type`` may be a bare string ("pool"/"landscape") or any
    string containing those tokens (e.g. "Weekly Pool Service"). We
    normalize + substring-match so the resolver survives legacy job
    docs whose type field carries the full service name.

    Priority:
      1. Substring match on ``service_type`` against a service_notes key.
      2. Fallback to the tech's ``specialties[0]``.
      3. Return ``None`` when neither resolves.
    """
    notes = (customer or {}).get("service_notes") or {}
    if not notes:
        return None
    stype = (service_type or "").strip().lower()
    if stype:
        # Direct key hit (fast path).
        if stype in notes and notes.get(stype):
            return notes[stype]
        # Substring match — covers "Weekly Pool Service" → "pool",
        # "Landscape maintenance" → "landscape", etc.
        for key, val in notes.items():
            if not val:
                continue
            if key and key.lower() in stype:
                return val
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
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]},
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
    customer's mirrored emails so we don't accidentally leak."""
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
    return await send_email(
        tenant["id"], to,
        subject=body.subject.strip() or "Message",
        html=f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{body.body}</pre>",
    )



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
