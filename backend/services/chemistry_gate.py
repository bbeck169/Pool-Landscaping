"""Feb-2026 · Chemistry required-readings gate.

Single source of truth for the "Required Four core readings needed
to close a job" business rule.  Used by every backend path that can
transition a job to ``completed``:

  * ``POST /api/jobs/{jid}/service-report/submit`` (tech submit)
  * ``PUT  /api/jobs/{jid}`` when the payload flips ``status`` to
    ``completed`` (admin edit)
  * ``mobile_sync._handle_job_close`` (offline replay)

The four required keys map to the canonical service-report field
names.  ``chemical_readings`` on either the ``service_reports`` doc
(list-of-dicts shape) OR the legacy ``jobs.chemical_readings`` dict
are both accepted — the helper normalises to a flat dict before the
check.

"Could Not Service" transitions and any other non-``completed``
status change are NOT gated.  See :func:`assert_core_readings_present`
for the raise contract.

Phase P17 · Feb-2026 · P0 HOTFIX — Chemistry Gate Key Unification
=================================================================
Production had techs seeing "Chemistry required readings missing"
even though every field was filled.  Root causes:

  1. Case / space aliases (``"pH"``, ``"Total Alkalinity"``,
     ``"Cyanuric Acid"``) failed to resolve because the alias-lookup
     path only tried ``.replace("-", "_")`` on the incoming key —
     ``"Total Alkalinity"`` normalised to ``"total alkalinity"``
     (space preserved) which did not match the snake-case alias
     ``"total_alkalinity"``.
  2. Zero-value collisions.  A payload carrying BOTH ``{"ph": 0}``
     (auto-persisted blank) and ``{"pH": 7.4}`` (real reading) let
     the ``0`` win under the "blank means None/empty-string only"
     rule.  0 is not a physically-meaningful pH / alkalinity / CYA
     reading — treat it as empty for those three fields (chlorine
     ``0`` remains a real reading).
  3. Dupe merge order-dependence.  Previous merge decided the
     winner while walking the input dict; dict iteration order
     leaked into the outcome for ambiguous payloads.

The fix consolidates every alias into a single :data:`ALIAS_MAP`,
normalises incoming keys with ``strip().lower().replace(" ", "_")
.replace("-", "_")`` before lookup, and rewrites
:func:`normalize_readings` as a two-pass loop (pass 1 buckets every
candidate value per canonical key, pass 2 picks the winner using
the "real beats empty; canonical spelling wins; else alphabetically
first" rules).  A WARN log fires on every legitimate alias
collision so ops can spot future dupes.

The 422 wire contract (``missing_fields`` / ``missing_labels`` /
``bodies``) flips under Phase P17.1 · Feb-2026 to the ``chlorine``
canonical (see :data:`CORE_READINGS`, :data:`_LABEL`,
:data:`DISPLAY_LABELS`).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import HTTPException

# ═════════════════════════════════════════════════════════════════════
# Canonical field names — the "Required Four" per Phase CHEM1
# (Feb-2026).  Every alias in :data:`ALIAS_MAP` folds onto one of
# these four keys.
#
# Phase P17.1 · Feb-2026 — the ``free_chlorine`` canonical was
# renamed to ``chlorine`` end-to-end. Legacy spellings
# (``free_chlorine``, ``free_cl``, ``freecl``, ``fc``,
# ``free chlorine``) remain as SOURCE aliases in :data:`ALIAS_MAP`
# pointing at ``chlorine`` so existing writes and stored docs
# continue to resolve correctly. The 422 wire contract
# (``missing_fields`` / ``missing_labels``) now emits ``chlorine``
# / ``Chlorine`` instead of ``free_cl`` / ``Free Cl``.
# ═════════════════════════════════════════════════════════════════════
CORE_READINGS: List[str] = [
    "chlorine",
    "alkalinity",
    "ph",
    "cyanuric_acid",
]

# UI-friendly SHORT labels for the ``missing_fields`` payload — used
# by legacy API consumers and machine parsers (kebab-y snake case).
_LABEL: Dict[str, str] = {
    "chlorine":       "chlorine",
    "alkalinity":     "alkalinity",
    "ph":             "ph",
    "cyanuric_acid":  "cya",
}

# Human-friendly DISPLAY labels for the ``missing_labels`` payload +
# every UI surface (button tooltips, inline banners, mobile hints).
# Product-approved wording (Feb-2026 spec).
DISPLAY_LABELS: Dict[str, str] = {
    "chlorine":       "Chlorine",
    "alkalinity":     "Alkalinity",
    "ph":             "pH",
    "cyanuric_acid":  "CYA",
}

# ═════════════════════════════════════════════════════════════════════
# Phase P17 · Feb-2026 — single source of truth for alias resolution.
#
# Incoming keys are normalised via
#     _norm_key(k) = k.strip().lower().replace(" ", "_").replace("-", "_")
# BEFORE lookup so ``"pH"`` → ``"ph"``, ``"Total Alkalinity"`` →
# ``"total_alkalinity"``, ``"Cyanuric Acid"`` → ``"cyanuric_acid"``,
# ``"CYA"`` → ``"cya"``, etc.
#
# Every canonical key is included as an identity entry so the same
# lookup handles both "already-canonical" and "aliased" input keys
# without a branching read path.
#
# Keep in sync with:
#   * frontend/src/utils/chemistryGate.js  :: ALIAS_MAP
#   * mobile/utils/chemistryGate.ts        :: ALIAS_MAP
# ═════════════════════════════════════════════════════════════════════
ALIAS_MAP: Dict[str, str] = {
    # ── ph ────────────────────────────────────────────────────
    "ph":               "ph",
    "p_h":              "ph",
    "ph_balance":       "ph",       # legacy — preserved
    # ── chlorine (Phase P17.1 · Feb-2026 canonical rename;
    # legacy spellings preserved as source aliases) ────────────
    "chlorine":         "chlorine",
    "free_chlorine":    "chlorine",
    "free_cl":          "chlorine",
    "freecl":           "chlorine",
    "fc":               "chlorine",
    # ── alkalinity ────────────────────────────────────────────
    "alkalinity":       "alkalinity",
    "total_alkalinity": "alkalinity",
    "ta":               "alkalinity",
    "alk":              "alkalinity",  # legacy — preserved
    # ── cyanuric_acid ─────────────────────────────────────────
    "cyanuric_acid":    "cyanuric_acid",
    "cyanuric":         "cyanuric_acid",
    "cya":              "cyanuric_acid",
}

# Zero-carve-out: 0 is a physically meaningful reading ONLY for
# chlorine (a fully-consumed pool CAN read 0.0 ppm free chlorine).
# For pH / alkalinity / CYA, 0 is a sentinel for "not entered" and
# MUST be treated as empty for both dedupe and gate purposes.
_ZERO_IS_EMPTY_KEYS = frozenset({"ph", "alkalinity", "cyanuric_acid"})


def _norm_key(k: Any) -> str:
    """Uniform key normalization used across ALIAS_MAP lookup and
    the "raw key equals canonical" check inside :func:`normalize_readings`.
    """
    if not isinstance(k, str):
        return ""
    return k.strip().lower().replace(" ", "_").replace("-", "_")


def _canonical_key(k: Any) -> Optional[str]:
    """Resolve an incoming payload key to its canonical
    :data:`CORE_READINGS` entry, or ``None`` when the key is not
    tracked.  Case- and whitespace-insensitive.
    """
    norm = _norm_key(k)
    if not norm:
        return None
    return ALIAS_MAP.get(norm)


def _is_valid_reading(v: Any) -> bool:
    """A reading is VALID when it parses as a real (finite) float.
    ``None`` / empty / whitespace / unparseable strings are MISSING.
    Booleans NEVER count as readings.

    Does NOT know about the zero-carve-out — that is the caller's
    responsibility (see :func:`_is_gate_valid`).
    """
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
        # Phase P17 · Feb-2026 — treat literal "null" / "None" as
        # empty (older mobile builds serialised missing readings
        # as the string ``"null"`` when hitting the /submit route).
        if s.lower() in ("null", "none"):
            return False
        try:
            f = float(s)
        except (TypeError, ValueError):
            return False
        return f == f and f not in (float("inf"), float("-inf"))
    return False


def _numeric_value(v: Any) -> Optional[float]:
    """Return the numeric value of ``v`` if it parses as a finite
    float, else ``None``.  Booleans are NOT numeric here.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None
    return None


