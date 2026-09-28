"""MTH-D · Feb-2026 — Rate-limit unit tests.

Locks:
  * 30 calls in the window succeed; the 31st is blocked with a
    positive ``retry_after``.
  * Per-user isolation — a second user still gets 30.
  * Sliding window — as entries expire the caller can proceed.
"""
from __future__ import annotations

from services.tenant_ai_rules.rate_limit import check_and_record, reset


def setup_function():
    reset()


def test_30_calls_allowed_31st_blocked():
    for i in range(30):
        allowed, remaining, retry = check_and_record("u1", now=1000.0 + i * 0.1)
        assert allowed, f"call {i} should succeed"
    allowed, remaining, retry = check_and_record("u1", now=1005.0)
    assert allowed is False
    assert remaining == 0
    assert retry >= 1


def test_per_user_isolation():
    for i in range(30):
        allowed, *_ = check_and_record("u_a", now=1000.0 + i * 0.1)
        assert allowed
    # u_a is at the ceiling.
    hit, *_ = check_and_record("u_a", now=1005.0)
    assert hit is False
    # u_b is still fresh.
    allowed, *_ = check_and_record("u_b", now=1005.0)
    assert allowed is True


def test_sliding_window_frees_up_slots():
    # First 30 calls all at t=0.
    for _ in range(30):
        allowed, *_ = check_and_record("u1", now=0.0)
        assert allowed
    # 31st blocked at t=1.
    blocked, *_ = check_and_record("u1", now=1.0)
    assert blocked is False
    # At t=61s the oldest recorded call has expired; a new call
    # slides in.
    allowed, remaining, _ = check_and_record("u1", now=61.0)
    assert allowed is True


def test_anonymous_bucket_still_rate_limited():
    for _ in range(30):
        assert check_and_record("", now=0.0)[0] is True
    blocked, *_ = check_and_record("", now=0.0)
    assert blocked is False


def test_custom_limit_and_window_respected():
    for _ in range(5):
        assert check_and_record("u1", limit=5, window_seconds=10,
                                  now=0.0)[0] is True
    blocked, remaining, retry = check_and_record(
        "u1", limit=5, window_seconds=10, now=0.0,
    )
    assert blocked is False
    assert retry <= 10
