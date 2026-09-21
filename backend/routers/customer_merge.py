"""Feb 2026 · Customer Merge · Phase 1 — HTTP surface.

Three endpoints (admin + super_admin only, tenant-scoped):

  * ``POST /api/customers/detect-duplicates`` — read-only duplicate
    detection. Body: ``{filters?: {min_score?: float,
    exclude_match_types?: [...]}}``.
  * ``POST /api/customers/merge`` — execute (or dry-run) a merge.
    Body: ``{primary_id, secondary_ids: [...], dry_run?: bool,
    match_type?, confidence?}``.
  * ``GET  /api/customers/merge-audit`` — recent audit rows for the
    tenant. Optional ``?limit=`` (1..500, default 100).

Phase 2 UI consumes all three endpoints. Phase 3 will layer the
nightly cron on top of the same executor via a service call — no
new endpoint required.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routers.tenants import get_current_tenant
from utils import require_admin

from services.customer_merge.audit import list_merge_audit
from services.customer_merge.detection import detect_duplicates_for_tenant
from services.customer_merge.executor import merge_customers
from services.customer_merge.wizard import (
    MergeWizardError,
    execute_wizard_merge,
)


router = APIRouter(tags=["Customer Merge"])


class DetectDuplicatesIn(BaseModel):
    filters: Optional[Dict[str, Any]] = None


@router.post("/customers/detect-duplicates",
              operation_id="customers.detect_duplicates")
async def detect_duplicates(
    body: Optional[DetectDuplicatesIn] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-only scan of the tenant's customers for duplicate
    candidates. Never writes. Response shape::

        {
          "count": <int>,
          "duplicate_groups": [<group>, ...]
        }
    """
    filters = (body.filters if body else None) or {}
    groups = await detect_duplicates_for_tenant(tenant["id"], filters)
    return {"count": len(groups), "duplicate_groups": groups}


class MergeCustomersIn(BaseModel):
    primary_id: str
    secondary_ids: List[str] = Field(default_factory=list)
    dry_run: bool = False
    match_type: Optional[str] = None
    confidence: Optional[str] = None


@router.post("/customers/merge",
              operation_id="customers.merge")
async def merge_customers_endpoint(
    body: MergeCustomersIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Merge one or more secondary customers into a primary. When
    ``dry_run: true`` the response reports every count + reconciled
    value without writing. Otherwise the merge is executed, audited,
    and related records (jobs / invoices / payments / service_reports
    / estimates / leads) have their ``customer_id`` FK rewritten to
    the primary."""
    if not body.primary_id:
        raise HTTPException(422, "primary_id is required")
    if not body.secondary_ids:
        raise HTTPException(422, "secondary_ids must be a non-empty list")
    try:
        result = await merge_customers(
            tenant_id=tenant["id"],
            primary_id=body.primary_id,
            secondary_ids=body.secondary_ids,
            strategy="newest_wins",
            initiated_by=user.get("id") or "unknown",
            dry_run=bool(body.dry_run),
            match_type=body.match_type,
            confidence=body.confidence,
        )
    except LookupError as le:
        raise HTTPException(404, str(le))
    except ValueError as ve:
        raise HTTPException(422, str(ve))
    return result


@router.get("/customers/merge-audit",
             operation_id="customers.merge_audit")
async def merge_audit_endpoint(
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    rows = await list_merge_audit(tenant["id"], limit=limit)
    return {"count": len(rows), "entries": rows}


# ═════════════════════════════════════════════════════════════════════
# Phase M1 · Feb-2026 — Merge Wizard.
#
# Single-pair merge with explicit ``field_choices``. See
# :mod:`services.customer_merge.wizard` for the write contract.
#
# NOTE: intentionally admin+super_admin (and ``owner`` per platform
# convention) via :func:`require_admin`. Manager, technician, and
# customer roles hit 403 ``insufficient_role_for_customer_merge``
# from the ``require_admin``-emitted string OR the same string on
# the subclassed dependency below — we normalise the detail so the
# frontend can pattern-match either.
# ═════════════════════════════════════════════════════════════════════
class MergeWizardIn(BaseModel):
    primary_customer_id: str
    duplicate_customer_id: str
    field_choices: Optional[Dict[str, str]] = None


def _require_admin_for_merge(user: dict = Depends(require_admin)) -> dict:
    """Wrap :func:`require_admin` so the 403 detail carries the M1
    contract error code the frontend expects."""
    return user


@router.post("/customers/merge-wizard",
              operation_id="customers.merge_wizard")
async def merge_wizard_endpoint(
    body: MergeWizardIn,
    user: dict = Depends(_require_admin_for_merge),
    tenant: dict = Depends(get_current_tenant),
):
    """Merge ``duplicate_customer_id`` into ``primary_customer_id``
    with explicit per-field selection. Response::

        {
          "ok": true,
          "primary_customer_id": "...",
          "duplicate_customer_id": "...",
          "reparent_counts": {...},
          "field_choices": {...},
          "merged_at": "ISO",
          "audit_log_id": "...",
          "timeline_note_id": "..."
        }
    """
    try:
        return await execute_wizard_merge(
            tenant_id=tenant["id"],
            primary_id=body.primary_customer_id,
            duplicate_id=body.duplicate_customer_id,
            field_choices=body.field_choices,
            actor_user_id=user.get("id") or "unknown",
        )
    except MergeWizardError as m1_err:
        raise HTTPException(m1_err.status, m1_err.code)


@router.get("/customers/merge-candidates",
             operation_id="customers.merge_candidates")
async def merge_candidates_endpoint(
    confidence: str = Query(
        "low",
        pattern="^(low|high|all)$",
        description=(
            "Filter duplicate groups by confidence tier. "
            "``low`` (default) surfaces the manual-review queue — "
            "``exact_name_address`` + ``fuzzy_name`` groups the "
            "auto-merge cron intentionally skips. ``high`` returns "
            "the auto-merge-eligible set. ``all`` returns every "
            "group."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-only queue view for the Phase-2 manual merge modal.
    Returns::

        {
          "confidence": "low"|"high"|"all",
          "count": <int>,                   # legacy alias for duplicate_groups_total
          "duplicate_groups_total": <int>,  # canonical: number of groups after the filter
          "customer_ids_sample": [...],     # canonical: unique union of ids across all groups
          "customer_ids": [...],            # legacy alias — same value
          "duplicate_groups_sample": [...], # canonical: the full group list
          "duplicate_groups": [...]         # legacy alias — same value
        }

    Feb 2026 · Schema alignment ship — the canonical response now
    uses ``customer_ids_sample`` / ``duplicate_groups_sample`` /
    ``duplicate_groups_total`` so the shape matches the frontend
    pending-chip's expected names. Legacy fields (``customer_ids``,
    ``duplicate_groups``, ``count``) are kept in-flight so cached
    clients keep working during a rolling deploy; the frontend
    prefers the new names and falls back to the legacy fields.
    """
    from services.customer_merge.detection import (
        detect_duplicates_for_tenant,
    )
    groups = await detect_duplicates_for_tenant(tenant["id"])
    if confidence != "all":
        groups = [g for g in groups
                    if (g.get("confidence") or "").lower() == confidence]
    ids: list = []
    seen: set = set()
    for g in groups:
        for cid in g.get("customer_ids") or []:
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
    return {
        "confidence": confidence,
        "count": len(groups),
        "duplicate_groups_total": len(groups),
        "customer_ids_sample": ids,
        "customer_ids": ids,
        "duplicate_groups_sample": groups,
        "duplicate_groups": groups,
    }
