"""WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — pytest for the
``maybe_fire_welcome_on_first_accepted_quote`` helper.

Seven cases:
  (a) First accept triggers send + stamps customer + writes audit.
  (b) Second accept does NOT trigger send (guard holds).
  (c) Decline-then-accept triggers only once.
  (d) Admin bulk-accept path NEVER calls the helper (contract test
      — helper itself has no role gate; this is a documentation
      test that confirms the helper is role-agnostic and fires
      whenever called).
  (e) Tenant toggle OFF → no send, no stamp.
  (f) Resend error → no stamp (retry possible on next accept).
  (g) Race detection — stamp returns ``modified_count == 0`` after
      a successful Resend send → WARNING tagged
      ``customer_welcome_email.race_detected`` is logged.
"""
from __future__ import annotations

import logging
import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _ids() -> tuple:
    tid = f"test-welcome-{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    qid = str(uuid.uuid4())
    return tid, cid, qid


async def _seed_min(db, tid: str, cid: str, qid: str,
                        *, tenant_toggle=None):
    tenant_doc = {"id": tid, "name": "Synthetic Co",
                   "settings": {"business_card": {
                       "company_name": "Synthetic Co",
                       "phone": "555-0100",
                   }}}
    if tenant_toggle is not None:
        tenant_doc["welcome_email_on_first_accepted_quote_enabled"] = (
            tenant_toggle
        )
    await db.tenants.insert_one(tenant_doc)
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Synthetic Cust",
        "email": f"cust-{uuid.uuid4().hex[:8]}@synthetic.test",
    })
    await db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "customer_id": cid,
        "doc_type": "quote", "status": "accepted",
    })


async def _cleanup(db, tid: str):
    await db.tenants.delete_many({"id": tid})
    await db.customers.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.audit_logs.delete_many({"tenant_id": tid})


def _patch_resend(monkeypatch, *, raise_exc: bool = False,
                      status: str = "sent",
                      msg_id: str = "re_mock_123"):
    """Install a mock send adapter for the helper's send step.
    Returns a list the caller can poll for captured payloads."""
    captured: list = []
    async def _send(**kw):
        captured.append(kw)
        if raise_exc:
            raise RuntimeError("mock Resend outage")
        return {
            "provider": "resend",
            "provider_status": status,
            "provider_response_id": msg_id,
        }
    import services.email.resend_adapter as _ad
    monkeypatch.setattr(_ad, "send", _send)
    return captured


