"""WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — wiring pytest.

Confirms the welcome helper is invoked from the three customer-
facing accept paths AND is NOT invoked from the admin bulk-accept
path.  Does not re-test the helper's internal pipeline — Commit 1's
test file (``test_customer_welcome_email.py``) covers that.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _ids():
    return (
        f"test-wire-{uuid.uuid4()}",
        str(uuid.uuid4()),  # cid
        str(uuid.uuid4()),  # qid
    )


async def _seed(db, tid, cid, qid):
    await db.tenants.insert_one({"id": tid, "name": "Wire-T"})
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Wire-Cust",
        "email": "wire@synthetic.test",
    })
    await db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "customer_id": cid,
        "doc_type": "quote", "status": "sent", "decision": None,
        "signature_status": "signed",
    })


async def _cleanup(db, tid):
    await db.tenants.delete_many({"id": tid})
    await db.customers.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.audit_logs.delete_many({"tenant_id": tid})


def _install_welcome_spy(monkeypatch):
    """Replace ``maybe_fire_welcome_on_first_accepted_quote`` with a
    spy that captures the call kwargs.  Returns the list."""
    captured: list = []
    async def _spy(**kw):
        captured.append(kw)
    import services.customer_welcome_email as mod
    monkeypatch.setattr(
        mod, "maybe_fire_welcome_on_first_accepted_quote", _spy,
    )
    return captured


# ─── authed accept — customer role → helper fires ─────────────────
def test_accept_estimate_customer_role_fires_helper(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed(db, tid, cid, qid)
            await db.users.insert_one({
                "id": "u-c", "tenant_id": tid, "role": "customer",
                "email": "c@x.test", "customer_id": cid,
            })
            captured = _install_welcome_spy(monkeypatch)
            # Also neutralise the admin notify + email/sms fanout so
            # the pytest focuses on the welcome-helper call site.
            import routers.estimate_viewer as mod
            async def _noop(*a, **kw): return None
            monkeypatch.setattr(mod, "_notify_admins", _noop)
            monkeypatch.setattr(mod, "_notify_admins_email_sms", _noop)
            monkeypatch.setattr(
                mod, "_phase_c_assert_signature_gate", _noop,
            )
            from routers.estimate_viewer import accept_estimate
            await accept_estimate(
                qid=qid,
                user={"id": "u-c", "role": "customer",
                        "customer_id": cid, "tenant_id": tid},
                tenant={"id": tid},
            )
            assert len(captured) == 1
            assert captured[0]["source"] == "authed_customer"
            assert captured[0]["customer_id"] == cid
            assert captured[0]["quote_id"] == qid
        finally:
            await _cleanup(db, tid)
            await db.users.delete_many({"tenant_id": tid})

    run_test(_run)


# ─── authed accept — admin role → helper does NOT fire ────────────
def test_accept_estimate_admin_role_does_not_fire_helper(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed(db, tid, cid, qid)
            captured = _install_welcome_spy(monkeypatch)
            import routers.estimate_viewer as mod
            async def _noop(*a, **kw): return None
            monkeypatch.setattr(mod, "_notify_admins", _noop)
            monkeypatch.setattr(mod, "_notify_admins_email_sms", _noop)
            monkeypatch.setattr(
                mod, "_phase_c_assert_signature_gate", _noop,
            )
            from routers.estimate_viewer import accept_estimate
            await accept_estimate(
                qid=qid,
                user={"id": "u-a", "role": "admin",
                        "tenant_id": tid},
                tenant={"id": tid},
            )
            assert len(captured) == 0, (
                "admin pass-through must NOT fire the welcome helper"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── Phase A path-based portal accept → helper fires ──────────────
def test_phase_a_approve_via_token_fires_helper(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed(db, tid, cid, qid)
            captured = _install_welcome_spy(monkeypatch)
            import routers.estimate_viewer as mod
            async def _noop(*a, **kw): return None
            monkeypatch.setattr(mod, "_notify_admins", _noop)
            monkeypatch.setattr(mod, "_notify_admins_email_sms", _noop)
            monkeypatch.setattr(
                mod, "_phase_c_assert_signature_gate", _noop,
            )
            monkeypatch.setattr(mod, "_phase_a_rate_gate",
                                   lambda *a, **kw: None)
            monkeypatch.setattr(mod, "_phase_a_recompute_and_persist",
                                   _noop)
            from routers.estimate_viewer import (
                _sign_estimate_token, phase_a_approve_via_token,
            )
            token = _sign_estimate_token(qid, cid, tid)
            await phase_a_approve_via_token(token=token)
            assert len(captured) == 1
            assert captured[0]["source"] == "portal"
            assert captured[0]["customer_id"] == cid
            assert captured[0]["quote_id"] == qid
        finally:
            await _cleanup(db, tid)

    run_test(_run)
