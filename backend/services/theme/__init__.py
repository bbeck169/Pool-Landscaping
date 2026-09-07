"""Phase I1.5.a — Tenant theme service package.

Exports:
  * ``presets`` — static in-code registry of ~31 industry presets.
  * ``validate`` — structural + solid-only + WCAG AA guard for
    ``PUT /api/tenants/me/theme``.
  * ``contrast`` — relative-luminance + ratio helpers used by the
    validator (kept isolated so I1.5.b can reuse them in the
    frontend preview via an /api round-trip if needed).

Backwards compat: existing tenants without a ``theme`` field render
identically because the router falls back to
``presets.get_preset("default")`` on GET without auto-writing.
"""
from .presets import PRESETS, get_preset, list_presets  # noqa: F401
from .validate import (  # noqa: F401
    validate_theme_payload,
    preview_theme_payload,
    ThemeValidationError,
    expand_default,
)
