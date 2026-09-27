"""LDM-C · Feb-2026 — Predictive Maintenance Scanner.

Companion to :mod:`services.live_dispatcher` and the third structural
pass of the AI Live Dispatcher + Predictive Maintenance track (see
``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md`` §LDM-C).

Cron entry point runs hourly; per-tenant gate fires exactly when the
tenant's local time is 06:00 (matches the tenant-tz pattern from
:mod:`services.equipment_trackers_cron`). At that gate, iterates
every active-pool-subscription customer and, for each of the two
tracker types (``filter`` / ``salt_cell``), drafts a pending
cross-sell action in ``ai_employee_actions`` when the interval
threshold from ``settings.automation_rules`` has lapsed.

Detection strategies chosen (see LDM-C recon narrative in the
commit body):
  * Filter cleaning:  ``equipment_service_trackers`` row where
                       ``tracker_type == "filter"`` and
                       ``is_active == True``. Structured
                       ``last_cleaned_at`` field.
  * Salt cell:        same collection, ``tracker_type == "salt_cell"``.

Both types share the ``last_cleaned_at`` schema — the Phase-11
equipment tracker already rolls this forward on job completion
(see ``routers/equipment_trackers.py::log_cleaning_from_job``),
so we don't need to grep visit history or free-text checklists.

Cross-sell action shape (per user-ruling #1)::

    {
        id, tenant_id, customer_id,
        action_type: "cross_sell_filter" | "cross_sell_salt_cell",
        status:      "pending",
        drafted_by:  "marco_executive",
        drafted_at:  <iso>,
        due_reason:  "Overdue by X months",
        customer_last_service_at: <iso | null>,
        suggested_price_range:    null,   # follow-up per user-ruling #8
        # Compatibility fields for existing ai_employee_actions surface
        employee_key: "marco_executive",
        action:       "marco.cross_sell_filter" | "marco.cross_sell_salt_cell",
        title / summary / source
    }

Dedupe (per user-ruling #5): a new draft is suppressed when a row
with ``status ∈ {pending, in_review}`` already exists for the same
``(tenant_id, customer_id, action_type)``. Completed / rejected
actions do NOT suppress — the scanner re-drafts on the next
sweep, so a customer who declined last quarter can be re-nudged.

Cross-tenant safety: every mongo query includes ``tenant_id``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from utils import new_id, now_iso


logger = logging.getLogger("maintenance_scanner")


# ═════════════════════════════════════════════════════════════════════
# Tunables.
# ═════════════════════════════════════════════════════════════════════
DEFAULT_TZ = "America/Phoenix"
CRON_HOUR_LOCAL = 6  # tenant-local hour at which the daily scan fires
DRAFTED_BY = "marco_executive"
ACTION_TYPE_FILTER = "cross_sell_filter"
ACTION_TYPE_SALT_CELL = "cross_sell_salt_cell"
_ACTION_NAMESPACE = "marco."   # matches existing ai_employee_actions convention
_TRACKER_LABEL = {
    "filter": "Filter cleaning",
    "salt_cell": "Salt cell replacement",
}
_TRACKER_TO_INTERVAL_KEY = {
    "filter": "filter_clean_interval_months",
    "salt_cell": "salt_cell_replacement_months",
}
_TRACKER_TO_ACTION_TYPE = {
    "filter": ACTION_TYPE_FILTER,
    "salt_cell": ACTION_TYPE_SALT_CELL,
}
# Statuses that KEEP the dedupe window open. Anything else (done,
# rejected, cancelled, executed, ...) leaves us free to re-draft.
_DEDUPE_STATUSES = frozenset({"pending", "in_review"})

# LDM-A defaults mirror — same rationale as live_dispatcher.
_DEFAULT_FILTER_MONTHS = 6
_DEFAULT_SALT_CELL_MONTHS = 36

# Days-in-a-month for overdue math. Aligns with the standard 30.44
# calendar-day estimate used by the P11 equipment tracker.
_DAYS_PER_MONTH = 30.44


# ═════════════════════════════════════════════════════════════════════
# Public entry points.
# ═════════════════════════════════════════════════════════════════════
async def scan(
    db,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Unconditional per-tenant sweep. Test entry point + manual
    trigger surface — does NOT enforce the 06:00 tenant-local gate.

    Returns aggregate counts::

        {
            "tenants_scanned":      int,
            "subscriptions_checked": int,
            "filter_overdue":       int,
            "salt_cell_overdue":    int,
            "actions_drafted":      int,
            "actions_deduped":      int,
            "no_history_flagged":   int,
        }
    """
    now = now or datetime.now(timezone.utc)
    stats = _fresh_stats()
    async for tenant in db.tenants.find(
        {},
        {"_id": 0, "id": 1, "timezone": 1,
         "settings.automation_rules": 1},
    ):
        stats["tenants_scanned"] += 1
        tid = tenant.get("id")
        if not tid:
            continue
        rules = _rules_with_defaults(tenant)
        await _scan_tenant(db, tenant, tid, rules, now, stats)
    return stats


