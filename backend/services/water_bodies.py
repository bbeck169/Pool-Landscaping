"""Feb-2026 · Multi-body service reports — Phase 1 (backend).

Adds first-class ``water_bodies[]`` support to service reports. A single
service visit can now log distinct chemistry / chemicals / media / notes
for each body of water on the property (Pool + Spa + Fountain, etc.).

Design (approved Feb-2026):
  * Type-picker: ``pool | spa | water_feature | fountain | other``.
  * ``water_bodies[0]`` mirrors the legacy top-level ``chemical_readings``
    / ``chemicals_added`` fields for backward compatibility. The
    migration populates it from those top-level fields on first boot.
  * Trimmed chemistry allow-lists per body type (see ``READING_ALLOWLIST``
    / ``CHEMICAL_ALLOWLIST``). ``other`` is fully free-form.
  * Required-readings gate only fires for ``pool`` bodies — Spa /
    WaterFeature / Fountain are soft-warn-only. Existing chemistry gate
    in ``services.chemistry_gate`` operates on top-level ``chemical_readings``
    which is kept in sync with ``water_bodies[0]``.

This module is HTTP-free — it only exposes constants + pure helpers so
the router, the migration, and future callers (mobile sync, doorhanger
renderer, etc.) can share validation without recursion.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils import new_id


# ─── Body types ────────────────────────────────────────────────────────
BODY_TYPES: Tuple[str, ...] = (
    "pool",
    "spa",
    "water_feature",
    "fountain",
    "other",
)


BODY_TYPE_LABELS: Dict[str, str] = {
    "pool":          "Pool",
    "spa":           "Spa",
    "water_feature": "Water Feature",
    "fountain":      "Fountain",
    "other":         "Other",
}


# ─── Reading allow-lists (approved Feb-2026 kickoff) ───────────────────
# Keys are the canonical reading keys used by ``services.chemistry_gate``
# and ``services.chemistry_bands``. ``other`` accepts any of the union
# below (fully free-form).
READING_ALLOWLIST: Dict[str, Tuple[str, ...]] = {
    "pool": (
        "free_chlorine", "total_chlorine", "ph", "alkalinity",
        "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates",
    ),
    "spa": (
        "free_chlorine", "ph", "alkalinity", "calcium_hardness",
    ),
    "water_feature": (
        "free_chlorine", "ph",
    ),
    "fountain": (
        "free_chlorine", "ph",
    ),
    "other": (
        "free_chlorine", "total_chlorine", "ph", "alkalinity",
        "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates",
    ),
}


# Required-reading list per body type. Only ``pool`` is strictly gated on
# submit; every other type is soft-warn (empty list = no required set).
READING_REQUIRED: Dict[str, Tuple[str, ...]] = {
    "pool": (
        "free_chlorine", "total_chlorine", "ph", "alkalinity", "cyanuric_acid",
    ),
    "spa": (),
    "water_feature": (),
    "fountain": (),
    "other": (),
}


# ─── Chemical allow-lists ──────────────────────────────────────────────
# Slugs come from ``config_chemicals.CHEMICALS_CATALOG``. ``other``
# accepts any known slug.
CHEMICAL_ALLOWLIST: Dict[str, Tuple[str, ...]] = {
    "pool": (
        "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
        "shock", "clarifier", "phosphate_remover", "salt", "enzymes",
    ),
    "spa": (
        "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
        "shock", "clarifier", "enzymes",
    ),
    "water_feature": (
        "liquid_chlorine", "muriatic_acid", "clarifier", "enzymes",
        "phosphate_remover",
    ),
    "fountain": (
        "liquid_chlorine", "muriatic_acid", "clarifier", "enzymes",
        "phosphate_remover",
    ),
    "other": (
        "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
        "shock", "clarifier", "phosphate_remover", "salt", "enzymes",
    ),
}


# ─── Validation errors ─────────────────────────────────────────────────
class WaterBodyValidationError(ValueError):
    """Raised when a ``water_bodies`` payload fails the type-scoped
    allow-list check. Router callers convert this to a 422 detail
    payload so the FE can flag the offending body + field."""

    def __init__(self, detail: Dict[str, Any]):
        super().__init__(detail.get("message") or "water_body_invalid")
        self.detail = detail


# ─── Reading-key aliasing ──────────────────────────────────────────────
# Reuses the canonicaliser from the chemistry gate so old free-form keys
# (``free_cl``, ``cya``, …) canonicalise correctly before the allow-list
# check. Extended readings (``salt``, ``tds``, ``calcium_hardness``,
# ``phosphates``) are not in the chemistry-gate ``CORE_READINGS`` set,
# so we accept them via a small local extension. Kept as a lazy import
# to avoid a circular reference.
_EXTENDED_READING_KEYS: Tuple[str, ...] = (
    "calcium_hardness", "salt", "tds", "phosphates",
)


_EXTENDED_ALIASES: Dict[str, str] = {
    "calcium":              "calcium_hardness",
    "hardness":             "calcium_hardness",
    "total_hardness":       "calcium_hardness",
    "total dissolved solids": "tds",
    "total_dissolved_solids": "tds",
    "phosphate":            "phosphates",
}


def _canonical_reading_key(key: str) -> Optional[str]:
    from services.chemistry_gate import _canonical_key  # noqa: WPS437
    ck = _canonical_key(key or "")
    if ck:
        return ck
    if not isinstance(key, str):
        return None
    norm = key.strip().lower().replace("-", "_")
    if norm in _EXTENDED_READING_KEYS:
        return norm
    return _EXTENDED_ALIASES.get(norm)


# ─── Public validation API ─────────────────────────────────────────────
def normalize_body_type(raw: Any) -> str:
    """Return the canonical body type slug for a raw payload value.

    Missing / unknown values default to ``"pool"`` (backward compat — the
    legacy flow only ever wrote pool bodies).
    """
    if isinstance(raw, str):
        s = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if s in BODY_TYPES:
            return s
    return "pool"


def validate_body(body: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """Validate a single body dict against the trimmed allow-lists.

    Returns a normalized copy with:
      * ``type``  → canonical slug.
      * ``label`` → coerced to the display label when blank.
      * ``id``    → assigned when missing.
      * ``sequence`` → set to ``index`` when missing.
      * ``readings`` / ``chemicals_used`` / ``media`` / ``notes`` →
        defaulted to empty list / string when omitted.

    Raises :class:`WaterBodyValidationError` on any allow-list breach.
    Callers turn the raised ``.detail`` dict into an HTTPException(422).
    """
    if not isinstance(body, dict):
        raise WaterBodyValidationError({
            "message": "water_body_must_be_object",
            "index": index,
        })
    b = dict(body)
    b["type"] = normalize_body_type(b.get("type"))
    body_type = b["type"]
    allowed_readings = set(READING_ALLOWLIST[body_type])
    allowed_chems = set(CHEMICAL_ALLOWLIST[body_type])

    # ── Readings ──
    readings = b.get("readings") or []
    if not isinstance(readings, list):
        raise WaterBodyValidationError({
            "message": "readings_must_be_list",
            "index": index, "type": body_type,
        })
    norm_readings: List[Dict[str, Any]] = []
    for r_i, r in enumerate(readings):
        if not isinstance(r, dict):
            continue
        raw_key = r.get("key") or r.get("name") or ""
        canonical = _canonical_reading_key(str(raw_key))
        # For ``other`` bodies we still coerce known aliases when we can
        # but pass the raw key through untouched so freeform readings
        # (e.g. "orp") aren't silently dropped.
        effective_key = canonical or (
            str(raw_key).strip().lower() if body_type == "other" else canonical
        )
        if not effective_key:
            # Unrecognized empty key — skip silently rather than 422.
            continue
        if body_type != "other" and effective_key not in allowed_readings:
            raise WaterBodyValidationError({
                "message": "reading_not_allowed_for_body_type",
                "index": index, "type": body_type,
                "key": effective_key,
                "allowed": sorted(allowed_readings),
            })
        norm_readings.append({
            "key":   effective_key,
            "name":  r.get("name") or effective_key.replace("_", " ").title(),
            "unit":  r.get("unit"),
            "value": r.get("value"),
            "ts":    r.get("ts"),
        })
    b["readings"] = norm_readings

    # ── Chemicals ──
    chems = b.get("chemicals_used") or b.get("chemicals_added") or []
    if not isinstance(chems, list):
        raise WaterBodyValidationError({
            "message": "chemicals_used_must_be_list",
            "index": index, "type": body_type,
        })
    norm_chems: List[Dict[str, Any]] = []
    for c_i, c in enumerate(chems):
        if not isinstance(c, dict):
            continue
        slug = (c.get("product_slug") or c.get("slug")
                or c.get("chemical_slug") or "")
        slug = str(slug or "").strip().lower() if slug else ""
        name = c.get("name") or c.get("chemical") or ""
        # If a slug is provided AND allow-list is enforced (non-other),
        # verify. When only a name is provided we let it through — the
        # snapshot layer resolves by name too.
        if slug and body_type != "other" and slug not in allowed_chems:
            raise WaterBodyValidationError({
                "message": "chemical_not_allowed_for_body_type",
                "index": index, "type": body_type,
                "slug": slug,
                "allowed": sorted(allowed_chems),
            })
        norm_chems.append({
            **c,
            "product_slug": slug or c.get("product_slug"),
            "name": name,
        })
    b["chemicals_used"] = norm_chems
    # Drop legacy ``chemicals_added`` alias so persisted docs use the
    # canonical field name.
    b.pop("chemicals_added", None)

    # ── Media ──
    media = b.get("media") or []
    if not isinstance(media, list):
        raise WaterBodyValidationError({
            "message": "media_must_be_list",
            "index": index, "type": body_type,
        })
    b["media"] = [m for m in media if isinstance(m, dict)]

    # ── Notes / label / id / sequence ──
    b["notes"] = str(b.get("notes") or "")
    b["label"] = (b.get("label") or "").strip() or BODY_TYPE_LABELS[body_type]
    if not b.get("id"):
        b["id"] = new_id()
    seq = b.get("sequence")
    if not isinstance(seq, int):
        b["sequence"] = index
    return b


def validate_water_bodies(bodies: Any) -> List[Dict[str, Any]]:
    """Validate + normalize an incoming ``water_bodies`` payload.

    Empty / missing arrays raise — callers should skip the call
    entirely when they don't intend to touch bodies. Passing ``[]``
    means "clear all bodies" and is rejected here (the router
    handler enforces the ≥ 1-body invariant).
    """
    if bodies is None:
        raise WaterBodyValidationError({
            "message": "water_bodies_missing",
        })
    if not isinstance(bodies, list):
        raise WaterBodyValidationError({
            "message": "water_bodies_must_be_list",
        })
    if not bodies:
        raise WaterBodyValidationError({
            "message": "water_bodies_must_have_at_least_one_body",
        })
    out: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for i, b in enumerate(bodies):
        norm = validate_body(b, index=i)
        # Dedupe accidental id collisions from the client.
        if norm["id"] in seen_ids:
            norm["id"] = new_id()
        seen_ids.add(norm["id"])
        norm["sequence"] = i
        out.append(norm)
    return out


# ─── Legacy → water_bodies materialisation ─────────────────────────────
def _detect_body_type_from_job(job: Dict[str, Any]) -> str:
    """Infer the body type slug for the migration's default body.

    Pool jobs (chemistry-bearing) → ``"pool"``. Everything else
    (landscape, generic, repair, etc.) → ``"other"`` so the strict pool
    allow-list doesn't accidentally reject legacy landscape reports on
    the first read.
    """
    try:
        from services.chemistry_gate import is_pool_job
        return "pool" if is_pool_job(job) else "other"
    except Exception:
        # Fail-safe: if we can't detect, assume pool (matches the
        # legacy default the tech UI produced).
        return "pool"


def _media_from_photos(photos: Any) -> List[Dict[str, Any]]:
    """Coerce a legacy ``photos`` list into a body ``media`` list. Each
    photo becomes a ``{kind: "photo", ...}`` media dict; strings are
    wrapped as ``{url: <str>, kind: "photo"}``.
    """
    if not isinstance(photos, list):
        return []
    out: List[Dict[str, Any]] = []
    for p in photos:
        if isinstance(p, dict):
            out.append({"kind": p.get("kind") or "photo", **p})
        elif isinstance(p, str) and p:
            out.append({"kind": "photo", "url": p})
    return out


def build_default_body_from_report(
    rep: Dict[str, Any],
    *,
    job: Optional[Dict[str, Any]] = None,
    include_media: bool = True,
) -> Dict[str, Any]:
    """Construct ``water_bodies[0]`` from the legacy top-level fields
    on a service_report doc. Used by the boot migration and by the
    bootstrap path when a report is created without an explicit body.

    ``include_media`` = False when the caller wants to keep top-level
    ``photos`` as the canonical media store (the router does this to
    avoid double-counting during backward-compat renders).
    """
    body_type = _detect_body_type_from_job(job or {})
    return {
        "id": new_id(),
        "type": body_type,
        "label": BODY_TYPE_LABELS[body_type],
        "sequence": 0,
        "readings": list(rep.get("chemical_readings") or []),
        "chemicals_used": list(rep.get("chemicals_added") or []),
        "media": (_media_from_photos(rep.get("photos")) if include_media else []),
        "notes": str(rep.get("notes") or ""),
    }


# ─── Read-side helpers ─────────────────────────────────────────────────
def iter_water_bodies(rep: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the ``water_bodies`` array on the report, materialising a
    single default body from legacy top-level fields when the array is
    missing / empty. Never mutates the input.
    """
    bodies = rep.get("water_bodies")
    if isinstance(bodies, list) and bodies:
        return bodies
    return [build_default_body_from_report(rep)]


