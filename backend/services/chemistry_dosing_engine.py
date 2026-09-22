"""Sprint 3b · Feb-2026 — Sandboxed tenant-authored dosing formula engine.

Evaluates per-chemical dosing formulas authored by tenants using
``simpleeval`` as the safe expression evaluator.  Formulas are
short arithmetic expressions bound to a fixed-length list of names
and a whitelisted function set.

Whitelisted **names**:
    ``current``          — the reading value (ppm/pH)
    ``min_target``       — tenant's lower bound
    ``max_target``       — tenant's upper bound
    ``avg_target``       — bull's-eye (ideal) target
    ``volume_gallons``   — pool volume
    ``delta``            — ``avg_target - current`` (positive when short)

Whitelisted **functions**:
    ``abs``, ``min``, ``max``, ``round``

The whitelist matches EXACTLY what the AZ default formulas need —
no more, no less (per Sprint 3b brief).  ``math.log10`` and every
other builtin are deliberately excluded.

Every unsafe construct (attribute access, lambdas, list-comps,
imports, generator expressions, star-args) is blocked by SimpleEval
defaults; we assert two extra guards on top:
    * ``simpleeval.MAX_POWER = 100`` — kills the ``2**2**2**2**2``
      exponent-blow-up class of pathological formulas.
    * Formula string length capped at :data:`_FORMULA_MAX_LEN` chars.
    * Wall-clock cap at :data:`_TIMEOUT_S` seconds via
      ``concurrent.futures``.

On any error (bad syntax, unsafe construct, timeout, division by
zero, unbound name), :func:`evaluate` returns ``evaluation_ok=False``
with the underlying error string.  Callers may choose to fall back
to the AZ default formula (see :data:`AZ_DEFAULT_FORMULAS`) which is
itself a sandbox-safe SimpleEval string, so tenants can never poison
the fallback path.
"""
from __future__ import annotations

import concurrent.futures
import logging
import re
from typing import Any, Dict, Optional, Tuple

import simpleeval
from simpleeval import (
    FeatureNotAvailable,
    FunctionNotDefined,
    InvalidExpression,
    NameNotDefined,
    NumberTooHigh,
    SimpleEval,
)

log = logging.getLogger("chemistry_dosing_engine")

# ── Sandbox hardening. ─────────────────────────────────────────────
_FORMULA_MAX_LEN = 200
_TIMEOUT_S = 0.1
_SAFE_FUNCTIONS: Dict[str, Any] = {
    "abs":   abs,
    "min":   min,
    "max":   max,
    "round": round,
}
_ALLOWED_NAMES: Tuple[str, ...] = (
    "current",
    "min_target",
    "max_target",
    "avg_target",
    "volume_gallons",
    "delta",
)

# Cap exponent-blow-up formulas.  ``MAX_POWER=100`` means ``x**y``
# raises when ``y > 100`` — plenty of headroom for legitimate
# scaling factors, kills the pathological blow-up formulas.
simpleeval.MAX_POWER = 100
simpleeval.MAX_STRING_LENGTH = 1000


# ── AZ default formulas (each returns a numeric dose in the
# chemical's default unit — see module-level docstring in
# ``services.pool_dosing`` for the underlying chemistry).  Every
# formula uses only whitelisted names + functions and is round-trip
# equivalent to the hardcoded math in ``pool_dosing.compute``. ────
#
# Key: chemical + adjustment path.  ``ph`` is split into ``ph_up``
# (soda ash) and ``ph_down`` (muriatic acid). The others need only
# an "up" path — a "wait / drain" branch is a non-dose recommendation
# (see :func:`is_wait_case`).
AZ_DEFAULT_FORMULAS: Dict[str, str] = {
    # Liquid chlorine 12.5% — round(gallons, 2)
    # oz = 10 * delta/2 * scale (scale = gal/10000)
    # gal = oz / 128  ⇒  qty = delta * volume / 256000
    "chlorine":            "round(max(0, (avg_target - current) * volume_gallons / 256000), 2)",
    # Soda ash — round(lbs, 1)
    # oz = 6 * delta/0.2 * scale = 30*delta*volume/10000 ; lbs = oz/16
    "ph_up":               "round(max(0, (avg_target - current) * volume_gallons * 3 / 16000), 1)",
    # Muriatic acid — round(gal, 2)
    # oz = 8 * delta/0.2 * scale = 40*delta*volume/10000 ; gal = oz/128
    "ph_down":             "round(max(0, (current - avg_target) * volume_gallons / 32000), 2)",
    # Sodium bicarb — round(lbs, 1)
    # oz = 21 * delta/10 * scale = 21*delta*volume/100000 ; lbs = oz/16
    "alkalinity_up":       "round(max(0, (avg_target - current) * volume_gallons * 21 / 1600000), 1)",
    # Cyanuric acid granular — round(oz, 1)
    # oz = 13 * delta/10 * scale = 13*delta*volume/100000
    "cyanuric_acid_up":    "round(max(0, (avg_target - current) * volume_gallons * 13 / 100000), 1)",
    # Calcium chloride — round(oz, 1)
    # oz = 10 * delta/10 * scale = delta*volume/10000
    "calcium_hardness_up": "round(max(0, (avg_target - current) * volume_gallons / 10000), 1)",
    # Pool salt (NaCl) — round(lbs, 1)
    # lb = 25 * delta/300 * scale = delta*volume/120000
    "salt_up":             "round(max(0, (avg_target - current) * volume_gallons / 120000), 1)",
}