async def hourly_tick() -> Dict[str, int]:
    """Cron entry — hourly. Only tenants whose local wall-clock
    hour equals :data:`CRON_HOUR_LOCAL` are actually scanned.
    Mirrors the pattern in
    :mod:`services.equipment_trackers_cron.hourly_scan`.

    Never re-raises — a Mongo hiccup or tz resolution error logs
    a warning and skips the offending tenant."""
    from server import db
    now_utc = datetime.now(timezone.utc)
    stats = _fresh_stats()
    tenants_seen = 0
    tenants_gated_in = 0
    async for tenant in db.tenants.find(
        {},
        {"_id": 0, "id": 1, "timezone": 1,
         "settings.automation_rules": 1},
    ):
        tenants_seen += 1
        tid = tenant.get("id")
        if not tid:
            continue
        try:
            local = _tenant_local_now(tenant, now_utc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[maintenance_scanner] tz resolve failed tenant=%s: %s",
                tid, exc,
            )
            continue
        if local.hour != CRON_HOUR_LOCAL:
            continue
        tenants_gated_in += 1
        stats["tenants_scanned"] += 1
        rules = _rules_with_defaults(tenant)
        try:
            await _scan_tenant(db, tenant, tid, rules, now_utc, stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[maintenance_scanner] tenant=%s scan errored: %s",
                tid, exc,
            )
    if tenants_gated_in:
        logger.info(
            "[maintenance_scanner] hourly tick — tenants_seen=%s "
            "tenants_gated_in=%s actions_drafted=%s deduped=%s "
            "filter_overdue=%s salt_cell_overdue=%s",
            tenants_seen, tenants_gated_in,
            stats["actions_drafted"], stats["actions_deduped"],
            stats["filter_overdue"], stats["salt_cell_overdue"],
        )
    return stats


def register_maintenance_scanner_cron(scheduler) -> None:
    """Hook into the APScheduler instance built in server.py.
    Runs hourly; per-tenant local-hour gate lives inside the tick."""
    if scheduler is None:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
        scheduler.add_job(
            hourly_tick,
            CronTrigger(minute=0),
            id="maintenance_scanner.hourly",
            replace_existing=True,
        )
        logger.info(
            "[maintenance_scanner.cron] hourly tick registered "
            "(local %02d:00 tenant gate)",
            CRON_HOUR_LOCAL,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "[maintenance_scanner.cron] scheduler registration"
            " failed: %s", exc,
        )


# ═════════════════════════════════════════════════════════════════════
# Internal — per-tenant sweep.
# ═════════════════════════════════════════════════════════════════════
async def _scan_tenant(
    db, tenant: Dict[str, Any], tid: str,
    rules: Dict[str, int],
    now: datetime,
    stats: Dict[str, int],
) -> None:
    """Iterate every active-pool-subscription customer and flag
    overdue filter + salt-cell service."""
    # 1. Collect unique customer_ids with an active pool billing plan.
    #    ``service`` is free-text (see models.BillingPlanIn); pattern-
    #    match ``pool`` case-insensitive so "Monthly Pool Service",
    #    "Weekly Pool Care", "Pool Service Only" all match while
    #    non-pool plans (e.g. "Landscape Maintenance") are excluded.
    seen_customers: set = set()
    async for plan in db.billing_plans.find(
        {
            "tenant_id": tid,
            "active": {"$ne": False},
            "service": {"$regex": "pool", "$options": "i"},
        },
        {"_id": 0, "customer_id": 1},
    ):
        cid = plan.get("customer_id")
        if not cid or cid in seen_customers:
            continue
        seen_customers.add(cid)
        stats["subscriptions_checked"] += 1
        try:
            await _evaluate_customer(
                db, tid, cid, rules, now, stats,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[maintenance_scanner] tenant=%s customer=%s eval"
                " error: %s", tid, cid, exc,
            )


