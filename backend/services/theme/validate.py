"""Phase I1.5.a — Structural + WCAG AA guard for tenant theme
payloads sent to ``PUT /api/tenants/me/theme``.

Contract (locked here, mirrored in
``tests/test_i15a_tenant_theme_endpoint.py``):

* Sections: ``menu``, ``rail``, ``tiles``, ``buttons``, ``accents``.
* Every slot is ``{ mode: 'solid'|'gradient', solid?: '#RRGGBB',
  gradient?: { from: '#RRGGBB', to: '#RRGGBB', angle: 0..360 } }``.
* **Solid-only slots** (small-element / text): ``menu.text``,
  ``rail.text``, ``tiles.text``, ``tiles.border``,
  ``buttons.text``, ``accents.text``, ``accents.link``,
  ``accents.focus_ring``, ``accents.badge_text``.
  Gradient in any of these → 400.
* **Gradient-eligible slots** (fills): ``menu.bg``, ``rail.bg``,
  ``tiles.bg``, ``buttons.bg``, ``accents.primary``,
  ``accents.secondary``, ``accents.badge_bg``.
* **WCAG AA (≥ 4.5:1) contrast** enforced on these text-vs-fill
  pairs when *both* sides are solid (gradient sides are skipped —
  auto-validating a two-stop gradient is out of scope for MVP; the
  frontend surfaces a warning in I1.5.b):

    - menu.text vs menu.bg
    - rail.text vs rail.bg
    - tiles.text vs tiles.bg
    - buttons.text vs buttons.bg
    - accents.link vs DEFAULT_LINK_CANVAS (#ffffff)
    - accents.badge_text vs accents.badge_bg

* Non-paired solid slots (e.g. ``tiles.border``,
  ``accents.focus_ring``) are format-validated but not contrast-
  checked (a11y guidance is ≥3:1 for non-text, low priority for MVP).

* Unknown top-level sections or slots are rejected so we don't
  quietly persist typos.

* ``preset: str`` is optional at the payload root and defaults to
  ``"custom"`` when the caller omits it (any string is accepted —
  the ``apply-preset`` endpoint is the authoritative writer of a
  known preset key).
"""
from __future__ import annotations

import re
from typing import Any, Dict

from .contrast import contrast_ratio


# ── Slot topology ─────────────────────────────────────────────────
SECTIONS: Dict[str, Dict[str, str]] = {
    # slot_name -> "gradient" | "solid"
    "menu": {"bg": "gradient", "text": "solid"},
    "rail": {"bg": "gradient", "text": "solid"},
    "tiles": {"bg": "gradient", "text": "solid", "border": "solid"},
    "buttons": {"bg": "gradient", "text": "solid"},
    "accents": {
        "primary": "gradient",
        "secondary": "gradient",
        "text": "solid",
        "link": "solid",
        "focus_ring": "solid",
        "badge_bg": "gradient",
        "badge_text": "solid",
    },
}

# (fg_path, bg_path_or_literal). Literal starts with ``#``.
CONTRAST_PAIRS: list[tuple[tuple[str, str], str]] = [
    (("menu", "text"), "menu.bg"),
    (("rail", "text"), "rail.bg"),
    (("tiles", "text"), "tiles.bg"),
    (("buttons", "text"), "buttons.bg"),
    (("accents", "link"), "#ffffff"),
    (("accents", "badge_text"), "accents.badge_bg"),
]

