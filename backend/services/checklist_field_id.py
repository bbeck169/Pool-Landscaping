"""Phase 17 · Feb-2026 — Checklist cross-collection field_id stamp.

Phase 14 Follow-up 4 shipped ``orderChecklistByTemplate`` with
label-based matching between form_templates (``chk_<slug>`` field_
ids) and the service-report checklist items (which had no stable
cross-collection identifier). Phase 17 introduces a mechanical
``chk_<slug>`` field_id convention and stamps it onto every item
in:

  * ``industry_checklist_templates.items[]`` — platform-level
    defaults for the 23 seeded industries.
  * ``tenant_checklist_overrides.items[]`` — per-tenant overrides.

Zero-regression contract:
  * Existing ``key`` (snake_case stable id on
    industry_checklist_templates / tenant_checklist_overrides) is
    preserved as the primary cross-doc identifier where present.
  * ``field_id`` is derived from ``key`` when the item already has
    one (``chk_<key>``); otherwise from the slugified label.
  * Collision disambiguation inside a single template: suffix
    ``_2``, ``_3``, … until unique.
  * Items that already carry a ``field_id`` are preserved as-is
    (no overwrite — stability lock).

Phase 7A note
-------------
The Phase 7A seed in ``backend/routers/form_templates.py`` used
HAND-CURATED field_ids (``chk_skim_surface``, ``chk_vacuum_floor``)
rather than a mechanical slug of the full label. Phase 17 does NOT
retroactively re-slug those seeds — they remain the canonical
form_template ids. The ``orderChecklistByTemplate`` helper keeps
label-match as a fallback so these curated ids continue to work
alongside the mechanically-slugged migrated items.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_label(label: str) -> str:
    """Deterministic slug: lowercase, non-alphanum → ``_``, collapse
    repeats, trim leading/trailing ``_``. Empty string returned
    for empty / all-punctuation input (caller must guard)."""
    if not isinstance(label, str):
        return ""
    out = _SLUG_RE.sub("_", label.lower()).strip("_")
    # Collapse any multiple underscores the regex may have left
    # behind at boundary edges.
    while "__" in out:
        out = out.replace("__", "_")
    return out


def _candidate_field_id(item: Dict[str, Any]) -> str:
    """Pick the raw (pre-disambiguation) ``field_id`` for ``item``.

    Priority:
      1. explicit ``field_id`` already set → use as-is
      2. ``key`` present → ``chk_<key>``
      3. ``label`` present → ``chk_<slug(label)>``
      4. nothing usable → empty string (caller skips)
    """
    existing = str(item.get("field_id") or "").strip()
    if existing:
        return existing
    key = str(item.get("key") or "").strip()
    if key:
        return f"chk_{key}"
    label = str(item.get("label") or "").strip()
    slug = slug_label(label)
    if slug:
        return f"chk_{slug}"
    return ""


def stamp_field_ids(items: Iterable[Dict[str, Any]]
                     ) -> List[Dict[str, Any]]:
    """Return a new list of items where each item carries a stable
    ``field_id``. Idempotent: items that already have one are
    passed through unchanged. Collisions inside the same list are
    disambiguated by ``_2``, ``_3``, … suffix.
    """
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in items or ():
        if not isinstance(item, dict):
            out.append(item)
            continue
        if item.get("field_id"):
            seen.add(item["field_id"])
            out.append(item)
            continue
        raw = _candidate_field_id(item)
        if not raw:
            # Unstampable (no label/key) — pass through unchanged.
            out.append(dict(item))
            continue
        final = raw
        n = 2
        while final in seen:
            final = f"{raw}_{n}"
            n += 1
        seen.add(final)
        out.append({**item, "field_id": final})
    return out


def stamped_counts(before: List[Dict[str, Any]],
                    after: List[Dict[str, Any]]) -> Dict[str, int]:
    """Shared helper for the migration script's reporting pass."""
    stamped = 0
    skipped = 0
    for b, a in zip(before, after):
        had = bool(b.get("field_id")) if isinstance(b, dict) else False
        has = bool(a.get("field_id")) if isinstance(a, dict) else False
        if not had and has:
            stamped += 1
        elif had and has:
            skipped += 1
    return {"stamped": stamped, "skipped": skipped}