async def _evaluate_customer(
    db, tid: str, cid: str,
    rules: Dict[str, int],
    now: datetime,
    stats: Dict[str, int],
) -> None:
    """Check both tracker types for one customer."""
    # Optional — hydrate customer name once for the action title.
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tid},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not cust:
        # LDM-E · Cross-tenant safety warning. A billing_plan
        # references a customer_id that does NOT resolve within
        # this tenant's customers collection. That's either a
        # soft-deleted customer or (rarely) cross-tenant data
        # corruption where the plan carries a customer_id owned by
        # another tenant. Refuse to draft an action and log the
        # incident for security review.
        logger.warning(
            "[maintenance_scanner.security] cross_tenant_customer_id"
            " tenant=%s customer_id=%s — skipping action draft",
            tid, cid,
        )
        return
    customer_name = cust.get("name") or ""

    for tracker_type in ("filter", "salt_cell"):
        interval_months = int(rules[_TRACKER_TO_INTERVAL_KEY[tracker_type]])
        # Read the structured last-service field from the P11
        # equipment tracker. When absent, treat as "no history"
        # (per user-ruling #3 — action still drafts).
        tracker = await db.equipment_service_trackers.find_one(
            {
                "tenant_id": tid,
                "customer_id": cid,
                "tracker_type": tracker_type,
                "is_active": True,
            },
            {"_id": 0, "last_cleaned_at": 1},
        )
        last_cleaned_at = None
        overdue_reason: Optional[str] = None
        if tracker is None or not tracker.get("last_cleaned_at"):
            overdue_reason = (
                f"No {_TRACKER_LABEL[tracker_type].lower()} history found"
            )
        else:
            last_cleaned_at = str(tracker["last_cleaned_at"])
            overdue_reason = _overdue_reason(
                last_cleaned_at=last_cleaned_at,
                interval_months=interval_months,
                today=now.date(),
                tracker_label=_TRACKER_LABEL[tracker_type],
            )
        if not overdue_reason:
            continue

        # Overdue OR no-history — attempt draft.
        if tracker_type == "filter":
            stats["filter_overdue"] += 1
        else:
            stats["salt_cell_overdue"] += 1
        if last_cleaned_at is None:
            stats["no_history_flagged"] += 1

        action_type = _TRACKER_TO_ACTION_TYPE[tracker_type]
        if await _dedupe_hit(db, tid, cid, action_type):
            stats["actions_deduped"] += 1
            continue
        await _draft_cross_sell(
            db, tid=tid, cid=cid, customer_name=customer_name,
            tracker_type=tracker_type,
            action_type=action_type,
            last_cleaned_at=last_cleaned_at,
            reason=overdue_reason,
        )
        stats["actions_drafted"] += 1


async def _dedupe_hit(
    db, tid: str, cid: str, action_type: str,
) -> bool:
    existing = await db.ai_employee_actions.find_one(
        {
            "tenant_id": tid,
            "customer_id": cid,
            "action_type": action_type,
            "status": {"$in": list(_DEDUPE_STATUSES)},
        },
        {"_id": 0, "id": 1},
    )
    return existing is not None


