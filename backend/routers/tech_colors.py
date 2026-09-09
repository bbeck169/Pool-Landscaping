"""Feb-2026 · Live-Tech-Map · Phase 1 — palette read endpoint.

Exposes the approved 12-color palette so the Phase 2 Settings UI
(and anyone else who needs to render a color picker) doesn't have
to hard-code the palette on the client.

* ``GET /api/tech-colors/palette`` — admin-authed, returns
  ``{"palette": [{"name": ..., "hex": ...}, ...]}``. No tenant
  scoping — the palette is global, not per-tenant.

RBAC: any authed user (this is a display-only read; the
palette hexes themselves are not sensitive), but we still require
an auth token so we don't expose a public unauth endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from constants.tech_colors import TECH_COLOR_PALETTE
from utils import get_current_user

router = APIRouter()


@router.get("/tech-colors/palette",
             operation_id="techColors.palette.get",
             tags=["tech-colors"])
async def get_palette(user: dict = Depends(get_current_user)):
    """Return the approved 12-color palette used across the
    dispatch board + schedule map."""
    return {
        "palette": [
            {"name": name, "hex": hex_} for (name, hex_) in TECH_COLOR_PALETTE
        ],
    }
