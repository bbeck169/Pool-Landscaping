"""SO-A · Feb-2026 — rate limit tests for schedule-ai recommendations.

Reuses the MTH-D rate-limit test shape but against the SO-A namespace.
"""
from __future__ import annotations

from services.schedule_optimizer.rate_limit import (
    check_and_record, reset, DEFAULT_LIMIT, DEFAULT_WINDOW_S,
)


def setup_function():
    reset()


def test_10_calls_allowed_11th_blocked():
    for i in range(DEFAULT_LIMIT):
        allowed, _rem, _retry = check_and_record("u1", now=1000.0 + i * 0.1)
        assert allowed, f"call {i} should succeed"
    allowed, remaining, retry = check_and_record("u1", now=1005.0)
    assert allowed is False
    assert remaining == 0
    assert retry >= 1


def test_per_user_isolation():
    for i in range(DEFAULT_LIMIT):
        allowed, *_ = check_and_record("u_a", now=1000.0 + i * 0.1)
        assert allowed
    # User B still has a full budget.
    allowed, remaining, _retry = check_and_record("u_b", now=1005.0)
    assert allowed
    assert remaining == DEFAULT_LIMIT - 1


def test_sliding_window_frees_up_slots():
    for i in range(DEFAULT_LIMIT):
        check_and_record("u1", now=1000.0 + i * 0.1)
    # 11th within window → blocked.
    blocked, *_ = check_and_record("u1", now=1005.0)
    assert blocked is False
    # After the window slides past the earliest entry the limiter
    # accepts a fresh call.
    after = 1000.0 + DEFAULT_WINDOW_S + 1.0
    allowed, _rem, _retry = check_and_record("u1", now=after)
    assert allowed


def test_namespace_isolated_from_mth_d_bucket():
    """Ensure MTH-D and SO-A limiters don't share state — pounding
    one must not exhaust the other."""
    from services.tenant_ai_rules import rate_limit as mth_d_rl
    mth_d_rl.reset()

    for _ in range(DEFAULT_LIMIT):
        check_and_record("u_shared", now=1000.0)
    # SO-A user should now be blocked.
    blocked, *_ = check_and_record("u_shared", now=1000.0)
    assert blocked is False

    # But the MTH-D bucket for the same user id is still full budget.
    allowed, remaining, _r = mth_d_rl.check_and_record(
        "u_shared", now=1000.0,
    )
    assert allowed
    assert remaining == mth_d_rl.DEFAULT_LIMIT - 1


def test_reset_specific_user_only():
    for _ in range(DEFAULT_LIMIT):
        check_and_record("u1", now=1000.0)
    for _ in range(DEFAULT_LIMIT):
        check_and_record("u2", now=1000.0)
    reset("u1")
    # u1 has a full budget again.
    allowed, remaining, _ = check_and_record("u1", now=1000.0)
    assert allowed and remaining == DEFAULT_LIMIT - 1
    # u2 remains blocked.
    blocked, *_ = check_and_record("u2", now=1000.0)
    assert blocked is False
