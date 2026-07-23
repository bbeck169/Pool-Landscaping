"""Phase 17 · Feb-2026 — Route Assignment Overrides + Permanent Moves.

This module owns the temporary "shift route this week" and the
irreversible "permanent reassign" mechanics for the Dispatch Board.

Two collections:

* ``route_assignment_overrides`` — additive, timed overrides.
  Additive means we NEVER mutate customers.assigned_tech_ids;
  instead the resolver applies the most-recent unexpired override
  when the dispatch board asks "who owns this stop right now?".
  Rows expire on Saturday 23:59:59 in the tenant timezone.

* ``assignment_change_log`` — audit trail for PERMANENT reassigns.
  Written once per affected customer + surfaced in Customer Detail.

The resolver ``resolve_effective_assignments`` is exposed so the
dispatch-board GET endpoint can transparently rewrite pin +
route-stop assignments before returning them.

Sat-cutoff math:

    - ``end_at`` is *always* Saturday 23:59:59.999999 in the tenant
      timezone. If ``now`` is already Saturday, we still end today
      (which surfaces the "same-day no-op" warning in the UI).
    - Auto-revert requires zero cron work — the resolver simply
      filters out overrides where ``end_at < now`` (in UTC).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from config import db, logger


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _tenant_tz(tenant: Dict[str, Any]):
    tz_name = tenant.get("timezone") or "America/Phoenix"
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Phoenix")


def compute_end_at(now_utc: datetime, tenant: Dict[str, Any]) -> datetime:
    """Saturday 23:59:59.999999 in the tenant timezone, converted
    to UTC. If ``now`` is already Saturday (tenant-local), we still
    end that same Saturday — the UI surfaces the same-day warning."""
    tz = _tenant_tz(tenant)
    now_local = now_utc.astimezone(tz)
    # Python weekday: Mon=0 … Sun=6. Saturday=5.
    days_ahead = (5 - now_local.weekday()) % 7
    saturday_local = (now_local + timedelta(days=days_ahead)).replace(
        hour=23, minute=59, second=59, microsecond=999999,
    )
    return saturday_local.astimezone(timezone.utc)


def is_same_day_no_op(now_utc: datetime, tenant: Dict[str, Any]) -> bool:
    """True when ``now`` is already Saturday in tenant tz — the
    override will only cover the remainder of today. UI surfaces
    this as a warning."""
    tz = _tenant_tz(tenant)
    return now_utc.astimezone(tz).weekday() == 5


async def resolve_effective_assignments(
    tenant_id: str,
    customer_ids: Optional[Iterable[str]] = None,
    at: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return ``{customer_id: {source_tech_id, target_tech_ids, override_id}}``
    for every customer currently under an active override at ``at``.

    Customers with no active override are omitted (caller falls back
    to the doc's ``assigned_tech_ids``)."""
    at = at or _now_utc()
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "canceled_at": {"$exists": False},
        "start_at": {"$lte": at.isoformat()},
        "end_at": {"$gte": at.isoformat()},
    }
    if customer_ids:
        q["customer_ids"] = {"$in": list(customer_ids)}

    # Sort by created_at DESC so last-write-wins.
    overrides: List[Dict[str, Any]] = await db.route_assignment_overrides.find(
        q, {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    resolved: Dict[str, Dict[str, Any]] = {}
    for ov in overrides:
        for cid in ov.get("customer_ids") or []:
            if cid in resolved:
                continue  # earlier (newer) override already applied
            resolved[cid] = {
                "override_id": ov["id"],
                "source_tech_id": ov["source_tech_user_id"],
                "target_tech_id": ov["target_tech_user_id"],
                "end_at": ov["end_at"],
                "scope": ov.get("scope"),
            }
    return resolved


async def apply_overrides_to_customers(
    tenant_id: str, customers: List[Dict[str, Any]],
    at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Mutates ``customers`` in place so their ``assigned_tech_ids``
    reflect the active override target. Each shifted customer gets
    ``override_source_tech_id`` added. Returns the same list for
    chaining."""
    if not customers:
        return customers
    cids = [c["id"] for c in customers if c.get("id")]
    if not cids:
        return customers
    resolved = await resolve_effective_assignments(tenant_id, cids, at)
    if not resolved:
        return customers
    for c in customers:
        r = resolved.get(c.get("id"))
        if not r:
            continue
        src = r["source_tech_id"]
        tgt = r["target_tech_id"]
        # Remove source from effective assignment; add target.
        new_techs = [t for t in (c.get("assigned_tech_ids") or []) if t != src]
        if tgt not in new_techs:
            new_techs.append(tgt)
        c["assigned_tech_ids"] = new_techs
        c["override_source_tech_id"] = src
        c["override_id"] = r["override_id"]
        c["override_end_at"] = r["end_at"]
    return customers


async def create_override(
    tenant_id: str,
    source_tech_user_id: str,
    target_tech_user_id: str,
    customer_ids: List[str],
    scope: str,
    tenant: Dict[str, Any],
    created_by: Optional[str],
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert an override row + return the persisted doc. Callers
    should check ``existing_override_conflict`` via the helper below
    BEFORE calling this on the second confirm-tap."""
    now = _now_utc()
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "source_tech_user_id": source_tech_user_id,
        "target_tech_user_id": target_tech_user_id,
        "customer_ids": list(customer_ids),
        "scope": scope,
        "start_at": now.isoformat(),
        "end_at": compute_end_at(now, tenant).isoformat(),
        "created_by": created_by,
        "created_at": now.isoformat(),
        "notes": notes or None,
    }
    await db.route_assignment_overrides.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def find_conflicting_overrides(
    tenant_id: str, customer_ids: List[str],
) -> List[Dict[str, Any]]:
    """Return active overrides whose customer_ids intersect the
    caller's proposed set. Used to surface the
    ``existing_override_conflict`` warning before commit."""
    now = _now_utc().isoformat()
    return await db.route_assignment_overrides.find(
        {"tenant_id": tenant_id,
          "canceled_at": {"$exists": False},
          "start_at": {"$lte": now},
          "end_at": {"$gte": now},
          "customer_ids": {"$in": list(customer_ids)}},
        {"_id": 0},
    ).to_list(50)


async def cancel_active_overrides_for_customers(
    tenant_id: str, customer_ids: List[str], canceled_by: Optional[str],
) -> int:
    """Soft-cancel every active override touching any of the given
    customers. Called by the PERMANENT reassign path so no ghost
    override lingers after we've mutated the master."""
    now = _now_utc().isoformat()
    res = await db.route_assignment_overrides.update_many(
        {"tenant_id": tenant_id,
          "canceled_at": {"$exists": False},
          "end_at": {"$gte": now},
          "customer_ids": {"$in": list(customer_ids)}},
        {"$set": {"canceled_at": now, "canceled_by": canceled_by,
                    "canceled_reason": "superseded_by_permanent"}},
    )
    return res.modified_count


async def perform_permanent_reassign(
    tenant_id: str,
    source_tech_user_id: str,
    target_tech_user_id: str,
    customer_ids: List[str],
    tenant: Dict[str, Any],
    changed_by: Optional[str],
    scope: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Mutate the master assignment forever.

    Steps:
      1) Flip ``recurring_job_templates.assigned_tech_id`` from
         source → target for every affected customer.
      2) Cascade this week's already-scheduled ``jobs`` from source
         → target so today→Sat also change (matches "existing
         scheduled jobs for THIS WEEK will also move" copy).
      3) Update ``customers.assigned_tech_ids`` directly so the
         dispatch board reflects the change without waiting for
         ``recompute_customer_denorm``.
      4) Cancel every overlapping active override for those
         customers.
      5) Write one ``assignment_change_log`` row per customer.
    """
    now = _now_utc()
    end_of_week = compute_end_at(now, tenant)
    now_iso = now.isoformat()

    # 1) Templates.
    await db.recurring_job_templates.update_many(
        {"tenant_id": tenant_id, "customer_id": {"$in": customer_ids},
          "assigned_tech_id": source_tech_user_id, "active": True},
        {"$set": {"assigned_tech_id": target_tech_user_id}},
    )

    # 2) Cascade this week's scheduled jobs.
    #    scheduled_date is stored as ``YYYY-MM-DD`` (string) or ISO
    #    prefix — bracket both by a $regex range over the tenant-tz
    #    week window. Use tenant-local Mon→Sat for the range so we
    #    don't accidentally grab last week's Friday.
    tz = _tenant_tz(tenant)
    today_local = now.astimezone(tz).date()
    days_ahead = (5 - today_local.weekday()) % 7
    from datetime import date as _date, timedelta as _td
    end_date = today_local + _td(days=days_ahead)
    # inclusive date range
    date_regex = "|".join(
        (today_local + _td(days=i)).isoformat()
        for i in range((end_date - today_local).days + 1)
    ) or today_local.isoformat()
    await db.jobs.update_many(
        {"tenant_id": tenant_id, "customer_id": {"$in": customer_ids},
          "technician_id": source_tech_user_id,
          "scheduled_date": {"$regex": f"^({date_regex})"}},
        {"$set": {"technician_id": target_tech_user_id}},
    )

    # 3) Denorm — replace source with target in customers.assigned_tech_ids.
    await db.customers.update_many(
        {"tenant_id": tenant_id, "id": {"$in": customer_ids},
          "assigned_tech_ids": source_tech_user_id},
        {"$pull": {"assigned_tech_ids": source_tech_user_id}},
    )
    await db.customers.update_many(
        {"tenant_id": tenant_id, "id": {"$in": customer_ids},
          "assigned_tech_ids": {"$ne": target_tech_user_id}},
        {"$addToSet": {"assigned_tech_ids": target_tech_user_id}},
    )

    # 4) Cancel overlapping overrides.
    canceled_n = await cancel_active_overrides_for_customers(
        tenant_id, customer_ids, changed_by,
    )

    # 5) Audit log.
    log_rows = [{
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": cid,
        "from_tech_user_id": source_tech_user_id,
        "to_tech_user_id": target_tech_user_id,
        "changed_by": changed_by,
        "changed_at": now_iso,
        "scope": scope,
        "note": notes or None,
    } for cid in customer_ids]
    if log_rows:
        await db.assignment_change_log.insert_many(log_rows)

    logger.info(
        "[phase17-permanent] tenant=%s source=%s target=%s customers=%s "
        "canceled_overrides=%s",
        tenant_id, source_tech_user_id, target_tech_user_id,
        len(customer_ids), canceled_n,
    )
    return {
        "permanent": True,
        "updated_customer_ids": customer_ids,
        "changed_log_entries": len(log_rows),
        "canceled_overrides": canceled_n,
    }
