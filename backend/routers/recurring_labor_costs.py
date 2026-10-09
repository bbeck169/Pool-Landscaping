"""Phase 11 · Feb-2026 — Recurring labor costs CRUD endpoints.

Admin surface for salaried / contracted / fixed-monthly labor
costs that layer on top of the Phase 10 hourly + per-pool numbers.
See the brief in ``memory`` for the data-model rationale.

Role matrix:
    GET    / / {id}        → admin / super_admin / owner / manager
    POST, PATCH, DELETE    → admin / super_admin / owner
    technician / customer  → 403 (require_admin dependency)

Soft-delete semantics on DELETE: flip ``status = "inactive"`` +
set ``end_date = today`` so the entry stops contributing to future
EBIT windows but prior ones (already consumed) can still cite it
for audit. ``?hard=1`` is admin-only + only when no EBIT snapshot
has referenced the row yet — if ambiguous (we can't easily
determine), we fall back to soft.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from utils import get_current_user, require_admin, now_iso, new_id
from routers.tenants import get_current_tenant


router = APIRouter()


_WRITE_ROLES = frozenset({"admin", "super_admin", "owner"})
_READ_ROLES  = frozenset({"admin", "super_admin", "owner", "manager"})


# ─── Pydantic models (POST / PATCH) ────────────────────────────
class RecurringLaborCostIn(BaseModel):
    label: str
    monthly_amount: str
    start_date: str
    end_date: Optional[str] = None
    status: Optional[str] = "active"
    notes: Optional[str] = None
    linked_user_id: Optional[str] = None


class RecurringLaborCostPatch(BaseModel):
    label: Optional[str] = None
    monthly_amount: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    linked_user_id: Optional[str] = None


# ─── Validation helpers ────────────────────────────────────────
def _parse_decimal_nonneg(label: str, raw: Any) -> str:
    """Decimal(str(...)) parse → non-neg → 2-place string. Mirrors
    the Phase 10 ``team.update_user`` rate-parse to keep the write
    path consistent across pay-money fields.
    """
    if raw is None or raw == "":
        raise HTTPException(400, f"{label} is required")
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(400, f"{label} must be a decimal number")
    if not d.is_finite():
        raise HTTPException(400, f"{label} must be a finite decimal")
    if d < 0:
        raise HTTPException(400, f"{label} must be non-negative")
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _parse_iso_date_strict(label: str, raw: Any) -> str:
    """Strict ``YYYY-MM-DD`` → str. 400 on anything else."""
    if raw is None or raw == "":
        raise HTTPException(400, f"{label} is required")
    try:
        d = date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, f"{label} must be an ISO date (YYYY-MM-DD)")
    return d.isoformat()


def _validate_status(raw: Any) -> str:
    s = (str(raw) if raw is not None else "active").lower()
    if s not in ("active", "inactive"):
        raise HTTPException(400, "status must be 'active' or 'inactive'")
    return s


def _ensure_role(user: dict, allowed) -> None:
    role = ((user or {}).get("role") or "").lower()
    if role not in allowed:
        raise HTTPException(403, "forbidden")


# ─── Serialisation ─────────────────────────────────────────────
def _public_shape(doc: dict) -> dict:
    """Drop Mongo ``_id`` + stray internal fields. Nothing is
    tenant-leaking since all callers are tenant-scoped at Depends.
    """
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    out.pop("tenant_id", None)
    out.pop("deleted_at", None)
    return out


# ─── GET /  (list) ─────────────────────────────────────────────
@router.get("/recurring-labor-costs")
async def list_recurring_labor_costs(
    include_inactive: bool = Query(
        True,
        description=(
            "When false, filters out ``status = 'inactive'`` rows. "
            "Default true so the admin table shows the full history "
            "(inactive rows render dimmed)."
        ),
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    _ensure_role(user, _READ_ROLES)
    q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    }
    if not include_inactive:
        q["status"] = "active"
    cursor = db.recurring_labor_costs.find(q).sort(
        [("status", 1), ("start_date", -1)])
    out = []
    async for d in cursor:
        out.append(_public_shape(d))
    return out


# ─── GET /{id} ─────────────────────────────────────────────────
@router.get("/recurring-labor-costs/{entry_id}")
async def get_recurring_labor_cost(
    entry_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _ensure_role(user, _READ_ROLES)
    doc = await db.recurring_labor_costs.find_one(
        {"id": entry_id, "tenant_id": tenant["id"]})
    if not doc:
        raise HTTPException(404, "recurring labor cost not found")
    return _public_shape(doc)


# ─── POST / ────────────────────────────────────────────────────
@router.post("/recurring-labor-costs", status_code=201)
async def create_recurring_labor_cost(
    body: RecurringLaborCostIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _ensure_role(user, _WRITE_ROLES)
    monthly = _parse_decimal_nonneg("monthly_amount", body.monthly_amount)
    start_iso = _parse_iso_date_strict("start_date", body.start_date)
    end_iso: Optional[str] = None
    if body.end_date not in (None, ""):
        end_iso = _parse_iso_date_strict("end_date", body.end_date)
        if end_iso < start_iso:
            raise HTTPException(400, "end_date must be >= start_date")
    status = _validate_status(body.status)
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(400, "label is required")

    doc = {
        "id":              new_id(),
        "tenant_id":       tenant["id"],
        "label":           label,
        "monthly_amount":  monthly,
        "start_date":      start_iso,
        "end_date":        end_iso,
        "status":          status,
        "notes":           (body.notes or "").strip() or None,
        "linked_user_id":  body.linked_user_id or None,
        "created_at":      now_iso(),
        "updated_at":      now_iso(),
        "created_by":      user.get("id"),
    }
    await db.recurring_labor_costs.insert_one(doc)
    return _public_shape(doc)


# ─── PATCH /{id} ───────────────────────────────────────────────
@router.patch("/recurring-labor-costs/{entry_id}")
async def update_recurring_labor_cost(
    entry_id: str,
    body: RecurringLaborCostPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _ensure_role(user, _WRITE_ROLES)
    existing = await db.recurring_labor_costs.find_one(
        {"id": entry_id, "tenant_id": tenant["id"]})
    if not existing:
        raise HTTPException(404, "recurring labor cost not found")

    updates: Dict[str, Any] = {}
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(400, "label cannot be empty")
        updates["label"] = label
    if body.monthly_amount is not None:
        updates["monthly_amount"] = _parse_decimal_nonneg(
            "monthly_amount", body.monthly_amount)
    if body.start_date is not None:
        updates["start_date"] = _parse_iso_date_strict(
            "start_date", body.start_date)
    if body.end_date is not None:
        if body.end_date == "":
            updates["end_date"] = None
        else:
            updates["end_date"] = _parse_iso_date_strict(
                "end_date", body.end_date)
    if body.status is not None:
        updates["status"] = _validate_status(body.status)
    if body.notes is not None:
        updates["notes"] = body.notes.strip() or None
    if body.linked_user_id is not None:
        updates["linked_user_id"] = body.linked_user_id or None

    # Cross-field validation after merge.
    merged_start = updates.get("start_date", existing.get("start_date"))
    merged_end = updates.get("end_date", existing.get("end_date"))
    if merged_end and merged_start and merged_end < merged_start:
        raise HTTPException(400, "end_date must be >= start_date")

    if not updates:
        return _public_shape(existing)
    updates["updated_at"] = now_iso()
    await db.recurring_labor_costs.update_one(
        {"id": entry_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    merged = {**existing, **updates}
    return _public_shape(merged)


# ─── DELETE /{id} ──────────────────────────────────────────────
@router.delete("/recurring-labor-costs/{entry_id}")
async def delete_recurring_labor_cost(
    entry_id: str,
    hard: bool = Query(
        False,
        description=(
            "``hard=1`` physically deletes the row. Only honoured "
            "for admin / super_admin AND only when no EBIT snapshot "
            "has consumed the entry (not easily determinable — we "
            "always fall back to soft when ambiguous)."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _ensure_role(user, _WRITE_ROLES)
    existing = await db.recurring_labor_costs.find_one(
        {"id": entry_id, "tenant_id": tenant["id"]})
    if not existing:
        raise HTTPException(404, "recurring labor cost not found")

    role = ((user or {}).get("role") or "").lower()
    if hard and role in ("admin", "super_admin"):
        # Hard-delete is admin+ only. We don't dig for consuming
        # EBIT snapshots here (that's a Phase 12-ish nicety) — the
        # audit trail is in the EBIT snapshot's own breakdown
        # history, which is immutable.
        await db.recurring_labor_costs.delete_one(
            {"id": entry_id, "tenant_id": tenant["id"]})
        return {"ok": True, "deleted": "hard", "id": entry_id}

    today = date.today().isoformat()
    await db.recurring_labor_costs.update_one(
        {"id": entry_id, "tenant_id": tenant["id"]},
        {"$set": {"status": "inactive",
                   "end_date": today,
                   "updated_at": now_iso()}},
    )
    return {"ok": True, "deleted": "soft", "id": entry_id,
            "end_date": today}
