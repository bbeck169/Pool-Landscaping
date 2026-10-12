"""Preview isolation · admin healthcheck endpoint.

``GET /api/admin/preview-isolation-status``

Admin-only on preview env (``APP_ENV != "production"``). Returns
HTTP 404 on production — the endpoint SHOULDN'T even exist in prod,
so leaking its presence is pointless. ``admin`` role or higher is
required.

Response (``application/json``)::

    {
      "env": "development",
      "db_name": "Pool_&_Landscaping_of_Vistancia",
      "connected_mongo_host": "localhost:27017",
      "preview_synthetic_salt_configured": true,
      "preview_tenant_whitelist_size": 1,
      "registry": {
        "declared_pii_routes": 41,
        "status": "GREEN" | "AMBER" | "RED",
        "missing_registered_routes": [...],
        "unregistered_pii_shaped_routes": [...]
      },
      "pii_shape_audit": {
        "customers_total": 720,
        "customers_matching_preview_pattern": 720,
        "customers_with_real_pii_shape": 0,
        "status": "GREEN" | "RED"
      },
      "last_boot_scrub": {
        "at": "2026-10-11T...",
        "actor": "system:preview_boot_scrubber",
        "total_rows_scrubbed": 120,
        "counts": {"customers": 120, ...}
      } | null,
      "generated_at": "<iso>"
    }

Status is RED when ``pii_shape_audit.customers_with_real_pii_shape
> 0`` or when ``registry.status == "RED"``. The admin dashboard
reads this endpoint and shows a persistent banner on preview when
RED.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from config import db
from utils import require_admin
from services.preview_isolation import (
    is_production_env,
    PREVIEW_SYNTHETIC_SALT,
    PREVIEW_TENANT_WHITELIST,
    audit_route_registry,
)

router = APIRouter()

# Match the preview namespace shape — same regex as scrubber.
_PREVIEW_NAME_RE = re.compile(
    r"^Preview (Customer|Lead|Subscriber|Co )\s*\d{4}", re.IGNORECASE,
)


def _mongo_host() -> str:
    url = os.environ.get("MONGO_URL", "")
    # ``mongodb://localhost:27017`` → ``localhost:27017``.
    return url.split("://", 1)[-1].split("/", 1)[0] if url else ""


@router.get("/admin/preview-isolation-status")
async def preview_isolation_status(user: dict = Depends(require_admin)):
    # Production: 404 — endpoint does not exist here.
    if is_production_env():
        raise HTTPException(status_code=404, detail="not_found")

    # ── registry audit ──────────────────────────────────
    # Deferred import so the endpoint stays decoupled from app module
    # import order.
    from server import app as _app
    registry_report = audit_route_registry(_app)

    # ── pii shape audit ─────────────────────────────────
    try:
        total = await db.customers.count_documents({})
    except Exception:
        total = 0
    try:
        synthetic = await db.customers.count_documents({
            "name": {"$regex": r"^Preview Customer\s*\d{4}", "$options": "i"}
        })
    except Exception:
        synthetic = 0
    real_shape = max(total - synthetic, 0)
    pii_status = "GREEN" if real_shape == 0 else "RED"

    # ── last boot scrub ─────────────────────────────────
    last_scrub = None
    try:
        row = await db.audit_logs.find_one(
            {"event": {"$in": ["pii_boot_scrub", "pii_scrub"]}},
            sort=[("at", -1)],
            projection={"_id": 0, "at": 1, "actor": 1, "meta": 1},
        )
        if row:
            meta = row.get("meta") or {}
            last_scrub = {
                "at": row.get("at"),
                "actor": row.get("actor"),
                "total_rows_scrubbed": meta.get("total")
                    or sum((meta.get("scrubbed_counts") or {}).values()),
                "counts": meta.get("scrubbed_counts") or {},
            }
    except Exception:
        last_scrub = None

    overall = "GREEN"
    if pii_status == "RED" or registry_report["status"] == "RED":
        overall = "RED"
    elif registry_report["status"] == "AMBER":
        overall = "AMBER"

    return {
        "env": (os.environ.get("APP_ENV", "preview") or "preview").lower(),
        "db_name": os.environ.get("DB_NAME", ""),
        "connected_mongo_host": _mongo_host(),
        "preview_synthetic_salt_configured": bool(PREVIEW_SYNTHETIC_SALT),
        "preview_tenant_whitelist_size": len(PREVIEW_TENANT_WHITELIST),
        "registry": {
            "declared_pii_routes": registry_report["declared_pii_routes"],
            "total_routes": registry_report["total_routes"],
            "status": registry_report["status"],
            "missing_registered_routes": [
                f"{m} {p}" for m, p in registry_report["missing_registered_routes"]
            ],
            "unregistered_pii_shaped_routes": [
                f"{m} {p}" for m, p in registry_report["unregistered_pii_shaped_routes"]
            ][:20],
        },
        "pii_shape_audit": {
            "customers_total": total,
            "customers_matching_preview_pattern": synthetic,
            "customers_with_real_pii_shape": real_shape,
            "status": pii_status,
        },
        "last_boot_scrub": last_scrub,
        "overall_status": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
