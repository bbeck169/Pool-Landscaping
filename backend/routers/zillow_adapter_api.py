"""Task TT · Feb 2026 — HTTP surface for the RapidAPI-Zillow adapter.

Thin wrapper — every endpoint returns the adapter's native shape::

    {"unavailable": False, "data": {...}, "cached": bool}
    {"unavailable": True,  "reason": "<code>"}

The frontend renders a graceful ``property-map-unavailable`` banner
when ``unavailable === true``. HTTP status is always ``200`` even on
graceful degradation so the frontend fetch layer doesn't fire its
generic error path.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from services.property_data import ZillowClient
from utils import get_current_user

router = APIRouter(prefix="/zillow-adapter", tags=["zillow-adapter"])


class SearchIn(BaseModel):
    address: str


@router.get("/search-by-address")
async def search_by_address(
    address: str = Query(..., min_length=3),
    user: dict = Depends(get_current_user),
):
    tenant_id = (user or {}).get("tenant_id")
    return await ZillowClient().search_by_address(address, tenant_id=tenant_id)


@router.get("/property/{zpid}")
async def property_detail(
    zpid: str,
    user: dict = Depends(get_current_user),
):
    tenant_id = (user or {}).get("tenant_id")
    return await ZillowClient().property_detail(zpid, tenant_id=tenant_id)


@router.get("/zestimate/{zpid}")
async def zestimate(
    zpid: str,
    user: dict = Depends(get_current_user),
):
    tenant_id = (user or {}).get("tenant_id")
    return await ZillowClient().zestimate(zpid, tenant_id=tenant_id)
