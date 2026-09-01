"""Phase I3 · Feb-2026 — Comprehensive post-deploy health check.

Single super_admin-only endpoint that runs ten independent checks
against the live process + database so a human deploying can get a
GO / GO_WITH_WARNINGS / NO_GO verdict from one call.

Complements — does NOT replace — the anonymous k8s probes at
``/health/live`` and ``/health/ready``. Those two remain the
liveness / readiness contract for the orchestrator; this endpoint
exposes deeper internal state that we would never leak to an
unauthenticated caller (env-var presence, feature-gate values, RC
from-number resolution, etc.).

Never returns 5xx: every failure mode is encoded in the payload so
ops can grep the JSON. Each check is timed and independent — one
bad check can't tank the others.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends

from config import db
from utils import require_super_admin

logger = logging.getLogger("admin_health_check")
router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Constants — mirror the ``/health/ready`` gate list so a required
# migration missing is caught here too. Kept in sync manually; the
# short length makes churn cheap.
# ═══════════════════════════════════════════════════════════════════
REQUIRED_MIGRATIONS: List[str] = ["perf_customers_v1"]

# Environment variables the endpoint checks for presence. Missing =
# ``fail``; present but empty = ``warn``. Aligned with the H5.5
# integrations audit + the RC SMS + Stripe integration playbooks.
_REQUIRED_ENV = ["EMERGENT_LLM_KEY", "STRIPE_SECRET_KEY", "RC_SMS_DEFAULT_FROM"]

# Feature gates surfaced (informational only — never fail).
_FEATURE_GATES = [
    "SOSHIE_MODERATION_ENABLED",
    "SOSHIE_REGEX_PREFILTER_ENABLED",
    "INTEGRITY_CHECK_ENFORCE",
    "HEALTH_READY_INTEGRITY_CHECK",
    "ENABLE_SCHEDULER",
]

# Mongo ping ceiling — matches the k8s ready-probe ceiling so a
# comprehensive check doesn't get a rosier verdict than the
# readiness probe.
_MONGO_TIMEOUT_S = 0.5

# Hot-path smoke ceiling per call. 1s per call is generous — the
# routes themselves usually answer in <50ms.
_HOTPATH_TIMEOUT_S = 1.0


# ═══════════════════════════════════════════════════════════════════
# Timing helper — every check reports ``duration_ms``.
# ═══════════════════════════════════════════════════════════════════
async def _timed(name: str, coro_fn: Callable) -> Dict[str, Any]:
    """Run ``await coro_fn()`` and return a check-shaped dict.

    ``coro_fn`` must return ``(status, details)``. On raise the
    check is coerced to ``fail`` with the exception text truncated
    to 200 chars — comprehensive check never bubbles a 500.
    """
    t0 = time.monotonic()
    try:
        status, details = await coro_fn()
    except Exception as exc:  # noqa: BLE001 — defensive on every check
        logger.warning("[health-check] check %s raised: %s", name, exc)
        status = "fail"
        details = {"error": str(exc)[:200]}
    return {
        "name": name,
        "status": status,
        "details": details,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


# ═══════════════════════════════════════════════════════════════════
# Individual checks
# ═══════════════════════════════════════════════════════════════════
async def _check_boot_state() -> Any:
    # Read the F4 snapshot from ``server`` lazily so this module can
    # be imported before ``server`` has fully evaluated (matters at
    # test-suite bootstrap time).
    import server as _srv
    state = _srv._F4_BOOT_INTEGRITY_STATE  # noqa: SLF001
    if not state.get("complete"):
        return "warn", {
            "complete": False,
            "reason": "boot_integrity_pending",
            "dangling_refs_total": state.get("dangling_refs_total"),
        }
    if state.get("error"):
        return "fail", {
            "complete": True,
            "error": str(state["error"])[:200],
            "dangling_refs_total": state.get("dangling_refs_total"),
        }
    drt = int(state.get("dangling_refs_total") or 0)
    # Recovery-mode signal: mirror the ``/health/ready`` semantics.
    enforce = (os.environ.get("INTEGRITY_CHECK_ENFORCE") or "").strip().lower()
    is_enforced = enforce not in ("false", "0", "off", "no")
    if drt > 0 and is_enforced:
        return "fail", {
            "complete": True,
            "dangling_refs_total": drt,
            "integrity_check_enforce": True,
        }
    if drt > 0:
        return "warn", {
            "complete": True,
            "dangling_refs_total": drt,
            "integrity_check_enforce": False,
            "note": "recovery_mode",
        }
    return "ok", {"complete": True, "dangling_refs_total": 0}


async def _check_mongo_ping() -> Any:
    try:
        await asyncio.wait_for(db.command("ping"), timeout=_MONGO_TIMEOUT_S)
        return "ok", {"timeout_s": _MONGO_TIMEOUT_S}
    except asyncio.TimeoutError:
        return "fail", {"error": "mongo_ping_timeout",
                            "timeout_s": _MONGO_TIMEOUT_S}


async def _check_required_migrations() -> Any:
    missing: List[str] = []
    for key in REQUIRED_MIGRATIONS:
        row = await db.migration_status.find_one(
            {"key": key}, {"_id": 0, "completed_at": 1},
        )
        if not row or not row.get("completed_at"):
            missing.append(key)
    if missing:
        return "fail", {"missing": missing, "required": REQUIRED_MIGRATIONS}
    return "ok", {"applied": REQUIRED_MIGRATIONS}


async def _check_optional_migrations() -> Any:
    # A "pending" optional migration = a ``migration_status`` row
    # without ``completed_at`` whose key is not in
    # ``REQUIRED_MIGRATIONS``. In practice migration writers only
    # insert on completion, so this is expected to be empty. When
    # non-empty it's a warn — some background sentinel got stuck
    # part-way, or someone hand-inserted a placeholder.
    required = set(REQUIRED_MIGRATIONS)
    pending: List[str] = []
    async for row in db.migration_status.find(
        {"completed_at": {"$in": [None, ""]}}, {"_id": 0, "key": 1},
    ):
        key = row.get("key")
        if key and key not in required:
            pending.append(key)
    if pending:
        return "warn", {"pending": sorted(pending),
                            "pending_count": len(pending)}
    return "ok", {"pending": [], "pending_count": 0}


async def _check_hotpath_smoke() -> Any:
    """Exercise three critical read paths WITHOUT going through the
    HTTP stack. The intent is verifying the DB-backed handlers work
    end-to-end; a broken index or a Mongo permission drift would
    surface here before an operator finds it via the frontend."""
    results: Dict[str, Any] = {}
    overall = "ok"

    # Customers list — mimic the shape the ``GET /customers`` handler
    # uses (single tenant scope isn't required for the smoke; we're
    # just verifying the index + count path answers).
    try:
        n = await asyncio.wait_for(
            db.customers.count_documents({}, limit=1),
            timeout=_HOTPATH_TIMEOUT_S,
        )
        results["customers_list"] = {"status": "ok", "count_probe": int(n)}
    except Exception as exc:  # noqa: BLE001
        results["customers_list"] = {"status": "fail",
                                        "error": str(exc)[:120]}
        overall = "fail"

    # Jobs list — same pattern.
    try:
        n = await asyncio.wait_for(
            db.jobs.count_documents({}, limit=1),
            timeout=_HOTPATH_TIMEOUT_S,
        )
        results["jobs_list"] = {"status": "ok", "count_probe": int(n)}
    except Exception as exc:  # noqa: BLE001
        results["jobs_list"] = {"status": "fail",
                                    "error": str(exc)[:120]}
        overall = "fail"

    # Readiness handler — call directly, don't round-trip HTTP.
    try:
        from server import _k8s_health_ready  # noqa: PLC0415
        ready_resp = await asyncio.wait_for(
            _k8s_health_ready(), timeout=_HOTPATH_TIMEOUT_S,
        )
        # _k8s_health_ready returns either a dict or a JSONResponse
        # depending on failure state — coerce for reporting.
        if hasattr(ready_resp, "status_code"):
            code = int(getattr(ready_resp, "status_code", 0))
            results["health_ready"] = {"status": "warn" if code >= 500
                                          else "ok",
                                          "http_status": code}
            if code >= 500:
                overall = "warn" if overall == "ok" else overall
        else:
            body_status = (ready_resp or {}).get("status")
            results["health_ready"] = {"status": "ok",
                                          "handler_status": body_status}
    except Exception as exc:  # noqa: BLE001
        results["health_ready"] = {"status": "fail",
                                      "error": str(exc)[:120]}
        overall = "fail"

    return overall, results


async def _check_comms_gate() -> Any:
    """Verify the dispatch_guard module is importable + exposes
    ``guard_and_log``. This is the H5.5 discovery: comms are
    idempotency-gated by the dispatch_guard collection, and a
    boot-time import failure would leave the pipeline duplicating
    sends. We check module state, not runtime behavior."""
    try:
        from services.comms_hardening import dispatch_guard as _dg  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": f"import_failed: {str(exc)[:120]}"}
    if not callable(getattr(_dg, "guard_and_log", None)):
        return "fail", {"error": "guard_and_log_not_callable"}
    if not callable(getattr(_dg, "mark_dispatch_result", None)):
        return "warn", {"note": "mark_dispatch_result_missing"}
    return "ok", {"module": "services.comms_hardening.dispatch_guard",
                     "guard_and_log": True,
                     "mark_dispatch_result": True}


async def _check_rc_from_number(tenant_id: Optional[str]) -> Any:
    """Ask the RC SMS adapter to resolve a from-number for the
    caller's tenant. Priority is tenant.rc_sms_from_number →
    RC_SMS_DEFAULT_FROM → RC extension auto-lookup. A ``None`` from
    this means the RC client will raise inside every send."""
    try:
        from services.sms.rc_adapter import RingCentralSMSAdapter  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": f"import_failed: {str(exc)[:120]}"}
    try:
        adapter = RingCentralSMSAdapter()
        resolved = await adapter._resolve_from(tenant_id)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": f"resolve_failed: {str(exc)[:120]}"}
    if not resolved:
        return "fail", {"resolved": None,
                            "note": "no_from_number_resolvable"}
    # Never leak the actual number in the response — surface presence
    # only. Ops can pull the setting via the RC-SMS settings API.
    return "ok", {"resolved": True,
                     "length": len(str(resolved))}


async def _check_scheduler() -> Any:
    """APScheduler flag + running state. When the app was booted
    with ``ENABLE_SCHEDULER=false`` (worker-split deployment) the
    scheduler is intentionally quiescent — that's OK; we surface it
    as a note in details."""
    try:
        import server as _srv  # noqa: PLC0415
        gate = bool(getattr(_srv, "_ENABLE_SCHEDULER", False))
        sched = getattr(_srv, "scheduler", None)
        running = bool(getattr(sched, "running", False)) if sched else False
        job_count = len(sched.get_jobs()) if sched and running else 0
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": str(exc)[:120]}
    if not gate:
        return "ok", {"enable_scheduler_gate": False,
                        "running": running, "job_count": job_count,
                        "note": "scheduler_disabled_by_gate"}
    if not running:
        return "fail", {"enable_scheduler_gate": True,
                          "running": False, "job_count": 0,
                          "note": "scheduler_expected_running_but_not"}
    return "ok", {"enable_scheduler_gate": True,
                     "running": True, "job_count": job_count}


async def _check_env_sanity() -> Any:
    """Every entry in ``_REQUIRED_ENV`` must be set. Missing = fail
    (deploy is broken). Present but empty = warn."""
    missing: List[str] = []
    empty: List[str] = []
    present: List[str] = []
    for key in _REQUIRED_ENV:
        raw = os.environ.get(key)
        if raw is None:
            missing.append(key)
        elif not raw.strip():
            empty.append(key)
        else:
            present.append(key)
    if missing:
        return "fail", {"missing": missing, "empty": empty,
                            "present_count": len(present)}
    if empty:
        return "warn", {"missing": [], "empty": empty,
                            "present_count": len(present)}
    return "ok", {"missing": [], "empty": [],
                     "present_count": len(present)}


async def _check_feature_gates() -> Any:
    """Feature-gate snapshot. Informational — every check row is
    ``ok``. When ``INTEGRITY_CHECK_ENFORCE=false`` we annotate the
    details with a recovery-mode signal so ops don't miss that the
    pod is running in a lenient posture."""
    values: Dict[str, str] = {}
    for key in _FEATURE_GATES:
        raw = os.environ.get(key)
        values[key] = raw if raw is not None else "(unset)"
    notes: List[str] = []
    ice = (os.environ.get("INTEGRITY_CHECK_ENFORCE") or "").strip().lower()
    if ice in ("false", "0", "off", "no"):
        notes.append("INTEGRITY_CHECK_ENFORCE=false — recovery mode")
    return "ok", {"values": values, "notes": notes}


# ═══════════════════════════════════════════════════════════════════
# Verdict + recommendations
# ═══════════════════════════════════════════════════════════════════
def _compute_verdict(checks: List[Dict[str, Any]]) -> str:
    statuses = [c.get("status") for c in checks]
    if "fail" in statuses:
        return "NO_GO"
    if "warn" in statuses:
        return "GO_WITH_WARNINGS"
    return "GO"


def _compute_summary(checks: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"checks_total": len(checks), "ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        s = c.get("status")
        if s in out:
            out[s] += 1
    return out


def _compute_recommendations(checks: List[Dict[str, Any]]) -> List[str]:
    recs: List[str] = []
    for c in checks:
        name = c.get("name")
        status = c.get("status")
        details = c.get("details") or {}
        if name == "boot_state" and status == "fail":
            recs.append(
                "Boot integrity scan failed — check backend startup "
                "logs and run the F2 data-repair dry-run before "
                "declaring GO.",
            )
        elif name == "boot_state" and status == "warn":
            if details.get("note") == "recovery_mode":
                recs.append(
                    f"{details.get('dangling_refs_total')} dangling "
                    "refs present but INTEGRITY_CHECK_ENFORCE=false. "
                    "Consider running Data Repair or re-enable "
                    "enforcement.",
                )
            elif not details.get("complete"):
                recs.append(
                    "Boot integrity scan still pending. Re-run the "
                    "health check in ~30s or check /health/ready.",
                )
        elif name == "mongo_ping" and status == "fail":
            recs.append(
                "Mongo ping timed out — verify MONGO_URL + network "
                "reachability from the pod.",
            )
        elif name == "required_migrations" and status == "fail":
            missing = details.get("missing") or []
            recs.append(
                f"Required migration(s) not applied: {', '.join(missing)}."
                " Check startup logs — the boot path is expected to "
                "run these automatically.",
            )
        elif name == "optional_migrations" and status == "warn":
            pending = details.get("pending") or []
            recs.append(
                f"{len(pending)} non-required migration(s) pending: "
                f"{', '.join(pending[:5])}"
                f"{'…' if len(pending) > 5 else ''}. Safe to GO, but "
                "investigate stuck sentinels.",
            )
        elif name == "hotpath_smoke" and status == "fail":
            failed = [k for k, v in details.items()
                          if isinstance(v, dict) and v.get("status") == "fail"]
            recs.append(
                "Hot-path smoke failing on: "
                f"{', '.join(failed) or 'unknown'}. Check backend logs.",
            )
        elif name == "comms_gate" and status != "ok":
            recs.append(
                "Comms dispatch guard module not fully loaded — every "
                "outbound send will bypass idempotency. Restart the "
                "pod and re-check.",
            )
        elif name == "rc_sms_from_number" and status == "fail":
            recs.append(
                "No RC SMS from-number resolvable for this tenant. "
                "Set RC_SMS_DEFAULT_FROM or configure a "
                "tenant.rc_sms_from_number.",
            )
        elif name == "scheduler" and status == "fail":
            recs.append(
                "APScheduler was expected to be running "
                "(ENABLE_SCHEDULER=true) but isn't. Restart the pod "
                "or check for a startup crash in the scheduler "
                "registration.",
            )
        elif name == "env_sanity" and status == "fail":
            missing = details.get("missing") or []
            recs.append(
                f"Missing required env vars: {', '.join(missing)}. "
                "Deploy is misconfigured — set them and redeploy.",
            )
        elif name == "env_sanity" and status == "warn":
            empty = details.get("empty") or []
            recs.append(
                f"Env vars present but empty: {', '.join(empty)}. "
                "Treated as unset by dependent integrations.",
            )
        elif name == "feature_gates":
            for note in (details.get("notes") or []):
                recs.append(note)
            # Explicit "unset" hints for the moderation gates so an
            # operator can see when they're relying on the default.
            values = details.get("values") or {}
            for key in ("SOSHIE_MODERATION_ENABLED",
                          "SOSHIE_REGEX_PREFILTER_ENABLED"):
                if values.get(key) == "(unset)":
                    recs.append(
                        f"{key} is unset (defaults to enabled) — set "
                        "explicitly for clarity.",
                    )
    return recs


# ═══════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/health-check/comprehensive")
async def comprehensive_health_check(
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Run every deploy-critical check in one call and return a
    verdict payload. Never 5xxes — every failure mode is encoded in
    the payload so ops can grep for it."""
    tenant_id = user.get("tenant_id")

    checks: List[Dict[str, Any]] = []
    checks.append(await _timed("boot_state", _check_boot_state))
    checks.append(await _timed("mongo_ping", _check_mongo_ping))
    checks.append(await _timed(
        "required_migrations", _check_required_migrations,
    ))
    checks.append(await _timed(
        "optional_migrations", _check_optional_migrations,
    ))
    checks.append(await _timed("hotpath_smoke", _check_hotpath_smoke))
    checks.append(await _timed("comms_gate", _check_comms_gate))
    checks.append(await _timed(
        "rc_sms_from_number",
        lambda: _check_rc_from_number(tenant_id),
    ))
    checks.append(await _timed("scheduler", _check_scheduler))
    checks.append(await _timed("env_sanity", _check_env_sanity))
    checks.append(await _timed("feature_gates", _check_feature_gates))

    verdict = _compute_verdict(checks)
    summary = _compute_summary(checks)
    recommendations = _compute_recommendations(checks)

    return {
        "overall_verdict": verdict,
        "tenant_id": tenant_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_version": os.environ.get("APP_VERSION") or "dev",
        "checks": checks,
        "summary": summary,
        "recommendations": recommendations,
    }
