"""Phase 31 · Step 1 — Workstream events (tap-job → checklist telemetry spine).

A tenant-scoped append-only stream that the UI (web + mobile) will use to
record structured "workstream" moments as techs move through the tap-job
flow — e.g. `checklist.opened`, `checklist.item_toggled`, `report.submitted`,
`photo.uploaded`. This step ships **only the backend spine + resolver**.
The UI wiring (checklist modal, mobile screen, tap-job handler, /workstream
web page) lands in Phase 31 · Step 2.

Endpoints (all `/api`-prefixed via server.py):
- POST /api/workstream/events   — admin | super_admin | technician
- GET  /api/workstream/events   — admin | super_admin (list, tenant-scoped)

Discovery pass (Feb 15 2026) confirmed there is no pre-existing
"workstream" or "activity_events" collection. `GET /api/activity`
(operations.py) is a **read-only synthesized feed** off jobs/quotes/leads —
it has no write endpoint, no collection, and cannot be reused for
structured tap-job telemetry. That's why we mint a new router here.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

# Roles allowed to WRITE an event. Customers/portal users are excluded on purpose:
# workstream is technician/operations telemetry, never customer surface.
_WRITER_ROLES = {"admin", "super_admin", "technician"}
# Roles allowed to LIST events (management surface only).
_READER_ROLES = {"admin", "super_admin"}


class WorkstreamEventIn(BaseModel):
    """Wire body for POST /api/workstream/events.

    `type` is required and free-form (e.g. `checklist.opened`,
    `report.submitted`, `photo.uploaded`) so downstream UI features can
    add new moments without a schema migration. `payload` is an opaque
    JSON blob the caller owns — we do not validate its shape here.
    """
    type: str = Field(..., min_length=1, max_length=120)
    payload: Optional[Dict[str, Any]] = None
    # Optional structured link to the resource the event is about
    # (e.g. `{ "type": "job", "id": "<jid>" }`). Free-form on purpose.
    related_ref: Optional[Dict[str, Any]] = None


@router.post("/workstream/events")
async def create_event(
    body: WorkstreamEventIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in _WRITER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to create workstream events")

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "type": body.type,
        "actor_user_id": user["id"],
        "actor_role": user.get("role"),
        "payload": body.payload or {},
        "related_ref": body.related_ref or None,
        "created_at": now_iso(),
    }
    await db.workstream_events.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/workstream/events")
async def list_events(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(50, ge=1, le=500),
    type: Optional[str] = Query(None, description="Exact-match filter on `type`"),
):
    if user.get("role") not in _READER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to list workstream events")

    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if type:
        q["type"] = type

    cur = db.workstream_events.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cur.to_list(limit)


# ── Python mirror of the JS `getChecklistType(job)` helper ────────────────
# Kept here (not in service_reports.py) so the checklist-type resolver has
# a single, testable home that mirrors the JS/TS helpers on web + mobile.
# Distinct from service_reports._detect_template() which returns
# "pool" | "landscape" | "generic" (backend template key). The client-facing
# names are "pool" | "landscaping" | "generic" per the Phase 31 brief.
_POOL_KEYWORDS = ("pool", "chem")
_LANDSCAPING_KEYWORDS = ("landscap", "lawn", "mow", "garden", "trim", "blow")


def get_checklist_type(job: Dict[str, Any] | None) -> str:
    if not job:
        return "generic"
    hay = " ".join(
        str(job.get(k) or "") for k in ("service_type", "job_type", "title")
    ).lower()
    for kw in _POOL_KEYWORDS:
        if kw in hay:
            return "pool"
    for kw in _LANDSCAPING_KEYWORDS:
        if kw in hay:
            return "landscaping"
    return "generic"
