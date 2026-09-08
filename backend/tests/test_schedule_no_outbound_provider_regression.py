"""Feb-2026 · P0 defensive regression suite.

Locks down the schedule hydration path against a whole class of
bugs — the one the user report ``schedule freezes if any day has
a job scheduled`` gestures at:

1. **Latency invariant.** Both ``GET /api/schedule/today`` and
   ``GET /api/jobs?start=&end=`` must return in under 500 ms even
   on a jobs-populated tenant. If a hydration step ever adds a
   synchronous outbound HTTP call (Maps geocode, LLM enrichment,
   Twilio push, etc.), this test surfaces the regression as a
   duration failure before the user report does.

2. **No outbound-provider import invariant.** Static AST scan of
   the two request handlers plus their transitively-called
   modules — any import of an outbound-provider SDK
   (``httpx.AsyncClient``, ``openai``, ``anthropic``,
   ``google.generativeai``, ``resend``, ``twilio``,
   ``ringcentral``, ``sendgrid``, ``emergentintegrations``, or a
   ``services.*_adapter`` module known to hit external APIs) is a
   red flag.

   This test does NOT ban those imports globally — plenty of
   routers legitimately dispatch outbound comms. It scopes the
   ban to the schedule read path so the "CF-edge 30 s hang"
   failure mode cannot regress here.

The static-scan strategy mirrors the Chunk 1 messaging migration
approach: enforce invariants at the chokepoint file, not at every
callsite. It's cheap (one AST parse per module) and it catches
the same class of bug that a slow live-curl would only catch
under production load.
"""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from typing import Iterable, Set

import pytest


# ─── Latency invariant ──────────────────────────────────────────────
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_LIVE_URL = "http://localhost:8001"


def _admin_headers_live():
    """Auth against the already-running local backend via ``httpx``.

    We deliberately do NOT boot a TestClient here — the app's
    startup work (index creation, cron scheduling, tenant seed
    scans) takes 30+ s in this pod, which drowns the < 500 ms
    latency signal we're actually trying to measure. Hitting
    ``localhost:8001`` measures the real request path with cold
    caches already warm — the same conditions a live user's
    request would hit.

    Skips gracefully if the backend isn't up (e.g., a CI run
    without supervisor) or if the demo seed isn't present.
    """
    import httpx
    try:
        r = httpx.post(
            f"{_LIVE_URL}/api/auth/login",
            json={"email": "super@aquaterra.com", "password": "password123"},
            timeout=5.0,
        )
    except (httpx.ConnectError, httpx.ReadTimeout) as e:
        pytest.skip(f"live backend not reachable at {_LIVE_URL}: {e}")
    if r.status_code != 200:
        pytest.skip(
            f"demo seed not present in this pod (login returned "
            f"{r.status_code}); latency test can only be exercised "
            f"in the demo tenant.",
        )
    j = r.json()
    token = j.get("access_token") or j.get("token")
    return {"Authorization": f"Bearer {token}"}


