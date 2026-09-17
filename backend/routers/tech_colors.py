"""Feb-2026 · Live-Tech-Map · Phase 1 — palette read endpoint.

Exposes the approved palette so the Settings UI (and anyone else who
needs to render a color picker) doesn't have to hard-code the
palette on the client.

* ``GET /api/tech-colors/palette`` — admin-authed, returns
  ``{"palette": [{"name": ..., "hex": ...}, ...]}``. No tenant
  scoping — the palette is global, not per-tenant.

Feb-2026 · Preset Palette Contrast Reconciliation
--------------------------------------------------
The response is filtered through :func:`services.color.
validate_color_hex_for_pin` so hexes that would fail the map-pin
contrast guard (< 3.0 WCAG vs white) are silently dropped BEFORE
they reach the client. Legacy users seeded with those colors keep
their raw values on the row (backward-compat reads); the migration
in ``services.migrations.legacy_low_contrast_color_migration``
moves those users off the blocked hexes.

The raw ``TECH_COLOR_PALETTE`` constant is NOT mutated — the
filter runs at the API edge so historical hash-slot assignments
stay byte-identical (deterministic ``palette[hash % len(PALETTE)]``
callers still hit the same slot).
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from fastapi import APIRouter, Depends

from constants.tech_colors import TECH_COLOR_PALETTE
from services.color import contrast_ratio_vs_white
from utils import get_current_user


router = APIRouter()
log = logging.getLogger("tech_colors")


_MIN_CONTRAST = 3.0


def _filtered_palette() -> List[Tuple[str, str]]:
    """Drop palette entries that fail the pin contrast guard."""
    out: List[Tuple[str, str]] = []
    for name, hex_ in TECH_COLOR_PALETTE:
        try:
            ratio = contrast_ratio_vs_white(hex_)
        except Exception:  # noqa: BLE001 — malformed entries are dropped too
            continue
        if ratio >= _MIN_CONTRAST:
            out.append((name, hex_))
    return out


# Compute once at import time so the startup log reflects the delta
# ops needs to eyeball. The reference is cached — ``get_palette`` reads
# from it on every request.
_FILTERED = _filtered_palette()
_DROPPED_COUNT = len(TECH_COLOR_PALETTE) - len(_FILTERED)
log.info(
    "[tech_colors.palette.startup] total=%d passing=%d dropped=%d",
    len(TECH_COLOR_PALETTE), len(_FILTERED), _DROPPED_COUNT,
)


@router.get("/tech-colors/palette",
             operation_id="techColors.palette.get",
             tags=["tech-colors"])
async def get_palette(user: dict = Depends(get_current_user)):
    """Return the approved palette filtered to WCAG-passing hexes only."""
    return {
        "palette": [
            {"name": name, "hex": hex_} for (name, hex_) in _FILTERED
        ],
    }
