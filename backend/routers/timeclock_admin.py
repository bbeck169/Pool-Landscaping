"""Phase 12 · Feb-2026 — Admin Time-Clock Punch Edits.

Admin / super_admin surface for payroll corrections against the
``timeclock_punches`` collection. Operates on **shifts** (pair of
``in`` + optional ``out`` rows sharing a ``shift_id``) rather than
raw punch rows so the API vocabulary matches the Time Clock UI's
mental model of "a shift has a clock-in and a clock-out time".

Routes (all admin + super_admin only — NOT owner, NOT manager,
NOT tech):

    GET    /api/timeclock/admin/punches?user_id=&start=&end=
                                        &include_deleted=0
    POST   /api/timeclock/admin/punches
    PATCH  /api/timeclock/admin/punches/{shift_id}
    DELETE /api/timeclock/admin/punches/{shift_id}

Shift storage model
-------------------
Each shift is stored as 1 or 2 rows in ``timeclock_punches`` with
a shared ``shift_id`` field (new in Phase 12). The ``in`` row is
the anchor and carries the audit metadata:

    {shift_id, tenant_id, user_id,
     punch_type: "in"|"out", timestamp (ISO UTC),
     source: "web"|"mobile"|"admin_manual",
     lat, lng, accuracy_m, geo_denied, job_id,
     # audit (anchor row only)
     edited_by, edited_at, edit_reason,
     audit_log: [...],
     deleted_at}

Legacy rows written by the tech ``/timeclock/punch`` endpoint have
no ``shift_id`` — the GET list reconstructs those into shifts via
a state-machine pass and surfaces them with ``shift_id = <in.id>``
so the UI can still edit them (first edit stamps a real
``shift_id`` onto both rows).

Phase 6 timer-close integration
-------------------------------
When an admin fills a previously-null ``clock_out`` on a shift
whose IN row carries a ``job_id``, we invoke the Phase 6
``close_open_timers_for_job`` helper. Idempotency is enforced
inside that helper so repeat edits don't duplicate close events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timeclock/admin", tags=["timeclock-admin"])

# Strict role gate per Phase 12 spec — admin + super_admin only.
# Explicitly NOT ``owner``, NOT ``manager``, NOT ``tech``.
_ALLOWED_ROLES = {"admin", "super_admin"}
_ALLOWED_SOURCES = {"web", "mobile", "admin_manual"}


def _require_admin_strict(user: dict = Depends(get_current_user)) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden",
                    "msg": "Admin or super_admin role required."},
        )
    return user


# ─── Pydantic models ──────────────────────────────────────────────
class AdminPunchCreate(BaseModel):
    user_id: str
    clock_in: str
    clock_out: Optional[str] = None
    source: Literal["web", "mobile", "admin_manual"] = "admin_manual"
    reason: str = Field(..., min_length=3)
    job_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class AdminPunchPatch(BaseModel):
    clock_in: Optional[str] = None
    clock_out: Optional[str] = None  # explicit null allowed via sentinel below
    source: Optional[Literal["web", "mobile", "admin_manual"]] = None
    reason: str = Field(..., min_length=3)
    job_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    clear_clock_out: bool = False


# ─── Helpers ──────────────────────────────────────────────────────
def _parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as exc:                                     # noqa: BLE001
        raise HTTPException(400, detail={
            "code": "bad_timestamp",
            "msg": f"Invalid ISO timestamp: {ts!r} ({exc})",
        }) from exc


def _validate_reason(reason: Optional[str]) -> str:
    r = (reason or "").strip()
    if len(r) < 3:
        raise HTTPException(400, detail={
            "code": "reason_required",
            "msg": "A reason of at least 3 characters is required.",
        })
    return r


async def _target_user_in_tenant(tenant_id: str, user_id: str) -> dict:
    u = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "tenant_id": 1, "role": 1},
    )
    if not u:
        raise HTTPException(404, detail={
            "code": "user_not_found",
            "msg": "Target user not found in this tenant.",
        })
    return u


def _row_snapshot(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {
        "timestamp": row.get("timestamp"),
        "source": row.get("source"),
        "job_id": row.get("job_id"),
        "lat": row.get("lat"),
        "lng": row.get("lng"),
    }


def _shift_snapshot(in_row: Optional[dict], out_row: Optional[dict]) -> dict:
    return {
        "clock_in": in_row.get("timestamp") if in_row else None,
        "clock_out": out_row.get("timestamp") if out_row else None,
        "source": in_row.get("source") if in_row else None,
        "job_id": in_row.get("job_id") if in_row else None,
    }


def _diff(before: Optional[dict], after: Optional[dict]) -> Dict[str, Dict[str, Any]]:
    """Return only the keys that changed. Compact per Phase 12 spec."""
    before = before or {}
    after = after or {}
    keys = set(before) | set(after)
    out = {}
    for k in keys:
        if before.get(k) != after.get(k):
            out[k] = {"from": before.get(k), "to": after.get(k)}
    return out


def _audit_entry(*, actor_id: str, action: str, reason: str,
                 before: Optional[dict], after: Optional[dict]) -> dict:
    return {
        "edited_by": actor_id,
        "edited_at": now_iso(),
        "action": action,
        "reason": reason,
        "before": before,
        "after": after,
    }


async def _load_shift(tenant_id: str, shift_id: str,
                       *, include_deleted: bool = False
                       ) -> tuple[Optional[dict], Optional[dict]]:
    """Return (in_row, out_row) for a shift. ``shift_id`` may also be
    an IN row id for legacy pairs (reconstructed on first edit)."""
    base = {"tenant_id": tenant_id}
    if not include_deleted:
        base["deleted_at"] = {"$in": [None]}
    rows = await db.timeclock_punches.find(
        {**base, "shift_id": shift_id},
        {"_id": 0},
    ).to_list(2)
    if rows:
        in_row = next((r for r in rows if r.get("punch_type") == "in"), None)
        out_row = next((r for r in rows if r.get("punch_type") == "out"), None)
        return in_row, out_row
    # Legacy fallback — ``shift_id`` collides with the IN row's id.
    in_row = await db.timeclock_punches.find_one(
        {"tenant_id": tenant_id, "id": shift_id, "punch_type": "in"},
        {"_id": 0},
    )
    if not in_row:
        return None, None
    if not include_deleted and in_row.get("deleted_at"):
        return None, None
    # Find the OUT row paired by immediate temporal succession.
    out_row = await db.timeclock_punches.find_one(
        {"tenant_id": tenant_id,
         "user_id": in_row["user_id"],
         "punch_type": "out",
         "timestamp": {"$gte": in_row["timestamp"]},
         "deleted_at": {"$in": [None]} if not include_deleted else {"$exists": True}},
        {"_id": 0},
        sort=[("timestamp", 1)],
    )
    return in_row, out_row


async def _overlap_conflict(tenant_id: str, user_id: str,
                            ci: datetime, co: Optional[datetime],
                            *, exclude_shift_id: Optional[str] = None) -> Optional[str]:
    """Return a human-readable error if ``[ci, co or ∞]`` overlaps
    any existing (non-deleted) shift for ``user_id``. Otherwise ``None``.

    Overlap definition (per Phase 12 spec):
        (a.ci < b.co OR b.co is None) AND
        (b.ci < a.co OR a.co is None)
    """
    cursor = db.timeclock_punches.find(
        {"tenant_id": tenant_id, "user_id": user_id,
          "punch_type": "in",
          "deleted_at": {"$in": [None]}},
        {"_id": 0, "id": 1, "shift_id": 1, "timestamp": 1},
    )
    inflight = [r async for r in cursor]
    for row in inflight:
        sid = row.get("shift_id") or row.get("id")
        if exclude_shift_id and sid == exclude_shift_id:
            continue
        # Pair for this IN.
        other_in, other_out = await _load_shift(tenant_id, sid)
        if not other_in:
            continue
        b_ci = _parse_iso(other_in["timestamp"])
        b_co = _parse_iso(other_out["timestamp"]) if other_out else None
        a_before_b_end = (b_co is None) or (ci < b_co)
        b_before_a_end = (co is None) or (b_ci < co)
        if a_before_b_end and b_before_a_end:
            return (f"Overlapping punch for this user: existing shift "
                    f"{b_ci.isoformat()} → "
                    f"{b_co.isoformat() if b_co else 'open'} conflicts.")
    return None


def _public_shift(in_row: dict, out_row: Optional[dict]) -> dict:
    sid = in_row.get("shift_id") or in_row.get("id")
    return {
        "shift_id": sid,
        "user_id": in_row.get("user_id"),
        "clock_in": in_row.get("timestamp"),
        "clock_out": out_row.get("timestamp") if out_row else None,
        "source": in_row.get("source"),
        "job_id": in_row.get("job_id"),
        "lat": in_row.get("lat"),
        "lng": in_row.get("lng"),
        "edited_by": in_row.get("edited_by"),
        "edited_at": in_row.get("edited_at"),
        "edit_reason": in_row.get("edit_reason"),
        "audit_log": in_row.get("audit_log") or [],
        "deleted_at": in_row.get("deleted_at"),
    }


# ─── Endpoints ────────────────────────────────────────────────────
@router.get("/punches")
async def list_punches(
    user_id: str = Query(...),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    actor: dict = Depends(_require_admin_strict),
):
    tenant_id = actor["tenant_id"]
    await _target_user_in_tenant(tenant_id, user_id)
    base = {"tenant_id": tenant_id, "user_id": user_id}
    if not include_deleted:
        base["deleted_at"] = {"$in": [None]}
    if start:
        base["timestamp"] = {"$gte": f"{start}T00:00:00+00:00"}
    if end:
        base.setdefault("timestamp", {})["$lte"] = f"{end}T23:59:59+00:00"
    rows = await db.timeclock_punches.find(base, {"_id": 0}).sort(
        "timestamp", 1).to_list(2000)
    # Group by shift_id (fallback: pair legacy via state machine).
    shifts: Dict[str, Dict[str, Any]] = {}
    legacy_in: Optional[dict] = None
    for r in rows:
        sid = r.get("shift_id")
        if sid:
            s = shifts.setdefault(sid, {"in": None, "out": None})
            s[r["punch_type"]] = r
        else:
            if r["punch_type"] == "in":
                if legacy_in:
                    shifts[legacy_in["id"]] = {"in": legacy_in, "out": None}
                legacy_in = r
            else:  # out
                if legacy_in:
                    shifts[legacy_in["id"]] = {"in": legacy_in, "out": r}
                    legacy_in = None
                else:
                    shifts[r["id"]] = {"in": None, "out": r}
    if legacy_in:
        shifts[legacy_in["id"]] = {"in": legacy_in, "out": None}
    items = []
    for pair in shifts.values():
        if pair["in"]:
            items.append(_public_shift(pair["in"], pair["out"]))
        elif pair["out"]:
            # Orphan OUT — surface for admin visibility (rare).
            items.append({
                "shift_id": pair["out"]["id"],
                "user_id": pair["out"]["user_id"],
                "clock_in": None,
                "clock_out": pair["out"].get("timestamp"),
                "source": pair["out"].get("source"),
                "job_id": pair["out"].get("job_id"),
                "lat": pair["out"].get("lat"),
                "lng": pair["out"].get("lng"),
                "edited_by": None,
                "edited_at": None,
                "edit_reason": None,
                "audit_log": [],
                "deleted_at": pair["out"].get("deleted_at"),
                "orphan_out": True,
            })
    items.sort(key=lambda s: s.get("clock_in") or s.get("clock_out") or "")
    return {"items": items, "count": len(items)}


@router.post("/punches")
async def create_punch(body: AdminPunchCreate,
                       actor: dict = Depends(_require_admin_strict)):
    tenant_id = actor["tenant_id"]
    reason = _validate_reason(body.reason)
    if body.source not in _ALLOWED_SOURCES:
        raise HTTPException(400, detail={
            "code": "bad_source",
            "msg": f"source must be one of {sorted(_ALLOWED_SOURCES)}.",
        })
    await _target_user_in_tenant(tenant_id, body.user_id)
    ci = _parse_iso(body.clock_in)
    co = _parse_iso(body.clock_out) if body.clock_out else None
    if co and co < ci:
        raise HTTPException(400, detail={
            "code": "clock_out_before_clock_in",
            "msg": "clock_out must be greater than or equal to clock_in.",
        })
    conflict = await _overlap_conflict(tenant_id, body.user_id, ci, co)
    if conflict:
        raise HTTPException(400, detail={
            "code": "overlapping_punch", "msg": conflict,
        })
    sid = new_id()
    now = now_iso()
    audit = _audit_entry(
        actor_id=actor["id"], action="create", reason=reason,
        before=None,
        after=_shift_snapshot(
            {"timestamp": ci.isoformat(), "source": body.source,
             "job_id": body.job_id},
            {"timestamp": co.isoformat()} if co else None),
    )
    in_doc = {
        "id": new_id(), "shift_id": sid,
        "tenant_id": tenant_id, "user_id": body.user_id,
        "punch_type": "in", "timestamp": ci.isoformat(),
        "source": body.source, "lat": body.lat, "lng": body.lng,
        "accuracy_m": None, "geo_denied": False,
        "job_id": body.job_id,
        "edited_by": actor["id"], "edited_at": now, "edit_reason": reason,
        "audit_log": [audit], "deleted_at": None,
    }
    await db.timeclock_punches.insert_one(in_doc)
    out_row = None
    if co is not None:
        out_doc = {
            "id": new_id(), "shift_id": sid,
            "tenant_id": tenant_id, "user_id": body.user_id,
            "punch_type": "out", "timestamp": co.isoformat(),
            "source": body.source, "lat": body.lat, "lng": body.lng,
            "accuracy_m": None, "geo_denied": False,
            "job_id": body.job_id, "deleted_at": None,
        }
        await db.timeclock_punches.insert_one(out_doc)
        out_row = out_doc
        # Timer-close integration — a brand-new paired shift with a
        # job_id should sweep any still-open job_timers for that job
        # so the Phase 6 universal-close invariant holds.
        if body.job_id:
            try:
                from routers.job_timers import close_open_timers_for_job
                await close_open_timers_for_job(
                    job_id=body.job_id, tenant_id=tenant_id,
                    actor_user_id=actor["id"],
                    reason="admin_punch_edit",
                )
            except Exception as exc:                            # noqa: BLE001
                logger.warning("[timeclock-admin] timer close failed: %s", exc)
    in_row = {k: v for k, v in in_doc.items() if k != "_id"}
    return _public_shift(in_row, out_row)


@router.patch("/punches/{shift_id}")
async def edit_punch(shift_id: str, body: AdminPunchPatch,
                     actor: dict = Depends(_require_admin_strict)):
    tenant_id = actor["tenant_id"]
    reason = _validate_reason(body.reason)
    in_row, out_row = await _load_shift(tenant_id, shift_id)
    if not in_row:
        raise HTTPException(404, detail={"code": "shift_not_found"})

    # Compute desired state.
    ci = _parse_iso(body.clock_in) if body.clock_in \
        else _parse_iso(in_row["timestamp"])
    if body.clear_clock_out:
        co: Optional[datetime] = None
    elif body.clock_out:
        co = _parse_iso(body.clock_out)
    elif out_row:
        co = _parse_iso(out_row["timestamp"])
    else:
        co = None
    if co and co < ci:
        raise HTTPException(400, detail={
            "code": "clock_out_before_clock_in",
            "msg": "clock_out must be greater than or equal to clock_in.",
        })
    # Legacy row? Backfill a shift_id onto both halves so future edits
    # can round-trip by shift_id.
    canonical_sid = in_row.get("shift_id") or in_row.get("id")
    conflict = await _overlap_conflict(
        tenant_id, in_row["user_id"], ci, co,
        exclude_shift_id=canonical_sid,
    )
    if conflict:
        raise HTTPException(400, detail={
            "code": "overlapping_punch", "msg": conflict,
        })

    before = _shift_snapshot(in_row, out_row)
    new_source = body.source or in_row.get("source") or "admin_manual"
    new_job_id = body.job_id if body.job_id is not None else in_row.get("job_id")
    new_lat = body.lat if body.lat is not None else in_row.get("lat")
    new_lng = body.lng if body.lng is not None else in_row.get("lng")

    now = now_iso()
    audit_entry_shape = {
        "edited_by": actor["id"],
        "edited_at": now,
        "action": "edit",
        "reason": reason,
    }
    in_update = {
        "shift_id": canonical_sid,
        "timestamp": ci.isoformat(),
        "source": new_source,
        "job_id": new_job_id,
        "lat": new_lat,
        "lng": new_lng,
        "edited_by": actor["id"],
        "edited_at": now,
        "edit_reason": reason,
    }
    # Phase 6 integration flag — we fire the timer-close after persist
    # IF the shift transitions from open → closed with a job attached.
    was_open = out_row is None
    will_close = co is not None
    now_closes_with_job = (
        was_open and will_close and (new_job_id or in_row.get("job_id"))
    )

    # Persist IN row changes + append audit (full compact diff).
    after_in_snapshot = {
        "timestamp": in_update["timestamp"],
        "source": in_update["source"],
        "job_id": in_update["job_id"],
    }
    after = {
        "clock_in": in_update["timestamp"],
        "clock_out": co.isoformat() if co else None,
        "source": in_update["source"],
        "job_id": in_update["job_id"],
    }
    changes = _diff(before, after)
    audit_entry = {**audit_entry_shape, "before": before, "after": after,
                   "changes": changes}
    await db.timeclock_punches.update_one(
        {"id": in_row["id"], "tenant_id": tenant_id},
        {"$set": in_update, "$push": {"audit_log": audit_entry}},
    )

    # Handle OUT row — create, update, or clear.
    if co is None and out_row is not None:
        # Clearing clock_out — soft-delete the OUT row.
        await db.timeclock_punches.update_one(
            {"id": out_row["id"], "tenant_id": tenant_id},
            {"$set": {"deleted_at": now}},
        )
        out_row = None
    elif co is not None and out_row is None:
        out_doc = {
            "id": new_id(), "shift_id": canonical_sid,
            "tenant_id": tenant_id, "user_id": in_row["user_id"],
            "punch_type": "out", "timestamp": co.isoformat(),
            "source": new_source, "lat": new_lat, "lng": new_lng,
            "accuracy_m": None, "geo_denied": False,
            "job_id": new_job_id, "deleted_at": None,
        }
        await db.timeclock_punches.insert_one(out_doc)
        out_row = out_doc
    elif co is not None and out_row is not None:
        await db.timeclock_punches.update_one(
            {"id": out_row["id"], "tenant_id": tenant_id},
            {"$set": {
                "shift_id": canonical_sid,
                "timestamp": co.isoformat(),
                "source": new_source,
                "job_id": new_job_id,
                "lat": new_lat,
                "lng": new_lng,
            }},
        )

    # Phase 6 — if we just closed an open shift tied to a job, run the
    # universal timer-close sweep for that job.
    if now_closes_with_job:
        job_for_close = new_job_id or in_row.get("job_id")
        try:
            from routers.job_timers import close_open_timers_for_job
            await close_open_timers_for_job(
                job_id=job_for_close, tenant_id=tenant_id,
                actor_user_id=actor["id"],
                reason="admin_punch_edit",
            )
        except Exception as exc:                                # noqa: BLE001
            logger.warning("[timeclock-admin] timer close failed: %s", exc)

    # Reload rows to return the fresh audit tail + updated OUT.
    in_row = await db.timeclock_punches.find_one(
        {"id": in_row["id"], "tenant_id": tenant_id}, {"_id": 0})
    if out_row:
        out_row = await db.timeclock_punches.find_one(
            {"id": out_row["id"], "tenant_id": tenant_id}, {"_id": 0})
    return _public_shift(in_row, out_row)


@router.delete("/punches/{shift_id}")
async def delete_punch(shift_id: str,
                       reason: str = Query(..., min_length=3),
                       hard: int = Query(0),
                       actor: dict = Depends(_require_admin_strict)):
    """Delete a timeclock shift.

    Feb-2026 · Mobile Ticket 2 Part 1 — ``hard=1`` upgrade.
    When ``hard=1`` the row(s) are permanently removed from
    ``db.timeclock_punches`` after being snapshotted into
    ``db.timeclock_hard_deletes`` (operator wants destructive-
    but-recoverable-by-DB-admin semantics).  ``hard=0`` (default)
    preserves the pre-ticket soft-delete contract byte-for-byte.
    """
    tenant_id = actor["tenant_id"]
    reason = _validate_reason(reason)
    in_row, out_row = await _load_shift(tenant_id, shift_id)
    if not in_row and not out_row:
        raise HTTPException(404, detail={"code": "shift_not_found"})
    now = now_iso()
    before = _shift_snapshot(in_row, out_row)
    audit = _audit_entry(
        actor_id=actor["id"], action="delete", reason=reason,
        before=before, after=None,
    )

    _hard = bool(hard)
    if _hard:
        # Snapshot the full row(s) BEFORE deleting so a fat-finger
        # is recoverable by a DB admin.  Store the complete
        # pre-delete doc (not the ``_shift_snapshot`` summary) so
        # every field — audit_log, geo, edit history, etc. — is
        # preserved verbatim.
        for row in (in_row, out_row):
            if not row:
                continue
            await db.timeclock_hard_deletes.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "shift_id": shift_id,
                "collection": "timeclock_punches",
                "original_id": row["id"],
                "deleted_by": actor["id"],
                "deleted_at": now,
                "reason": reason,
                "original_row": row,
            })
            await db.timeclock_punches.delete_one(
                {"id": row["id"], "tenant_id": tenant_id},
            )
        return {"ok": True, "shift_id": shift_id, "deleted_at": now,
                "hard": True}

    # Soft delete (pre-ticket contract).
    if in_row:
        await db.timeclock_punches.update_one(
            {"id": in_row["id"], "tenant_id": tenant_id},
            {"$set": {"deleted_at": now,
                       "edited_by": actor["id"],
                       "edited_at": now,
                       "edit_reason": reason},
             "$push": {"audit_log": audit}},
        )
    if out_row:
        await db.timeclock_punches.update_one(
            {"id": out_row["id"], "tenant_id": tenant_id},
            {"$set": {"deleted_at": now}},
        )
    return {"ok": True, "shift_id": shift_id, "deleted_at": now,
            "hard": False}
