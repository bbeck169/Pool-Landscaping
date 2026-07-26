"""Phase 26 · Feb-2026 · Supercool MCP integration router.

Endpoints (all admin/super_admin gated; connect / disconnect / refresh
require super_admin per the phase spec):

* ``GET  /api/integrations/supercool/status``
* ``POST /api/integrations/supercool/connect``
* ``GET  /api/integrations/supercool/callback`` — browser redirect target
* ``POST /api/integrations/supercool/disconnect``
* ``POST /api/integrations/supercool/refresh-catalog``
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from utils import get_current_user
from services import mcp_oauth_client as mcp


router = APIRouter(tags=["Integrations · Supercool"])


def SUPERCOOL_URL() -> str:
    return (os.environ.get("SUPERCOOL_MCP_URL")
            or "https://mcp.supercool.com/mcp").rstrip("/")


def _super_admin_or_403(user: dict) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")


def _admin_or_403(user: dict) -> None:
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


@router.get("/integrations/supercool/status",
             operation_id="integrations.supercool.status")
async def status(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    return await mcp.connection_status(tid, SUPERCOOL_URL())


class ConnectResponse(BaseModel):
    authorize_url: str
    state: str
    redirect_uri: str


@router.post("/integrations/supercool/connect",
              operation_id="integrations.supercool.connect")
async def connect(user: Dict[str, Any] = Depends(get_current_user)):
    _super_admin_or_403(user)
    tid = user.get("tenant_id")
    uid = user.get("id")
    if not tid or not uid:
        raise HTTPException(400, "Missing tenant_id / user_id")
    r = await mcp.build_authorize_url(tid, uid, SUPERCOOL_URL())
    if r.get("error"):
        raise HTTPException(502,
            f"Could not start Supercool OAuth: {r.get('reason') or r.get('error')}")
    return {"authorize_url": r["authorize_url"], "state": r["state"],
            "redirect_uri": mcp.redirect_uri(),
            "discovery_source": r.get("discovery_source")}


@router.get("/integrations/supercool/callback",
             operation_id="integrations.supercool.callback",
             include_in_schema=True)
async def callback(code: Optional[str] = Query(None),
                     state: Optional[str] = Query(None),
                     error: Optional[str] = Query(None),
                     error_description: Optional[str] = Query(None)):
    """Browser lands here after the user authorizes at Supercool.
    Exchanges the code + redirects to the settings page with either
    ``?connected=1`` (success) or ``?error=...`` (failure)."""
    base = mcp.app_base_url()
    settings_url = f"{base}/settings/integrations/supercool"

    if error:
        return RedirectResponse(
            url=f"{settings_url}?error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(
            url=f"{settings_url}?error=missing_code_or_state",
            status_code=302)
    r = await mcp.exchange_code(state=state, code=code)
    if r.get("error"):
        return RedirectResponse(
            url=f"{settings_url}?error={r['error']}", status_code=302)
    return RedirectResponse(
        url=f"{settings_url}?connected=1", status_code=302)


@router.post("/integrations/supercool/disconnect",
              operation_id="integrations.supercool.disconnect")
async def disconnect(user: Dict[str, Any] = Depends(get_current_user)):
    _super_admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    await mcp.revoke_connection(tid, SUPERCOOL_URL())
    return {"ok": True}


@router.post("/integrations/supercool/refresh-catalog",
              operation_id="integrations.supercool.refreshCatalog")
async def refresh_catalog(user: Dict[str, Any] = Depends(get_current_user)):
    _super_admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    server_url = SUPERCOOL_URL()
    token = await mcp.get_valid_access_token(tid, server_url)
    if not token:
        raise HTTPException(400,
            "Not connected — click 'Connect Supercool' first.")
    try:
        tools = await mcp.list_mcp_tools(tid, server_url)
    except RuntimeError as e:
        raise HTTPException(502, f"Supercool refresh failed: {e}")
    catalog = await mcp.cached_catalog(tid, server_url)
    return {
        "ok": True, "tool_count": len(tools),
        "fetched_at": (catalog or {}).get("fetched_at"),
        "tools": tools,
    }


@router.get("/integrations/supercool/catalog",
             operation_id="integrations.supercool.getCatalog")
async def get_catalog(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    c = await mcp.cached_catalog(tid, SUPERCOOL_URL())
    return c or {"tools": [], "fetched_at": None}