def _is_effectively_empty(ck: Optional[str], v: Any) -> bool:
    """Phase P17 · Feb-2026 — unified emptiness check used for both
    dedupe ("real beats empty") and the gate ("missing readings").

    A value is EMPTY when:
      * ``None``
      * whitespace-only string, OR literal ``"null"`` / ``"None"``
        (case-insensitive)
      * numeric ``0`` — ONLY when ``ck`` is in
        :data:`_ZERO_IS_EMPTY_KEYS` (pH / alkalinity / CYA).
        ``chlorine`` treats 0 as a real reading.

    Booleans are always empty (see :func:`_is_valid_reading`).
    """
    if v is None:
        return True
    if isinstance(v, bool):
        return True
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("null", "none"):
            return True
    if ck in _ZERO_IS_EMPTY_KEYS:
        num = _numeric_value(v)
        if num is not None and num == 0.0:
            return True
    return False


def _is_gate_valid(ck: str, v: Any) -> bool:
    """True when the gate should count ``v`` as a real reading under
    canonical key ``ck``.  Combines :func:`_is_valid_reading` (does
    it parse?) with the per-key zero-carve-out.
    """
    if _is_effectively_empty(ck, v):
        return False
    return _is_valid_reading(v)


# Kept for backward-compat with call sites that already imported the
# private helper (Phase CHEM2 external callers).  Delegates to the
# unified :func:`_is_effectively_empty` with ``ck=None`` so the
# original semantics (blank == None or whitespace) are preserved.
def _is_blank_reading(v: Any) -> bool:
    return _is_effectively_empty(None, v)


