"""Phase 11 · Feb 2026 — Equipment Service Trackers.

Unified backend for the pool/landscape service-tracker feature. Two
launch tracker types (``filter`` and ``salt_cell``) — the schema is
future-proofed so heater / pump / auto-cleaner / etc. can be added
by inserting a row in :data:`_TRACKER_LABELS` and shipping a matching
frontend list page. No enum churn required.

═══════════════════════════════════════════════════════════════════════
Collection: ``equipment_service_trackers``
───────────────────────────────────────────────────────────────────────
{
  id              str  (uuid)
  tenant_id       str
  customer_id     str
  property_id     str | None       # optional — a customer may have >1
  tracker_type    "filter" | "salt_cell" | (future types)
  interval_months int                # cadence for auto due-date calc
  last_cleaned_at str | None         # ISO date, e.g. "2026-01-15"
  due_at          str | None         # ISO date (last_cleaned + interval)
  is_active       bool
  history         [{ cleaned_at, by_user_id, by_user_name,
                     source, note, job_id?, prev_due_at?, new_due_at? }]
  created_at, updated_at, created_by
}

``status_computed`` is NEVER stored — it is derived at query-time via
:func:`_compute_status` using ``due_at`` and the per-tenant setting
``tenant.equipment_service_coming_due_days`` (default 30).

Auto-log path: :func:`log_cleaning_from_job` is invoked from
``routers/jobs.py`` when a Filter Cleaning / Salt Cell Cleaning job
transitions to ``completed`` — creates the tracker row on first log
and rolls the due date forward from the job's ``completed_at``.

Reminders: ``send_customer_reminders_for_coming_due()`` fires from
:func:`services.equipment_trackers_cron.hourly_scan` on Monday at
08:00 tenant-local time (see :mod:`services.equipment_trackers_cron`).
Optional per-tenant flag ``equipment_service_customer_reminders_enabled``
gates SMS / email — default OFF.
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ───────────────────────────── Constants ─────────────────────────────
_TRACKER_LABELS: Dict[str, str] = {
    "filter": "Filter",
    "salt_cell": "Salt Cell",
}
_TRACKER_TYPES = set(_TRACKER_LABELS.keys())
_DEFAULT_INTERVALS: Dict[str, int] = {
    "filter": 3,       # every 3 months (~90 days)
    "salt_cell": 12,   # yearly
}
_STATUS_VALUES = ("current", "coming_due", "past_due")
_DEFAULT_COMING_DUE_DAYS = 30


def tracker_label(ttype: str) -> str:
    """Public helper — merge-tag resolvers use it for EQUIPMENT_TYPE."""
    return _TRACKER_LABELS.get(ttype, (ttype or "").replace("_", " ").title())


# ─────────────────────── Date math helpers ────────────────────────────
def _add_months_iso(iso_date: str, months: int) -> str:
    """Add whole months to an ISO date string. Clamps day when the
    target month is shorter (Jan 31 + 1mo → Feb 28/29)."""
    d = date.fromisoformat(iso_date[:10])
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    mm = m % 12 + 1
    # Clamp day.
    from calendar import monthrange
    dd = min(d.day, monthrange(y, mm)[1])
    return date(y, mm, dd).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def _compute_status(due_at: Optional[str], coming_due_days: int) -> str:
    """Derive tri-state status at query time. ``current`` when no
    ``due_at`` is set (freshly created, never cleaned)."""
    if not due_at:
        return "current"
    try:
        due = date.fromisoformat(str(due_at)[:10])
    except (TypeError, ValueError):
        return "current"
    today = date.today()
    if due < today:
        return "past_due"
    delta = (due - today).days
    if delta <= int(coming_due_days or _DEFAULT_COMING_DUE_DAYS):
        return "coming_due"
    return "current"


def _tenant_coming_due_days(tenant: dict) -> int:
    try:
        v = int(tenant.get("equipment_service_coming_due_days") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else _DEFAULT_COMING_DUE_DAYS


# ─────────────────────────── Serialisation ────────────────────────────
def _serialize(row: dict, tenant: dict) -> dict:
    row = dict(row)
    row.pop("_id", None)
    row["status_computed"] = _compute_status(
        row.get("due_at"), _tenant_coming_due_days(tenant),
    )
    row["type_label"] = tracker_label(row.get("tracker_type", ""))
    return row


# ─────────────────────────── Pydantic models ──────────────────────────
class TrackerCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    property_id: Optional[str] = None
    tracker_type: str = Field(..., description="'filter' or 'salt_cell'")
    interval_months: Optional[int] = None
    last_cleaned_at: Optional[str] = None
    is_active: bool = True


class TrackerPatch(BaseModel):
    interval_months: Optional[int] = None
    last_cleaned_at: Optional[str] = None
    is_active: Optional[bool] = None
    property_id: Optional[str] = None


class MarkCleanedIn(BaseModel):
    cleaned_at: Optional[str] = None
    note: Optional[str] = None


def _validate_tracker_type(t: str) -> None:
    if t not in _TRACKER_TYPES:
        raise HTTPException(422, f"tracker_type must be one of {sorted(_TRACKER_TYPES)}")


def _validate_interval_months(m: Any) -> int:
    try:
        v = int(m)
    except (TypeError, ValueError):
        raise HTTPException(422, "interval_months must be a positive integer")
    if v < 1 or v > 120:
        raise HTTPException(422, "interval_months must be between 1 and 120")
    return v


# ═══════════════════════════ Endpoints ════════════════════════════════
@router.get("/equipment/trackers")
async def list_trackers(
    tracker_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None,
        description="One of current | coming_due | past_due"),
    customer_id: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    q: Optional[str] = Query(None,
        description="Case-insensitive substring match on customer_name / address"),
    limit: int = Query(500, ge=1, le=2000),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List trackers for the current tenant with derived
    ``status_computed`` on each row."""
    if user.get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if tracker_type:
        _validate_tracker_type(tracker_type)
        query["tracker_type"] = tracker_type
    if customer_id:
        query["customer_id"] = customer_id
    if property_id:
        query["property_id"] = property_id
    if is_active is not None:
        query["is_active"] = is_active

    rows = await db.equipment_service_trackers.find(
        query, {"_id": 0},
    ).sort([("due_at", 1), ("updated_at", -1)]).to_list(limit)

    coming_due_days = _tenant_coming_due_days(tenant)

    # Enrich with customer name/address (many rows may share customer).
    cust_ids = list({r.get("customer_id") for r in rows if r.get("customer_id")})
    cust_map: Dict[str, dict] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "address": 1, "email": 1, "phone": 1},
        ):
            cust_map[c["id"]] = c

    prop_map: Dict[str, dict] = {}
    prop_ids = list({r.get("property_id") for r in rows if r.get("property_id")})
    if prop_ids:
        async for p in db.properties.find(
            {"id": {"$in": prop_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "address": 1, "label": 1},
        ):
            prop_map[p["id"]] = p

    q_lc = (q or "").strip().lower()
    out: List[dict] = []
    for r in rows:
        r["status_computed"] = _compute_status(r.get("due_at"), coming_due_days)
        if status and r["status_computed"] != status:
            continue
        c = cust_map.get(r.get("customer_id"), {})
        p = prop_map.get(r.get("property_id"), {}) if r.get("property_id") else {}
        r["customer_name"] = c.get("name") or ""
        r["customer_email"] = c.get("email") or ""
        r["customer_phone"] = c.get("phone") or ""
        r["property_address"] = p.get("address") or c.get("address") or ""
        r["type_label"] = tracker_label(r.get("tracker_type", ""))
        if q_lc:
            hay = f"{r['customer_name']} {r['property_address']}".lower()
            if q_lc not in hay:
                continue
        out.append(r)

    counts = {"current": 0, "coming_due": 0, "past_due": 0}
    for r in out:
        counts[r["status_computed"]] = counts.get(r["status_computed"], 0) + 1

    return {
        "trackers": out,
        "count": len(out),
        "counts_by_status": counts,
        "coming_due_days": coming_due_days,
    }


@router.get("/equipment/trackers/{tid}")
async def get_tracker(
    tid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")
    row = await db.equipment_service_trackers.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Tracker not found")
    return _serialize(row, tenant)


@router.post("/equipment/trackers", status_code=201)
async def create_tracker(
    body: TrackerCreate,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    _validate_tracker_type(body.tracker_type)
    interval = _validate_interval_months(
        body.interval_months if body.interval_months is not None
        else _DEFAULT_INTERVALS[body.tracker_type],
    )
    # Enforce single-tracker-of-each-type per (customer, property) pair.
    existing = await db.equipment_service_trackers.find_one({
        "tenant_id": tenant["id"], "customer_id": body.customer_id,
        "property_id": body.property_id, "tracker_type": body.tracker_type,
    }, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(
            409,
            "A tracker of this type already exists for this customer/property — "
            "edit the existing one instead.",
        )

    last = (body.last_cleaned_at or "").strip() or None
    due = _add_months_iso(last, interval) if last else None

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "property_id": body.property_id,
        "tracker_type": body.tracker_type,
        "interval_months": interval,
        "last_cleaned_at": last,
        "due_at": due,
        "is_active": bool(body.is_active),
        "history": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.equipment_service_trackers.insert_one(doc)
    return _serialize(doc, tenant)


@router.patch("/equipment/trackers/{tid}")
async def patch_tracker(
    tid: str,
    body: TrackerPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.equipment_service_trackers.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Tracker not found")

    patch: Dict[str, Any] = {}
    recompute_due = False

    if body.interval_months is not None:
        patch["interval_months"] = _validate_interval_months(body.interval_months)
        recompute_due = True

    if body.last_cleaned_at is not None:
        last_raw = (body.last_cleaned_at or "").strip() or None
        patch["last_cleaned_at"] = last_raw
        recompute_due = True

    if body.is_active is not None:
        patch["is_active"] = bool(body.is_active)

    if body.property_id is not None:
        patch["property_id"] = body.property_id or None

    if not patch:
        return _serialize(row, tenant)

    # Roll due_at forward whenever interval or last-cleaned changes.
    if recompute_due:
        last = patch.get("last_cleaned_at", row.get("last_cleaned_at"))
        interval = patch.get("interval_months", row.get("interval_months") or 0)
        patch["due_at"] = _add_months_iso(last, interval) if last and interval else None

    patch["updated_at"] = now_iso()
    await db.equipment_service_trackers.update_one({"id": tid}, {"$set": patch})
    row.update(patch)
    return _serialize(row, tenant)


@router.delete("/equipment/trackers/{tid}", status_code=204)
async def delete_tracker(
    tid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Soft-delete via ``is_active=False`` — history is preserved for
    audit."""
    row = await db.equipment_service_trackers.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not row:
        raise HTTPException(404, "Tracker not found")
    await db.equipment_service_trackers.update_one(
        {"id": tid},
        {"$set": {"is_active": False, "updated_at": now_iso()}},
    )
    from fastapi import Response
    return Response(status_code=204)


@router.post("/equipment/trackers/{tid}/mark-cleaned")
async def mark_cleaned(
    tid: str,
    body: MarkCleanedIn = Body(default_factory=MarkCleanedIn),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Record a cleaning. Rolls ``last_cleaned_at`` forward and
    recomputes ``due_at``. Admin, manager, or the assigned technician
    may fire this."""
    if user.get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")
    row = await db.equipment_service_trackers.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Tracker not found")

    cleaned_at = (body.cleaned_at or "").strip() or _today_iso()
    interval = int(row.get("interval_months") or _DEFAULT_INTERVALS.get(
        row.get("tracker_type", ""), 3,
    ))
    new_due = _add_months_iso(cleaned_at, interval)
    entry = {
        "cleaned_at": cleaned_at,
        "by_user_id": user.get("id"),
        "by_user_name": user.get("name") or user.get("email") or "",
        "source": "manual",
        "note": (body.note or "").strip() or None,
        "prev_due_at": row.get("due_at"),
        "new_due_at": new_due,
    }
    await db.equipment_service_trackers.update_one(
        {"id": tid},
        {
            "$set": {
                "last_cleaned_at": cleaned_at,
                "due_at": new_due,
                "updated_at": now_iso(),
            },
            "$push": {"history": entry},
        },
    )
    row["last_cleaned_at"] = cleaned_at
    row["due_at"] = new_due
    row["history"] = (row.get("history") or []) + [entry]
    row["updated_at"] = now_iso()
    return _serialize(row, tenant)


# ═════════════════════ Auto-log from completed jobs ═══════════════════
def _infer_tracker_type_from_job(job: dict) -> Optional[str]:
    """Match by explicit ``maintenance_type`` first, then by service
    type name (matches the pattern in ``routers/maintenance.py``)."""
    if not job:
        return None
    mt = (job.get("maintenance_type") or "").strip().lower()
    if mt in _TRACKER_TYPES:
        return mt
    st = (job.get("service_type") or "").lower()
    if "salt" in st and "cell" in st:
        return "salt_cell"
    if "filter" in st and "clean" in st:
        return "filter"
    return None


async def log_cleaning_from_job(job: dict) -> Optional[dict]:
    """Called by ``routers/jobs.py`` when a job flips to ``completed``.
    Idempotently creates (or updates) the tracker row for the job's
    ``(customer_id, property_id, tracker_type)`` combo and appends a
    history entry sourced ``"job"``.

    Never raises — logs and returns ``None`` on failure so callers can
    fire-and-forget."""
    try:
        ttype = _infer_tracker_type_from_job(job)
        if not ttype:
            return None
        tenant_id = job.get("tenant_id")
        cid = job.get("customer_id")
        if not tenant_id or not cid:
            return None
        cleaned_at = (job.get("completed_at") or now_iso())[:10]
        interval = _DEFAULT_INTERVALS[ttype]
        # Try to inherit interval from the customer's own preference if set.
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant_id}, {"_id": 0, "maintenance_intervals": 1},
        ) or {}
        mi = cust.get("maintenance_intervals") or {}
        days_key = "filter_interval_days" if ttype == "filter" else "salt_cell_interval_days"
        if isinstance(mi.get(days_key), (int, float)) and mi[days_key] > 0:
            interval = max(1, int(round(mi[days_key] / 30.0)))
        new_due = _add_months_iso(cleaned_at, interval)
        query = {
            "tenant_id": tenant_id, "customer_id": cid,
            "property_id": job.get("property_id"), "tracker_type": ttype,
        }
        existing = await db.equipment_service_trackers.find_one(query, {"_id": 0})
        entry = {
            "cleaned_at": cleaned_at,
            "by_user_id": job.get("technician_id") or job.get("completed_by"),
            "by_user_name": job.get("technician_name") or "",
            "source": "job",
            "job_id": job.get("id"),
            "prev_due_at": (existing or {}).get("due_at"),
            "new_due_at": new_due,
        }
        if existing:
            await db.equipment_service_trackers.update_one(
                {"id": existing["id"]},
                {
                    "$set": {
                        "last_cleaned_at": cleaned_at,
                        "due_at": new_due,
                        "interval_months": interval,
                        "is_active": True,
                        "updated_at": now_iso(),
                    },
                    "$push": {"history": entry},
                },
            )
            return {**existing,
                    "last_cleaned_at": cleaned_at,
                    "due_at": new_due,
                    "interval_months": interval}
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "customer_id": cid,
            "property_id": job.get("property_id"),
            "tracker_type": ttype,
            "interval_months": interval,
            "last_cleaned_at": cleaned_at,
            "due_at": new_due,
            "is_active": True,
            "history": [entry],
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": job.get("technician_id") or "system",
        }
        await db.equipment_service_trackers.insert_one(doc)
        return doc
    except Exception as exc:  # pragma: no cover — never break job completion
        logger.warning(f"[phase11] log_cleaning_from_job failed: {exc}")
        return None


# ═══════════════════════════ Index bootstrap ══════════════════════════
async def ensure_indexes() -> None:
    try:
        await db.equipment_service_trackers.create_index(
            [("tenant_id", 1), ("tracker_type", 1), ("due_at", 1)],
            name="est_tenant_type_due_idx",
        )
        await db.equipment_service_trackers.create_index(
            [("tenant_id", 1), ("customer_id", 1),
             ("property_id", 1), ("tracker_type", 1)],
            name="est_uniqueish_idx",
        )
    except Exception as exc:
        logger.warning(f"[phase11] equipment tracker indexes skipped: {exc}")