# ─── (a) First accept triggers send + stamp + audit ───────────────
def test_welcome_first_accept_sends_stamps_audits(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid)
            captured = _patch_resend(monkeypatch)

            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid,
                source="portal",
            )
            assert len(captured) == 1
            # Subject copy locked verbatim per approval D2.
            assert captured[0]["subject"] == (
                "Thanks for choosing Synthetic Co — welcome aboard"
            )
            # Portal link via the shared absolute-URL helper — the
            # Wingman fix we shipped guarantees an absolute HTTPS
            # link in the rendered body.
            assert "/portal/login" in captured[0]["html"]
            assert "file:///" not in captured[0]["html"]  # regression

            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid}, {"_id": 0},
            )
            assert cust["welcome_email_sent_at"]
            assert cust["welcome_email_message_id"] == "re_mock_123"
            assert cust["welcome_email_trigger_quote_id"] == qid

            audit = await db.audit_logs.find_one(
                {"tenant_id": tid, "event": "customer.welcome_email_sent"},
                {"_id": 0},
            )
            assert audit is not None
            assert audit["source"] == "portal"
            assert audit["trigger"] == "first_accepted_quote"
            assert audit["customer_id"] == cid
            assert audit["trigger_quote_id"] == qid
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (b) Second accept does NOT trigger send ─────────────────────
def test_welcome_second_accept_guarded_by_stamp(monkeypatch):
    tid, cid, qid1 = _ids()
    qid2 = str(uuid.uuid4())

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid1)
            # qid2 is still ``sent`` at the moment the first-accept
            # helper fires for qid1.  The pytest simulates the real
            # ordering: user accepts qid1 → welcome fires → later
            # the user accepts qid2 → welcome must NOT fire again.
            await db.quotes.insert_one({
                "id": qid2, "tenant_id": tid, "customer_id": cid,
                "doc_type": "quote", "status": "sent",
            })
            captured = _patch_resend(monkeypatch)
            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            # 1st accept → sends.
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid1,
                source="portal",
            )
            # Simulate the 2nd quote now flipping to ``accepted``.
            await db.quotes.update_one(
                {"id": qid2}, {"$set": {"status": "accepted"}},
            )
            # 2nd accept → should be guarded by BOTH (i) the prior-
            # accept count (qid1 is now accepted) AND (ii) the
            # ``welcome_email_sent_at`` stamp from the first call.
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid2,
                source="portal",
            )
            assert len(captured) == 1, (
                f"expected one send only, got {len(captured)}"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (c) Decline then accept triggers once ───────────────────────
def test_welcome_decline_then_accept_fires_once(monkeypatch):
    tid, cid, _ = _ids()
    qid_declined = str(uuid.uuid4())
    qid_accepted = str(uuid.uuid4())

    async def _run(db):
        try:
            await db.tenants.insert_one({
                "id": tid, "name": "Synthetic",
                "settings": {"business_card": {
                    "company_name": "Synthetic",
                }},
            })
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Cust",
                "email": "x@synthetic.test",
            })
            await db.quotes.insert_many([
                {"id": qid_declined, "tenant_id": tid,
                 "customer_id": cid, "status": "declined"},
                {"id": qid_accepted, "tenant_id": tid,
                 "customer_id": cid, "status": "accepted"},
            ])
            captured = _patch_resend(monkeypatch)
            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid,
                quote_id=qid_accepted, source="portal",
            )
            # Decline doesn't count towards prior-accepts; this is
            # the first ACCEPT so the welcome fires.
            assert len(captured) == 1
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (d) Role-agnostic contract test ──────────────────────────────
def test_welcome_helper_is_role_agnostic(monkeypatch):
    """Documentation test — the helper itself has no role gate.
    Role gating is at the caller.  Calling with source='admin'
    STILL sends — exclusion of admin bulk-accept lives in the
    caller (``routers/estimate_viewer.py``) which never invokes
    this helper on the admin pass-through branch.  Commit 2's
    wiring test asserts the admin bulk-accept path is wire-free.
    """
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid)
            captured = _patch_resend(monkeypatch)
            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid,
                source="admin_test_only",
            )
            assert len(captured) == 1
            audit = await db.audit_logs.find_one(
                {"tenant_id": tid}, {"_id": 0},
            )
            assert audit["source"] == "admin_test_only"
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (e) Tenant toggle OFF ────────────────────────────────────────
def test_welcome_tenant_toggle_off_skips_send(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid, tenant_toggle=False)
            captured = _patch_resend(monkeypatch)
            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid,
                source="portal",
            )
            assert len(captured) == 0
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid}, {"_id": 0},
            )
            assert cust.get("welcome_email_sent_at") is None
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (f) Resend error → no stamp ──────────────────────────────────
def test_welcome_resend_failure_does_not_stamp(monkeypatch):
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid)
            _patch_resend(monkeypatch, raise_exc=True)
            from services.customer_welcome_email import (
                maybe_fire_welcome_on_first_accepted_quote,
            )
            await maybe_fire_welcome_on_first_accepted_quote(
                tenant_id=tid, customer_id=cid, quote_id=qid,
                source="portal",
            )
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid}, {"_id": 0},
            )
            assert cust.get("welcome_email_sent_at") is None, (
                "stamp must NOT fire on provider failure"
            )
            audit = await db.audit_logs.find_one(
                {"tenant_id": tid}, {"_id": 0},
            )
            assert audit is None, "no audit row on failed send"
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (g) Race detection warning ───────────────────────────────────
def test_welcome_race_detected_warning_fires(monkeypatch, caplog):
    """Simulate the vanishingly-rare window where two concurrent
    accepts both pass the pre-check + trigger-check + successfully
    send via Resend.  The atomic ``update_one`` only one of them
    will win; the loser's ``modified_count == 0`` must trip the
    ``customer_welcome_email.race_detected`` ops warning.

    Scenario simulated: our worker passes the pre-check, calls
    Resend (success), and in the window between send and stamp
    ANOTHER worker atomically stamps the customer.  Our stamp
    then finds ``welcome_email_sent_at != None`` and returns
    ``modified_count == 0``.
    """
    tid, cid, qid = _ids()

    async def _run(db):
        try:
            await _seed_min(db, tid, cid, qid)
            # Install a send-adapter mock that STAMPS the customer
            # as a side-effect of the send — simulates a concurrent
            # worker winning the race in the gap between send and
            # our stamp.
            async def _racing_send(**kw):
                await db.customers.update_one(
                    {"id": cid, "tenant_id": tid},
                    {"$set": {
                        "welcome_email_sent_at":
                            "2026-02-09T00:00:00+00:00",
                        "welcome_email_message_id": "racer-wins",
                    }},
                )
                return {
                    "provider": "resend",
                    "provider_status": "sent",
                    "provider_response_id": "re_mock_loser",
                }
            import services.email.resend_adapter as _ad
            monkeypatch.setattr(_ad, "send", _racing_send)

            with caplog.at_level(logging.WARNING):
                from services.customer_welcome_email import (
                    maybe_fire_welcome_on_first_accepted_quote,
                )
                await maybe_fire_welcome_on_first_accepted_quote(
                    tenant_id=tid, customer_id=cid,
                    quote_id=qid, source="portal",
                )
            matched = [
                r for r in caplog.records
                if "customer_welcome_email.race_detected"
                in r.getMessage()
            ]
            assert matched, (
                "expected race_detected WARNING; got: "
                + str([r.getMessage()[:80] for r in caplog.records])
            )
            # Loser's audit row must NOT be written — only the
            # winning worker's stamp lands.
            audit = await db.audit_logs.find_one(
                {"tenant_id": tid}, {"_id": 0},
            )
            assert audit is None
        finally:
            await _cleanup(db, tid)

    run_test(_run)
