"""Phase P53 · Feb-2026 — Phase 10 behavior regression lockdown.

P53 explicitly does NOT modify the Phase-10 referral automation
(reward-on-30-day-paid-window). To keep the untouched machinery
truly untouched, we lock the following invariants:

  1. ``fire_referral_conversion_hook`` continues to flip a referral
     to ``pending_paid_window`` on close-won (Phase-10 default).
  2. The Phase-10 watcher continues to CAS-guard against double
     credit issuance via a status transition on ``referral_id``.
  3. Refund/dispute detection inside the 30-day window still voids
     the referral before credit is issued (F2 refund guard).
  4. The Phase-10 reward primitive is unchanged — the ledger row
     lives in ``customer_credits`` with ``source="referral_credit"``.

These are guardrails: any future P-phase that silently degrades
Phase-10 semantics trips these tests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dotenv import dotenv_values


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Close-won hook default status is ``pending_paid_window``
# ═════════════════════════════════════════════════════════════════════
def test_close_won_hook_defaults_to_pending_paid_window_status():
    """The Phase-10 close-won hook flips referrals to
    ``pending_paid_window`` UNLESS the tenant explicitly opted into
    the legacy immediate-credit path. P53 must not have flipped that
    default."""
    import inspect

    from routers.referral_rewards import fire_referral_conversion_hook

    src = inspect.getsource(fire_referral_conversion_hook)
    # The Phase-10 default: pending_paid_window branch is present.
    assert "pending_paid_window" in src, (
        "close-won hook lost the pending_paid_window branch — "
        "P53 must not modify Phase 10 behavior"
    )
    # The legacy_immediate_referral_credit gate is intact.
    assert "legacy_immediate_referral_credit" in src, (
        "close-won hook lost the legacy_immediate_referral_credit "
        "gate — Phase 10 behavior regressed"
    )


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Watcher CAS-guard on referral_id is intact
# ═════════════════════════════════════════════════════════════════════
def test_watcher_uses_status_guarded_cas_on_referral_id():
    """The watcher's double-credit protection relies on a
    status-guarded CAS transition (``pending_paid_window`` →
    ``crediting_in_progress``). P53 must not have swapped this for
    a weaker guard."""
    import inspect

    from services.referral_watcher import _try_credit_referral

    src = inspect.getsource(_try_credit_referral)
    # The CAS filter is on both id AND status.
    assert "crediting_in_progress" in src, (
        "watcher lost the CAS transient state — Phase 10 CAS "
        "guard regressed"
    )
    # The status filter is used in the CAS update.
    assert 'status": "pending_paid_window' in src, (
        "watcher lost the CAS pre-state filter — Phase 10 double-"
        "credit protection regressed"
    )


# ═════════════════════════════════════════════════════════════════════
# Section 3 — Refund/dispute guard inside 30-day window is intact
# ═════════════════════════════════════════════════════════════════════
def test_refund_dispute_guard_inside_window_intact():
    """The Phase-10 F2 refund guard voids the referral BEFORE credit
    issuance when the referred customer's paid invoice is refunded
    inside the 30-day window. P53 must not have removed this."""
    import inspect

    from services.referral_watcher import (
        _check_refund_or_dispute_inside_window,
        _try_credit_referral,
    )

    src_check = inspect.getsource(_check_refund_or_dispute_inside_window)
    src_try = inspect.getsource(_try_credit_referral)

    # Refund + dispute event types both checked.
    assert "charge.refunded" in src_check
    assert "charge.dispute.created" in src_check
    # Try-credit path calls the guard.
    assert "_check_refund_or_dispute_inside_window" in src_try


# ═════════════════════════════════════════════════════════════════════
# Section 4 — Ledger primitive unchanged (customer_credits + source)
# ═════════════════════════════════════════════════════════════════════
def test_ledger_writes_to_customer_credits_with_referral_credit_source():
    """The Phase-10 ledger primitive is ``db.customer_credits`` with
    ``source="referral_credit"``. P53 must not have redirected to a
    new collection."""
    import inspect

    from services.referral_watcher import _try_credit_referral

    src = inspect.getsource(_try_credit_referral)
    assert 'db.customer_credits.insert_one' in src, (
        "watcher stopped writing to db.customer_credits — a new "
        "ledger primitive would silently break Phase 10 reporting"
    )
    assert '"source": "referral_credit"' in src, (
        "watcher stopped tagging ledger rows with "
        'source="referral_credit" — reporting queries will break'
    )
    # Balance rollup still hits the same collection.
    assert 'db.customer_credits_balance.update_one' in src, (
        "watcher stopped rolling the balance — Phase 10 balance "
        "cache would drift"
    )


# ═════════════════════════════════════════════════════════════════════
# Section 5 — 30-day paid window constant unchanged
# ═════════════════════════════════════════════════════════════════════
def test_paid_window_days_constant_is_still_30():
    """P53 must not have shortened the paid-window guard — that
    would eliminate the refund-protection window Phase 10 added."""
    from services.referral_watcher import PAID_WINDOW_DAYS

    assert PAID_WINDOW_DAYS == 30, (
        f"PAID_WINDOW_DAYS={PAID_WINDOW_DAYS} — Phase 10 refund-"
        f"protection window regressed (was 30)"
    )
