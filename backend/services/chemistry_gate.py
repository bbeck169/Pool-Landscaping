"""Feb-2026 · Chemistry required-readings gate.

Single source of truth for the "5 core readings needed to close a
job" business rule.  Used by every backend path that can transition
a job to ``completed``:

  * ``POST /api/jobs/{jid}/service-report/submit`` (tech submit)
  * ``PUT  /api/jobs/{jid}`` when the payload flips ``status`` to
    ``completed`` (admin edit)
  * ``mobile_sync._handle_job_close`` (offline replay)

The five required keys map to the canonical service-report field
names.  ``chemical_readings`` on either the ``service_reports`` doc
(list-of-dicts shape) OR the legacy ``jobs.chemical_readings`` dict
are both accepted — the helper normalises to a flat dict before the
check.

"Could Not Service" transitions and any other non-``completed``
status change are NOT gated.  See :func:`assert_core_readings_present`
for the raise contract.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from fastapi import HTTPException

# Canonical field names — the "Required Four" per Phase CHEM1 (Feb-2026).
# Aliases (``free_cl`` / ``cya`` / ``alk``) fold onto these keys during
# normalisation.
#
# Phase CHEM1 · Feb-2026 — ``total_chlorine`` was removed from the
# Required set. It is neither a required reading nor a persisted field
# any more; a one-shot ``$unset`` migration lives at
# ``services/migrations/chemistry_remove_total_chlorine_v1.py``.
CORE_READINGS: List[str] = [
    "free_chlorine",
    "alkalinity",
    "ph",
    "cyanuric_acid",
]

# UI-friendly SHORT labels for the ``missing_fields`` payload — used
# by legacy API consumers and machine parsers (kebab-y snake case).
_LABEL: Dict[str, str] = {
    "free_chlorine":  "free_cl",
    "alkalinity":     "alkalinity",
    "ph":             "ph",
    "cyanuric_acid":  "cya",
}

# Human-friendly DISPLAY labels for the ``missing_labels`` payload +
# every UI surface (button tooltips, inline banners, mobile hints).
# Product-approved wording (Feb-2026 spec).
DISPLAY_LABELS: Dict[str, str] = {
    "free_chlorine":  "Free Cl",
    "alkalinity":     "Alkalinity",
    "ph":             "pH",
    "cyanuric_acid":  "CYA",
}

_ALIASES: Dict[str, str] = {
    "free_cl":            "free_chlorine",
    "freecl":             "free_chlorine",
    "free chlorine":      "free_chlorine",
    # Feb-2026 · P12B — the pre-refactor default pool template used
    # a BARE ``"chlorine"`` key for the Free-Chlorine field.  The
    # template has since been renamed to ``"free_chlorine"``, but
    # any tenant that persisted the old key via
    # ``PUT /settings/service-templates`` before the fix still
    # writes ``chemical_readings[].key = "chlorine"``.  Fold onto
    # ``free_chlorine`` so those tenants stop hitting a phantom
    # ``chemistry_core_readings_missing`` on submit.
    "chlorine":           "free_chlorine",
    "cya":                "cyanuric_acid",
    "cyanuric":           "cyanuric_acid",
    "cyanuric acid":      "cyanuric_acid",
    "ph_balance":         "ph",
    "ph balance":         "ph",
    "alk":                "alkalinity",
    "total_alkalinity":   "alkalinity",
}


def _canonical_key(k: Any) -> Optional[str]:
    if not isinstance(k, str):
        return None
    norm = k.strip().lower().replace("-", "_")
    if norm in CORE_READINGS:
        return norm
    return _ALIASES.get(norm) or _ALIASES.get(norm.replace("_", " "))


def _is_valid_reading(v: Any) -> bool:
    """A reading is VALID when it parses as a real (finite) float.
    ``None`` / empty / whitespace / unparseable strings are MISSING.
    ``0`` and negative floats are treated as valid readings — real
    chemistry values, not sentinels."""
    if v is None:
        return False
    if isinstance(v, bool):
        # ``True`` / ``False`` are numeric in Python but we don't
        # want a stray boolean flag to satisfy the gate.
        return False
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        # Reject NaN / inf.
        return f == f and f not in (float("inf"), float("-inf"))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        try:
            f = float(s)
        except (TypeError, ValueError):
            return False
        return f == f and f not in (float("inf"), float("-inf"))
    return False


def _is_blank_reading(v: Any) -> bool:
    """Phase CHEM2 · Feb-2026 — "blank" means the tech never entered
    anything: ``None`` OR whitespace-only string. Every other value
    (including unparseable strings like ``"abc"`` or literal ``0``)
    is treated as a real, tech-entered value for merge purposes.

    Distinct from :func:`_is_valid_reading` — that helper decides
    whether the gate accepts the value; this one decides whether an
    alias collision should prefer this value over its peer.
    """
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def normalize_readings(source: Any) -> Dict[str, Any]:
    """Coerce a ``chemical_readings`` payload into a flat
    ``{canonical_key: value}`` dict.  Accepts:

    * list-of-dicts:   ``[{"key": "free_chlorine", "value": 2.5}, …]``
                       — the ``service_reports.chemical_readings`` shape.
    * dict:            ``{"free_chlorine": 2.5, …}``
                       — the legacy ``jobs.chemical_readings`` shape.

    Unknown / unaliased keys are dropped.

    Phase CHEM2 · Feb-2026 — Alias dedupe (prefer-value-over-blank):
        Legacy and canonical alias keys frequently coexist in the
        same payload (e.g. ``cyanuric`` + ``cyanuric_acid``,
        ``chlorine`` + ``free_chlorine``, ``total_alkalinity`` +
        ``alkalinity``, ``cya`` + ``cyanuric_acid``, …).  The merge
        below resolves every alias collision using two rules only:

          1. If one side is blank and the other is non-blank, KEEP
             the non-blank value under the canonical key. This is
             the common case where a tenant migrated schemas but
             left one shape empty.
          2. If both sides are non-blank, the value stored under
             the CANONICAL key wins; the alias hit is logged and
             dropped. This is a legitimate authoring collision
             that the tenant must eventually clean up in Mongo.

        Ordering within the input dict/list no longer decides the
        winner — the merge is order-independent.
    """
    out: Dict[str, Any] = {}
    # Provenance per canonical key — ``"canonical"`` means the value
    # was written by the canonical key itself (e.g. ``cyanuric_acid``);
    # ``"alias"`` means it came from a legacy alias (e.g. ``cyanuric``,
    # ``cya``).  Used by the both-non-blank branch to decide the
    # winner (rule 2 above).
    _prov: Dict[str, str] = {}

    def _norm_input_key(k: Any) -> str:
        return str(k or "").strip().lower().replace("-", "_")

    def _upsert(ck: str, raw_key: Any, val: Any) -> None:
        is_canonical_key = _norm_input_key(raw_key) == ck
        new_blank = _is_blank_reading(val)
        if ck not in out:
            out[ck] = val
            _prov[ck] = "canonical" if is_canonical_key else "alias"
            return
        stored_blank = _is_blank_reading(out[ck])
        stored_prov  = _prov.get(ck, "alias")
        # Rule 1 — one side blank, one side non-blank: keep the
        # non-blank value.
        if stored_blank and not new_blank:
            out[ck] = val
            _prov[ck] = "canonical" if is_canonical_key else "alias"
            return
        if (not stored_blank) and new_blank:
            return
        # Rule 2 — both non-blank: canonical wins.
        if (not stored_blank) and (not new_blank):
            if is_canonical_key and stored_prov != "canonical":
                logger.info(
                    "[chem-normalize] %s alias collision — keeping "
                    "%s, drop legacy %s",
                    ck, ck, out.get("_prev_key", "alias"),
                )
                out[ck] = val
                _prov[ck] = "canonical"
                return
            if (not is_canonical_key) and stored_prov == "canonical":
                logger.info(
                    "[chem-normalize] %s alias collision — keeping "
                    "%s, drop legacy %s",
                    ck, ck, raw_key,
                )
                return
            # Neither is the canonical key OR both look canonical
            # (impossible by construction). First-seen wins for
            # determinism and we still surface the collision.
            logger.info(
                "[chem-normalize] %s alias collision — keeping %s, "
                "drop legacy %s",
                ck, ck, raw_key,
            )
            return
        # Both blank — keep first-seen (already stored).
        return

    if isinstance(source, dict):
        for k, v in source.items():
            ck = _canonical_key(k)
            if ck:
                _upsert(ck, k, v)
        return out
    if isinstance(source, list):
        for row in source:
            if not isinstance(row, dict):
                continue
            raw = row.get("key") or row.get("name")
            ck = _canonical_key(raw)
            if not ck:
                continue
            _upsert(ck, raw, row.get("value"))
        return out
    return out


def missing_core_readings(source: Any) -> List[str]:
    """Return the machine-friendly SHORT label list of MISSING core
    readings (matches ``missing_fields`` in the 422 payload).
    Empty list means the gate would pass."""
    norm = normalize_readings(source)
    return [_LABEL[k] for k in CORE_READINGS if not _is_valid_reading(norm.get(k))]


def missing_core_reading_labels(source: Any) -> List[str]:
    """Return the human-friendly DISPLAY label list of MISSING core
    readings (matches ``missing_labels`` in the 422 payload).  Same
    ordering as :func:`missing_core_readings`."""
    norm = normalize_readings(source)
    return [DISPLAY_LABELS[k] for k in CORE_READINGS if not _is_valid_reading(norm.get(k))]


def assert_core_readings_present(source: Any) -> None:
    """Raise ``HTTPException(422)`` when any of the four core
    chemistry readings is missing.  Uses the same detail shape
    across every call site so the FE can key off ``detail`` and
    render ``missing_fields`` / ``missing_labels`` inline.
    """
    norm = normalize_readings(source)
    missing_keys = [k for k in CORE_READINGS
                    if not _is_valid_reading(norm.get(k))]
    if not missing_keys:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "detail": "chemistry_core_readings_missing",
            "missing_fields": [_LABEL[k] for k in missing_keys],
            "missing_labels": [DISPLAY_LABELS[k] for k in missing_keys],
            "message": "Cannot close job — required chemistry readings missing",
        },
    )


def _pick_primary_body(bodies: List[Any]) -> Optional[Dict[str, Any]]:
    """Return the primary body per the CHEM2 · Feb-2026 rule.

    Priority:
        1. A dict body with an explicit ``is_primary == True`` flag.
        2. Otherwise, the FIRST body in the list.
        3. If nothing dict-shaped is present, ``None``.

    Non-dict entries are skipped for both priorities so a malformed
    list (``[None, {"is_primary": True, ...}]``) still resolves the
    marked body correctly.
    """
    marked: Optional[Dict[str, Any]] = None
    first: Optional[Dict[str, Any]] = None
    for body in bodies:
        if not isinstance(body, dict):
            continue
        if first is None:
            first = body
        if body.get("is_primary") is True and marked is None:
            marked = body
    return marked if marked is not None else first


def assert_bodies_required_readings_present(bodies: Any) -> None:
    """Phase CHEM2 · Feb-2026 — primary-body-only enforcement of the
    Required Four.

    LOOSENED from CHEM1's every-body enforcement. Only the PRIMARY
    body (see :func:`_pick_primary_body`) is required to have all
    four canonical readings. Secondary bodies — spas, fountains,
    water features, secondary pools — may be entirely blank without
    blocking close.

    Exception CONTRACT preserved (byte-identical to CHEM1):

        * Class: :class:`fastapi.HTTPException`, ``status_code=422``.
        * ``detail`` schema (dict):
            ``{"detail":            "chemistry_core_readings_missing",
               "missing_fields":    [...],   # short/machine labels
               "missing_labels":    [...],   # human/display labels
               "bodies":            [ ... ], # length 0 or 1 (was: N)
               "message":           str}``
        * ``missing_fields`` / ``missing_labels`` ordering follows
          :data:`CORE_READINGS` (unchanged).
        * The ``bodies`` array now contains AT MOST ONE entry — the
          primary body — reflecting the narrowed enforcement. The
          field is retained so FE consumers keying on
          ``detail.bodies[0].id`` keep working; they simply always
          get a single-element array now.

    Human message narrowed to "Primary pool readings missing: …".
    """
    if not bodies or not isinstance(bodies, list):
        # Empty / malformed bodies list — the flat gate
        # (``assert_core_readings_present``) upstream already
        # handles the "no water bodies at all" case. Log at INFO so
        # ops can spot a stray write that dropped the array.
        logger.info(
            "assert_bodies_required_readings_present: no bodies to "
            "enforce (bodies=%r) — passing trivially",
            type(bodies).__name__ if bodies is not None else None,
        )
        return
    # Lazy import — avoid a top-level circular between chemistry_gate
    # and water_bodies (water_bodies imports from us at call sites).
    try:
        from services.water_bodies import READING_REQUIRED
    except Exception:                                     # noqa: BLE001
        return

    primary = _pick_primary_body(bodies)
    if primary is None:
        logger.info(
            "assert_bodies_required_readings_present: bodies list "
            "contains no dict entries — passing trivially",
        )
        return

    btype = (primary.get("type") or "").strip().lower() or "pool"
    required = READING_REQUIRED.get(btype) or ()
    if not required:
        # Primary body's type is not gated (e.g. a feature-only
        # body). Nothing to enforce.
        return
    norm = normalize_readings(primary.get("readings"))
    missing_keys = [k for k in required
                    if not _is_valid_reading(norm.get(k))]
    if not missing_keys:
        return

    # Preserve CORE_READINGS ordering for the union arrays even
    # though "union" is now a misnomer — we only have one body's
    # missing set. Kept named ``union_ordered`` to minimise diff
    # with the CHEM1 raise site.
    union_ordered = [k for k in CORE_READINGS if k in set(missing_keys)]
    offender = {
        "id":    primary.get("id"),
        "label": (primary.get("label")
                   or primary.get("name")
                   or btype.title()),
        "type":  btype,
        "missing_fields": [_LABEL[k] for k in missing_keys
                             if k in _LABEL],
        "missing_labels": [DISPLAY_LABELS[k] for k in missing_keys
                             if k in DISPLAY_LABELS],
    }
    _primary_label = offender["label"] or "Primary pool"
    _missing_display = ", ".join(offender["missing_labels"])
    raise HTTPException(
        status_code=422,
        detail={
            "detail": "chemistry_core_readings_missing",
            "missing_fields": [_LABEL[k] for k in union_ordered
                                 if k in _LABEL],
            "missing_labels": [DISPLAY_LABELS[k] for k in union_ordered
                                 if k in DISPLAY_LABELS],
            "bodies": [offender],
            "message": (
                f"{_primary_label} readings missing: {_missing_display}."
                if _missing_display
                else f"{_primary_label} readings missing."
            ),
        },
    )


def gather_readings_for_job(job: Dict[str, Any],
                             service_report: Optional[Dict[str, Any]] = None,
                             ) -> Dict[str, Any]:
    """Compose the flat readings dict from BOTH the service_report
    (preferred) and the job doc (legacy fallback).  Used by the
    admin PUT and mobile-sync paths where the caller may not have
    the service_report in hand.

    Feb-2026 · Multi-body chemistry-gate fallback — when NEITHER
    the flat ``chemical_readings`` mirror nor the legacy
    ``jobs.chemical_readings`` dict produced any core values, dig
    into the structured ``water_bodies[]`` array on the service
    report and flatten its FIRST pool body's readings (via
    ``services.water_bodies.iter_water_bodies +
    flatten_pool_readings``). Only fires as a fallback so existing
    single-body reports keep hitting the fast path unmodified.
    """
    combined: Dict[str, Any] = {}
    if service_report:
        combined.update(normalize_readings(service_report.get("chemical_readings")))
    if job:
        legacy = normalize_readings(job.get("chemical_readings"))
        for k, v in legacy.items():
            combined.setdefault(k, v)
    if service_report and not combined:
        try:
            # Lazy import — avoids a startup circular between
            # ``chemistry_gate`` and ``water_bodies``.
            from services.water_bodies import (
                flatten_pool_readings, iter_water_bodies,
            )
            flat_rows = flatten_pool_readings(
                iter_water_bodies(service_report),
            )
            combined.update(normalize_readings(flat_rows))
        except Exception:  # noqa: BLE001
            # Best-effort fallback — never crash the gate because
            # the multi-body layer had a shape it couldn't digest.
            pass
    return combined


def is_pool_job(job: Dict[str, Any]) -> bool:
    """Pool jobs are the only ones that carry chemistry.  Landscape
    jobs don't have readings — the gate MUST NOT block their
    completion.  Reuses the same heuristic surface as
    ``routers/jobs._derive_checklist_kind`` (imported lazily to
    avoid a hard dependency in this small helper module)."""
    try:
        from routers.jobs import _derive_checklist_kind
        return _derive_checklist_kind(job, None) == "pool"
    except Exception:
        # Fail-safe fallback — treat as pool so we err toward
        # gating rather than accidentally letting a pool job close
        # without readings.  If the caller knows it's a landscape
        # job it can skip calling the gate entirely.
        return True


def warn_if_pool_job_on_non_pool_tenant(job: Dict[str, Any],
                                         tenant: Dict[str, Any]) -> None:
    """Feb-2026 · Multi-industry Phase C — data-drift resilience.

    If ``is_pool_job(job)`` returns True but the tenant's
    ``industries`` array does NOT contain ``"pools"``, log a
    warning.  We intentionally do NOT raise — the gate itself
    still fires because the *job* is a pool job, but the
    tenant/job mismatch is worth surfacing to ops so they can
    either flip the tenant's Industries setting or reclassify
    the job.

    Import site: called from ``chemistry_required_gate`` /
    ``chemistry_required_reading_gate`` after ``is_pool_job``
    but before the reading validator loop, so a warning fires
    on every mismatched call.
    """
    if not is_pool_job(job):
        return
    try:
        from services.industries import tenant_has_industry
        if tenant and not tenant_has_industry(tenant, "pools"):
            from config import logger
            logger.warning(
                "[chem-gate] tenant=%s job=%s pool-shaped but tenant "
                "industries=%s — expected 'pools'. Reclassify the "
                "job or activate the Pools industry in Settings.",
                tenant.get("id"), job.get("id"),
                tenant.get("industries"),
            )
    except Exception:
        # Never crash the completion path on a diagnostic log.
        pass