FORMULA_KEYS: Tuple[str, ...] = tuple(AZ_DEFAULT_FORMULAS.keys())


# ── Preflight guardrails (before we hand the string to SimpleEval).
# Cheap string-level rejects that surface a friendlier error than a
# post-parse SimpleEval exception. ─────────────────────────────────
# Matches ``identifier.identifier`` — used to reject attribute
# access (e.g. ``current.real``) at the preflight stage.  Kept as
# a compiled regex so we can reason about the exact pattern:
# start-of-token identifier, then a literal dot, then the first
# character of another identifier.  Numeric literals like
# ``0.00013`` are safe because the dot is preceded by a digit.
_ATTR_ACCESS_RE = re.compile(r"[A-Za-z_]\w*\s*\.\s*[A-Za-z_]")

_FORBIDDEN_SUBSTRINGS: Tuple[str, ...] = (
    "__",       # dunder anything
    "import",   # import statement or __import__ name
    "lambda",
    "\n",
    ";",
    "yield",
    "await",
    "async",
)


def _preflight(formula: str) -> Optional[str]:
    if not isinstance(formula, str):
        return "formula must be a string"
    if not formula.strip():
        return "formula is empty"
    if len(formula) > _FORMULA_MAX_LEN:
        return f"formula exceeds max length ({_FORMULA_MAX_LEN})"
    lowered = formula.lower()
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in lowered:
            return f"forbidden substring '{bad}'"
    if _ATTR_ACCESS_RE.search(formula):
        return "unsafe_construct: attribute access"
    return None


# ── Core evaluate. ─────────────────────────────────────────────────
_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _executor() -> concurrent.futures.ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="dosing-eval",
        )
    return _EXECUTOR


def _run_simpleeval(formula: str, names: Dict[str, Any]) -> Any:
    """Runs ``formula`` in a SimpleEval sandbox seeded with ``names``
    + the whitelisted function set. Raises on any evaluator error."""
    ev = SimpleEval(
        names=dict(names),
        functions=dict(_SAFE_FUNCTIONS),
    )
    return ev.eval(formula)


