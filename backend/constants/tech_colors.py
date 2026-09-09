"""Feb-2026 · Live-Tech-Map · Phase 1 — 12-color palette + hash helper.

User-approved (Q2) Feb-2026 palette: Tailwind 500-tier, colorblind-
friendly. This is the single source of truth for BOTH:

* ``display_color_hex`` slot assignment on ``db.users`` (technicians)
* ``color`` slot assignment on ``db.crews``

The palette is intentionally short (12 colors) — beyond that, hue
similarity makes tech-vs-tech readability collapse on the dispatch
map. If ops needs a 13+ tech tenant we add a "shade" tier per hue
rather than growing the base palette.

The frontend mirror lives at
``/app/frontend/src/lib/techColorsPalette.js`` — the two must stay
in lockstep.  When editing this file, edit that file in the same PR.
"""
from __future__ import annotations

import hashlib
from typing import Final, List, Optional, Tuple

# ── Palette ────────────────────────────────────────────────────────
# Tailwind 500-tier hexes. Order matters — deterministic hash
# assignment reads palette[hash % len(PALETTE)] so re-ordering
# would re-key every existing tech that was auto-filled.
TECH_COLOR_PALETTE: Final[List[Tuple[str, str]]] = [
    ("blue",    "#3B82F6"),
    ("red",     "#EF4444"),
    ("emerald", "#10B981"),
    ("amber",   "#F59E0B"),
    ("violet",  "#8B5CF6"),
    ("pink",    "#EC4899"),
    ("teal",    "#14B8A6"),
    ("orange",  "#F97316"),
    ("indigo",  "#6366F1"),
    ("lime",    "#84CC16"),
    ("cyan",    "#06B6D4"),
    ("fuchsia", "#D946EF"),
]

PALETTE_HEXES: Final[List[str]] = [hex_ for (_, hex_) in TECH_COLOR_PALETTE]
PALETTE_HEX_SET: Final[frozenset[str]] = frozenset(h.upper() for h in PALETTE_HEXES)


def is_palette_color(hex_str: Optional[str]) -> bool:
    """Return True when ``hex_str`` is one of the 12 approved palette colors.

    Case-insensitive on the hex digits. Rejects None, empty string,
    and any RGB not in the palette. Used by PATCH endpoints to gate
    writes so custom off-palette colors can't sneak back in after
    the palette lock landed.
    """
    if not hex_str or not isinstance(hex_str, str):
        return False
    return hex_str.upper() in PALETTE_HEX_SET


def deterministic_color_for_id(seed: str) -> str:
    """SHA-256-based deterministic assignment: ``palette[hash % 12]``.

    Chosen over Python's built-in ``hash()`` because the latter is
    salted per-process on modern CPython — two workers would assign
    different colors to the same seed. SHA-256 is stable across
    processes, machines, and re-boots, which is what the migration
    contract needs.

    Contract:
      * Same ``seed`` → same color, forever.
      * Different seeds → uniformly distributed across the 12 slots.

    Used by:
      * ``services/tech_color_migration.py`` null-fill migration.
      * Any tool that needs a stable fallback color for a tech row.
    """
    if not seed or not isinstance(seed, str):
        # Deterministic fallback for empty/missing seed — always
        # returns palette[0]. Callers shouldn't reach this in
        # practice (they should skip the row instead) but the guard
        # keeps ``hash()`` from raising on ``None``.
        return PALETTE_HEXES[0]
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # First 4 bytes → 32-bit uint → modulo palette length.
    idx = int.from_bytes(digest[:4], "big") % len(PALETTE_HEXES)
    return PALETTE_HEXES[idx]


__all__ = [
    "TECH_COLOR_PALETTE",
    "PALETTE_HEXES",
    "PALETTE_HEX_SET",
    "is_palette_color",
    "deterministic_color_for_id",
]
