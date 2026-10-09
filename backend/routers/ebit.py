"""Phase 53a · Feb-2026 — Editable EBIT report backend.

Six admin/super_admin-only endpoints under ``/api/ebit/*``:

* ``GET  /ebit/compute``                — live compute, no save
* ``GET  /ebit/snapshots``              — list versioned snapshots
* ``GET  /ebit/snapshots/{id}``         — fetch a single snapshot
* ``POST /ebit/snapshots``              — save a new (v1 or v+1) version
* ``PATCH /ebit/snapshots/{id}/adjustments`` — new version w/ deltas
* ``PATCH /ebit/snapshots/{id}/overrides``   — new version w/ absolutes

Immutability: every write creates a NEW ``ebit_snapshots`` document
with ``version = max(existing versions for tenant+range) + 1``.
Prior documents are never mutated or deleted. History is inherent.

Role gate (locked pick 4B): only ``super_admin`` + ``admin`` may
call ANY endpoint. All others → 403.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from services.finance.ebit import (
    apply_edits,
    blank_adjustments,
    blank_overrides,
    compute_ebit,
    resolve_range,
)
from utils import get_current_user

# Phase 53d · Feb-2026 — OpenAPI contract lock. Exposing the range
# enum as a ``Literal`` type gives the auto-generated docs the exact
# accepted values instead of relying on the description string. The
# runtime behavior is unchanged (``resolve_range`` still owns the
# validation), but a client generator now knows what to send.
RangeKind = Literal[
    "this_month", "last_month", "qtd", "ytd",
    "monthly", "quarterly", "custom",
]
RevenueBasis = Literal["cash", "accrual"]


router = APIRouter()

# Phase 53c-fix · Feb-2026 — split role gate so managers can VIEW
# (GET compute + GET snapshots list + GET snapshot detail) but cannot
# MUTATE (POST snapshot / PATCH adjustments / PATCH overrides).
_VIEWER_ROLES = frozenset({"admin", "super_admin", "manager"})
_EDITOR_ROLES = frozenset({"admin", "super_admin"})
# Retained alias so any external caller of the private helper keeps
# the historical semantics (editor-only) — the module is not part of
# a public contract but a handful of tests reference it by name.
_ALLOWED_ROLES = _EDITOR_ROLES
_INDEXES_ENSURED = False


def _require_editor(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _EDITOR_ROLES:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})


def _require_viewer(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _VIEWER_ROLES:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})


def _require_role(user: Dict[str, Any]) -> None:
    """Backwards-compat: editor-only gate (POST + PATCH endpoints)."""
    _require_editor(user)


def _require_tenant(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


async def _ensure_indexes() -> None:
    global _INDEXES_ENSURED
    if _INDEXES_ENSURED:
        return
    try:
        await db.ebit_snapshots.create_index(
            [("tenant_id", 1), ("range_from", 1), ("range_to", 1),
              ("version", -1)],
            name="ebit_tenant_range_version_desc",
        )
        await db.ebit_snapshots.create_index(
            [("tenant_id", 1), ("saved_at", -1)],
            name="ebit_tenant_saved_desc",
        )
        _INDEXES_ENSURED = True
    except Exception:
        # Non-fatal — index creation can race across concurrent
        # cold starts; the query still works, just less efficient.
        _INDEXES_ENSURED = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_basis(basis: Optional[str]) -> str:
    b = (basis or "cash").lower().strip()
    if b not in ("cash", "accrual"):
        raise HTTPException(422, {"error": "invalid_revenue_basis",
                                    "allowed": ["cash", "accrual"]})
    return b


def _resolve_range_or_422(kind: str, f: Optional[str], t: Optional[str]) -> tuple[str, str]:
    try:
        return resolve_range(kind, f, t)
    except ValueError as e:
        raise HTTPException(422, {"error": str(e)}) from e


async def _next_version(
    tenant_id: str, range_from: str, range_to: str,
) -> int:
    doc = await db.ebit_snapshots.find_one(
        {"tenant_id": tenant_id,
          "range_from": range_from,
          "range_to": range_to},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    if not doc:
        return 1
    try:
        return int(doc.get("version") or 0) + 1
    except (TypeError, ValueError):
        return 1


# ═══════════════════════════════════════════════════════════════════
# 1. GET /ebit/compute — live compute, no save
# ═══════════════════════════════════════════════════════════════════
@router.get("/ebit/compute")
async def ebit_compute(
    range: RangeKind = Query("this_month",
                              description="Time-range preset. Custom windows require ?from + ?to."),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    revenue_basis: RevenueBasis = Query("cash",
                                          description="cash (paid_at) or accrual (created_at)"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_viewer(user)
    tenant_id = _require_tenant(user)
    basis = _validate_basis(revenue_basis)
    rf, rt = _resolve_range_or_422(range, from_, to)
    live = await compute_ebit(db, tenant_id, rf, rt, basis)
    live["range_kind"] = range
    live["line_adjustments"] = blank_adjustments()
    live["line_overrides"] = blank_overrides()
    return live


# ═══════════════════════════════════════════════════════════════════
# 1b. GET /ebit/trend — Phase 53e (dashboard tile support)
#     Returns N months of EBIT values (default 6, capped 24) in a
#     single round-trip so dashboards can render a compact sparkline
#     without firing six sequential /ebit/compute requests.
# ═══════════════════════════════════════════════════════════════════
@router.get("/ebit/trend")
async def ebit_trend(
    months: int = Query(6, ge=1, le=24,
                         description="Number of trailing months incl. current."),
    revenue_basis: RevenueBasis = Query("cash"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_viewer(user)
    tenant_id = _require_tenant(user)
    basis = _validate_basis(revenue_basis)

    from datetime import datetime, timezone, timedelta as _td
    now = datetime.now(timezone.utc)
    # Build [month_start, month_end) tuples going backwards.
    buckets = []
    y, m = now.year, now.month
    for _i in range(months):
        month_start = datetime(y, m, 1, tzinfo=timezone.utc)
        if m == 12:
            next_start = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_start = datetime(y, m + 1, 1, tzinfo=timezone.utc)
        month_end = next_start - _td(seconds=1)
        buckets.append((month_start, month_end))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    buckets.reverse()  # oldest → newest

    out = []
    for (bs, be) in buckets:
        live = await compute_ebit(
            db, tenant_id, bs.isoformat(), be.isoformat(), basis)
        out.append({
            "month": bs.strftime("%Y-%m"),
            "revenue": live.get("revenue", 0),
            "cogs":    live.get("cogs", 0),
            "opex":    live.get("opex", 0),
            "depreciation": live.get("depreciation", 0),
            # Phase 16 · Feb-2026 — surface the Phase 10 / Phase 11
            # labor slices per bucket so the trend identity
            # ``ebit == revenue - cogs - opex - depreciation
            #            - labor_cost_total`` is reconstructible
            # from the payload. Arithmetic was already correct
            # inside compute_ebit (Phase 11 subtraction baked in);
            # this is a field-exposure fix only. Default to 0 for
            # pre-Phase-11 compute_ebit returns via ``.get(..., 0)``.
            "labor_cost": live.get("labor_cost", 0),
            "recurring_labor_cost": live.get("recurring_labor_cost", 0),
            "labor_cost_total": live.get("labor_cost_total", 0),
            "ebit":    live.get("ebit", 0),
        })
    return {"months": months, "revenue_basis": basis, "series": out}


# ═══════════════════════════════════════════════════════════════════
# 2. GET /ebit/snapshots — list
# ═══════════════════════════════════════════════════════════════════
@router.get("/ebit/snapshots")
async def ebit_snapshots_list(
    range_from: Optional[str] = Query(None),
    range_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_viewer(user)
    tenant_id = _require_tenant(user)
    await _ensure_indexes()

    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if range_from:
        q["range_from"] = range_from
    if range_to:
        q["range_to"] = range_to

    if range_from and range_to:
        sort_spec = [("version", -1)]
    else:
        sort_spec = [("saved_at", -1)]

    rows = await db.ebit_snapshots.find(
        q, {"_id": 0},
    ).sort(sort_spec).to_list(limit)
    return {"snapshots": rows, "count": len(rows)}


# ═══════════════════════════════════════════════════════════════════
# 3. GET /ebit/snapshots/{id} — fetch one
# ═══════════════════════════════════════════════════════════════════
@router.get("/ebit/snapshots/{snapshot_id}")
async def ebit_snapshot_get(
    snapshot_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_viewer(user)
    tenant_id = _require_tenant(user)
    doc = await db.ebit_snapshots.find_one(
        {"id": snapshot_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, {"error": "snapshot_not_found"})
    return doc


# ═══════════════════════════════════════════════════════════════════
# Shared save helper
# ═══════════════════════════════════════════════════════════════════
async def _save_new_version(
    *,
    tenant_id: str,
    range_kind: str,
    range_from: str,
    range_to: str,
    revenue_basis: str,
    line_adjustments: Optional[Dict[str, Any]],
    line_overrides: Optional[Dict[str, Any]],
    author_user_id: str,
    author_display_name: str,
    note: str,
) -> Dict[str, Any]:
    await _ensure_indexes()
    live = await compute_ebit(
        db, tenant_id, range_from, range_to, revenue_basis)
    effective = apply_edits(live, line_adjustments, line_overrides)
    version = await _next_version(tenant_id, range_from, range_to)
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "range_kind": range_kind,
        "range_from": range_from,
        "range_to": range_to,
        "revenue_basis": revenue_basis,
        "version": version,
        "revenue": effective["revenue"],
        "cogs": effective["cogs"],
        "opex": effective["opex"],
        "depreciation": effective["depreciation"],
        "ebit": effective["ebit"],
        "breakdown": live["breakdown"],
        "computed_live": {
            "revenue": live["revenue"], "cogs": live["cogs"],
            "opex": live["opex"], "depreciation": live["depreciation"],
            "ebit": live["ebit"],
        },
        "line_adjustments": effective["line_adjustments"],
        "line_overrides": effective["line_overrides"],
        "author_user_id": author_user_id,
        # Phase 53d · Feb-2026 — contract-locked ``author_display_name``.
        # Falls back gracefully so existing user rows without ``name``
        # still produce a usable value on the versions modal.
        "author_display_name": author_display_name or "",
        "saved_at": _now_iso(),
        "note": note or "",
    }
    await db.ebit_snapshots.insert_one(dict(doc))
    return doc


# ═══════════════════════════════════════════════════════════════════
# 4. POST /ebit/snapshots — save a new (v1 or v+1) snapshot
# ═══════════════════════════════════════════════════════════════════
class SaveSnapshotBody(BaseModel):
    range_kind: str = Field(default="this_month")
    range_from: Optional[str] = None
    range_to: Optional[str] = None
    revenue_basis: Optional[str] = "cash"
    line_adjustments: Optional[Dict[str, Any]] = None
    line_overrides: Optional[Dict[str, Any]] = None
    note: Optional[str] = ""


@router.post("/ebit/snapshots")
async def ebit_snapshot_save(
    body: SaveSnapshotBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_role(user)
    tenant_id = _require_tenant(user)
    basis = _validate_basis(body.revenue_basis)
    rf, rt = _resolve_range_or_422(body.range_kind, body.range_from, body.range_to)

    doc = await _save_new_version(
        tenant_id=tenant_id,
        range_kind=body.range_kind,
        range_from=rf,
        range_to=rt,
        revenue_basis=basis,
        line_adjustments=body.line_adjustments,
        line_overrides=body.line_overrides,
        author_user_id=(user or {}).get("id") or "",
        author_display_name=(user or {}).get("name") or (user or {}).get("email") or "",
        note=body.note or "",
    )
    return doc


# ═══════════════════════════════════════════════════════════════════
# 5+6. PATCH /ebit/snapshots/{id}/{adjustments|overrides}
#     Each writes a NEW immutable version.
# ═══════════════════════════════════════════════════════════════════
class LineEditsBody(BaseModel):
    line_adjustments: Optional[Dict[str, Any]] = None
    line_overrides: Optional[Dict[str, Any]] = None
    note: Optional[str] = ""


async def _load_snapshot_or_404(snapshot_id: str, tenant_id: str) -> Dict[str, Any]:
    doc = await db.ebit_snapshots.find_one(
        {"id": snapshot_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, {"error": "snapshot_not_found"})
    return doc


@router.patch("/ebit/snapshots/{snapshot_id}/adjustments")
async def ebit_snapshot_patch_adjustments(
    snapshot_id: str,
    body: LineEditsBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_role(user)
    tenant_id = _require_tenant(user)
    prior = await _load_snapshot_or_404(snapshot_id, tenant_id)

    # Merge with prior adjustments so PATCH is additive against
    # what's already saved (mimics classic PATCH semantics).
    merged_adj = dict(prior.get("line_adjustments") or {})
    incoming = body.line_adjustments or {}
    for k in ("revenue", "cogs", "opex", "depreciation"):
        if k in incoming and incoming[k] is not None:
            try:
                merged_adj[k] = float(incoming[k])
            except (TypeError, ValueError):
                pass

    doc = await _save_new_version(
        tenant_id=tenant_id,
        range_kind=prior.get("range_kind") or "custom",
        range_from=prior["range_from"],
        range_to=prior["range_to"],
        revenue_basis=prior.get("revenue_basis") or "cash",
        line_adjustments=merged_adj,
        line_overrides=prior.get("line_overrides") or {},
        author_user_id=(user or {}).get("id") or "",
        author_display_name=(user or {}).get("name") or (user or {}).get("email") or "",
        note=body.note or f"adjust: {prior.get('id')}",
    )
    return doc


@router.patch("/ebit/snapshots/{snapshot_id}/overrides")
async def ebit_snapshot_patch_overrides(
    snapshot_id: str,
    body: LineEditsBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_role(user)
    tenant_id = _require_tenant(user)
    prior = await _load_snapshot_or_404(snapshot_id, tenant_id)

    merged_ovr = dict(prior.get("line_overrides") or {})
    incoming = body.line_overrides or {}
    for k in ("revenue", "cogs", "opex", "depreciation"):
        if k in incoming:
            v = incoming[k]
            if v is None:
                merged_ovr[k] = None
            else:
                try:
                    merged_ovr[k] = float(v)
                except (TypeError, ValueError):
                    pass

    doc = await _save_new_version(
        tenant_id=tenant_id,
        range_kind=prior.get("range_kind") or "custom",
        range_from=prior["range_from"],
        range_to=prior["range_to"],
        revenue_basis=prior.get("revenue_basis") or "cash",
        line_adjustments=prior.get("line_adjustments") or {},
        line_overrides=merged_ovr,
        author_user_id=(user or {}).get("id") or "",
        author_display_name=(user or {}).get("name") or (user or {}).get("email") or "",
        note=body.note or f"override: {prior.get('id')}",
    )
    return doc
