"""Task QQ · Feb 2026 — DEPRECATED native Lumino webhook receiver.

Lumino does not support native webhooks. This endpoint is retained
only so any external system still pointed at it gets a clear 410
Gone response with a pointer to the Zapier bridge.

Active async ingest path: ``/api/webhooks/lumino/zapier`` (see
``routers/lumino_zapier_bridge.py``).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/webhooks/lumino", operation_id="webhooks.lumino.deprecated")
async def receive_lumino_webhook_deprecated():
    raise HTTPException(
        410,
        "Lumino does not support native webhooks. Route async events "
        "through the Zapier bridge at /api/webhooks/lumino/zapier "
        "(shared-secret header required).",
    )