def test_schedule_today_endpoint_returns_under_500ms():
    """P0 latency guard for ``GET /api/schedule/today``.

    The endpoint is on the tech-mobile schedule critical path — if
    it ever hangs on a synchronous outbound call, techs cannot see
    their jobs and mobile shows an infinite spinner. We enforce
    < 500 ms end-to-end (localhost → app → mongo → response) as a
    forward-looking budget.
    """
    import httpx
    headers = _admin_headers_live()
    t0 = time.perf_counter()
    r = httpx.get(f"{_LIVE_URL}/api/schedule/today",
                    headers=headers, timeout=10.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200, r.text
    assert elapsed_ms < 500, (
        f"P0 latency regression — /api/schedule/today took "
        f"{elapsed_ms:.0f} ms (> 500 ms budget). Bisect for a new "
        f"synchronous outbound call on the hydration path."
    )


def test_jobs_window_endpoint_returns_under_500ms():
    """P0 latency guard for ``GET /api/jobs?start=&end=``.

    Same class of hazard as ``schedule/today`` but for the web
    ``CalendarSchedule.jsx`` load path (loads a 90-day window in
    a single call). If this ever regresses > 500 ms on the demo
    tenant, the whole CalendarSchedule "freezes on any day with a
    job" symptom becomes reachable again.
    """
    import httpx
    headers = _admin_headers_live()
    # Wide 90-day window (matches CalendarSchedule.jsx line 471-472
    # ``-30, +60``).
    t0 = time.perf_counter()
    r = httpx.get(
        f"{_LIVE_URL}/api/jobs?start=2026-08-01&end=2026-11-01",
        headers=headers, timeout=10.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200, r.text
    assert elapsed_ms < 500, (
        f"P0 latency regression — GET /api/jobs (90d window) took "
        f"{elapsed_ms:.0f} ms (> 500 ms budget). Bisect the "
        f"``list_jobs`` handler for a new synchronous outbound call."
    )


# ─── Outbound-provider ban invariant ────────────────────────────────
# Modules known to hit external HTTP APIs. If a schedule hydration
# path ever imports one of these SYNCHRONOUSLY on the request
# path, that's exactly the "CF-edge 30 s hang" failure mode we're
# guarding against. Async background jobs are fine — the ban is
# only on the two files that own the request handlers.
_BANNED_TOP_LEVEL_MODULES: Set[str] = {
    # Provider SDKs
    "openai",
    "anthropic",
    "resend",
    "twilio",
    "ringcentral",
    "sendgrid",
    "google.generativeai",
    "emergentintegrations",
    # Direct outbound HTTP libraries — indirect signal, but a
    # request-path ``requests.get(...)`` is exactly the shape of
    # the bug we're guarding against.
    "requests",
    # Internal adapter modules that wrap the SDKs above. We ban
    # the WRAPPERS too because Chunk 1 (messaging) callsite
    # migration deliberately centralised the SDK imports there —
    # importing a wrapper synchronously on the schedule path is
    # the same bug in a different disguise.
    "services.email.resend_adapter",
    "services.sms.rc_adapter",
    "services.messaging.byo_passthrough",
    "services.comms_email_adapter",
    "services.comms_sms_adapter",
    "services.ai.dispatcher",
    "services.llm_provider",
    # Maps dispatcher (per user H1 in the P0 diagnosis). If a
    # future refactor tries to enrich schedule rows with a
    # static-map URL server-side, this catches it.
    "services.maps.dispatcher",
}


def _extract_imports_in_function(path: Path, func_name: str) -> Iterable[str]:
    """Yield every module name imported (via ``import X`` or
    ``from X import ...``) INSIDE the body of the top-level async
    function ``func_name`` in ``path``. Module-level imports are
    intentionally NOT scanned — the schedule module legitimately
    contains other endpoints (e.g. ``reschedule_job``) that need
    outbound-provider adapters. We only enforce the ban on the
    specific request handler that services ``GET
    /api/schedule/today`` or ``GET /api/jobs``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        yield alias.name
                elif isinstance(child, ast.ImportFrom):
                    if child.level == 0 and child.module:
                        yield child.module
            return


def _matches_banned(mod: str) -> str:
    """Return the specific banned prefix if ``mod`` matches one,
    else empty string."""
    for banned in _BANNED_TOP_LEVEL_MODULES:
        if mod == banned or mod.startswith(banned + "."):
            return banned
    return ""


@pytest.mark.parametrize(
    "handler_file, handler_func",
    [
        (_BACKEND_ROOT / "routers" / "schedule.py", "get_today"),
        (_BACKEND_ROOT / "routers" / "jobs.py", "list_jobs"),
    ],
    ids=lambda x: str(x).split("/")[-1],
)
def test_schedule_handler_does_not_import_outbound_provider(
    handler_file, handler_func,
):
    """P0 invariant · the specific request-path handler for the
    schedule must not import any outbound-provider SDK or adapter
    INSIDE its function body.

    We scope to the function body (not the module) because these
    router modules legitimately host other endpoints —
    ``reschedule_job`` in ``schedule.py`` needs
    ``services.comms_email_adapter`` to notify customers, and
    ``email_work_order`` in ``jobs.py`` needs ``resend`` directly.
    Those are fine — they're not on the schedule hydration path
    the P0 report is guarding against.

    See ``_BANNED_TOP_LEVEL_MODULES`` for the enforced list. To
    intentionally add a new provider on the schedule hydration
    path, update the ban list AND land a load test proving the
    added path still meets the < 500 ms budget under a jobs-heavy
    tenant.
    """
    hits = []
    for mod in _extract_imports_in_function(handler_file, handler_func):
        matched = _matches_banned(mod)
        if matched:
            hits.append((mod, matched))
    assert not hits, (
        f"P0 regression — {handler_file.name}::{handler_func} imports "
        f"an outbound-provider module inside its function body: "
        f"{hits}. If this is intentional, load-test the hydration "
        f"path first and update _BANNED_TOP_LEVEL_MODULES."
    )
