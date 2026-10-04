# Phase O4 · Feb-2026 code-review — replaced the previous
# ``from models import *`` (F403/F405 suppressed) with an explicit
# import. Verified via AST scan that ``TechnicianIn`` is the only
# ``models`` name referenced in this file; add more here if new
# handlers land, do NOT go back to the wildcard.
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, require_super_admin,
                   send_sms, notify_customer, auth_response)
from models import TechnicianIn

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
    # Feb-2026 · P1 rework — three targeted fixes over the previous
    # implementation:
    #   * BUG A · Cross-shape dedupe. When a person has BOTH a
    #     ``db.technicians`` row (possibly without ``email`` /
    #     ``user_id``) AND a ``db.users`` row, the union used to emit
    #     BOTH. Post-hoc dedupe below now unions the identity signals
    #     (id / user_id / email / name) so the person surfaces exactly
    #     once.
    #   * BUG B · Role filter too permissive. Admin / super_admin /
    #     manager users were showing up in the tech filter dropdown —
    #     they aren't field-assignable. Removed from
    #     ``ASSIGNABLE_ROLES``; if a super_admin genuinely does field
    #     work, promote their user doc to ``role='technician'`` or
    #     ``role='tech_both'``.
    #   * BUG C · ``active=false`` users MUST be excluded from every
    #     assign-tech surface (backing the Feb-2026 admin Roster
    #     Cleanup UI's soft-deactivate flow).  Both the synth branch
    #     AND the tech-row branch filter on active — the tech-row
    #     branch cross-references ``db.users.active`` via the linked
    #     ``user_id`` since ``db.technicians`` rows don't carry an
    #     ``active`` field of their own.
    # (a) Real technician rows for THIS tenant.
    # SCH Phase II · Feb-2026 — strip soft-deleted techs (parity
    # with the users arm below). Prior behavior returned docs where
    # ``deleted_at`` was non-null, so a soft-deleted tech kept
    # haunting the Schedule / Dispatch / Workstream dropdowns.
    tech_docs = await db.technicians.find(
        {"tenant_id": tid,
         "$or": [{"deleted_at": None},
                 {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("name", 1).to_list(1000)
    linked_user_ids: set = {t.get("user_id") for t in tech_docs
                              if t.get("user_id")}

    # (b) Users in the tenant with a FIELD-ASSIGNABLE role — the
    #     previous permissive list (admin / super_admin / manager)
    #     was surfacing "Super Admin" / "Alex Admin" / "Morgan
    #     Manager" in the tech filter dropdown. Mirror the
    #     multi-department tech assignment code — pool_tech /
    #     landscape_tech / tech_both are legacy department-typed
    #     variants that also need to appear.
    ASSIGNABLE_ROLES = ["technician", "tech", "landscaper",
                          "landscape_tech", "pool_tech", "tech_both"]
    synth_docs: list = []
    async for u in db.users.find(
        {"tenant_id": tid,
         "role": {"$in": ASSIGNABLE_ROLES},
         # Skip migration-artifact rows (``lastowner-*@t.local``) —
         # they aren't real team members, just tenant-ownership
         # placeholders left behind by seed churn.
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

    # ── BUG C · exclude ``active=false`` techs whose linked users
    #    were soft-deactivated via Roster Cleanup. ``db.technicians``
    #    rows don't carry an ``active`` field; we pull the active
    #    flag from their linked user in one batched query.
    inactive_user_ids: set = set()
    if linked_user_ids:
        async for u in db.users.find(
            {"id": {"$in": list(linked_user_ids)}, "active": False},
            {"_id": 0, "id": 1},
        ):
            inactive_user_ids.add(u["id"])
    tech_docs = [t for t in tech_docs
                  if t.get("user_id") not in inactive_user_ids]

    docs = tech_docs + synth_docs

    # ── BUG A · Robust cross-shape dedupe. Unions the identity
    #    signals a real person can be spread across:
    #      * ``user_id`` (canonical when the tech row is linked).
    #      * ``id`` (tech row id — may equal the user id for synth).
    #      * lowercased email (survives the empty-email tech-row case).
    #      * lowercased name (last-resort for tech rows whose only
    #        contact field is a name).
    #    First row through wins. Real tech rows come first in ``docs``
    #    so they take precedence over synth rows (preserves
    #    display_color_hex + phone stamped on the tech row).
    seen_uids: set = set()
    seen_emails: set = set()
    seen_names: set = set()
    deduped: list = []
    for d in docs:
        uid = d.get("user_id")
        did = d.get("id")
        email = (d.get("email") or "").strip().lower()
        name = (d.get("name") or "").strip().lower()
        if uid and (uid in seen_uids or uid in seen_emails):
            continue
        if did and did in seen_uids:
            continue
        if email and email in seen_emails:
            continue
        if name and name in seen_names:
            continue
        if uid: seen_uids.add(uid)
        if did: seen_uids.add(did)
        if email: seen_emails.add(email)
        if name: seen_names.add(name)
        deduped.append(d)

    # Sort: field-worker roles first (technician / landscaper), then
    # alphabetical. Everything left in ``deduped`` is now field-
    # assignable so this is mostly a stable-alpha sort.
    def _sort_key(d: dict) -> tuple:
        r = (d.get("role") or "").lower()
        rank = 0 if r in {"technician", "tech", "landscaper",
                            "landscape_tech", "pool_tech", "tech_both"} else 1
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
        # K65.fix · Feb-2026 — moved out of this loop. See the bulk
        # ``$group`` counters below; individual ``count_documents``
        # calls used to run per-tech (2 × N sequential round-trips).
        # The map lookup here is O(1) per tech.
        pass
    # K65.fix · Feb-2026 — collapse the per-tech N+1 into a single
    # ``$group`` over ``db.jobs`` matching (tenant, technician IN
    # <every-tech-in-the-response>, status IN [pending, active]).
    # Groups by (technician_id, work_class) so we split ``repair``
    # vs derived-``service`` in the same round-trip.  Uses the
    # ``k15_jobs_tech_schedule_status`` covered index.  Non-fatal —
    # counters default to 0 on aggregation failure so the pill
    # still renders without breaking the endpoint.
    #
    # Response shape is preserved byte-for-byte with the pre-K65
    # loop: every doc still carries ``active_jobs``,
    # ``active_jobs_repair``, and ``active_jobs_service``.
    tech_id_list = [t.get("id") for t in docs if t.get("id")]
    counts_by_tid: Dict[str, Dict[str, int]] = {}
    if tech_id_list:
        try:
            agg = db.jobs.aggregate([
                {"$match": {
                    "tenant_id": tid,
                    "technician_id": {"$in": tech_id_list},
                    "status": {"$in": ["pending", "active"]},
                }},
                {"$group": {
                    "_id": {
                        "tid": "$technician_id",
                        # Legacy jobs without ``work_class`` count as
                        # "service" — matches the read-time invariant
                        # in ``services/work_class.py`` and preserves
                        # the pre-K65 subtraction fallback.
                        "wc": {"$ifNull": ["$work_class", "service"]},
                    },
                    "n": {"$sum": 1},
                }},
            ])
            async for row in agg:
                key = row.get("_id") or {}
                _tid = key.get("tid")
                _wc  = (key.get("wc") or "service").lower()
                _n   = int(row.get("n") or 0)
                if not _tid:
                    continue
                bucket = counts_by_tid.setdefault(_tid, {"repair": 0, "service": 0})
                if _wc == "repair":
                    bucket["repair"] += _n
                else:
                    bucket["service"] += _n
        except Exception as _exc:  # noqa: BLE001
            # Never break the endpoint on a counter aggregation glitch.
            logger.warning("[k65.fix] technicians count aggregate failed: %s", _exc)
            counts_by_tid = {}

    for t in docs:
        c = counts_by_tid.get(t.get("id")) or {"repair": 0, "service": 0}
        t["active_jobs_repair"] = int(c.get("repair", 0))
        t["active_jobs_service"] = int(c.get("service", 0))
        t["active_jobs"] = t["active_jobs_repair"] + t["active_jobs_service"]
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


# ──────────────────────────────────────────────────────────────────
# Phase P23.1 · Feb-2026 — Super-admin diagnostic: technicians across
# ALL tenants. Motivation: the ``p23_restore_ethan_steven_technicians``
# boot migration correctly restores two techs into a production
# tenant that DOES NOT EXIST on preview; the tester's admin account
# lives in a different tenant so ``GET /api/technicians`` returns
# empty (tenant isolation working as designed). This endpoint gives
# ops / super-admins a cross-tenant view WITHOUT loosening isolation
# on the tenant-scoped endpoint.
#
# Auth: strictly ``require_super_admin`` — do NOT permit regular
# admin.  Every row carries an explicit ``tenant_id`` field so the
# caller sees exactly which tenant each row belongs to.
#
# Response shape mirrors ``GET /api/technicians`` (same top-level
# fields on each doc: ``id``, ``name``, ``email``, ``department``,
# ``tenant_id``, ``active``, plus ``created_at`` / ``updated_at``
# when present) minus the ``active_jobs*`` counters (skipped
# deliberately — a cross-tenant fanout would 10x the read cost and
# the counters aren't the diagnostic point here).
# ──────────────────────────────────────────────────────────────────
@router.get("/admin/technicians/all-tenants")
async def list_technicians_all_tenants(
    user: dict = Depends(require_super_admin),
):
    """Cross-tenant technician listing for super-admin diagnostics.

    Returns every ``db.technicians`` row (ANY tenant, ANY active
    state) sorted by ``(tenant_id, name)``. Each doc includes its
    ``tenant_id`` so the caller sees the owning tenant explicitly.
    """
    docs = await db.technicians.find(
        {}, {"_id": 0},
    ).sort([("tenant_id", 1), ("name", 1)]).to_list(5000)
    return {"count": len(docs), "technicians": docs}


@router.get("/technicians/me")
async def get_technician_me(user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Auth-scoped tech resolver.

    Motivation
    ----------
    Mobile schedule filters jobs by ``user.technician_id``. On tenants
    where the ``technicians_user_id_backfill`` migration hasn't run in
    prod, that field can be ``None`` → an empty schedule. This endpoint
    lets mobile fall back to a linked technician row via three
    resolution strategies, all tenant-scoped:

      1. **Primary** — ``technicians.user_id == user.id``.
      2. **Email fallback** — ``technicians.email == user.email``
         (case-insensitive). Logged at INFO as
         ``tech_resolved_via_fallback method=email``.
      3. **Name fallback** — ``technicians.name == first_name +
         ' ' + last_name`` (case-insensitive). Logged as
         ``tech_resolved_via_fallback method=name``.

    Response shape MIRRORS ``GET /api/technicians/{tid}`` (including
    the ``jobs`` array) so the mobile client can share a single
    normaliser between the two endpoints.

    Guardrails
    ----------
    * Does NOT auto-create a ``technicians`` row on any miss — that
      would silently paper over real data-integrity problems.
    * Cross-tenant look-ups are impossible: every query bakes in
      ``tenant_id == tenant["id"]``.
    * Unauthenticated callers land at 401 via the shared
      ``get_current_user`` dependency (FastAPI's default when the
      dependency raises).
    """
    tid = tenant["id"]
    uid = user.get("id") or ""
    email = str(user.get("email") or "").strip()
    first = str(user.get("first_name") or "").strip()
    last = str(user.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip()

    doc = None
    resolved_via = None

    # (1) Primary — user_id link.
    if uid:
        doc = await db.technicians.find_one(
            {"tenant_id": tid, "user_id": uid}, {"_id": 0},
        )
        if doc:
            resolved_via = "user_id"

    # (2) Fallback — email match (case-insensitive).
    if not doc and email:
        # ``$regex`` with ``^…$`` anchoring + ``re.escape``-equivalent
        # for the email string so no injection through user-controlled
        # values. Emails are already-validated by the auth path but
        # be defensive.
        import re
        email_re = re.escape(email)
        doc = await db.technicians.find_one(
            {"tenant_id": tid,
              "email": {"$regex": f"^{email_re}$", "$options": "i"}},
            {"_id": 0},
        )
        if doc:
            resolved_via = "email"
            logger.info(
                "tech_resolved_via_fallback method=email "
                "tenant=%s user_id=%s tech_id=%s",
                tid, uid, doc.get("id"),
            )

    # (3) Fallback — name match (case-insensitive).
    if not doc and full_name:
        import re
        name_re = re.escape(full_name)
        doc = await db.technicians.find_one(
            {"tenant_id": tid,
              "name": {"$regex": f"^{name_re}$", "$options": "i"}},
            {"_id": 0},
        )
        if doc:
            resolved_via = "name"
            logger.info(
                "tech_resolved_via_fallback method=name "
                "tenant=%s user_id=%s tech_id=%s",
                tid, uid, doc.get("id"),
            )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="technician_not_found",
        )

    # Match the ``GET /api/technicians/{tid}`` shape: attach the
    # tech's jobs (soft-deleted rows filtered elsewhere; this
    # endpoint mirrors get_technician exactly for parity).
    doc["jobs"] = await db.jobs.find(
        {"technician_id": doc["id"]},
        {"_id": 0, "photos.data": 0},
    ).sort("scheduled_date", -1).to_list(200)
    # Surface which strategy resolved this — mobile can log a
    # deprecation warning when a fallback fires so ops can prioritise
    # running the ``technicians_user_id_backfill`` migration.
    doc["_resolved_via"] = resolved_via
    return doc


@router.get("/technicians/{tid}")
async def get_technician(tid: str, user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    # Techs can only view their own profile — enforce here.
    if user.get("role") == "technician" and user.get("id") != tid and user.get("technician_id") != tid:
        raise HTTPException(403, "You can only view your own profile")
    doc = await db.technicians.find_one({"id": tid}, {"_id": 0})
    if not doc:
        # Feb-2026 · List/Detail Symmetry Fix — the list endpoint
        # returns a UNION of ``db.technicians`` rows AND synth rows
        # sourced from ``db.users`` (see ``list_technicians`` for
        # the full rationale). The detail endpoint used to only
        # query ``db.technicians`` — so anyone whose row lives in
        # ``db.users`` (fixture G5b/G5d rows + tenants that never
        # got a matching ``db.technicians`` insert) 404'd here.
        # Now we fall back to the same synth shape used by the list
        # so both endpoints have consistent visibility rules.
        _synth_roles = ["technician", "tech", "landscaper",
                          "landscape_tech", "pool_tech", "tech_both"]
        u = await db.users.find_one(
            {"id": tid,
              "tenant_id": tenant["id"],
              "role": {"$in": _synth_roles},
              "$and": [
                  {"$or": [{"deleted_at": None},
                              {"deleted_at": {"$exists": False}}]},
                  {"$or": [{"active": {"$ne": False}},
                              {"active": {"$exists": False}}]},
              ]},
            {"_id": 0, "id": 1, "email": 1, "first_name": 1,
             "last_name": 1, "name": 1, "phone": 1, "role": 1,
             "display_color_hex": 1, "technician_id": 1},
        )
        if not u:
            raise HTTPException(404, "Technician not found")
        doc = {
            "id": u.get("technician_id") or u["id"],
            "user_id": u["id"],
            "name": (u.get("name")
                      or " ".join([u.get("first_name") or "",
                                    u.get("last_name") or ""]).strip()
                      or u.get("email") or "Unnamed"),
            "email": u.get("email"),
            "phone": u.get("phone"),
            "role": u.get("role"),
            "tenant_id": tenant["id"],
            "display_color_hex": u.get("display_color_hex"),
            "synthesized_from_users": True,
        }
    doc["jobs"] = await db.jobs.find({"technician_id": tid}, {"_id": 0, "photos.data": 0}).sort("scheduled_date", -1).to_list(200)
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


# ─────────────────────────────────────────────────────────────────
# Phase P23 · Feb-2026 — Soft-delete + delete-hardening.
#
# There is intentionally NO hard-delete path for technicians on this
# endpoint — the ~600-job FK relink incident that triggered P23 makes
# any future hard-delete a data-loss event. Callers get three
# outcomes:
#
#   1. No active jobs assigned to this tech → 200, soft-delete stamp
#      (``active: false, deleted_at, deleted_by``). Row remains in
#      ``db.technicians`` so the FK stays resolvable.
#   2. N > 0 active jobs assigned → 409 with ``TECHNICIAN_HAS_ACTIVE_JOBS``
#      + count + helpful hint. Doc UNCHANGED.
#   3. ``?force=true&reassign_to=<other>`` (admin-only) → validate
#      target, bulk-reassign active jobs, then soft-delete. Full
#      audit trail via ``deletion_audit`` (1 tech row + N job rows,
#      all sharing a single ``bulk_op_id``).
#
# Uses ``tenant_scoped_filter`` on every read/write. Never dict-
# spreads ``$or``.
# ─────────────────────────────────────────────────────────────────
@router.delete("/technicians/{tid}",
                 operation_id="technicians.softDelete")
async def soft_delete_technician(
    tid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
    force: bool = Query(
        False, description="P23: admin override that bulk-reassigns active jobs "
                              "to ``reassign_to`` and THEN soft-deletes the tech.",
    ),
    reassign_to: Optional[str] = Query(
        None, description="P23: required when ``force=true`` — the "
                              "technician_id that inherits the reassigned jobs.",
    ),
):
    """Soft-delete a technician. NEVER hard-deletes — see module
    header comment for the P23 rationale."""
    from services.query_scope import tenant_scoped_filter
    from routers.deletion_audit import write_deletion_audit_entry
    import uuid as _uuid

    tid_ = tid
    tenant_id = tenant["id"]
    now_utc = datetime.now(timezone.utc).isoformat()

    # 1) Locate the tech (tenant-scoped). Cross-tenant → 404.
    doc = await db.technicians.find_one(
        {"id": tid_, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Technician not found")
    if doc.get("deleted_at"):
        # Idempotent — a repeat delete of an already-soft-deleted tech
        # is a 200 with the current state, not a 409.
        return {
            "ok": True, "already_deleted": True,
            "id": tid_, "deleted_at": doc.get("deleted_at"),
        }

    # 2) Count active jobs still assigned to this tech (blocking set).
    # ``active`` = not-soft-deleted AND status ∉ {completed, cancelled}.
    # Uses ``tenant_scoped_filter`` so the soft-delete ``$or`` never
    # collides with any other disjunction we might add later.
    active_q = tenant_scoped_filter(
        tenant_id,
        technician_id=tid_,
        status={"$nin": ["completed", "cancelled"]},
    )
    active_count = await db.jobs.count_documents(active_q)

    # 3) Non-force path with N > 0 → 409 CONFLICT, doc unchanged.
    if active_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TECHNICIAN_HAS_ACTIVE_JOBS",
                "assigned_job_count": active_count,
                "message": (
                    f"Cannot delete technician: {active_count} active "
                    "jobs still assigned. Reassign or complete them "
                    "first, or use ?force=true&reassign_to=<other_tech_id>."
                ),
            },
        )

    # 4) Force path — validate and reassign before soft-deleting.
    bulk_op_id = str(_uuid.uuid4())
    reassigned_job_ids: List[str] = []
    if force:
        # Force without ``reassign_to`` is a caller error (no place to
        # send the jobs → hard-orphaning them defeats the purpose of
        # the whole P23 delete-hardening).
        if not reassign_to:
            raise HTTPException(
                status_code=400,
                detail=(
                    "force=true requires reassign_to=<other_technician_id> "
                    "so active jobs get a new owner instead of orphaning."
                ),
            )
        if reassign_to == tid_:
            raise HTTPException(
                status_code=400,
                detail="reassign_to cannot equal the technician being deleted",
            )
        # Target must exist, live in the same tenant, and be active.
        target = await db.technicians.find_one(
            {"id": reassign_to, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "active": 1, "deleted_at": 1},
        )
        if not target:
            raise HTTPException(
                status_code=400,
                detail="reassign_to technician not found in this tenant",
            )
        if target.get("deleted_at") or target.get("active") is False:
            raise HTTPException(
                status_code=400,
                detail="reassign_to technician is not active",
            )

        # Snapshot each affected job BEFORE the update — the audit
        # rows need the pre-reassign state.
        pre_update_docs = await db.jobs.find(
            active_q, {"_id": 0},
        ).to_list(length=None)
        reassigned_job_ids = [j["id"] for j in pre_update_docs]

        # Bulk reassign — same tenant-scoped filter shape so no
        # cross-tenant leak on the write.
        if reassigned_job_ids:
            await db.jobs.update_many(
                active_q,
                {"$set": {
                    "technician_id": reassign_to,
                    "reassigned_at": now_utc,
                    "reassigned_reason": "technician_deleted",
                    "reassigned_from": tid_,
                }},
            )

        # One ``deletion_audit`` row per reassigned job — same
        # ``bulk_op_id`` as the tech-level row below so the group
        # is queryable as a set.
        for pre in pre_update_docs:
            await write_deletion_audit_entry(
                tenant_id=tenant_id,
                resource_type="job",
                resource_id=pre["id"],
                user=user,
                snapshot=pre,
                deletion_reason="technician_deleted",
                bulk_op_id=bulk_op_id,
            )

    # 5) Soft-delete the technician itself. Snapshot BEFORE the flip.
    tech_snapshot = dict(doc)
    await db.technicians.update_one(
        {"id": tid_, "tenant_id": tenant_id},
        {"$set": {
            "active": False,
            "deleted_at": now_utc,
            "deleted_by": user.get("id"),
            "updated_at": now_utc,
        }},
    )

    # 6) Audit entry for the technician — always written, regardless
    # of which path fired (plain soft-delete or force-reassign).
    await write_deletion_audit_entry(
        tenant_id=tenant_id,
        resource_type="technician",
        resource_id=tid_,
        user=user,
        snapshot=tech_snapshot,
        deletion_reason=(
            "technician_deleted_with_force_reassign" if force
            else "technician_soft_deleted"
        ),
        bulk_op_id=bulk_op_id,
    )
    logger.info(
        "[p23-delete] soft-delete tech=%s tenant=%s by=%s force=%s "
        "reassign_to=%s jobs_reassigned=%s",
        tid_, tenant_id, user.get("email") or user.get("id"),
        force, reassign_to if force else None, len(reassigned_job_ids),
    )
    return {
        "ok": True,
        "id": tid_,
        "deleted_at": now_utc,
        "active_jobs_reassigned": len(reassigned_job_ids),
        "reassigned_to": reassign_to if force else None,
        "bulk_op_id": bulk_op_id,
    }


# ═════════════════════════════════════════════════════════════════════════
# Phase P42 · Feb-2026 — Team Member HARD DELETE (single + bulk).
#
# Physical removal of a technician + their linked user login + any
# pending invitation records. Coexists with the P23 soft-delete
# surface above (``DELETE /technicians/{tid}``) — do NOT collapse.
#
# Cascade behaviour per technician id:
#   1. Snapshot the tech + linked user + pending invites into an
#      ``audits`` doc kind ``technicians_hard_delete`` (forensic
#      recovery point — the rows themselves are gone after step 6).
#   2. Unassign FUTURE scheduled/pending jobs from this tech
#      (``technician_id=null, technician_name=null``). Job rows are
#      NEVER deleted. Past + in_progress jobs stay assigned.
#   3. delete_one the linked user row (if it belongs to the same
#      tenant). Cross-tenant user linkage is a data-integrity bug
#      that we surface but never act on — skipped + noted in the
#      response.
#   4. delete_many pending invitations for this tech's email /
#      user_id. Grep of the backend on shipping day showed **no
#      ``invitations`` collection exists** — team invites are one-
#      shot Resend emails logged into ``communications_log`` /
#      ``marketing_deliveries``. This step no-ops with count=0
#      today; if a first-class ``invitations`` collection lands
#      later, extend this block.
#   5. delete_one the technician doc.
#   6. Return per-tech counts.
#
# Security invariants (mirrored on the tests):
#   * Tenant-scoped every read + write. Cross-tenant id → 404.
#   * ``require_admin`` gate. Technician role → 403.
#   * Self-delete protection — 400 ``cannot_delete_self`` when the
#     caller resolves to the target tech.
#   * Last-admin orphan protection — 400
#     ``would_orphan_tenant_no_admin_remaining`` when the linked
#     user is the last admin/super_admin left in the tenant.
#   * In-progress-job protection — no hard-block per user spec,
#     but ERROR-level log so ops can audit later.
#   * Bulk cap: 500 ids per call. Deduplicates repeated ids.
# ═════════════════════════════════════════════════════════════════════════
_TECHNICIANS_HARD_DELETE_CAP = 500
_JOB_FUTURE_STATUSES = ("scheduled", "pending")
_JOB_IN_PROGRESS_STATUSES = ("in_progress",)


class _TechniciansHardDeleteBulkIn(__import__("pydantic").BaseModel):
    """Phase P42 · bulk-delete request body — a flat ``ids`` list."""
    ids: List[str]


async def _p42_snapshot_and_delete(
    *, tenant_id: str, tech_doc: dict, actor: dict,
    now_utc: str,
) -> dict:
    """Do the actual per-tech cascade + write the forensic audit.

    Assumes tenant-scoping + admin gate already checked. Returns
    the per-tech response payload dict.
    """
    from routers.deletion_audit import write_deletion_audit_entry
    tech_id = tech_doc["id"]

    # --- Snapshot linked user (tenant-scoped) ---
    linked_user_doc: Optional[dict] = None
    linked_user_id = tech_doc.get("user_id")
    if linked_user_id:
        linked_user_doc = await db.users.find_one(
            {"id": linked_user_id, "tenant_id": tenant_id}, {"_id": 0},
        )
    else:
        # Reverse-lookup fallback — ``users.technician_id == tech_id``.
        linked_user_doc = await db.users.find_one(
            {"tenant_id": tenant_id, "technician_id": tech_id}, {"_id": 0},
        )

    # --- Snapshot pending invites (schema-check — collection may not exist) ---
    pending_invite_ids: List[str] = []
    if "invitations" in await db.list_collection_names():
        inv_q: dict = {
            "tenant_id": tenant_id,
            "status": {"$in": ["pending", "sent"]},
        }
        # Match by email or user_id (whichever the invitation carries).
        or_clauses: List[dict] = []
        if tech_doc.get("email"):
            or_clauses.append({"email": tech_doc["email"]})
        if linked_user_id:
            or_clauses.append({"user_id": linked_user_id})
        if or_clauses:
            inv_q["$or"] = or_clauses
        pending_docs = await db.invitations.find(
            inv_q, {"_id": 0, "id": 1},
        ).to_list(500)
        pending_invite_ids = [d["id"] for d in pending_docs if d.get("id")]

    # --- Snapshot in-progress + future jobs BEFORE any mutation ---
    in_progress_count = await db.jobs.count_documents({
        "tenant_id": tenant_id,
        "technician_id": tech_id,
        "status": {"$in": list(_JOB_IN_PROGRESS_STATUSES)},
    })
    if in_progress_count > 0:
        # Per user spec — no hard-block, ERROR log so ops can audit.
        logger.error(
            "[p42] hard-delete of technician %s tenant=%s with "
            "in_progress jobs count=%s (proceeding per no-blocker rule)",
            tech_id, tenant_id, in_progress_count,
        )

    # --- Unassign FUTURE scheduled/pending jobs (do NOT delete) ---
    future_q = {
        "tenant_id": tenant_id,
        "technician_id": tech_id,
        "status": {"$in": list(_JOB_FUTURE_STATUSES)},
        "scheduled_start": {"$gt": now_utc},
    }
    unassign_res = await db.jobs.update_many(
        future_q,
        {"$set": {"technician_id": None, "technician_name": None,
                    "unassigned_at": now_utc,
                    "unassigned_reason": "technician_hard_deleted"}},
    )
    future_jobs_unassigned = unassign_res.modified_count

    # --- Write the forensic audit BEFORE the physical deletes ---
    audit_id = new_id()
    try:
        await db.audits.insert_one({
            "id": audit_id,
            "kind": "technicians_hard_delete",
            "tenant_id": tenant_id,
            "target_id": tech_id,
            "actor_user_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "tech_snapshot": tech_doc,
            "linked_user_snapshot": linked_user_doc,
            "pending_invite_ids": pending_invite_ids,
            "in_progress_job_count": in_progress_count,
            "future_jobs_unassigned": future_jobs_unassigned,
            "at": now_utc,
        })
    except Exception as e:                                            # noqa: BLE001
        logger.warning(
            f"[p42] audit insert failed for tech={tech_id}: {e}",
        )

    # --- Also write a deletion_audit row so the P23 forensic sweep
    #     surfaces this row alongside soft-delete history. ---
    try:
        await write_deletion_audit_entry(
            tenant_id=tenant_id,
            resource_type="technician",
            resource_id=tech_id,
            user=actor,
            snapshot=tech_doc,
            deletion_reason="technician_hard_deleted",
            bulk_op_id=None,
        )
    except Exception as e:                                            # noqa: BLE001
        logger.warning(
            f"[p42] deletion_audit write failed for tech={tech_id}: {e}",
        )

    # --- Cascade deletes ---
    linked_user_deleted = False
    if linked_user_doc:
        res = await db.users.delete_one(
            {"id": linked_user_doc["id"], "tenant_id": tenant_id},
        )
        linked_user_deleted = res.deleted_count == 1

    pending_invitations_deleted = 0
    if pending_invite_ids:
        del_res = await db.invitations.delete_many({
            "tenant_id": tenant_id, "id": {"$in": pending_invite_ids},
        })
        pending_invitations_deleted = del_res.deleted_count

    await db.technicians.delete_one(
        {"id": tech_id, "tenant_id": tenant_id},
    )

    return {
        "deleted": True,
        "tech_id": tech_id,
        "linked_user_deleted": linked_user_deleted,
        "pending_invitations_deleted": pending_invitations_deleted,
        "future_jobs_unassigned": future_jobs_unassigned,
        "audit_id": audit_id,
    }


async def _p42_pre_delete_checks(
    *, tenant_id: str, tech_doc: dict, actor: dict,
) -> Optional[dict]:
    """Return ``None`` when clear-to-delete, else a dict describing
    the block reason (used to build the 400 / skip-in-bulk responses).
    """
    tech_id = tech_doc["id"]
    linked_user_id = tech_doc.get("user_id")

    # --- Self-delete guard ---
    # Actor is the ``users`` row of the caller. If the caller IS the
    # linked user for this tech, block. Also block if the caller's
    # own row carries a ``technician_id`` matching this tech.
    if actor.get("id") and linked_user_id == actor.get("id"):
        return {"code": "cannot_delete_self",
                "tech_id": tech_id,
                "message": ("You can't hard-delete your own technician "
                             "profile. Ask another admin to do it.")}
    if actor.get("technician_id") == tech_id:
        return {"code": "cannot_delete_self",
                "tech_id": tech_id,
                "message": ("You can't hard-delete your own technician "
                             "profile. Ask another admin to do it.")}

    # --- Last-admin orphan guard ---
    # If the linked user is admin/super_admin AND removing them would
    # drop the tenant's admin-user count to zero → block.
    if linked_user_id:
        linked_user = await db.users.find_one(
            {"id": linked_user_id, "tenant_id": tenant_id},
            {"_id": 0, "role": 1, "deleted_at": 1},
        )
        if linked_user:
            role = (linked_user.get("role") or "").lower()
            if role in ("admin", "super_admin"):
                # Count remaining admins in the tenant, excluding
                # this one + soft-deleted ones.
                remaining = await db.users.count_documents({
                    "tenant_id": tenant_id,
                    "role": {"$in": ["admin", "super_admin"]},
                    "id": {"$ne": linked_user_id},
                    "$or": [{"deleted_at": None},
                             {"deleted_at": {"$exists": False}}],
                })
                if remaining <= 0:
                    return {
                        "code": "would_orphan_tenant_no_admin_remaining",
                        "tech_id": tech_id,
                        "message": (
                            "Can't delete — this would leave the tenant "
                            "with zero admin/super_admin users. Promote "
                            "another user to admin first."
                        ),
                    }
    return None


@router.delete("/technicians/{tech_id}/hard-delete",
                operation_id="technicians.hardDelete")
async def hard_delete_technician(
    tech_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P42 — physical removal of a technician + their linked
    user login + pending invitations. Future jobs are unassigned;
    job records are never deleted."""
    tech_doc = await db.technicians.find_one(
        {"id": tech_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not tech_doc:
        raise HTTPException(404, "Technician not found")

    block = await _p42_pre_delete_checks(
        tenant_id=tenant["id"], tech_doc=tech_doc, actor=user,
    )
    if block:
        raise HTTPException(400, block)

    now_utc = datetime.now(timezone.utc).isoformat()
    return await _p42_snapshot_and_delete(
        tenant_id=tenant["id"], tech_doc=tech_doc, actor=user,
        now_utc=now_utc,
    )


@router.post("/technicians/hard-delete-bulk",
              operation_id="technicians.hardDeleteBulk")
async def hard_delete_technicians_bulk(
    body: _TechniciansHardDeleteBulkIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P42 — bulk hard delete. Response reports per-tech
    outcomes so a caller can render a partial-success table. Ids
    that don't exist for this tenant (or belong to another tenant)
    land in ``not_found``. Self-delete + orphan blocks land in
    ``skipped`` with a stable ``code`` for the FE to switch on.
    """
    ids = list(body.ids or [])
    requested_count = len(ids)
    if requested_count == 0:
        return {"requested_count": 0, "deleted_count": 0,
                "not_found": [], "skipped": [], "results": [],
                "future_jobs_unassigned_total": 0,
                "linked_users_deleted_total": 0,
                "pending_invitations_deleted_total": 0}
    if requested_count > _TECHNICIANS_HARD_DELETE_CAP:
        raise HTTPException(
            400,
            "hard-delete-bulk capped at "
            f"{_TECHNICIANS_HARD_DELETE_CAP} techs per call",
        )

    # Dedupe while preserving caller order.
    seen: set = set()
    deduped: List[str] = []
    for rid in ids:
        if rid not in seen:
            seen.add(rid)
            deduped.append(rid)

    now_utc = datetime.now(timezone.utc).isoformat()
    existing = await db.technicians.find(
        {"tenant_id": tenant["id"], "id": {"$in": deduped}},
        {"_id": 0},
    ).to_list(_TECHNICIANS_HARD_DELETE_CAP)
    existing_by_id = {d["id"]: d for d in existing}
    not_found = [rid for rid in deduped if rid not in existing_by_id]

    results: List[dict] = []
    skipped: List[dict] = []
    fut_total = users_total = inv_total = 0
    for tech_id, tech_doc in existing_by_id.items():
        block = await _p42_pre_delete_checks(
            tenant_id=tenant["id"], tech_doc=tech_doc, actor=user,
        )
        if block:
            skipped.append(block)
            continue
        try:
            r = await _p42_snapshot_and_delete(
                tenant_id=tenant["id"], tech_doc=tech_doc, actor=user,
                now_utc=now_utc,
            )
        except Exception as e:                                        # noqa: BLE001
            logger.exception(f"[p42] bulk delete failed for {tech_id}: {e}")
            skipped.append({"code": "internal_error",
                            "tech_id": tech_id,
                            "message": "Internal error during delete."})
            continue
        results.append(r)
        fut_total += r["future_jobs_unassigned"]
        if r["linked_user_deleted"]:
            users_total += 1
        inv_total += r["pending_invitations_deleted"]

    return {
        "requested_count": requested_count,
        "deleted_count": len(results),
        "not_found": not_found,
        "skipped": skipped,
        "results": results,
        "future_jobs_unassigned_total": fut_total,
        "linked_users_deleted_total": users_total,
        "pending_invitations_deleted_total": inv_total,
    }