def normalize_readings(source: Any) -> Dict[str, Any]:
    """Coerce a ``chemical_readings`` payload into a flat
    ``{canonical_key: value}`` dict.  Accepts:

    * list-of-dicts:   ``[{"key": "chlorine", "value": 2.5}, …]``
                       — the ``service_reports.chemical_readings`` shape.
    * dict:            ``{"chlorine": 2.5, …}``
                       — the legacy ``jobs.chemical_readings`` shape.

    Unknown / unaliased keys are dropped.

    Phase P17 · Feb-2026 — two-pass dedupe.  Rewrites the CHEM2
    merge as an order-independent two-pass loop:

        1. Pass 1 walks every input entry and buckets ``(raw_key,
           value)`` tuples under the resolved canonical key.
        2. Pass 2 picks the winner per canonical key using these
           rules, in order:

              a. If any candidate is non-empty (see
                 :func:`_is_effectively_empty`) and any candidate
                 is empty, drop the empty ones.
              b. If exactly one non-empty candidate survives, it
                 wins.
              c. If multiple non-empty candidates survive AND one
                 of them is spelled with the canonical key
                 (``_norm_key(raw_key) == ck``), it wins.
              d. Otherwise the alphabetically-first alias (by
                 normalised key) wins — deterministic tie-break.
              e. Every collision at rules (c)/(d) logs a WARN so
                 ops can hunt down duplicate writes.
              f. All-empty buckets still emit a single entry under
                 the canonical key (first-seen value) so downstream
                 gate assertions can report "missing" cleanly.
    """
    # ── Pass 1 · bucket candidates ─────────────────────────────
    buckets: Dict[str, List[Tuple[Any, Any]]] = {}

    if isinstance(source, dict):
        iter_items: List[Tuple[Any, Any]] = list(source.items())
    elif isinstance(source, list):
        iter_items = []
        for row in source:
            if not isinstance(row, dict):
                continue
            raw = row.get("key") or row.get("name")
            iter_items.append((raw, row.get("value")))
    else:
        return {}

    for raw_key, val in iter_items:
        ck = _canonical_key(raw_key)
        if not ck:
            continue
        buckets.setdefault(ck, []).append((raw_key, val))

    # ── Pass 2 · pick winner per canonical ─────────────────────
    out: Dict[str, Any] = {}
    for ck, candidates in buckets.items():
        non_empty = [
            (rk, v) for (rk, v) in candidates
            if not _is_effectively_empty(ck, v)
        ]
        if not non_empty:
            # All empty — preserve first-seen so downstream gate
            # calls still report a missing entry cleanly.
            out[ck] = candidates[0][1]
            continue

        if len(non_empty) == 1:
            out[ck] = non_empty[0][1]
            continue

        # Multiple real values — canonical spelling wins, else the
        # alphabetically-first alias (by normalised key) for
        # determinism.
        canonical_hits = [
            (rk, v) for (rk, v) in non_empty if _norm_key(rk) == ck
        ]
        if canonical_hits:
            winner_raw, winner_val = canonical_hits[0]
        else:
            winner_raw, winner_val = sorted(
                non_empty, key=lambda t: _norm_key(t[0]),
            )[0]

        dropped = [
            rk for (rk, v) in non_empty
            if not (rk == winner_raw)
        ]
        logger.warning(
            "[chem-normalize] %s alias collision — keeping %s, "
            "dropped %s",
            ck, winner_raw, dropped,
        )
        out[ck] = winner_val

    return out


def missing_core_readings(source: Any) -> List[str]:
    """Return the machine-friendly SHORT label list of MISSING core
    readings (matches ``missing_fields`` in the 422 payload).
    Empty list means the gate would pass."""
    norm = normalize_readings(source)
    return [_LABEL[k] for k in CORE_READINGS
            if not _is_gate_valid(k, norm.get(k))]


def missing_core_reading_labels(source: Any) -> List[str]:
    """Return the human-friendly DISPLAY label list of MISSING core
    readings (matches ``missing_labels`` in the 422 payload).  Same
    ordering as :func:`missing_core_readings`."""
    norm = normalize_readings(source)
    return [DISPLAY_LABELS[k] for k in CORE_READINGS
            if not _is_gate_valid(k, norm.get(k))]


def assert_core_readings_present(source: Any) -> None:
    """Raise ``HTTPException(422)`` when any of the four core
    chemistry readings is missing.  Uses the same detail shape
    across every call site so the FE can key off ``detail`` and
    render ``missing_fields`` / ``missing_labels`` inline.
    """
    norm = normalize_readings(source)
    missing_keys = [k for k in CORE_READINGS
                    if not _is_gate_valid(k, norm.get(k))]
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
                    if not _is_gate_valid(k, norm.get(k))]
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
