"""Sep-2026 · Per-tenant DFS creds · /test endpoint rate-limit.

Direct-unit coverage of the in-memory rate-limit primitive. The
HTTP /test endpoint calls this helper as its first line, so unit
coverage here is sufficient — a cross-process HTTP test can't
share the in-memory bucket with the running backend.
"""
from __future__ import annotations

import time
from unittest.mock import patch

from fastapi import HTTPException


def test_cap_boundary_behavior():
    from routers.tenant_dataforseo_integration import (
        _rate_limit_test, _reset_rate_limit_for_tests, _TEST_RL_CAP,
    )
    _reset_rate_limit_for_tests()
    tid = "cap-boundary"
    for _ in range(_TEST_RL_CAP):
        _rate_limit_test(tid)  # no raise
    try:
        _rate_limit_test(tid)
        assert False, "MUST raise 429 after CAP hits"
    except HTTPException as e:
        assert e.status_code == 429
        assert e.detail["code"] == "rate_limited"
        assert "5 runs per hour" in e.detail["hint"]


def test_bucket_is_per_tenant():
    """Tenant A hitting the cap does not block tenant B."""
    from routers.tenant_dataforseo_integration import (
        _rate_limit_test, _reset_rate_limit_for_tests, _TEST_RL_CAP,
    )
    _reset_rate_limit_for_tests()
    for _ in range(_TEST_RL_CAP):
        _rate_limit_test("tenant-a")
    try:
        _rate_limit_test("tenant-a")
        assert False, "tenant A should be at cap"
    except HTTPException:
        pass
    # Tenant B is unaffected.
    for _ in range(_TEST_RL_CAP):
        _rate_limit_test("tenant-b")  # no raise


def test_window_expiry_frees_new_calls():
    """Simulate 61 minutes elapsing by monkey-patching ``time.time``
    inside the router so the window resets."""
    from routers import tenant_dataforseo_integration as mod
    mod._reset_rate_limit_for_tests()
    tid = "window-expiry"
    for _ in range(mod._TEST_RL_CAP):
        mod._rate_limit_test(tid)
    # Advance the clock by > 3600s.
    real_now = time.time()
    with patch.object(mod, "time") as fake_time:
        fake_time.time.return_value = real_now + 3700
        # Bucket should be cleared; new calls succeed.
        for _ in range(mod._TEST_RL_CAP):
            mod._rate_limit_test(tid)
