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
    # ─── Feb-2026 · Palette expansion (Ticket B) ──────────────────
    # 12 professional/desaturated colors appended AFTER the original
    # 12 so existing tenants' deterministic ``palette[hash % 12]``
    # assignments stay byte-identical. Anything that depended on
    # ``len(PALETTE_HEXES) == 12`` must be re-anchored to
    # ``len(PALETTE_HEXES)`` (see ``frontend/hooks/useTechColorsPalette``
    # for the cap that got raised).
    ("slate_amber",     "#B45309"),
    ("deep_teal",       "#0F766E"),
    ("royal_magenta",   "#A21CAF"),
    ("olive",           "#3F6212"),
    ("indigo_violet",   "#6D28D9"),
    ("brick_red",       "#B91C1C"),
    ("ocean_blue",      "#0369A1"),
    ("forest_green",    "#4D7C0F"),
    ("ruby_rose",       "#9F1239"),
    ("midnight_blue",   "#1E3A8A"),
    ("chestnut",        "#78350F"),
    ("moss",            "#365314"),
    # ─── Feb-2026 · CREWS-FIX 2b (slot 25) ───────────────────────
    # Sky-600 — matches brand accent used across emails + widget
    # so crews pinned to the brand color aren't rejected by the
    # palette-lock guard. Contrast vs white ≈ 4.10 (passes 3.0).
    ("sky",             "#0284C7"),
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
