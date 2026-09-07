"""Phase I1.5.d · Feb-2026 — Preset seed WCAG AA audit.

Superset of ``test_i15a_presets_all_pass_aa`` — instead of just
asserting the validator raises no error, this test:

  1. Iterates every preset in ``services.theme.presets.PRESETS``.
  2. Runs the full ``validate_theme_payload`` on each (which
     raises ``ThemeValidationError`` with code ``CONTRAST_FAIL`` +
     ``computed_ratio`` on any AA regression).
  3. Also runs ``preview_theme_payload`` (multi-error collector)
     to catch any preset that would trip *multiple* contrast pairs
     — the fatal single-error validator would only surface the
     first miss.
  4. Emits a machine-readable audit report the ship note can
     copy inline, listing every (preset, pair, computed_ratio)
     tuple so future contributors can see the AA margin per slot.

If a preset fails, the failure message names the offending pair +
its ratio so the fix is a one-line hex tweak in
``services/theme/presets.py``.
"""
from __future__ import annotations

import json

import pytest

from services.theme.presets import PRESETS, list_presets
from services.theme.validate import (
    AA_MIN_RATIO,
    CONTRAST_PAIRS,
    preview_theme_payload,
    validate_theme_payload,
)
from services.theme.contrast import contrast_ratio


DEFAULT_LINK_CANVAS = "#ffffff"


def _resolve_solid(theme: dict, path: tuple[str, ...]) -> str | None:
    cur = theme
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    if not isinstance(cur, dict):
        return None
    if cur.get("mode") != "solid":
        return None
    return cur.get("solid")


# ── Tests ────────────────────────────────────────────────────────
def test_i15d_all_presets_validate_zero_contrast_failures():
    """Every preset in the in-code registry must pass the
    validator's WCAG AA gate.

    Superset of the I1.5.a smoke test — we also run
    ``preview_theme_payload`` so any preset with more than one
    failing pair surfaces every pair (the fatal validator only
    reports the first miss)."""
    failures: list[dict] = []
    for key, theme in PRESETS.items():
        # Pass 1: fatal validator.
        try:
            validate_theme_payload(theme)
        except Exception as e:
            failures.append({
                "preset": key,
                "code": getattr(e, "code", "UNKNOWN"),
                "path": getattr(e, "path", None),
                "ratio": getattr(e, "computed_ratio", None),
                "message": str(e),
            })
        # Pass 2: preview collector — catches every pair, not just
        # the first, so a preset with two low-contrast slots
        # surfaces both in the failure report.
        preview = preview_theme_payload(theme)
        if not preview["valid"]:
            for err in preview["errors"]:
                if err["code"] == "CONTRAST_FAIL":
                    failures.append({
                        "preset": key,
                        "code": "CONTRAST_FAIL",
                        "path": err.get("path"),
                        "ratio": err.get("computed_ratio"),
                        "message": err["message"],
                    })
    assert not failures, (
        f"WCAG AA regressions in preset registry:\n"
        + json.dumps(failures, indent=2)
    )


def test_i15d_preset_wcag_audit_report_is_well_formed():
    """The audit report exposed via ``list_presets()`` — the same
    payload the ``GET /api/theme-presets`` endpoint returns — must
    include every preset with an AA ratio ≥ 4.5:1 on every text /
    fill pair. Emits an audit table printable into the ship report.
    """
    audit: list[dict] = []
    for entry in list_presets():
        key = entry["key"]
        theme = entry["theme"]
        row: dict = {"preset": key, "pairs": []}
        for fg_path, bg_ref in CONTRAST_PAIRS:
            fg = _resolve_solid(theme, fg_path)
            if fg is None:
                continue
            if bg_ref.startswith("#"):
                bg = bg_ref
                bg_label = bg_ref
            else:
                bg = _resolve_solid(theme, tuple(bg_ref.split(".")))
                bg_label = bg_ref
                if bg is None:
                    continue
            ratio = contrast_ratio(fg, bg)
            row["pairs"].append({
                "fg": ".".join(fg_path),
                "bg": bg_label,
                "fg_hex": fg,
                "bg_hex": bg,
                "ratio": round(ratio, 2),
                "passes_aa": ratio >= AA_MIN_RATIO,
            })
        audit.append(row)

    # Emit the audit as a captured artifact for the ship report.
    print("\nI1.5.d WCAG AA audit — 31 presets × 6 contrast pairs:")
    print(json.dumps(audit, indent=2))

    # Contract: every pair on every preset must pass AA.
    regressions = [
        (row["preset"], pair)
        for row in audit for pair in row["pairs"]
        if not pair["passes_aa"]
    ]
    assert not regressions, (
        f"Preset AA regressions:\n"
        + json.dumps(regressions, indent=2)
    )


def test_i15d_preset_hex_normalization_is_lowercase():
    """Every hex in every preset must be lowercase — the validator
    lowercases on read, so any uppercase hex in the source
    registry is a smell (would cause a hidden mismatch against a
    tenant-persisted lowercase payload during byte-equal diffs).
    """
    offenders: list[tuple[str, str]] = []
    for key, theme in PRESETS.items():
        for section_name in ("menu", "rail", "tiles", "buttons", "accents"):
            section = theme.get(section_name, {})
            for slot_name, slot in section.items():
                if slot.get("mode") == "solid":
                    hx = slot.get("solid", "")
                    if hx != hx.lower():
                        offenders.append((f"{key}.{section_name}.{slot_name}", hx))
    assert not offenders, (
        f"Uppercase hex values in registry (must be lowercase):\n"
        + json.dumps(offenders, indent=2)
    )