def _evaluate_raw(formula: str, names: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """Internal — returns ``(value_or_None, error_or_None)`` after
    running the formula on a worker thread with a wall-clock cap."""
    pre_err = _preflight(formula)
    if pre_err:
        return None, pre_err
    fut = _executor().submit(_run_simpleeval, formula, names)
    try:
        val = fut.result(timeout=_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        # Best-effort cancel — the SimpleEval thread will finish on
        # its own eventually. No IO involved, so it can't harm us.
        fut.cancel()
        return None, "timeout"
    except FeatureNotAvailable as ex:
        return None, f"unsafe_construct: {ex}"
    except FunctionNotDefined as ex:
        return None, f"unsafe_function: {ex}"
    except NameNotDefined as ex:
        return None, f"unknown_name: {ex}"
    except NumberTooHigh as ex:
        return None, f"number_too_high: {ex}"
    except InvalidExpression as ex:
        return None, f"bad_syntax: {ex}"
    except SyntaxError as ex:
        return None, f"bad_syntax: {ex}"
    except ZeroDivisionError:
        return None, "division_by_zero"
    except Exception as ex:                                       # noqa: BLE001
        return None, f"evaluation_error: {ex}"
    if not isinstance(val, (int, float)) or (isinstance(val, bool)):
        return None, "non_numeric_result"
    fv = float(val)
    if fv != fv or fv in (float("inf"), float("-inf")):
        return None, "non_finite_result"
    return fv, None


def evaluate(
    chemical: str,
    current: Any,
    target_range: Dict[str, Any],
    volume_gallons: Any,
    tenant_formula: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate a single dose recommendation.

    Args:
        chemical: One of :data:`FORMULA_KEYS` (``chlorine``,
            ``ph_up``, ``ph_down``, ``alkalinity_up``,
            ``cyanuric_acid_up``, ``calcium_hardness_up``,
            ``salt_up``).
        current: The current reading value (numeric or numeric string).
        target_range: ``{"min": float, "max": float, "ideal": float}``.
        volume_gallons: Pool volume in US gallons.
        tenant_formula: Optional tenant-authored SimpleEval formula.
            When present AND it evaluates cleanly, its result is
            returned; otherwise the AZ default is used and the
            tenant error is surfaced in the response.

    Returns:
        ``{recommended_dose_oz: float, formula_used: str,
           evaluation_ok: bool, source: "tenant"|"az_default",
           error?: str}``

        ``recommended_dose_oz`` is a legacy field name kept for
        compatibility with the Sprint 3b brief — the value is the
        raw numeric dose in the chemical's default unit (may be
        gallons/lbs/oz depending on the chemical). Downstream code
        is responsible for the unit label.
    """
    if chemical not in AZ_DEFAULT_FORMULAS:
        return {
            "recommended_dose_oz": 0.0,
            "formula_used": "",
            "evaluation_ok": False,
            "source": "unknown",
            "error": f"unknown_chemical: {chemical}",
        }
    try:
        c = float(current)
        v = float(volume_gallons)
        t_min = float(target_range.get("min"))
        t_max = float(target_range.get("max"))
        t_ideal = float(target_range.get("ideal", (t_min + t_max) / 2.0))
    except (TypeError, ValueError, AttributeError) as ex:
        return {
            "recommended_dose_oz": 0.0,
            "formula_used": "",
            "evaluation_ok": False,
            "source": "unknown",
            "error": f"invalid_inputs: {ex}",
        }
    names = {
        "current":        c,
        "min_target":     t_min,
        "max_target":     t_max,
        "avg_target":     t_ideal,
        "volume_gallons": v,
        "delta":          t_ideal - c,
    }
    tenant_error: Optional[str] = None
    if tenant_formula and tenant_formula.strip():
        val, err = _evaluate_raw(tenant_formula, names)
        if err is None:
            return {
                "recommended_dose_oz": float(val),
                "formula_used": tenant_formula.strip(),
                "evaluation_ok": True,
                "source": "tenant",
            }
        tenant_error = err
        log.info(
            "[dosing-engine] tenant formula rejected chemical=%s error=%s",
            chemical, err,
        )
    # Fall back to AZ default. This formula is authored in-repo and
    # cannot fail under sandbox constraints; a failure here would be
    # a code bug worth surfacing loudly.
    az_formula = AZ_DEFAULT_FORMULAS[chemical]
    val, err = _evaluate_raw(az_formula, names)
    if err is not None:
        log.error(
            "[dosing-engine] AZ default formula failed chemical=%s error=%s "
            "formula=%s names=%s",
            chemical, err, az_formula, names,
        )
        return {
            "recommended_dose_oz": 0.0,
            "formula_used": az_formula,
            "evaluation_ok": False,
            "source": "az_default",
            "error": err,
        }
    resp: Dict[str, Any] = {
        "recommended_dose_oz": float(val),
        "formula_used": az_formula,
        "evaluation_ok": True,
        "source": "az_default",
    }
    if tenant_error:
        resp["error"] = f"tenant_fallback: {tenant_error}"
    return resp


def dry_run_formula(formula: str) -> Dict[str, Any]:
    """Dry-run a candidate tenant formula against a synthetic
    reading + target + volume so the PATCH validator can reject bad
    formulas BEFORE they hit persistence.

    Returns ``{"ok": bool, "error"?: str, "sample_result"?: float}``.
    """
    names = {
        "current":        1.0,
        "min_target":     1.0,
        "max_target":     3.0,
        "avg_target":     2.0,
        "volume_gallons": 10_000.0,
        "delta":          1.0,
    }
    val, err = _evaluate_raw(formula, names)
    if err is not None:
        return {"ok": False, "error": err}
    return {"ok": True, "sample_result": float(val)}
