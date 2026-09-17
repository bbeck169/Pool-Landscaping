"""Feb-2026 · Ticket B · Palette length + first-12 byte-identical guard."""
from __future__ import annotations

from constants.tech_colors import PALETTE_HEXES, TECH_COLOR_PALETTE


# The pre-expansion 12 colors, pinned here as an inline literal so
# any accidental reorder in ``tech_colors.py`` trips this test
# instead of silently re-keying every tenant's tech colors.
_ORIGINAL_TWELVE = [
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


def test_palette_has_at_least_24_entries():
    assert len(TECH_COLOR_PALETTE) >= 24
    assert len(PALETTE_HEXES) == len(TECH_COLOR_PALETTE)


def test_original_twelve_indices_unchanged():
    for idx, (name, hex_) in enumerate(_ORIGINAL_TWELVE):
        assert TECH_COLOR_PALETTE[idx] == (name, hex_), (
            f"Palette index {idx} drifted from ({name!r}, {hex_!r}) "
            f"— re-keying tenants! Do not reorder."
        )


def test_appended_twelve_all_hex_unique():
    """Ensure the 12 new appended colors are unique among each other
    and unique against the original 12 (no accidental duplicate)."""
    hexes = [h.upper() for h in PALETTE_HEXES]
    assert len(set(hexes)) == len(hexes), "Duplicate hex in palette"


def test_appended_entries_are_valid_hex():
    for name, hex_ in TECH_COLOR_PALETTE[12:]:
        assert isinstance(name, str) and name, "Missing name"
        assert isinstance(hex_, str) and hex_.startswith("#")
        # 7 chars = "#" + 6 hex digits.
        assert len(hex_) == 7, f"Bad hex format: {hex_!r}"
        int(hex_[1:], 16)  # raises if non-hex
