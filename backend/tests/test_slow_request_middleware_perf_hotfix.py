"""P1 PERF-HOTFIX · Feb-2026 — slow-request log threshold + route pattern.

Pins the two observability contracts of ``_ServerTimingMiddleware`` in
``backend/server.py``:

  1. Slow-request threshold is **1500ms** (lowered from 5000ms) so a
     2-5s regression on the customer-profile mount endpoints
     (``/customers/{id}/kpi-summary``, ``/jobs?customer_id=...``,
     ``/quotes?customer_id=...``) emits a ``slow_request`` warning
     the operator can grep out of prod logs.
  2. The warning line carries a ``route=<fastapi_pattern>`` field
     (e.g. ``route=/api/customers/{cid}/kpi-summary``) alongside the
     existing bucketed ``path=`` (e.g. ``path=/api/customers/:uuid/kpi-summary``).
     The route pattern is bounded-cardinality by construction (one
     entry per registered FastAPI endpoint) so operators can group
     without the ``path=`` bucketing hiding adjacent endpoints.

The middleware source lives at ``backend/server.py:_ServerTimingMiddleware``.
This test asserts the thresholds + log shape by inspecting the
in-file source rather than booting FastAPI, which keeps the test
hermetic (no DB, no auth stack).
"""
from __future__ import annotations

import re
from pathlib import Path


_SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"


def _read_middleware_block() -> str:
    """Return the raw text of the ``_ServerTimingMiddleware`` class
    body + the following ``app.add_middleware(...)`` call. Narrow
    enough that the assertions are unambiguous but wide enough to
    cover the slow-request log statement."""
    src = _SERVER_PY.read_text(encoding="utf-8")
    m = re.search(
        r"class _ServerTimingMiddleware.*?app\.add_middleware\(_ServerTimingMiddleware\)",
        src, re.DOTALL,
    )
    assert m, "Could not locate _ServerTimingMiddleware class block"
    return m.group(0)


def test_slow_request_threshold_is_1500ms():
    """Threshold must be 1500ms, not the legacy 5000ms."""
    block = _read_middleware_block()
    # Exactly one guard clause of the form ``if dur_ms > 1500``.
    assert re.search(r"if\s+dur_ms\s*>\s*1500\b", block), (
        "slow-request threshold must be lowered to 1500ms "
        "(PERF-HOTFIX; blocked 2-5s regressions were hiding under "
        "the 5000ms floor on customer-profile mount endpoints)"
    )
    # Explicit regression guard: the legacy 5000 ms literal must
    # NOT appear as a bare threshold in this block.
    assert not re.search(r"if\s+dur_ms\s*>\s*5000\b", block), (
        "regression — the 5000ms slow-request threshold should "
        "have been replaced by the 1500ms PERF-HOTFIX threshold"
    )


def test_slow_request_log_line_contains_route_pattern_field():
    """The warning log must emit ``route=`` sourced from the matched
    FastAPI route pattern (not just the bucketed path)."""
    block = _read_middleware_block()
    # The slow-request log must include ``route={_route_pattern}``.
    assert re.search(r'f["\'][^"\']*\broute=\{_route_pattern\}', block), (
        "slow_request warning must include the ``route={pattern}`` "
        "field so operators can group by matched FastAPI endpoint "
        "without the bucketed path merging adjacent routes"
    )
    # The matched route is sourced via ``request.scope.get('route')``
    # + its ``.path`` attribute (Starlette APIRoute path_format).
    assert "request.scope.get(\"route\")" in block or \
           "request.scope.get('route')" in block, (
        "route pattern must be sourced from "
        "``request.scope.get('route')`` — the FastAPI/Starlette ASGI "
        "scope slot populated after the router matches"
    )
    assert 'getattr(_route, "path", None)' in block or \
           "getattr(_route, 'path', None)" in block, (
        "route pattern must fall back to the bucketed path when "
        "``.path`` is absent (unmatched 404s, auth bail-outs)"
    )


def test_route_pattern_falls_back_to_bucketed_path_on_unmatched_request():
    """Robustness — when the ASGI scope has no matched route (404s,
    auth-rejected pre-match), the warning must still fire with
    ``route=`` populated by the bucketed path fallback."""
    block = _read_middleware_block()
    # The fallback chain: ``getattr(_route, "path", None) or bucketed``
    assert re.search(
        r'getattr\(_route,\s*["\']path["\']\s*,\s*None\)\s*or\s+bucketed',
        block,
    ), (
        "``_route_pattern`` must fall back to the bucketed path "
        "when the matched route is absent — otherwise unmatched "
        "requests (404s, auth bail-outs) blow up the warning path "
        "with a None field"
    )
