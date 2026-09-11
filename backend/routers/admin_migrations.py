"""Feb-2026 · Admin migrations API — one-off backfill wrappers
super_admins can trigger from the deployed app without needing pod
shell access.

Currently exposes:
  * ``POST /admin/migrations/backfill-website-visitor-leads``
    — wraps ``migrations.task_p19_backfill_empty_website_visitor_leads
    .run_backfill_for_tenant`` behind the super_admin gate. Dry-run
    default; the caller MUST explicitly pass ``dry_run=false`` to
    write. Idempotent — safe to call twice.

Contract notes:
  * Tenant scoping strict. Default target = caller's own tenant.
  * When the caller passes ``tenant_slug`` different from their own,
    the endpoint logs a WARN before proceeding (cross-tenant admin
    action). Only super_admins can do this — the role gate already
    covers non-super callers.
  * The endpoint NEVER auto-runs on deploy — must be explicitly
    triggered.  There is no CRON, no lifespan hook.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant

from migrations.task_p19_backfill_empty_website_visitor_leads import (
    run_backfill_for_tenant,
)


logger = logging.getLogger("admin_migrations")

router = APIRouter()


def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


async def _resolve_target_tenant(
    caller_tenant: Dict[str, Any],
    tenant_slug: Optional[str],
) -> Dict[str, Any]:
    """Return the tenant doc to run the migration against.

    Default = caller's own tenant.  Super_admin may pass ``tenant_slug``
    to target a different tenant; if the slug doesn't resolve, raise
    404 rather than silently falling back — cross-tenant admin
    actions must never accidentally hit the wrong org.
    """
    if not tenant_slug:
        return caller_tenant
    target = await db.tenants.find_one(
        {"slug": tenant_slug}, {"_id": 0, "id": 1, "slug": 1, "name": 1},
    )
    if not target:
        raise HTTPException(404, f"tenant_not_found:{tenant_slug}")
    return target


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/backfill-website-visitor-leads
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/backfill-website-visitor-leads",
    operation_id="admin.migrations.backfill_website_visitor_leads",
)
async def backfill_website_visitor_leads(
    dry_run: bool = Query(
        True,
        description=(
            "Safety-first default. Set to false to actually write "
            "the enrichments. Idempotent either way."
        ),
    ),
    tenant_slug: Optional[str] = Query(
        None,
        description=(
            "Target tenant slug. Defaults to the caller's own tenant. "
            "Only super_admins can target a different tenant, and every "
            "cross-tenant invocation is logged at WARN."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    target = await _resolve_target_tenant(tenant, tenant_slug)
    is_cross = target["id"] != tenant["id"]

    log_line = (
        f"[p19-api] user={user.get('id')} email={user.get('email')} "
        f"caller_tenant={tenant['id']} target_tenant={target['id']} "
        f"target_slug={target.get('slug')} dry_run={dry_run} "
        f"cross_tenant={is_cross}"
    )
    if is_cross:
        logger.warning("CROSS-TENANT admin migration invocation · " + log_line)
    else:
        logger.info(log_line)

    report = await run_backfill_for_tenant(
        tenant_id=target["id"], dry_run=dry_run,
    )
    # Wrap the migration's per-tenant report with the tenant envelope
    # the frontend renders on the diff table.
    return {
        "tenant_id": target["id"],
        "tenant_slug": target.get("slug"),
        "tenant_name": target.get("name"),
        "dry_run": report["dry_run"],
        "matched_leads": report["matched_leads"],
        "enriched_leads": report["enriched_leads"],
        "skipped_no_match": report["skipped_no_match"],
        "skipped_no_new_data": report["skipped_no_new_data"],
        "enrichments": report["enrichments"],
        "warnings": report["warnings"],
    }



# ─────────────────────────────────────────────────────────────────────
# Roster Cleanup — list tech-adjacent users + soft-deactivate flow.
# ─────────────────────────────────────────────────────────────────────
# Roles the roster surface exposes for management. Matches the
# ``ASSIGNABLE_ROLES`` set in ``routers/technicians.py`` — that's the
# universe of users the tech-filter dropdowns pull from, so this is
# where duplicate / seed / stale accounts need to be surfaced first.
_TECH_ADJACENT_ROLES = [
    "technician", "tech", "landscaper",
    "landscape_tech", "pool_tech", "tech_both",
]


@router.get(
    "/admin/migrations/roster",
    operation_id="admin.migrations.roster_list",
)
async def list_roster_for_cleanup(
    include_inactive: bool = Query(
        True,
        description=(
            "Include ``active=false`` users so super_admins can "
            "re-activate a wrongly-deactivated user or view the "
            "full history."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Tenant-scoped roster of tech-adjacent users, each row
    annotated with a live ``active_jobs`` count so super_admins can
    see who's safe to deactivate.

    Returns ``[{ id, email, name, role, active, created_at,
    active_jobs, is_deactivated }]``.
    """
    _require_super_admin(user)
    tid = tenant["id"]
    q: Dict[str, Any] = {
        "tenant_id": tid,
        "role": {"$in": _TECH_ADJACENT_ROLES},
        "$and": [
            {"$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
        ],
    }
    if not include_inactive:
        q["$and"].append(
            {"$or": [{"active": {"$ne": False}},
                       {"active": {"$exists": False}}]},
        )

    users = await db.users.find(
        q,
        {"_id": 0, "id": 1, "email": 1, "first_name": 1,
         "last_name": 1, "name": 1, "role": 1, "active": 1,
         "created_at": 1, "department": 1},
    ).sort("created_at", -1).to_list(1000)

    rows: list = []
    for u in users:
        active_flag = u.get("active")
        rows.append({
            "id": u.get("id"),
            "email": u.get("email"),
            "name": (u.get("name")
                      or " ".join([u.get("first_name") or "",
                                    u.get("last_name") or ""]).strip()
                      or u.get("email") or "Unnamed"),
            "role": u.get("role"),
            "department": u.get("department"),
            "created_at": u.get("created_at"),
            "active": True if active_flag is None else bool(active_flag),
            "is_deactivated": active_flag is False,
            # Active jobs count — used by the UI to disable the row's
            # checkbox when non-zero (deactivate would strand work).
            "active_jobs": await db.jobs.count_documents(_active_q := {
                "tenant_id": tid,
                "$or": [
                    {"technician_id": u.get("id")},
                    {"assigned_to": u.get("id")},
                    {"assigned_technician_id": u.get("id")},
                    {"tech_user_id": u.get("id")},
                ],
                "status": {"$in": ["scheduled", "pending", "active",
                                     "in_progress"]},
            }),
            # Feb 2026 · Work-class split. Extra count on the repair
            # bucket only; ``service = total − repair`` so legacy jobs
            # without ``work_class`` land in service automatically.
            "active_jobs_repair": await db.jobs.count_documents(
                {**_active_q, "work_class": "repair"},
            ),
        })
        # ``service`` is derived — matches the read-time invariant in
        # ``backend/services/work_class.py``. Placed AFTER the append
        # so both keys reference the SAME row dict via -1 index.
        rows[-1]["active_jobs_service"] = max(
            0, rows[-1]["active_jobs"] - rows[-1]["active_jobs_repair"],
        )
    return rows


class _DeactivateBody(BaseModel):
    # Feb 2026 · Preview/Run refactor — ``user_ids`` is now optional.
    # When omitted / empty, the endpoint auto-resolves the candidate
    # set to "all tech-adjacent users on the caller's tenant" (same
    # universe as ``GET /roster``). This lets the Preview button on
    # the AdminMigrationsPage operate without first asking the user
    # to click through a checkbox list — the same UX contract the
    # Stripe migration cards use.
    user_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True


@router.post(
    "/admin/migrations/deactivate-users",
    operation_id="admin.migrations.deactivate_users",
)
async def deactivate_users(
    body: _DeactivateBody = Body(default=_DeactivateBody()),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Soft-deactivate a batch of tech-adjacent users.

    Contract:
      * super_admin only.
      * Tenant-scoped — the endpoint refuses to touch any user whose
        ``tenant_id`` doesn't match the caller's.
      * SOFT deactivation — writes ``active=false``. Does NOT
        hard-delete. History (jobs, invoices, service reports) is
        preserved and continues to render the (now-inactive) tech's
        name via the read-time cascade in
        ``services/tech_assignment.py``.
      * Refuses to deactivate users with ANY active job on the
        4-shape ``effective_tid`` union — returns them in
        ``skipped[]`` with reason ``"has_active_jobs"``. Caller
        must reassign first.
      * ``dry_run=true`` (default) reports what WOULD happen without
        writing.
      * Idempotent: deactivating an already-inactive user is a
        no-op (returned in ``skipped[]`` with reason ``"already_inactive"``).
      * Feb 2026 · **Auto-resolve mode** — when the caller sends an
        empty/omitted ``user_ids`` array, the endpoint expands the
        target set to every tech-adjacent user on the tenant (same
        role universe as ``GET /admin/migrations/roster``). This
        powers the Preview/Run card UX. Passing a non-empty list
        preserves the legacy explicit-selection path exactly.

    Response:
      ``{ dry_run, tenant_id, resolved_from, deactivated_count,
          skipped_count, deactivated: [user_id],
          deactivated_details: [{id, email, name, role, active_jobs}],
          skipped: [{user_id, reason}], errors: [] }``
    """
    _require_super_admin(user)
    tid = tenant["id"]
    dry = body.dry_run
    deactivated: list = []
    deactivated_details: list = []
    skipped: list = []
    errors: list = []

    # Feb 2026 · Auto-resolve when caller passes empty ``user_ids``.
    # Filter mirrors the ``GET /roster`` query: same tenant + same
    # ``_TECH_ADJACENT_ROLES`` set + soft-delete guard. The per-row
    # ``already_inactive`` / ``has_active_jobs`` skips below still
    # apply, so callers only ever see truly-cleanable rows land in
    # ``deactivated``.
    resolved_from = "explicit"
    target_ids: list = list(body.user_ids or [])
    if not target_ids:
        resolved_from = "auto"
        auto_rows = await db.users.find(
            {
                "tenant_id": tid,
                "role": {"$in": _TECH_ADJACENT_ROLES},
                "$and": [
                    {"$or": [{"deleted_at": None},
                              {"deleted_at": {"$exists": False}}]},
                ],
            },
            {"_id": 0, "id": 1},
        ).to_list(1000)
        target_ids = [r.get("id") for r in auto_rows if r.get("id")]

    logger.info(
        f"[roster-cleanup-api] user={user.get('id')} "
        f"email={user.get('email')} tenant={tid} "
        f"dry_run={dry} resolved_from={resolved_from} "
        f"target_count={len(target_ids)}"
    )

    for uid in target_ids:
        target = await db.users.find_one(
            {"id": uid, "tenant_id": tid},
            {"_id": 0, "id": 1, "email": 1, "name": 1, "first_name": 1,
             "last_name": 1, "role": 1, "active": 1},
        )
        if not target:
            # Wrong tenant OR user doesn't exist — collapse both into
            # ``not_found`` so we never leak whether a user exists in
            # a different tenant.
            skipped.append({"user_id": uid, "reason": "not_found"})
            continue
        if target.get("role") not in _TECH_ADJACENT_ROLES:
            skipped.append({"user_id": uid, "reason": "not_tech_adjacent"})
            continue
        if target.get("active") is False:
            skipped.append({"user_id": uid, "reason": "already_inactive"})
            continue
        # Active-jobs guard — same 4-shape union the tech filter uses.
        active_jobs = await db.jobs.count_documents({
            "tenant_id": tid,
            "$or": [
                {"technician_id": uid},
                {"assigned_to": uid},
                {"assigned_technician_id": uid},
                {"tech_user_id": uid},
            ],
            "status": {"$in": ["scheduled", "pending", "active",
                                 "in_progress"]},
        })
        if active_jobs > 0:
            skipped.append({
                "user_id": uid,
                "reason": "has_active_jobs",
                "active_jobs": active_jobs,
            })
            continue
        if not dry:
            try:
                await db.users.update_one(
                    {"id": uid, "tenant_id": tid},
                    {"$set": {
                        "active": False,
                        "deactivated_at": _now_iso(),
                        "deactivated_by": user.get("id"),
                    }},
                )
            except Exception as exc:                              # noqa: BLE001
                errors.append({"user_id": uid, "error": str(exc)})
                continue
        deactivated.append(uid)
        # Enrich the preview payload so the frontend can render a
        # human-readable ``email · role`` row without a second GET.
        deactivated_details.append({
            "id": uid,
            "email": target.get("email"),
            "name": (target.get("name")
                      or " ".join([target.get("first_name") or "",
                                    target.get("last_name") or ""]).strip()
                      or target.get("email") or "Unnamed"),
            "role": target.get("role"),
            "active_jobs": active_jobs,
        })

    return {
        "dry_run": dry,
        "tenant_id": tid,
        "resolved_from": resolved_from,
        "deactivated_count": len(deactivated),
        "skipped_count": len(skipped),
        "deactivated": deactivated,
        "deactivated_details": deactivated_details,
        "skipped": skipped,
        "errors": errors,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════
# Feb 2026 · Stripe → CRM migration endpoints
# ═════════════════════════════════════════════════════════════════════
@router.post(
    "/admin/migrations/sync-stripe-customers",
    operation_id="admin_migrations_sync_stripe_customers",
    summary="BYO-Stripe: import Stripe customers + attach cards to CRM",
)
async def sync_stripe_customers_endpoint(
    body: Dict[str, Any] = Body(default_factory=dict),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Walk the tenant's Stripe customer roster, match to CRM
    customers by email/phone, and (when ``dry_run=False``) attach
    the Stripe customer id + default payment method to each match.

    Super-admin only. Tenant-scoped. Idempotent — re-running only
    attaches customers that weren't already attached.
    """
    _require_super_admin(user)
    tid = tenant.get("id")
    if not tid:
        raise HTTPException(500, "tenant not resolved")
    from services.stripe_customer_sync import sync_stripe_customers
    from services.payments.stripe_charge import _UnconfiguredStripeError
    try:
        report = await sync_stripe_customers(
            tenant_id=tid,
            actor_user_id=user.get("id") or "",
            dry_run=bool(body.get("dry_run", True)),
            import_unmatched=bool(body.get("import_unmatched", False)),
            limit=body.get("limit"),
        )
    except _UnconfiguredStripeError as exc:
        raise HTTPException(
            400,
            "Stripe not configured — set STRIPE_SECRET_KEY_LIVE (or "
            "STRIPE_SECRET_KEY_TEST) in the process env before calling "
            "this endpoint.",
        )
    return report


@router.post(
    "/admin/migrations/sync-stripe-billing-history",
    operation_id="admin_migrations_sync_stripe_billing_history",
    summary="BYO-Stripe: import historical charges + invoices + subscriptions",
)
async def sync_stripe_billing_history_endpoint(
    body: Dict[str, Any] = Body(default_factory=dict),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Import Stripe billing history (charges, invoices,
    subscriptions) for the tenant. Historical-only — no receipts
    fire, no dashboard-revenue recalc, no CRM invoice status
    mutations. Prereq: at least one CRM customer must have
    ``stripe_customer_id`` set (run the customer sync first).
    """
    _require_super_admin(user)
    tid = tenant.get("id")
    if not tid:
        raise HTTPException(500, "tenant not resolved")
    from services.stripe_billing_history_sync import (
        PrereqNotMetError, sync_stripe_billing_history,
    )
    from services.payments.stripe_charge import _UnconfiguredStripeError
    try:
        report = await sync_stripe_billing_history(
            tenant_id=tid,
            actor_user_id=user.get("id") or "",
            dry_run=bool(body.get("dry_run", True)),
            months_back=int(body.get("months_back", 24)),
            include_subscriptions=bool(body.get("include_subscriptions", True)),
            limit_total=body.get("limit_total"),
            preview_sample_size=body.get("preview_sample_size"),
        )
    except PrereqNotMetError as exc:
        raise HTTPException(400, str(exc))
    except _UnconfiguredStripeError:
        raise HTTPException(
            400,
            "Stripe not configured — set STRIPE_SECRET_KEY_LIVE (or "
            "STRIPE_SECRET_KEY_TEST) in the process env before calling "
            "this endpoint.",
        )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/backfill-persona-avatars
# Feb 2026 — super_admin trigger for the persona ``avatar_url``
# backfill. Boot-migration also runs this on every server start
# (see ``server.py``); this endpoint lets ops force a re-run without
# a redeploy, which is what production needs after the initial sentinel
# has already fired for a schema tweak or a canonical-key addition.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/backfill-persona-avatars",
    operation_id="admin.migrations.backfill_persona_avatars",
)
async def backfill_persona_avatars(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the backfill against every ``ai_employees`` doc. "
            "Idempotent — docs already at the canonical URL are "
            "skipped in-cursor. Use this when the sentinel already "
            "fired but you've shipped new canonical persona keys or "
            "renamed portrait files."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.persona_avatar_backfill import (
        backfill_persona_avatar_urls,
    )
    report = await backfill_persona_avatar_urls(force=force)
    logger.info(
        "[persona-avatar-api] user=%s caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report



# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/unlink-tech-from-customer
# Feb 2026 · Miguel Munoz P0 — one-off cleanup for the "same email
# lives on both a workforce ``users`` record AND a customer ``users``
# record" data-quality issue that the ``routers/auth.login`` fix
# guards against. This endpoint soft-deletes the ORPHAN customer
# ``users`` record so the login flow no longer has ambiguity — the
# ``customers`` collection doc itself is untouched (invoices,
# properties, service history keep working). Super-admin only.
# ─────────────────────────────────────────────────────────────────────
class _UnlinkTechFromCustomerBody(BaseModel):
    email: str = Field(
        ...,
        description="The affected user's email address (case-insensitive)."
                    " Runs across all tenants.",
    )
    dry_run: bool = Field(
        False,
        description="When True, report what would happen without "
                    "writing anything.",
    )


@router.post(
    "/admin/migrations/unlink-tech-from-customer",
    operation_id="admin.migrations.unlink_tech_from_customer",
)
async def unlink_tech_from_customer(
    body: _UnlinkTechFromCustomerBody,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    from utils import now_iso as _now_iso
    WORKFORCE_ROLES = (
        "super_admin", "admin", "manager", "technician", "tech",
    )

    all_users = await db.users.find(
        {"email": email},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "tenant_id": 1,
         "customer_id": 1, "technician_id": 1, "department": 1,
         "deleted_at": 1, "active": 1, "name": 1},
    ).to_list(50)

    report: Dict[str, Any] = {
        "email": email,
        "dry_run": bool(body.dry_run),
        "found_users_records": len(all_users),
        "records": [
            {k: r.get(k) for k in ("id", "role", "tenant_id",
                                     "customer_id", "technician_id",
                                     "department", "deleted_at",
                                     "active", "name")}
            for r in all_users
        ],
        "workforce_records": [],
        "customer_records_to_soft_delete": [],
        "customer_records_soft_deleted": [],
        "actions": [],
    }

    if len(all_users) < 2:
        report["actions"].append(
            "no_action_needed_single_or_zero_users_record"
        )
        logger.info(
            "[unlink-tech-customer] user=%s email=%s → %s (records=%d)",
            (user or {}).get("id"), email,
            report["actions"][-1], len(all_users),
        )
        return report

    workforce = [
        r for r in all_users
        if (r.get("role") or "").lower() in WORKFORCE_ROLES
        and not r.get("deleted_at")
    ]
    customers = [
        r for r in all_users
        if (r.get("role") or "").lower() == "customer"
        and not r.get("deleted_at")
    ]
    report["workforce_records"] = [r["id"] for r in workforce]
    report["customer_records_to_soft_delete"] = [r["id"] for r in customers]

    if not workforce:
        report["actions"].append(
            "no_workforce_record_found_leaving_customer_intact"
        )
        return report

    if not customers:
        report["actions"].append(
            "no_customer_record_found_workforce_is_already_canonical"
        )
        return report

    if body.dry_run:
        report["actions"].append("dry_run_no_writes_performed")
        return report

    for c in customers:
        try:
            await db.users.update_one(
                {"id": c["id"]},
                {"$set": {
                    "deleted_at": _now_iso(),
                    "active": False,
                    "unlinked_by_migration": {
                        "actor_user_id": (user or {}).get("id"),
                        "workforce_record_ids": [r["id"] for r in workforce],
                        "ran_at": _now_iso(),
                        "endpoint": (
                            "POST /admin/migrations/"
                            "unlink-tech-from-customer"
                        ),
                    },
                }},
            )
            report["customer_records_soft_deleted"].append(c["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[unlink-tech-customer] soft-delete failed for "
                "users.id=%s email=%s: %s",
                c["id"], email, e,
            )

    report["actions"].append(
        f"soft_deleted_{len(report['customer_records_soft_deleted'])}"
        "_customer_users_records"
    )
    logger.info(
        "[unlink-tech-customer] actor=%s email=%s "
        "workforce=%s soft_deleted=%s",
        (user or {}).get("id"), email,
        report["workforce_records"],
        report["customer_records_soft_deleted"],
    )
    return report



# ─────────────────────────────────────────────────────────────────────
# Feb 2026 · Customer Merge Phase 3 — auto-merge sweep + summary card.
# The daily 09:15 UTC cron already runs the sweep unconditionally
# (respecting AUTO_MERGE_ENABLED). These endpoints let super_admins:
#   * View the latest run stats (card on /admin/migrations).
#   * Force a fresh sweep on demand against their own tenant.
# ─────────────────────────────────────────────────────────────────────
@router.get(
    "/admin/migrations/auto-merge-summary",
    operation_id="admin.migrations.auto_merge_summary",
)
async def auto_merge_summary(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Live stats card for the /admin/migrations page. Everything is
    computed on-demand from ``customer_merge_audit`` + a lightweight
    detection scan — no cron-side state required. Response::

        {
          "last_auto_run_at":   ISO | null,
          "auto_merged_total":  <int>,     # historical, all-time, this tenant
          "auto_merged_today":  <int>,     # count of audit rows created today
          "records_reassigned_today": <int>,
          "manual_queue_low_confidence": <int>,   # detection scan
          "auto_merge_enabled":  bool      # env flag view
        }
    """
    _require_super_admin(user)
    tid = tenant["id"]
    from datetime import datetime, timezone, timedelta
    from services.customer_merge.detection import (
        detect_duplicates_for_tenant,
    )
    from services.customer_merge.auto_merge import _env_flag_enabled

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_iso = day_start.isoformat()

    # Last auto run — sorted by created_at desc. ``initiated_by`` is
    # ``"auto"`` for the daily cron and ``"auto:<user_id>"`` for the
    # super_admin force-sweep endpoint — regex-match on the prefix
    # so both paths roll up into the same card.
    _AUTO_MATCH = {"$regex": "^auto"}
    last_auto = await db.customer_merge_audit.find_one(
        {"tenant_id": tid, "initiated_by": _AUTO_MATCH},
        sort=[("created_at", -1)],
        projection={"_id": 0, "created_at": 1},
    )

    auto_merged_total = await db.customer_merge_audit.count_documents({
        "tenant_id": tid, "initiated_by": _AUTO_MATCH,
    })

    today_rows = await db.customer_merge_audit.find(
        {"tenant_id": tid, "initiated_by": _AUTO_MATCH,
          "created_at": {"$gte": day_start_iso}},
        {"_id": 0, "secondary_ids": 1, "related_records_rewired": 1},
    ).to_list(1000)
    auto_merged_today = len(today_rows)
    records_reassigned_today = 0
    for row in today_rows:
        # secondary customers reassigned as merged.
        records_reassigned_today += len(row.get("secondary_ids") or [])
        # + related records rewired
        for _k, v in (row.get("related_records_rewired") or {}).items():
            try:
                records_reassigned_today += int(v)
            except Exception:  # noqa: BLE001
                pass

    # Manual queue = current low-confidence groups.
    try:
        groups = await detect_duplicates_for_tenant(tid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auto-merge-summary] detection failed: %s", exc)
        groups = []
    manual_queue = sum(
        1 for g in groups if (g.get("confidence") or "") == "low"
    )

    return {
        "tenant_id": tid,
        "last_auto_run_at": last_auto.get("created_at") if last_auto else None,
        "auto_merged_total": auto_merged_total,
        "auto_merged_today": auto_merged_today,
        "records_reassigned_today": records_reassigned_today,
        "manual_queue_low_confidence": manual_queue,
        "auto_merge_enabled": _env_flag_enabled(),
    }


@router.post(
    "/admin/migrations/auto-merge-sweep",
    operation_id="admin.migrations.auto_merge_sweep",
)
async def force_auto_merge_sweep(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Force one auto-merge sweep against the caller's tenant. Same
    behaviour as the daily 09:15 UTC cron but scoped to a single
    tenant + attributed to the invoking super_admin via the
    ``initiated_by`` audit field (``auto:<user_id>``). Bypasses the
    ``AUTO_MERGE_ENABLED`` env flag so ops can dry-fire even when the
    scheduler is temporarily disabled."""
    _require_super_admin(user)
    from services.customer_merge.auto_merge import (
        auto_merge_high_confidence_duplicates,
    )
    tid = tenant["id"]
    initiated_by = f"auto:{user.get('id') or 'unknown'}"
    report = await auto_merge_high_confidence_duplicates(
        tid, initiated_by=initiated_by,
    )
    logger.info(
        "[auto-merge-force] user=%s tenant=%s summary=%s",
        user.get("id"), tid, {k: report[k] for k in (
            "groups_found_high", "groups_auto_merged",
            "groups_skipped_low_confidence", "records_affected",
        )},
    )
    return report



# ─────────────────────────────────────────────────────────────────────
# Feb 2026 · Invoice line cost backfill · admin force-run endpoint.
# The backfill also runs at server boot (sentinel-guarded); this
# endpoint lets super_admins re-run it on demand — useful after
# importing a new pricebook or after historic invoices had their
# costs corrected upstream.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/invoice-line-cost-backfill",
    operation_id="admin.migrations.invoice_line_cost_backfill",
)
async def force_invoice_line_cost_backfill(
    force: bool = False,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Idempotent re-run of the invoice/quote line cost snapshot
    backfill.  ``force=true`` bypasses the sentinel; the default
    respects it (so a call with no query param on an already-run
    system is a no-op)."""
    _require_super_admin(user)
    from services.migrations.invoice_line_cost_backfill import (
        run_invoice_line_cost_backfill,
    )
    report = await run_invoice_line_cost_backfill(force=bool(force))
    logger.info(
        "[invoice-line-cost-backfill-force] user=%s force=%s summary=%s",
        user.get("id"), force,
        {k: (report.get("summary") or {}).get(k, 0) for k in (
            "tenants_scanned", "docs_scanned", "docs_updated",
            "lines_hydrated_ws", "lines_hydrated_lc",
            "lines_linked_by_name",
        )},
    )
    return report




# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · P0 fix — Invoice number backfill.
# Heals invoices persisted with a null / missing / empty
# ``invoice_number`` field so no operator ever sees "Invoice #: -"
# on the invoices list again. Ships alongside the canonical
# ``insert_invoice`` helper that plugged the three write paths
# feeding the bug (service_reports auto-invoice, accrue_chem_invoice
# chem drafts, reports.py legacy billing-plan runner).
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/backfill-invoice-numbers",
    operation_id="admin.migrations.backfill_invoice_numbers",
)
async def force_invoice_number_backfill(
    force: bool = Query(
        False,
        description=(
            "Bypass the ``feb2026_invoice_number_backfill_v1`` "
            "sentinel. Default respects it so a call with no query "
            "param on an already-run system is a no-op."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Assign human-readable ``INV-YYYY-NNNNNN`` numbers to any
    invoice doc that was persisted with a null / missing / empty
    ``invoice_number`` field. Idempotent — a valid number is never
    overwritten. Response mirrors the sibling
    ``invoice-line-cost-backfill`` endpoint's shape."""
    _require_super_admin(user)
    from services.migrations.invoice_number_backfill import (
        run_invoice_number_backfill,
    )
    report = await run_invoice_number_backfill(force=bool(force))
    logger.info(
        "[invoice-number-backfill-force] user=%s force=%s summary=%s",
        user.get("id"), force, report.get("summary"),
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · P0 fix — Orphan-paid invoice audit.
#
# Heals invoices flipped ``payment_status = "paid"`` without a
# matching payment_record (Hector Guerrero bug). Idempotent +
# sentinel-guarded (``feb2026_orphan_paid_audit_v1``). Default
# entry point is dry-run so operators can review the diff before
# the real flip.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/audit-orphan-paid-invoices",
    operation_id="admin.migrations.audit_orphan_paid_invoices",
)
async def force_orphan_paid_audit(
    dry_run: bool = Query(
        True,
        description=(
            "Safety-first default. When true (default), the audit "
            "returns the diff summary + per-tenant counts WITHOUT "
            "writing. Set to false to actually flip orphan-paid "
            "invoices to ``pending_reconciliation`` + write audit "
            "rows."
        ),
    ),
    force: bool = Query(
        True,
        description=(
            "Whether to bypass the ``feb2026_orphan_paid_audit_v1`` "
            "sentinel. Default true so the admin endpoint can be "
            "invoked at any time even after the boot migration has "
            "already stamped its sentinel."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Scan every invoice with ``payment_status = "paid"`` but no
    proof (no ``payment_records``, no Stripe id, no whitelisted
    ``paid_method``) and flip to ``pending_reconciliation``. Every
    flip writes an audit row to ``db.invoice_status_audit`` so
    operators have a complete trail for Stripe reconciliation.

    ``dry_run=true`` (default) matches + returns the diff without
    writing. Operators MUST review the dry-run output before
    invoking again with ``dry_run=false``.
    """
    _require_super_admin(user)
    from services.migrations.invoice_status_audit import (
        run_orphan_paid_audit,
    )
    report = await run_orphan_paid_audit(
        force=bool(force), dry_run=bool(dry_run),
    )
    logger.info(
        "[orphan-paid-audit-force] user=%s dry_run=%s force=%s summary=%s",
        user.get("id"), dry_run, force, report.get("summary"),
    )
    return report



# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/chemical-usage-events-water-body
# Feb-2026 · Multi-body Phase 1 · Option 2 — super_admin trigger for
# the ``chemical_usage_events`` water-body backfill. The boot
# migration runs this on every server start (see ``server.py``); this
# endpoint lets ops force a re-run without a redeploy — required
# after fixing an ambiguous multi-body attribution or after the
# ``service_reports.water_bodies`` migration re-links a legacy report.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/chemical-usage-events-water-body",
    operation_id="admin.migrations.chemical_usage_events_water_body",
)
async def backfill_chemical_usage_events_water_body(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the backfill. Events that already carry a "
            "``water_body_id`` (including explicit null after prior "
            "runs) are still skipped by the per-doc guard."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.chemical_usage_events_water_body import (
        run_chemical_usage_events_water_body_migration,
    )
    report = await run_chemical_usage_events_water_body_migration(force=force)
    logger.info(
        "[chemical-usage-events-water-body-migration] user=%s "
        "caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report

@router.post(
    "/admin/migrations/service-reports-water-bodies",
    operation_id="admin.migrations.service_reports_water_bodies",
)
async def backfill_service_reports_water_bodies(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the backfill. Docs that already carry a non-empty "
            "``water_bodies`` are still skipped by the per-doc guard."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.service_reports_water_bodies import (
        run_water_bodies_migration,
    )
    report = await run_water_bodies_migration(force=force)
    logger.info(
        "[water-bodies-migration] user=%s caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/service-category-chemicals
# Feb-2026 · Backlog #1 Part 2 — super_admin trigger for the
# "Chemicals" service-category enforcement backfill. Also runs on
# every boot (see ``server.py``); this endpoint lets ops force a
# re-run after adding new chemical pricebook items or after fixing a
# tenant's service_categories collection.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/service-category-chemicals",
    operation_id="admin.migrations.service_category_chemicals",
)
async def backfill_service_category_chemicals(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the backfill. Per-tenant + per-item guards still "
            "prevent double-linking."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.service_category_chemicals import (
        run_service_category_chemicals_migration,
    )
    report = await run_service_category_chemicals_migration(force=force)
    logger.info(
        "[service-category-chemicals-migration] user=%s "
        "caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/revenue-line-items-uuid-category
# Feb-2026 · Backlog #1 Tightening T1 — super_admin trigger for the
# historical line_items[].category UUID backfill. Also runs on every
# boot (see ``server.py``); this endpoint lets ops force a re-run
# after a bulk restore or after fixing an income_categories rename.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/revenue-line-items-uuid-category",
    operation_id="admin.migrations.revenue_line_items_uuid_category",
)
async def backfill_revenue_line_items_uuid_category(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the backfill. Line items already containing a "
            "non-UUID ``category`` string are skipped by the per-line "
            "filter."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.revenue_line_items_uuid_category import (
        run_revenue_line_items_uuid_category_migration,
    )
    report = await run_revenue_line_items_uuid_category_migration(force=force)
    logger.info(
        "[revenue-line-items-uuid-category-migration] user=%s "
        "caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/pricebook-suppliers
# Backlog #iii · Feb-2026 — super_admin trigger for the multi-supplier
# fold-up. Also runs on every boot (see ``server.py``); this endpoint
# lets ops force a re-run after a bulk pricebook restore or after
# fixing supplier display-name typos in the catalog.
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/pricebook-suppliers",
    operation_id="admin.migrations.pricebook_suppliers",
)
async def backfill_pricebook_suppliers(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-runs the fold-up. Per-item dedup on supplier_name "
            "still prevents duplicates."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.pricebook_suppliers import (
        run_pricebook_suppliers_migration,
    )
    report = await run_pricebook_suppliers_migration(force=force)
    logger.info(
        "[pricebook-suppliers-migration] user=%s caller_tenant=%s "
        "force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/notification-dispatch-log
# Backlog #iv · Feb-2026 — super_admin trigger for the notification
# dispatch log + scheduler-lease index bootstrap.  Also runs on every
# boot (see ``server.py``); this endpoint lets ops force a re-run
# after a manual Mongo intervention (dropped index, restored backup).
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/notification-dispatch-log",
    operation_id="admin.migrations.notification_dispatch_log",
)
async def backfill_notification_dispatch_log(
    force: bool = Query(
        False,
        description=(
            "When true, bypasses the ``db.migrations`` sentinel and "
            "re-checks every index.  Idempotent — existing indexes "
            "are left alone."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    from services.migrations.notification_dispatch_log import (
        run_notification_dispatch_log_migration,
    )
    report = await run_notification_dispatch_log_migration(force=force)
    logger.info(
        "[notification-dispatch-log-migration] user=%s "
        "caller_tenant=%s force=%s report=%s",
        user.get("id"), tenant.get("id"), force, report,
    )
    return report


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/backfill-first-access
# Feb-2026 · Customer temp password + first-access tracking rollout.
#
# For every ``users`` row this endpoint hunts for positive evidence
# that the account has completed at least one sign-in — an existing
# ``last_login_at`` field OR a matching ``audit_logs`` row with
# ``event="login"`` and ``status="success"`` (workforce) OR
# ``event="portal_login"`` (customer). When found, the row is stamped
# ``has_ever_logged_in=True`` + ``first_access_at`` (earliest positive
# signal available; the ``last_login_at`` timestamp is used as a
# floor when no dated audit row survives). For customer-role rows the
# ``portal_first_login_at`` denorm is mirrored to ``customers``.
#
# Rules (matches the greenlit spec):
#   * NO row is marked ``has_ever_logged_in=True`` without evidence.
#   * ``first_access_at`` may be an upper bound for pre-feature rows
#     that only survive with a bare ``last_login_at`` (documented in
#     the memo).
#   * Idempotent — safe to run twice. Skips rows already stamped.
#   * Dry-run default; caller must pass ``dry_run=false`` to write.
# ─────────────────────────────────────────────────────────────────────

class BackfillFirstAccessBody(BaseModel):
    dry_run: bool = Field(
        default=True,
        description="When true (default), returns the counts that would be updated without writing.",
    )
    tenant_slug: Optional[str] = Field(
        default=None,
        description="Optional — super_admin only. Target a different tenant.",
    )


@router.post(
    "/admin/migrations/backfill-first-access",
    operation_id="admin.migrations.backfill_first_access",
)
async def backfill_first_access(
    body: BackfillFirstAccessBody = Body(default_factory=BackfillFirstAccessBody),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """One-shot idempotent backfill for the Feb-2026 first-access
    tracking rollout. See module docstring for exact evidence rules."""
    _require_super_admin(user)
    target = await _resolve_target_tenant(tenant, body.tenant_slug)
    tid = target["id"]

    counts = {
        "users_scanned": 0,
        "users_already_stamped": 0,
        "users_stamped": 0,
        "customers_denormed": 0,
        "no_evidence": 0,
    }

    q_users = {"tenant_id": tid,
                "$or": [{"has_ever_logged_in": {"$ne": True}},
                          {"has_ever_logged_in": {"$exists": False}}]}
    async for u in db.users.find(q_users, {"_id": 0}):
        counts["users_scanned"] += 1
        if u.get("has_ever_logged_in"):
            counts["users_already_stamped"] += 1
            continue

        # Evidence hunt.
        email = (u.get("email") or "").lower()
        last_login = u.get("last_login_at")
        first_evidence = None

        # 1) Earliest matching audit row (login success OR portal_login).
        audit_q: Dict[str, Any] = {
            "email": email,
            "$or": [
                {"event": "login", "status": "success"},
                {"event": "portal_login"},
            ],
        }
        audit_row = await db.audit_logs.find_one(
            audit_q,
            {"_id": 0, "created_at": 1},
            sort=[("created_at", 1)],
        )
        if audit_row and audit_row.get("created_at"):
            first_evidence = audit_row["created_at"]

        # 2) Fallback — ``last_login_at`` on the user row (floor).
        if not first_evidence and last_login:
            first_evidence = (last_login if isinstance(last_login, str)
                                else last_login.isoformat())

        if not first_evidence:
            counts["no_evidence"] += 1
            continue

        counts["users_stamped"] += 1
        if body.dry_run:
            continue

        await db.users.update_one(
            {"id": u["id"]},
            {"$set": {
                "has_ever_logged_in": True,
                "first_access_at": first_evidence,
                "first_access_backfilled": True,
            }},
        )
        if u.get("role") == "customer" and u.get("customer_id"):
            res = await db.customers.update_one(
                {"id": u["customer_id"], "tenant_id": tid,
                  "$or": [{"portal_first_login_at": None},
                            {"portal_first_login_at": {"$exists": False}}]},
                {"$set": {"portal_first_login_at": first_evidence}},
            )
            if res.modified_count:
                counts["customers_denormed"] += 1

    logger.info(
        "[first-access-backfill] user=%s tenant=%s dry_run=%s counts=%s",
        user.get("id"), tid, body.dry_run, counts,
    )
    return {
        "ok": True,
        "dry_run": body.dry_run,
        "tenant_id": tid,
        **counts,
    }


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/clear-stale-forced-reset-flags
# Feb-2026 · P0 customer forced-password-reset loop fix — backfill.
#
# Some customers have both ``has_ever_logged_in=True`` AND
# ``must_change_password_on_next_login=True`` on their ``users`` row
# from prior bug exposure (e.g., admin rotated their password AFTER
# they had already completed a first login). The Feb-2026 login gate
# now ignores the stale flag for these rows (see ``routers.auth
# ._should_fork_temp_password_flow``), so leaving them as-is is
# harmless — but keeping the flag set produces noisy anomaly audits
# on every login. This migration clears the stale flag on rows where
# the fix conditions are satisfied.
#
# Scope: customer-role users only. Non-customer rows are NEVER
# touched by this migration.
#
# Idempotent. Dry-run default. Super_admin only.
# ─────────────────────────────────────────────────────────────────────

class ClearStaleForcedResetFlagsBody(BaseModel):
    dry_run: bool = Field(
        default=True,
        description=(
            "Safety-first default. Set to false to actually flip "
            "``must_change_password_on_next_login`` to False on the "
            "affected rows."
        ),
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional — super_admin may target a specific tenant. "
            "When omitted, ALL tenants are scanned."
        ),
    )


@router.post(
    "/admin/migrations/clear-stale-forced-reset-flags",
    operation_id="admin.migrations.clear_stale_forced_reset_flags",
)
async def clear_stale_forced_reset_flags(
    body: ClearStaleForcedResetFlagsBody = Body(
        default_factory=ClearStaleForcedResetFlagsBody),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Flip ``must_change_password_on_next_login`` to False on
    customer rows where ``has_ever_logged_in=True`` was already set
    (i.e., the flag is stale post-first-login). Returns count
    envelope ``{scanned, flipped, skipped, errors, dry_run}``."""
    _require_super_admin(user)

    q: Dict[str, Any] = {
        "role": "customer",
        "has_ever_logged_in": True,
        "must_change_password_on_next_login": True,
    }
    if body.tenant_id:
        q["tenant_id"] = body.tenant_id

    counts = {"scanned": 0, "flipped": 0, "skipped": 0, "errors": 0}
    async for u in db.users.find(q, {"_id": 0, "id": 1, "tenant_id": 1}):
        counts["scanned"] += 1
        if body.dry_run:
            counts["skipped"] += 1
            continue
        try:
            res = await db.users.update_one(
                {"id": u["id"],
                  # Re-check inside the write so a concurrent write
                  # can't undo has_ever_logged_in and leave us
                  # flipping the wrong row.
                  "has_ever_logged_in": True,
                  "must_change_password_on_next_login": True,
                  "role": "customer"},
                {"$set": {"must_change_password_on_next_login": False,
                            "stale_forced_reset_cleared_at": (
                                datetime.now(timezone.utc).isoformat()
                            )}},
            )
            if getattr(res, "modified_count", 0):
                counts["flipped"] += 1
            else:
                counts["skipped"] += 1
        except Exception as exc:  # pragma: no cover
            counts["errors"] += 1
            logger.warning(
                "[clear-stale-forced-reset] uid=%s failed: %s",
                u.get("id"), exc,
            )

    logger.info(
        "[clear-stale-forced-reset] user=%s tenant_id=%s dry_run=%s counts=%s",
        user.get("id"), body.tenant_id, body.dry_run, counts,
    )
    return {
        "ok": True,
        "dry_run": body.dry_run,
        "tenant_id": body.tenant_id,
        **counts,
    }