async def _draft_cross_sell(
    db, *, tid: str, cid: str, customer_name: str,
    tracker_type: str, action_type: str,
    last_cleaned_at: Optional[str], reason: str,
) -> None:
    """Insert a pending cross-sell row shaped per user-ruling #1
    (LDM-C fields) AND the existing ai_employee_actions surface
    (compat fields — ``employee_key`` / ``action`` / ``title`` /
    ``summary`` — so the shared moderation UI can list this row
    alongside Soshie / Casey drafts without any extra plumbing)."""
    tracker_label = _TRACKER_LABEL[tracker_type]
    stamp = now_iso()
    title = (
        f"{tracker_label} overdue — "
        f"{customer_name or 'customer'}"
    ).strip()
    doc: Dict[str, Any] = {
        # LDM-C canonical fields.
        "id": new_id(),
        "tenant_id": tid,
        "customer_id": cid,
        "action_type": action_type,
        "status": "pending",
        "drafted_by": DRAFTED_BY,
        "drafted_at": stamp,
        "due_reason": reason,
        "customer_last_service_at": last_cleaned_at,
        # Follow-up per user-ruling #8 — pricebook lookup can enrich
        # later. Left explicit-null so the UI can badge it.
        "suggested_price_range": None,
        # Compatibility with existing ai_employee_actions surface.
        "employee_key": DRAFTED_BY,
        "action": f"{_ACTION_NAMESPACE}{action_type}",
        "title": title,
        "summary": reason,
        "params": {
            "customer_id": cid,
            "tracker_type": tracker_type,
        },
        "source": "maintenance_scanner",
        "created_at": stamp,
        "updated_at": stamp,
    }
    await db.ai_employee_actions.insert_one(doc)


# ═════════════════════════════════════════════════════════════════════
# Helpers.
# ═════════════════════════════════════════════════════════════════════
def _fresh_stats() -> Dict[str, int]:
    return {
        "tenants_scanned": 0,
        "subscriptions_checked": 0,
        "filter_overdue": 0,
        "salt_cell_overdue": 0,
        "actions_drafted": 0,
        "actions_deduped": 0,
        "no_history_flagged": 0,
    }


def _rules_with_defaults(tenant: Dict[str, Any]) -> Dict[str, int]:
    rules = (
        (tenant.get("settings") or {}).get("automation_rules") or {}
    )
    return {
        "filter_clean_interval_months": (
            rules.get("filter_clean_interval_months")
            if isinstance(rules.get("filter_clean_interval_months"), int)
            else _DEFAULT_FILTER_MONTHS
        ),
        "salt_cell_replacement_months": (
            rules.get("salt_cell_replacement_months")
            if isinstance(rules.get("salt_cell_replacement_months"), int)
            else _DEFAULT_SALT_CELL_MONTHS
        ),
    }


def _tenant_local_now(tenant: Dict[str, Any],
                        now_utc: datetime) -> datetime:
    tz = (tenant.get("timezone") or "").strip() or DEFAULT_TZ
    try:
        return now_utc.astimezone(ZoneInfo(tz))
    except Exception:  # noqa: BLE001
        return now_utc.astimezone(ZoneInfo(DEFAULT_TZ))


def _overdue_reason(*, last_cleaned_at: str, interval_months: int,
                     today: date, tracker_label: str) -> Optional[str]:
    """Return a human-readable overdue string, or None when the
    service is still within the tolerance window.

    Overdue math (per user-ruling #3)::

        overdue_by_months = (today - last_cleaned).days / 30.44
                            - interval_months
        overdue_by_months > 0 → flag
    """
    try:
        last = date.fromisoformat(last_cleaned_at[:10])
    except Exception:  # noqa: BLE001
        return f"Invalid last-service date on {tracker_label}"
    days_ago = (today - last).days
    if days_ago <= 0:
        return None
    months_ago = days_ago / _DAYS_PER_MONTH
    overdue_by_months = months_ago - interval_months
    if overdue_by_months <= 0:
        return None
    if overdue_by_months >= 1.0:
        return f"Overdue by {round(overdue_by_months, 1)} months"
    days = int(round(overdue_by_months * _DAYS_PER_MONTH))
    if days <= 0:
        days = 1
    return f"Overdue by {days} days"


__all__ = [
    "scan",
    "hourly_tick",
    "register_maintenance_scanner_cron",
    "ACTION_TYPE_FILTER",
    "ACTION_TYPE_SALT_CELL",
    "CRON_HOUR_LOCAL",
    "DRAFTED_BY",
]
