from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *

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
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": payload}
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
