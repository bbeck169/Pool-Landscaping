"""Phase I4 · Feb-2026 — Soshie brand-brain async ingest endpoints.

Three endpoints:

* ``POST /api/soshie/brand-brain/ingest`` — 202 Accepted with a
  ``job_id`` in the body + ``Location`` header. Fires the worker
  via ``asyncio.create_task``; the response returns in <500ms.
* ``GET  /api/soshie/brand-brain/ingest/{job_id}`` — current job
  status + progress.
* ``GET  /api/soshie/brand-brain/ingest/latest`` — most recent job
  for the current tenant. Enables the "resume banner" on page
  reload.

All three are admin+ gated. Multi-tenant scoped via
``get_current_tenant``. The legacy ``POST /api/soshie/ingest-website``
in ``routers/soshie_publishing.py`` is shimmed to this async flow
in the same commit — bookmarks and mobile keep working.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import db
from routers.tenants import get_current_tenant
from services.soshie.brand_ingest_jobs import (
    COLLECTION,
    MAX_TOTAL_PATHS,
    create_ingest_job,
    spawn_ingest_job,
)
from utils import require_admin

router = APIRouter()


class IngestBody(BaseModel):
    website_url: str = Field(..., min_length=3, max_length=500)
    extra_paths: List[str] = Field(default_factory=list, max_length=10)


def _sanitize_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip Mongo ``_id`` so the row is JSON-serializable."""
    if not row:
        return None
    out = dict(row)
    out.pop("_id", None)
    return out


@router.post("/soshie/brand-brain/ingest", status_code=202)
async def start_ingest(
    body: IngestBody,
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> JSONResponse:
    """Kick off an async ingest job. Returns 202 with the row +
    a ``Location`` header pointing at the status endpoint."""
    website_url = (body.website_url or "").strip()
    if not website_url:
        raise HTTPException(status_code=400, detail="website_url_required")
    extra_paths = [p.strip() for p in (body.extra_paths or []) if p.strip()]
    # Path cap: home + up to MAX_TOTAL_PATHS-1 extras.
    if len(extra_paths) > (MAX_TOTAL_PATHS - 1):
        raise HTTPException(
            status_code=400,
            detail=(
                f"too_many_paths: submit at most {MAX_TOTAL_PATHS - 1} "
                "extra paths (home page is always crawled)"
            ),
        )
    row = await create_ingest_job(
        tenant["id"], website_url, extra_paths,
        user_id=user.get("id"),
    )
    spawn_ingest_job(row["id"])
    location = f"/api/soshie/brand-brain/ingest/{row['id']}"
    return JSONResponse(
        status_code=202,
        content=_sanitize_row(row),
        headers={"Location": location},
    )


@router.get("/soshie/brand-brain/ingest/latest")
async def latest_ingest(
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Most recent job for the current tenant (any status). Used
    by the frontend on /soshie mount to detect an in-flight
    ingest and render a resume banner."""
    cursor = db[COLLECTION].find(
        {"tenant_id": tenant["id"]},
    ).sort("started_at", -1).limit(1)
    latest = None
    async for r in cursor:
        latest = r
        break
    if not latest:
        return {"job": None}
    return {"job": _sanitize_row(latest)}


@router.get("/soshie/brand-brain/ingest/{job_id}")
async def get_ingest(
    job_id: str = Path(..., min_length=8, max_length=64),
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Poll one job by id. Enforces tenant scope."""
    row = await db[COLLECTION].find_one(
        {"id": job_id, "tenant_id": tenant["id"]},
    )
    if not row:
        raise HTTPException(status_code=404, detail="ingest_job_not_found")
    return _sanitize_row(row)
