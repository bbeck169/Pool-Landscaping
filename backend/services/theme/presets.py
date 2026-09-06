"""Phase I1.5.a — Static in-code registry of tenant theme presets.

31 entries (default + 30 verticals). Structured so I1 (industry
profile) can later import + auto-apply a preset on industry
selection without a refactor — see ``get_preset()``.

**Contract (matches ``services/theme/validate.py``):** each preset
is a fully-expanded ``TenantTheme`` dict with ``menu``, ``rail``,
``tiles``, ``buttons``, ``accents`` sections and a top-level
``preset`` key that echoes the registry key.

All presets in this file are constructed via ``_p()`` with dark
brand shades (Tailwind ``-700`` / ``-800`` / ``-900``) so the paired
WCAG AA (≥ 4.5:1) contrast checks in the validator pass out-of-the-
box. If you add or edit a preset, run
``pytest backend/tests/test_i15a_tenant_theme_endpoint.py -k presets_all_pass_aa``
to lock the contract.

Rationale for a static in-code registry (vs. DB seed) at this
sub-phase: preset defaults ship with the app version and never
diverge across tenants; DB seeds would break the "no auto-write on
GET" backwards-compat rule. I1.5.d migration will move any
tenant-persisted overrides into ``tenant.theme`` — presets remain
in-code as the source-of-truth defaults.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


def _s(hex_: str) -> Dict[str, Any]:
    """Solid slot builder."""
    return {"mode": "solid", "solid": hex_.lower()}


def _p(
    *,
    menu_bg: str,
    button_bg: str,
    accent_primary: str,
    accent_secondary: str,
    accent_link: str,
    accent_focus: str,
    accent_badge_bg: str = "#f1f5f9",
    accent_badge_text: str = "#0f172a",
    rail_bg: str | None = None,
    tile_bg: str = "#ffffff",
    tile_text: str = "#0f172a",
    tile_border: str = "#e5e7eb",
    menu_text: str = "#ffffff",
    rail_text: str = "#ffffff",
    button_text: str = "#ffffff",
    accent_text: str = "#0f172a",
) -> Dict[str, Any]:
    """Build a fully-expanded solid-only preset.

    ``rail_bg`` defaults to ``menu_bg`` (single dark surface across
    the shell — matches the existing Pool & Landscaping look).
    """
    if rail_bg is None:
        rail_bg = menu_bg
    return {
        "preset": "",  # filled in below
        "menu": {"bg": _s(menu_bg), "text": _s(menu_text)},
        "rail": {"bg": _s(rail_bg), "text": _s(rail_text)},
        "tiles": {
            "bg": _s(tile_bg),
            "text": _s(tile_text),
            "border": _s(tile_border),
        },
        "buttons": {"bg": _s(button_bg), "text": _s(button_text)},
        "accents": {
            "primary": _s(accent_primary),
            "secondary": _s(accent_secondary),
            "text": _s(accent_text),
            "link": _s(accent_link),
            "focus_ring": _s(accent_focus),
            "badge_bg": _s(accent_badge_bg),
            "badge_text": _s(accent_badge_text),
        },
    }


# ── Registry ─────────────────────────────────────────────────────
_RAW: Dict[str, Dict[str, Any]] = {
    # Default = combined pool_landscape (existing look — navy shell +
    # green brand accent). Any existing tenant with no theme reads
    # this from GET without an auto-write.
    "default": _p(
        menu_bg="#0f172a", button_bg="#166534",
        accent_primary="#166534", accent_secondary="#0f172a",
        accent_link="#0f172a", accent_focus="#166534",
        accent_badge_bg="#dcfce7", accent_badge_text="#14532d",
    ),
    "pool_landscape": _p(
        menu_bg="#0f172a", button_bg="#166534",
        accent_primary="#166534", accent_secondary="#0f172a",
        accent_link="#0f172a", accent_focus="#166534",
        accent_badge_bg="#dcfce7", accent_badge_text="#14532d",
    ),
    "pool": _p(
        menu_bg="#155e75", button_bg="#0e7490",
        accent_primary="#0e7490", accent_secondary="#155e75",
        accent_link="#155e75", accent_focus="#0e7490",
        accent_badge_bg="#cffafe", accent_badge_text="#164e63",
    ),
    "landscape": _p(
        menu_bg="#14532d", button_bg="#166534",
        accent_primary="#166534", accent_secondary="#14532d",
        accent_link="#166534", accent_focus="#365314",
        accent_badge_bg="#dcfce7", accent_badge_text="#14532d",
    ),
    "hvac": _p(
        menu_bg="#1e40af", button_bg="#c2410c",
        accent_primary="#c2410c", accent_secondary="#1e40af",
        accent_link="#1e40af", accent_focus="#c2410c",
        accent_badge_bg="#ffedd5", accent_badge_text="#7c2d12",
    ),
    "plumbing": _p(
        menu_bg="#1e3a8a", button_bg="#1d4ed8",
        accent_primary="#1d4ed8", accent_secondary="#1e3a8a",
        accent_link="#1e40af", accent_focus="#1d4ed8",
        accent_badge_bg="#dbeafe", accent_badge_text="#1e3a8a",
    ),
    "electrical": _p(
        menu_bg="#18181b", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#18181b",
        accent_link="#713f12", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "roofing": _p(
        menu_bg="#334155", button_bg="#b91c1c",
        accent_primary="#b91c1c", accent_secondary="#334155",
        accent_link="#991b1b", accent_focus="#b91c1c",
        accent_badge_bg="#fee2e2", accent_badge_text="#991b1b",
    ),
    "solar": _p(
        menu_bg="#075985", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#075985",
        accent_link="#075985", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "cleaning": _p(
        menu_bg="#0369a1", button_bg="#0369a1",
        accent_primary="#0369a1", accent_secondary="#075985",
        accent_link="#075985", accent_focus="#0369a1",
        accent_badge_bg="#e0f2fe", accent_badge_text="#0c4a6e",
    ),
    "pest_control": _p(
        menu_bg="#365314", button_bg="#4d7c0f",
        accent_primary="#4d7c0f", accent_secondary="#365314",
        accent_link="#365314", accent_focus="#4d7c0f",
        accent_badge_bg="#ecfccb", accent_badge_text="#365314",
    ),
    "moving": _p(
        menu_bg="#78350f", button_bg="#c2410c",
        accent_primary="#c2410c", accent_secondary="#78350f",
        accent_link="#78350f", accent_focus="#c2410c",
        accent_badge_bg="#ffedd5", accent_badge_text="#7c2d12",
    ),
    "painting": _p(
        menu_bg="#6b21a8", button_bg="#7e22ce",
        accent_primary="#7e22ce", accent_secondary="#6b21a8",
        accent_link="#6b21a8", accent_focus="#7e22ce",
        accent_badge_bg="#f3e8ff", accent_badge_text="#581c87",
    ),
    "flooring": _p(
        menu_bg="#44403c", button_bg="#78350f",
        accent_primary="#78350f", accent_secondary="#44403c",
        accent_link="#78350f", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "drywall": _p(
        menu_bg="#3f3f46", button_bg="#52525b",
        accent_primary="#52525b", accent_secondary="#3f3f46",
        accent_link="#3f3f46", accent_focus="#52525b",
        accent_badge_bg="#f4f4f5", accent_badge_text="#27272a",
    ),
    "handyman": _p(
        menu_bg="#7f1d1d", button_bg="#b91c1c",
        accent_primary="#b91c1c", accent_secondary="#7f1d1d",
        accent_link="#991b1b", accent_focus="#b91c1c",
        accent_badge_bg="#fee2e2", accent_badge_text="#7f1d1d",
    ),
    "fencing": _p(
        menu_bg="#57534e", button_bg="#78350f",
        accent_primary="#78350f", accent_secondary="#57534e",
        accent_link="#78350f", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "appliance_repair": _p(
        menu_bg="#1e293b", button_bg="#b91c1c",
        accent_primary="#b91c1c", accent_secondary="#1e293b",
        accent_link="#1e293b", accent_focus="#b91c1c",
        accent_badge_bg="#fee2e2", accent_badge_text="#7f1d1d",
    ),
    "garage_door": _p(
        menu_bg="#7f1d1d", button_bg="#334155",
        accent_primary="#334155", accent_secondary="#7f1d1d",
        accent_link="#7f1d1d", accent_focus="#334155",
        accent_badge_bg="#fee2e2", accent_badge_text="#7f1d1d",
    ),
    "auto_detail": _p(
        menu_bg="#18181b", button_bg="#3f3f46",
        accent_primary="#3f3f46", accent_secondary="#18181b",
        accent_link="#18181b", accent_focus="#3f3f46",
        accent_badge_bg="#f4f4f5", accent_badge_text="#18181b",
    ),
    "junk_removal": _p(
        menu_bg="#18181b", button_bg="#c2410c",
        accent_primary="#c2410c", accent_secondary="#18181b",
        accent_link="#7c2d12", accent_focus="#c2410c",
        accent_badge_bg="#ffedd5", accent_badge_text="#7c2d12",
    ),
    "snow_removal": _p(
        menu_bg="#075985", button_bg="#0369a1",
        accent_primary="#0369a1", accent_secondary="#075985",
        accent_link="#075985", accent_focus="#0369a1",
        accent_badge_bg="#e0f2fe", accent_badge_text="#0c4a6e",
    ),
    "notary": _p(
        menu_bg="#7f1d1d", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#7f1d1d",
        accent_link="#7f1d1d", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "photography": _p(
        menu_bg="#18181b", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#18181b",
        accent_link="#713f12", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "salon": _p(
        menu_bg="#9d174d", button_bg="#be185d",
        accent_primary="#be185d", accent_secondary="#9d174d",
        accent_link="#9d174d", accent_focus="#be185d",
        accent_badge_bg="#fce7f3", accent_badge_text="#831843",
    ),
    "spa": _p(
        menu_bg="#134e4a", button_bg="#0f766e",
        accent_primary="#0f766e", accent_secondary="#134e4a",
        accent_link="#115e59", accent_focus="#0f766e",
        accent_badge_bg="#ccfbf1", accent_badge_text="#134e4a",
    ),
    "dental": _p(
        menu_bg="#155e75", button_bg="#0e7490",
        accent_primary="#0e7490", accent_secondary="#155e75",
        accent_link="#155e75", accent_focus="#0e7490",
        accent_badge_bg="#cffafe", accent_badge_text="#164e63",
    ),
    "medical": _p(
        menu_bg="#1e3a8a", button_bg="#1d4ed8",
        accent_primary="#1d4ed8", accent_secondary="#1e3a8a",
        accent_link="#1e40af", accent_focus="#1d4ed8",
        accent_badge_bg="#dbeafe", accent_badge_text="#1e3a8a",
    ),
    "legal": _p(
        menu_bg="#14532d", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#14532d",
        accent_link="#14532d", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "real_estate": _p(
        menu_bg="#0f172a", button_bg="#a16207",
        accent_primary="#a16207", accent_secondary="#0f172a",
        accent_link="#0f172a", accent_focus="#a16207",
        accent_badge_bg="#fef3c7", accent_badge_text="#713f12",
    ),
    "fitness": _p(
        menu_bg="#18181b", button_bg="#b91c1c",
        accent_primary="#b91c1c", accent_secondary="#18181b",
        accent_link="#991b1b", accent_focus="#b91c1c",
        accent_badge_bg="#fee2e2", accent_badge_text="#7f1d1d",
    ),
}


# Stamp each preset with its key so consumers can round-trip
# ``get_preset(k)["preset"] == k`` without an extra lookup.
for _k, _v in _RAW.items():
    _v["preset"] = _k


# Public API ──────────────────────────────────────────────────────
PRESETS: Dict[str, Dict[str, Any]] = _RAW


def get_preset(key: str) -> Dict[str, Any]:
    """Return a **deep copy** of the preset for ``key``.

    Deep copy prevents downstream mutation from leaking back into
    the module-level registry (e.g. an admin PATCH that starts from
    a preset and tweaks a slot must not corrupt the source).

    Falls back to the ``default`` preset when ``key`` is unknown so
    callers never see a KeyError — the router validates keys before
    calling this for ``apply-preset``.
    """
    return deepcopy(_RAW.get(key) or _RAW["default"])


def list_presets() -> List[Dict[str, Any]]:
    """Return the registry as a JSON-serializable list, one entry
    per preset. Each entry is ``{key, name, theme}`` where ``name``
    is a title-cased human label derived from the key
    (e.g. ``"pool_landscape"`` → ``"Pool Landscape"``).
    """
    out: List[Dict[str, Any]] = []
    for key, theme in _RAW.items():
        out.append({
            "key": key,
            "name": key.replace("_", " ").title(),
            "theme": deepcopy(theme),
        })
    return out
