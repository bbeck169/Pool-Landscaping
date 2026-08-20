# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *  # noqa: F403,F405

from routers.tenants import get_current_tenant

router = APIRouter()


# ----------------------- Technicians -----------------------
@router.get("/technicians")
async def list_technicians(user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    """List assignable techs for the current tenant.

    Feb-2026 · P0 fix — the prior implementation did
    ``db.technicians.find({})`` with **no tenant filter** and no union
    against ``db.users``. Two consequences:
      1. Cross-tenant leak (any authed user could see other tenants'
         technician rows).
      2. Real team members added through the roster UI live in
         ``db.users`` with ``role in {technician, landscaper}`` but
         no matching ``db.technicians`` row — so Schedule, Crews,
         Dispatch, Workstream, Reviews, etc. only saw stale seed
         rows (Mike Rivera / Sara Nguyen / Luis Marquez / Carlos
         Rivera and dupes) rendered to the user as "demo accounts".

    Fix: return the UNION of (a) real ``db.technicians`` rows for
    this tenant + (b) synthesized rows from ``db.users`` (role in
    the technician-ish set) that lack a matching tech row. Dedupe
    by ``user_id``. Every returned doc has an ``id`` — for
    synthesized rows the id is the user's id so downstream
    assign-tech flows continue to hit ``users``.
    """
    tid = tenant["id"]
    # (a) Real technician rows for THIS tenant.
    tech_docs = await db.technicians.find(
        {"tenant_id": tid}, {"_id": 0},
    ).sort("name", 1).to_list(1000)
    linked_user_ids: set = {t.get("user_id") for t in tech_docs
                              if t.get("user_id")}

    # (b) Users in the tenant with an assignable role who lack a
    #     technicians row. Use the same role set the Team page uses
    #     so Schedule / Crews assignee dropdowns match the Team
    #     roster count.
    # Feb-2026 · P1 — also honour ``role='tech'`` (singular): 5
    # preview users were written with this legacy variant and were
    # invisible in every picker. See also the one-shot normaliser
    # ``scripts/normalize_role_tech_to_technician.py`` which rewrites
    # the field so future queries don't need the alias.
    ASSIGNABLE_ROLES = ["technician", "tech", "landscaper", "admin",
                          "super_admin", "manager"]
    synth_docs: list = []
    async for u in db.users.find(
        {"tenant_id": tid,
         "role": {"$in": ASSIGNABLE_ROLES},
         # Skip migration-artifact rows (``lastowner-*@t.local``) —
         # they aren't real team members, just tenant-ownership
         # placeholders left behind by seed churn. Not caught by the
         # earlier data-hygiene sweep because their domain is
         # ``@t.local``, not ``@aquaterra.com`` / ``@plofv.com``.
         "email": {"$not": {"$regex": "@t\\.local$", "$options": "i"}},
         "$and": [
             {"$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}]},
             {"$or": [{"active": {"$ne": False}},
                        {"active": {"$exists": False}}]},
         ]},
        {"_id": 0, "id": 1, "email": 1, "first_name": 1,
         "last_name": 1, "name": 1, "phone": 1, "role": 1,
         "display_color_hex": 1, "technician_id": 1},
    ):
        # Skip if the user is already represented by a real tech row.
        if u.get("id") in linked_user_ids:
            continue
        if u.get("technician_id") in {t.get("id") for t in tech_docs}:
            continue
        synth_docs.append({
            "id": u.get("technician_id") or u.get("id"),
            "user_id": u.get("id"),
            "name": (u.get("name")
                      or " ".join([u.get("first_name") or "",
                                    u.get("last_name") or ""]).strip()
                      or u.get("email") or "Unnamed"),
            "email": u.get("email"),
            "phone": u.get("phone"),
            "role": u.get("role"),
            "tenant_id": tid,
            "display_color_hex": u.get("display_color_hex"),
            "synthesized_from_users": True,
        })

    docs = tech_docs + synth_docs
    # Feb-2026 · Dedupe by email — the ``db.technicians`` collection
    # has legacy duplicate rows (e.g. 4× "Carlos Rivera" seed rows)
    # that visually crowd out real team members in every picker.
    seen_emails: set = set()
    deduped: list = []
    for d in docs:
        e = (d.get("email") or "").strip().lower()
        if e and e in seen_emails:
            continue
        if e:
            seen_emails.add(e)
        deduped.append(d)
    # Sort: field-worker roles first (technician / landscaper),
    # then admin / manager / super_admin, then alphabetical inside
    # each bucket. Prioritizes the "assign this job" audience.
    def _sort_key(d: dict) -> tuple:
        r = (d.get("role") or "").lower()
        rank = 0 if r in {"technician", "landscaper"} else 1
        return (rank, (d.get("name") or "").lower())
    docs = sorted(deduped, key=_sort_key)

    # Enrich each real tech row with the linked user's display color
    # (unchanged from the prior behavior) + active-jobs count.
    color_by_uid: dict = {}
    if linked_user_ids:
        async for u in db.users.find(
            {"id": {"$in": list(linked_user_ids)}},
            {"_id": 0, "id": 1, "display_color_hex": 1},
        ):
            if u.get("display_color_hex"):
                color_by_uid[u["id"]] = u["display_color_hex"]
    for t in docs:
        # active_jobs runs per-row — cheap on Mongo (indexed) and
        # matches the prior contract the FE relies on.
        t["active_jobs"] = await db.jobs.count_documents(
            {"tenant_id": tid, "technician_id": t.get("id"),
             "status": {"$in": ["pending", "active"]}},
        )
        if not t.get("display_color_hex") and t.get("user_id"):
            t["display_color_hex"] = color_by_uid.get(t["user_id"])
    return docs


@router.post("/technicians")
async def create_technician(body: TechnicianIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "active": True, "created_at": now_iso()})
    await db.technicians.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/technicians/{tid}")
async def get_technician(tid: str, user: dict = Depends(get_current_user)):
    # Techs can only view their own profile — enforce here.
    if user.get("role") == "technician" and user.get("id") != tid and user.get("technician_id") != tid:
        raise HTTPException(403, "You can only view your own profile")
    doc = await db.technicians.find_one({"id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Technician not found")
    doc["jobs"] = await db.jobs.find({"technician_id": tid}, {"_id": 0}).sort("scheduled_date", -1).to_list(200)
    return doc


@router.get("/technicians/{tid}/performance")
async def technician_performance(tid: str, user: dict = Depends(get_current_user)):
    """Computed performance metrics over the last 90 days."""
    if user.get("role") == "technician" and user.get("id") != tid and user.get("technician_id") != tid:
        raise HTTPException(403, "You can only view your own profile")
    from datetime import datetime, timezone, timedelta  # noqa: F811
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    from utils import not_deleted_filter as _nd
    jobs = await db.jobs.find(
        {"technician_id": tid, "created_at": {"$gte": cutoff}, **_nd()}, {"_id": 0}
    ).to_list(500)
    total = len(jobs)
    completed = [j for j in jobs if j.get("status") == "completed"]
    on_time = [j for j in completed if not j.get("late")]
    durations = [j.get("duration_min") or 0 for j in completed if j.get("duration_min")]
    ratings = [j.get("rating") for j in completed if j.get("rating") is not None]
    return {
        "period_days": 90,
        "total_jobs": total,
        "completed_jobs": len(completed),
        "completion_rate": round(100 * len(completed) / total, 1) if total else 0,
        "on_time_rate": round(100 * len(on_time) / len(completed), 1) if completed else 0,
        "avg_duration_min": round(sum(durations) / len(durations)) if durations else 0,
        "avg_customer_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
    }

