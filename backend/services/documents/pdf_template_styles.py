"""Phase 14B · Feb-2026 — PDF template styles helper.

Loads the active ``form_templates`` doc for a given tenant +
form_type and exposes the per-field styles in a dict keyed by
``field_id``. Primary consumer: the invoice + estimate PDF
renderers (``routers/invoice_viewer.py``,
``routers/estimate_viewer.py``) so admin-driven style edits in the
Phase 7B editor propagate to printed PDFs — specifically unlocking
the ``line_items_table`` header-row background + border colors that
Phase 7A/7C unlocked on the web runtime.

Zero-regression contract: any failure (no template, deleted tenant,
DB blip, malformed doc) returns ``None`` so the caller falls back
to its current hardcoded ReportLab styles. The two PDF renderers
guard every call site with ``if styles:`` and leave the pre-7A
hex literals untouched when the helper returns ``None``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from config import db

logger = logging.getLogger(__name__)


# Keys we expose downstream. Keep the surface small so the PDF
# renderer plumbing stays trivial — only the fields that have
# user-visible effect in ReportLab (background color, text color,
# border color, cell padding).
_SURFACE_KEYS = ("bg_color", "text_color", "border_color",
                  "padding_y", "width_cols")


async def load_pdf_template_styles(
    *, tenant_id: str, form_type: str,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Return a ``{field_id: {bg_color, text_color, ...}}`` dict for
    the current (``is_current=True``) template of the given
    tenant + form_type, or ``None`` if no template exists / the
    fetch fails.

    Only the keys enumerated in ``_SURFACE_KEYS`` are passed
    through — downstream PDF code consumes a stable minimal shape
    without having to care about editor-only metadata (version,
    locked_reorder, label, etc.).
    """
    if not tenant_id or not form_type:
        return None
    try:
        doc = await db.form_templates.find_one(
            {"tenant_id": tenant_id,
              "form_type": form_type,
              "is_current": True},
            {"_id": 0, "fields": 1},
        )
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("[pdf_template_styles] fetch failed "
                        "tenant=%s form_type=%s: %s",
                        tenant_id, form_type, exc)
        return None
    if not doc or not isinstance(doc.get("fields"), list):
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for field in doc["fields"]:
        if not isinstance(field, dict):
            continue
        fid = field.get("field_id")
        if not isinstance(fid, str):
            continue
        style = field.get("style") or {}
        if not isinstance(style, dict):
            continue
        picked: Dict[str, Any] = {}
        for k in _SURFACE_KEYS:
            if k in style:
                picked[k] = style[k]
        if picked:
            out[fid] = picked
    return out or None


def hex_or_default(value: Any, default: str) -> str:
    """Return ``value`` iff it looks like a safe ``#RRGGBB`` string;
    else ``default``. ReportLab's ``HexColor`` crashes on
    malformed inputs, so sanitise before passing it through.
    """
    if not isinstance(value, str):
        return default
    v = value.strip()
    if len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v
        except ValueError:
            return default
    return default
