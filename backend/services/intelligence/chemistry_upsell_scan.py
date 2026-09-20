"""Phase A2 · Feb-2026 · Proactive Intelligence — Chemistry Upsell scan.

Producer #2 for the ``intelligence_alerts`` store. Detects
customers whose last three completed visits show chemistry
readings that were out of the tenant's configured target band on
the SAME side (all three high, or all three low — a mixed set is
ignored). Each hit becomes a ``recommended`` alert under
``category="chemistry_upsell"`` with a suggested corrective
service pinned in ``actor_context.recommended_action``.

Data model
----------
* Chemistry readings live on ``service_reports`` at
  ``chemical_readings: [{key, name, value, unit}, ...]``.
* Reports are linked to the tenant via ``jobs`` (through
  ``job_id`` → ``jobs.tenant_id`` / ``customer_id``).
* Tenant target bands live at ``tenants.settings.chemistry.targets.{key}``
  with ``{min, max, ideal, unit}``. See
  :mod:`services.chemistry_tenant_targets` for the merge helper
  used elsewhere; here we intentionally read the RAW stored
  ``targets`` block so unconfigured measurements are skipped (per
  the Phase A2 brief) instead of falling back to AZ defaults.

Idempotency + shift semantics
-----------------------------
* Alert key is ``chemistry_upsell:cust:{customer_id}:{measurement}:v{hash}``
  where ``hash`` is a short deterministic hash of the three sorted
  report IDs. Rerunning the scan for the same trio is a no-op
  (dedup wins). When a new visit lands and the trailing-three
  window shifts, the hash changes → a fresh alert can emit. Older
  alerts remain in the store (historical); a dismissed alert
  stays dismissed even after the window shifts.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config import db
from services.intelligence.alerts import emit_alert

logger = logging.getLogger("intelligence.chemistry_upsell_scan")


# ── Recommendation lookup — per (measurement, direction). Values
# are ``(action_slug, human_label)``. ``action_slug`` is what the
# frontend passes as the ``service_type`` query-param to the
# quote-new prefill; ``human_label`` is what the alert title says.
_RECO: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("salt",             "high"): ("filter_clean",          "Filter clean recommended"),
    ("salt",             "low"):  ("salt_addition",         "Salt addition recommended"),
    ("calcium_hardness", "high"): ("partial_drain",         "Partial drain recommended"),
    ("calcium_hardness", "low"):  ("water_treatment",       "Water treatment recommended"),
    ("cyanuric_acid",    "high"): ("partial_drain",         "Partial drain recommended"),
    ("cyanuric_acid",    "low"):  ("stabilizer_addition",   "Stabilizer addition recommended"),
    ("ph",               "high"): ("ph_treatment",          "pH balancing recommended"),
    ("ph",               "low"):  ("ph_treatment",          "pH balancing recommended"),
    ("free_chlorine",    "high"): ("chlorine_treatment",    "Chlorine balance recommended"),
    ("free_chlorine",    "low"):  ("chlorine_treatment",    "Chlorine balance recommended"),
    ("alkalinity",       "high"): ("alkalinity_treatment",  "Alkalinity balancing recommended"),
    ("alkalinity",       "low"):  ("alkalinity_treatment",  "Alkalinity balancing recommended"),
}
_FALLBACK_RECO: Tuple[str, str] = ("chemistry_review", "Chemistry review recommended")

# Human labels for the measurement (used in title / body).
_MEASUREMENT_LABELS: Dict[str, str] = {
    "salt":             "salt",
    "calcium_hardness": "calcium hardness",
    "cyanuric_acid":    "cyanuric acid",
    "ph":               "pH",
    "free_chlorine":    "free chlorine",
    "alkalinity":       "alkalinity",
}


def _hash_visit_ids(ids: Iterable[str]) -> str:
    """Short deterministic hash of the three sorted visit/report IDs.
    Kept to 12 hex chars — collision risk is negligible at the
    per-customer scope but the string stays log-readable."""
    joined = "|".join(sorted(str(i) for i in ids))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _coerce_reading(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pick_reading(report: Dict[str, Any], key: str) -> Optional[float]:
    """Extract the numeric reading for ``key`` from a service report,
    tolerating both the ``chemical_readings`` array shape (canonical)
    and the ``readings`` array shape (some tenant seeds still use
    the shorter name)."""
    arrays = report.get("chemical_readings") or report.get("readings") or []
    if not isinstance(arrays, list):
        return None
    for row in arrays:
        if not isinstance(row, dict):
            continue
        row_key = row.get("key") or row.get("name")
        if row_key == key:
            return _coerce_reading(row.get("value"))
    return None


def _direction(values: List[float], tmin: float, tmax: float) -> Optional[str]:
    """Return ``"high"`` if every value is strictly > tmax,
    ``"low"`` if every value is strictly < tmin, otherwise None
    (mixed or in-band)."""
    if all(v > tmax for v in values):
        return "high"
    if all(v < tmin for v in values):
        return "low"
    return None


def _tenant_configured_targets(tenant_doc: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    """Read the RAW ``settings.chemistry.targets`` block and return
    only the keys with valid numeric min+max. Unlike
    ``services.chemistry_tenant_targets.merge_with_defaults``, this
    does NOT backfill AZ defaults — an unconfigured measurement
    yields no alerts."""
    stored = ((tenant_doc.get("settings") or {}).get("chemistry")
              or {}).get("targets") or {}
    out: Dict[str, Tuple[float, float]] = {}
    if not isinstance(stored, dict):
        return out
    for key, row in stored.items():
        if not isinstance(row, dict):
            continue
        raw_min = row.get("min")
        raw_max = row.get("max")
        if raw_min is None or raw_max is None:
            continue
        try:
            tmin = float(raw_min)
            tmax = float(raw_max)
        except (TypeError, ValueError):
            continue
        if tmax < tmin:
            continue
        out[key] = (tmin, tmax)
    return out


async def _iter_tenants(explicit: Optional[str]) -> List[Dict[str, Any]]:
    if explicit:
        row = await db.tenants.find_one(
            {"id": explicit},
            {"_id": 0, "id": 1, "settings": 1},
        )
        return [row] if row else []
    out: List[Dict[str, Any]] = []
    async for t in db.tenants.find(
        {"active": True},
        {"_id": 0, "id": 1, "settings": 1},
    ):
        if t.get("id"):
            out.append(t)
    return out


def _format_readings_line(
    values: List[float], unit: str, tmin: float, tmax: float,
) -> str:
    """Human single-line body — ``"Readings: 4200 / 4400 / 4600 ppm. Target: 2700-3400 ppm."``.
    Trailing period is intentional so the caller can join with a
    recommended-action sentence."""
    def _fmt(v: float) -> str:
        # Drop trailing zeros / decimal noise. pH stays two-decimal.
        if v == int(v):
            return str(int(v))
        return f"{v:g}"
    unit_s = f" {unit}" if unit else ""
    readings = " / ".join(_fmt(v) for v in values)
    target = f"{_fmt(tmin)}-{_fmt(tmax)}"
    return f"Readings: {readings}{unit_s}. Target: {target}{unit_s}."


async def _scan_one_tenant(tenant: Dict[str, Any]) -> Dict[str, int]:
    tid = tenant["id"]
    targets = _tenant_configured_targets(tenant)
    scanned = emitted = deduped = 0
    if not targets:
        return {"scanned_customers": 0, "alerts_emitted": 0,
                "alerts_deduped": 0}

    # For each customer under the tenant, pull the last three
    # submitted service reports (via their jobs).
    async for cust in db.customers.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1},
    ):
        cid = cust.get("id")
        if not cid:
            continue
        scanned += 1
        jobs = await db.jobs.find(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "id": 1},
        ).to_list(20000)
        jids = [j["id"] for j in jobs if j.get("id")]
        if not jids:
            continue
        reports = await db.service_reports.find(
            {"job_id":       {"$in": jids},
             "submitted_at": {"$ne": None}},
            {"_id": 1, "job_id": 1, "submitted_at": 1,
             "chemical_readings": 1, "readings": 1},
        ).sort("submitted_at", -1).limit(3).to_list(3)
        if len(reports) < 3:
            continue

        # Deterministic per-trio id list for the dedup hash + the
        # most recent report drives the alert's ``job_id`` link.
        report_ids = [str(r.get("_id")) for r in reports]
        vhash = _hash_visit_ids(report_ids)
        newest = reports[0]

        for key, (tmin, tmax) in targets.items():
            trio: List[Optional[float]] = [
                _pick_reading(r, key) for r in reports
            ]
            if any(v is None for v in trio):
                continue
            values: List[float] = [v for v in trio if v is not None]
            direction = _direction(values, tmin, tmax)
            if direction is None:
                continue
            action_slug, action_label = _RECO.get(
                (key, direction), _FALLBACK_RECO,
            )
            label = _MEASUREMENT_LABELS.get(key, key.replace("_", " "))
            unit = ""
            first_row = ((reports[0].get("chemical_readings")
                           or reports[0].get("readings") or []))
            for row in (first_row if isinstance(first_row, list) else []):
                if isinstance(row, dict) and (
                    row.get("key") == key or row.get("name") == key
                ):
                    unit = row.get("unit") or ""
                    break

            direction_word = "High" if direction == "high" else "Low"
            title = (f"{direction_word} {label} for 3 visits — "
                     f"{action_label.lower()}")
            body = (f"{_format_readings_line(values, unit, tmin, tmax)} "
                    f"Suggest a {action_slug.replace('_', ' ')} upsell.")

            # Ordered visit ids are the reports newest → oldest to
            # match the readings order in ``body`` / ``actor_context``.
            ordered_ids = report_ids
            actor_context = {
                "measurement":          key,
                "direction":            direction,
                "readings":             values,
                "visit_ids":            ordered_ids,
                "target_min":           tmin,
                "target_max":           tmax,
                "unit":                 unit,
                "recommended_action":   action_slug,
                "suggested_service_type": action_slug,
            }

            alert_key = (
                f"chemistry_upsell:cust:{cid}:{key}:v{vhash}"
            )
            inserted, _doc = await emit_alert(
                tid,
                category="chemistry_upsell",
                severity="recommended",
                alert_key=alert_key,
                title=title,
                body=body,
                customer_id=cid,
                job_id=newest.get("job_id"),
                actor_context=actor_context,
            )
            if inserted:
                emitted += 1
            else:
                deduped += 1

    return {
        "scanned_customers": scanned,
        "alerts_emitted":    emitted,
        "alerts_deduped":    deduped,
    }


async def run_chemistry_upsell_scan(
    tenant_id: Optional[str] = None,
    now: Optional[datetime] = None,   # noqa: ARG001 — reserved for parity
) -> Dict[str, Any]:
    """Scan each active tenant (or one specific tenant when
    ``tenant_id`` is set) for chemistry-upsell candidates.

    ``now`` is accepted for API parity with the A1 missed-service
    scan (some future test may want to freeze the clock); the
    logic here doesn't currently depend on the wall clock because
    the trailing-three-visits window is data-driven.

    :returns: Aggregate summary dict plus per-tenant breakdown.
    """
    tenants = await _iter_tenants(tenant_id)
    aggregate: Dict[str, Any] = {
        "tenant_id":          tenant_id,
        "scanned_customers":  0,
        "alerts_emitted":     0,
        "alerts_deduped":     0,
        "by_tenant":          {},
    }
    for t in tenants:
        summary = await _scan_one_tenant(t)
        aggregate["scanned_customers"] += summary["scanned_customers"]
        aggregate["alerts_emitted"]    += summary["alerts_emitted"]
        aggregate["alerts_deduped"]    += summary["alerts_deduped"]
        aggregate["by_tenant"][t["id"]] = summary
    if tenant_id and tenant_id in aggregate["by_tenant"]:
        aggregate.update(aggregate["by_tenant"][tenant_id])
        aggregate["by_tenant"] = {
            tenant_id: aggregate["by_tenant"][tenant_id]
        }
    return aggregate


async def run_chemistry_upsell_scan_all_tenants() -> Dict[str, Any]:
    """APScheduler entry point — no arguments. Wraps the tenant
    fan-out with logging so a failure in a single tenant is loud
    without crashing the scheduler thread."""
    try:
        result = await run_chemistry_upsell_scan(tenant_id=None)
        logger.info(
            "[chemistry-upsell-scan] scanned=%d emitted=%d "
            "deduped=%d tenants=%d",
            result["scanned_customers"], result["alerts_emitted"],
            result["alerts_deduped"], len(result["by_tenant"]),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("[chemistry-upsell-scan] failed: %s", exc)
        return {"error": str(exc)}
