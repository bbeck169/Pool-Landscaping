"""Phase 52 · Zillow (OpenWeb Ninja) healthcheck.

Inspects local env only — does NOT hit OpenWeb Ninja's API from this
route to keep from burning quota on health polls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from utils import require_admin
from config import OPENWEB_NINJA_API_KEY

router = APIRouter(prefix="/zillow", tags=["zillow"])


@router.get("/health")
async def zillow_health(user: dict = Depends(require_admin)):
    return {"configured": bool(OPENWEB_NINJA_API_KEY)}