DEFAULT_LINK_CANVAS = "#ffffff"
AA_MIN_RATIO = 4.5

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeValidationError(ValueError):
    """Raised by ``validate_theme_payload`` on any contract violation.

    Router lifts this into an HTTP 400 with the ``.message`` body.
    """

    def __init__(self, code: str, message: str, path: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def as_detail(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path:
            d["path"] = self.path
        return d


# ── Format helpers ────────────────────────────────────────────────
def _validate_hex(color: Any, path: str) -> str:
    if not isinstance(color, str) or not _HEX_RE.match(color):
        raise ThemeValidationError(
            "INVALID_HEX",
            f"Expected '#RRGGBB' at {path}, got {color!r}.",
            path=path,
        )
    return color.lower()


def _validate_slot(slot: Any, allow_gradient: bool, path: str) -> Dict[str, Any]:
    if not isinstance(slot, dict):
        raise ThemeValidationError(
            "INVALID_SLOT",
            f"Slot at {path} must be an object.",
            path=path,
        )
    mode = slot.get("mode")
    if mode not in ("solid", "gradient"):
        raise ThemeValidationError(
            "INVALID_MODE",
            f"Slot at {path} must have mode='solid' or 'gradient'.",
            path=path,
        )
    if mode == "gradient" and not allow_gradient:
        raise ThemeValidationError(
            "GRADIENT_NOT_ALLOWED",
            f"Text / small-element slot at {path} must be solid — "
            "gradients aren't supported here for legibility.",
            path=path,
        )
    if mode == "solid":
        return {"mode": "solid", "solid": _validate_hex(slot.get("solid"), f"{path}.solid")}
    # gradient
    g = slot.get("gradient")
    if not isinstance(g, dict):
        raise ThemeValidationError(
            "INVALID_GRADIENT",
            f"gradient object required at {path}.gradient.",
            path=f"{path}.gradient",
        )
    frm = _validate_hex(g.get("from"), f"{path}.gradient.from")
    to = _validate_hex(g.get("to"), f"{path}.gradient.to")
    angle = g.get("angle")
    if not isinstance(angle, (int, float)) or not (0 <= float(angle) <= 360):
        raise ThemeValidationError(
            "INVALID_ANGLE",
            f"gradient.angle at {path} must be a number in [0, 360].",
            path=f"{path}.gradient.angle",
        )
    return {"mode": "gradient", "gradient": {"from": frm, "to": to, "angle": float(angle)}}


def _validate_section(name: str, section: Any) -> Dict[str, Any]:
    if not isinstance(section, dict):
        raise ThemeValidationError(
            "INVALID_SECTION",
            f"Section '{name}' must be an object.",
            path=name,
        )
    slot_spec = SECTIONS[name]
    unknown = set(section) - set(slot_spec)
    if unknown:
        raise ThemeValidationError(
            "UNKNOWN_SLOT",
            f"Unknown slot(s) in '{name}': {sorted(unknown)}.",
            path=name,
        )
    out: Dict[str, Any] = {}
    for slot_name, kind in slot_spec.items():
        if slot_name not in section:
            raise ThemeValidationError(
                "MISSING_SLOT",
                f"Missing slot '{slot_name}' in section '{name}'.",
                path=f"{name}.{slot_name}",
            )
        allow_gradient = (kind == "gradient")
        out[slot_name] = _validate_slot(section[slot_name], allow_gradient,
                                          f"{name}.{slot_name}")
    return out


# ── Contrast enforcement ─────────────────────────────────────────
def _resolve_solid(node: Dict[str, Any], path_parts: tuple[str, ...]) -> str | None:
    cur: Any = node
    for p in path_parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    if not isinstance(cur, dict):
        return None
    if cur.get("mode") != "solid":
        return None
    return cur.get("solid")


def _enforce_contrast(theme: Dict[str, Any]) -> None:
    for fg_path, bg_ref in CONTRAST_PAIRS:
        fg = _resolve_solid(theme, fg_path)
        if fg is None:
            # fg slots are solid-only so this only trips when the slot
            # itself is malformed, which prior structural validation
            # would already have caught. Skip defensively.
            continue
        if bg_ref.startswith("#"):
            bg = bg_ref
        else:
            bg_path = tuple(bg_ref.split("."))
            bg = _resolve_solid(theme, bg_path)
            if bg is None:
                # Paired bg is a gradient — MVP skips gradient contrast
                # (frontend surfaces a soft warning in I1.5.b).
                continue
        ratio = contrast_ratio(fg, bg)
        if ratio < AA_MIN_RATIO:
            fg_label = ".".join(fg_path)
            bg_label = bg_ref if bg_ref.startswith("#") else bg_ref
            raise ThemeValidationError(
                "CONTRAST_FAIL",
                f"Low contrast ({ratio:.2f}:1) between {fg_label} ({fg}) "
                f"and {bg_label} ({bg}). WCAG AA requires ≥ {AA_MIN_RATIO}:1 "
                "for body text. Pick a darker text color or a lighter "
                "background (or vice versa) and try again.",
                path=fg_label,
            )


# ── Public entry point ────────────────────────────────────────────
def validate_theme_payload(payload: Any) -> Dict[str, Any]:
    """Validate + normalize a theme payload for persistence.

    Returns the sanitized theme dict (hex lowercased, angle float,
    unknown keys stripped) on success. Raises
    ``ThemeValidationError`` on any violation — router lifts into
    HTTP 400.
    """
    if not isinstance(payload, dict):
        raise ThemeValidationError(
            "INVALID_PAYLOAD",
            "Theme payload must be a JSON object.",
        )
    # Preset key is free-form (custom preset writes flow through
    # ``apply-preset`` which is authoritative for registry keys).
    preset = payload.get("preset", "custom")
    if not isinstance(preset, str) or not preset:
        raise ThemeValidationError(
            "INVALID_PRESET_KEY",
            "preset must be a non-empty string.",
            path="preset",
        )
    unknown_sections = set(payload) - set(SECTIONS) - {"preset"}
    if unknown_sections:
        raise ThemeValidationError(
            "UNKNOWN_SECTION",
            f"Unknown top-level section(s): {sorted(unknown_sections)}.",
        )
    out: Dict[str, Any] = {"preset": preset}
    for name in SECTIONS:
        if name not in payload:
            raise ThemeValidationError(
                "MISSING_SECTION",
                f"Missing section '{name}' — send all 5 sections "
                "(menu, rail, tiles, buttons, accents).",
                path=name,
            )
        out[name] = _validate_section(name, payload[name])
    _enforce_contrast(out)
    return out


# ── Backwards-compat GET fallback ────────────────────────────────
def expand_default() -> Dict[str, Any]:
    """Return the ``default`` preset expanded — used by
    ``GET /api/tenants/me/theme`` when the tenant has never set a
    theme. **Does not** write to the DB.
    """
    # Late import to avoid a circular dep with the presets module.
    from .presets import get_preset
    return get_preset("default")