def flatten_chemicals_used(bodies: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a single concatenated ``chemicals_used`` list across every
    body. Used for the top-level ``chemicals_added`` mirror so legacy
    consumers (auto-invoice, chemical usage snapshot, per-tech spend
    rollups) see chemicals from every body without body-awareness.
    """
    out: List[Dict[str, Any]] = []
    for b in bodies:
        for c in (b.get("chemicals_used") or b.get("chemicals_added") or []):
            if isinstance(c, dict):
                out.append(c)
    return out


def flatten_pool_readings(bodies: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the readings that should back the chemistry required-
    readings gate. Only the FIRST body of type ``"pool"`` contributes —
    additional pool bodies are still validated by allow-list but do not
    aggregate into the gate (the gate operates on a single primary
    body). Callers use this for the top-level ``chemical_readings``
    mirror so ``chemistry_gate.assert_core_readings_present`` keeps
    working unmodified.
    """
    for b in bodies:
        if (b.get("type") or "").lower() == "pool":
            return list(b.get("readings") or [])
    # No pool body → gate never fires; return the first body's readings
    # for legacy display / API surface parity.
    for b in bodies:
        return list(b.get("readings") or [])
    return []


def summarize_body(b: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact ``{id, type, label, sequence, reading_count,
    chemical_count, media_count, has_notes}`` summary. Used by the
    customer history list surface so the FE can render "1 Pool · 1 Spa"
    style badges without loading every body's full payload.
    """
    return {
        "id":              b.get("id"),
        "type":            b.get("type") or "pool",
        "label":           b.get("label") or BODY_TYPE_LABELS.get(
                              b.get("type") or "pool", "Pool"),
        "sequence":        int(b.get("sequence") or 0),
        "reading_count":   len(b.get("readings") or []),
        "chemical_count":  len(b.get("chemicals_used")
                                or b.get("chemicals_added") or []),
        "media_count":     len(b.get("media") or []),
        "has_notes":       bool((b.get("notes") or "").strip()),
    }


# ─── Write-side pipeline (Feb-2026 · shared validate/flatten step) ───
_LEGACY_MIRROR_KEYS: Tuple[str, ...] = (
    "chemical_readings", "chemicals_added", "notes",
)


def apply_water_bodies_payload(upd: Dict[str, Any],
                                 rep: Dict[str, Any],
                                 ) -> Dict[str, Any]:
    """Presence-aware validate + flatten pipeline shared by every write
    path that persists a partial service_report patch (the web
    ``PATCH /api/service-reports/{jid}`` handler AND the mobile-sync
    ``service_report.upsert`` handler).

    Semantics (approved Feb-2026 chemistry-gate ship):

      * ``"water_bodies" in upd`` (any value, INCLUDING an explicit
        ``[]`` which is a deliberate clear) → validate via
        :func:`validate_water_bodies`, coerce ``upd["water_bodies"]``
        to the validated list, AND rebuild the top-level
        ``chemical_readings`` mirror via :func:`flatten_pool_readings`
        so the required-readings chemistry gate keeps working
        unchanged on downstream consumers.

      * ``"water_bodies"`` NOT in upd, but any of the legacy top-level
        keys ``chemical_readings`` / ``chemicals_added`` / ``notes``
        IS in upd → merge those into the existing report's
        ``water_bodies[0]`` (spawning one from
        :func:`build_default_body_from_report` when the array is
        empty) so the multi-body surface stays in sync with legacy
        writes.

      * ``"water_bodies"`` NOT in upd AND no legacy mirror keys either
        → no-op. Every key ABSENT from ``upd`` is left untouched by
        this pipeline; the caller must $set only ``upd`` so Mongo's
        native ``$set`` semantics preserve every persisted key not
        present in the incoming patch.

    Never uses ``upd.get("water_bodies")`` — the presence check is
    ``in`` because ``[]`` is a legitimate clear signal and ``None``
    is a legacy-shape mistake we ignore. Returns the SAME ``upd``
    dict (mutated in place) for chaining convenience.
    """
    if "water_bodies" in upd:
        raw = upd["water_bodies"]
        # Feb-2026 · Deliberate-clear semantics — an explicit
        # ``water_bodies: []`` (or ``None``) is a customer/tech
        # opt-in wipe, NOT a validation failure. ``validate_water_bodies``
        # rejects empty arrays for structured writes, so we short-
        # circuit here and clear the flat mirror in lockstep.
        if raw is None or (isinstance(raw, list) and len(raw) == 0):
            upd["water_bodies"] = []
            upd["chemical_readings"] = []
            return upd
        # Non-empty array — hits the validator + flatten path.
        # ``validate_water_bodies`` raises :class:`WaterBodyValidationError`
        # (a ``ValueError`` subclass carrying an ``exc.detail`` dict).
        # We let it propagate as-is so callers can re-raise the
        # structured 422 detail without loss.
        bodies = validate_water_bodies(raw)
        upd["water_bodies"] = bodies
        # Feb-2026 · P0 autosave dual-write fix — the web checklist
        # writes tech edits to TOP-LEVEL ``chemical_readings`` /
        # ``chemicals_added`` (see ``PoolChecklistForm.updReading`` +
        # ``_updChem``) but never syncs those edits back into the
        # client's ``water_bodies[0]`` mirror.  Every autosave
        # therefore sent BOTH:
        #   * ``water_bodies``       — stale (missing the newest keystroke)
        #   * ``chemical_readings``  — fresh
        # Without this merge, the flatten step below would REBUILD
        # the fresh top-level keys from the stale mirror and silently
        # zero out the tech's edit on every save.  Legacy top-level
        # values win when BOTH are present because they carry the
        # freshest write.  See:
        #   backend/tests/test_service_report_autosave_dual_write.py
        if bodies and (
            "chemical_readings" in upd or "chemicals_added" in upd
        ):
            body0 = dict(bodies[0])
            if "chemical_readings" in upd:
                body0["readings"] = list(upd["chemical_readings"] or [])
            if "chemicals_added" in upd:
                body0["chemicals_used"] = list(upd["chemicals_added"] or [])
            bodies[0] = body0
            upd["water_bodies"] = bodies
        # Rebuild the flat mirror unconditionally when
        # ``water_bodies`` is present in the patch — even when the
        # array is empty (an explicit clear). ``flatten_pool_readings``
        # returns ``[]`` for empty inputs which correctly clears the
        # top-level ``chemical_readings`` too. ``chemicals_added``
        # rebuild covers every downstream consumer (auto-invoice,
        # chemical usage snapshot, per-tech spend rollups).
        upd["chemical_readings"] = flatten_pool_readings(bodies)
        upd["chemicals_added"] = flatten_chemicals_used(bodies)
        return upd

    if any(k in upd for k in _LEGACY_MIRROR_KEYS):
        existing_bodies = list(rep.get("water_bodies") or [])
        if not existing_bodies:
            existing_bodies = [build_default_body_from_report(rep)]
        body0 = dict(existing_bodies[0])
        if "chemical_readings" in upd:
            body0["readings"] = list(upd["chemical_readings"] or [])
        if "chemicals_added" in upd:
            body0["chemicals_used"] = list(upd["chemicals_added"] or [])
        if "notes" in upd:
            body0["notes"] = str(upd["notes"] or "")
        existing_bodies[0] = body0
        upd["water_bodies"] = existing_bodies

    return upd
