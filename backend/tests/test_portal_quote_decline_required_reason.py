"""PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026.

Pytest coverage for the required-reason contract on the Phase A
path-based portal decline endpoint
``POST /portal/quotes/via-token/{token}/decline``.

Four cases:
  (i)   Valid payload → persists ``decline_reason_category`` +
        ``decline_reason_text`` + legacy ``decline_reason`` on the
        quote doc AND writes an ``audit_logs`` row with
        ``event="quote.declined"`` + ``source="portal"``.
  (ii)  400 ``decline_reason_required`` when both fields are missing.
  (iii) 400 ``decline_reason_text_too_short`` when text < 10 chars.
  (iv)  400 ``decline_reason_category_invalid`` when the category
        value is not in the canonical enum.

Direct in-process invocation via ``tests._f7_loop_fixture.run_test``
— the handler consumes a magic-link JWT minted by the module's own
``_sign_estimate_token`` helper so no HTTP layer is needed.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _ids():
    tid = f"test-portal-decline-{uuid.uuid4()}"
    qid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    return tid, qid, cid


async def _seed_quote(db, tid: str, qid: str, cid: str):
    await db.tenants.insert_one({"id": tid, "name": "T"})
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Portal Decline Cust",
    })
    await db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "customer_id": cid,
        "doc_type": "quote",
        "status": "sent",       # Phase A actionable statuses: {sent, viewed}
        "decision": None,
    })


def _mint_token(qid: str, cid: str, tid: str) -> str:
    from routers.estimate_viewer import _sign_estimate_token
    return _sign_estimate_token(qid, cid, tid)


async def _cleanup(db, tid: str):
    await db.tenants.delete_many({"id": tid})
    await db.customers.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.audit_logs.delete_many({"tenant_id": tid})


# ─── Case (i) · Valid payload — persist + audit ───────────────────
def test_portal_decline_valid_payload_persists_and_audits():
    tid, qid, cid = _ids()

    async def _run(db):
        try:
            await _seed_quote(db, tid, qid, cid)
            token = _mint_token(qid, cid, tid)

            from routers.estimate_viewer import (
                _PhaseATopLevelDeclineIn, phase_a_decline_via_token,
            )
            body = _PhaseATopLevelDeclineIn(
                decline_reason_category="too_expensive",
                decline_reason_text=(
                    "This is 4x higher than the two competitor "
                    "quotes we received. We'd need to see "
                    "line-item deltas to reconsider."
                ),
            )
            await phase_a_decline_via_token(token=token, body=body)

            doc = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert doc["status"] == "declined", doc
            assert doc["decision"] == "declined", doc
            assert doc["decline_reason_category"] == "too_expensive", doc
            assert doc["decline_reason_text"].startswith(
                "This is 4x higher"
            ), doc
            # Legacy field mirrors the structured text (back-compat
            # per the Feb-2026 deprecation plan).
            assert doc["decline_reason"] == doc["decline_reason_text"], doc

            audit = await db.audit_logs.find_one(
                {"tenant_id": tid, "entity_id": qid,
                 "event": "quote.declined"},
                {"_id": 0},
            )
            assert audit is not None, "audit_logs row missing"
            assert audit["source"] == "portal", audit
            assert audit["decline_reason_category"] == "too_expensive", audit
            assert audit["decline_reason_text"] == doc["decline_reason_text"], audit
            assert audit["customer_id"] == cid, audit
            assert audit["entity_kind"] == "quote", audit
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── Case (ii) · Missing both fields → 400 ────────────────────────
def test_portal_decline_missing_reason_rejected():
    tid, qid, cid = _ids()

    async def _run(db):
        try:
            await _seed_quote(db, tid, qid, cid)
            token = _mint_token(qid, cid, tid)

            from routers.estimate_viewer import (
                _PhaseATopLevelDeclineIn, phase_a_decline_via_token,
            )
            body = _PhaseATopLevelDeclineIn()  # empty payload
            with pytest.raises(HTTPException) as exc_info:
                await phase_a_decline_via_token(token=token, body=body)
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail["code"] == "decline_reason_required"
            # Doc must NOT have been mutated.
            doc = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert doc["status"] == "sent", doc
            assert doc.get("decision") is None, doc
            # No audit row.
            audit = await db.audit_logs.find_one(
                {"tenant_id": tid, "entity_id": qid}, {"_id": 0},
            )
            assert audit is None
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── Case (iii) · Text too short → 400 ────────────────────────────
def test_portal_decline_text_too_short_rejected():
    tid, qid, cid = _ids()

    async def _run(db):
        try:
            await _seed_quote(db, tid, qid, cid)
            token = _mint_token(qid, cid, tid)

            from routers.estimate_viewer import (
                _PhaseATopLevelDeclineIn, phase_a_decline_via_token,
            )
            body = _PhaseATopLevelDeclineIn(
                decline_reason_category="other",
                decline_reason_text="too short",  # 9 chars (< 10)
            )
            with pytest.raises(HTTPException) as exc_info:
                await phase_a_decline_via_token(token=token, body=body)
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail["code"] == (
                "decline_reason_text_too_short"
            )
            assert exc_info.value.detail["min"] == 10
            doc = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert doc["status"] == "sent", doc
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── Case (iv) · Invalid category → 400 ───────────────────────────
def test_portal_decline_invalid_category_rejected():
    tid, qid, cid = _ids()

    async def _run(db):
        try:
            await _seed_quote(db, tid, qid, cid)
            token = _mint_token(qid, cid, tid)

            from routers.estimate_viewer import (
                _PhaseATopLevelDeclineIn, phase_a_decline_via_token,
            )
            body = _PhaseATopLevelDeclineIn(
                decline_reason_category="not_a_real_category",
                decline_reason_text=(
                    "This free-text is long enough to pass the 10-"
                    "char minimum but the category is garbage."
                ),
            )
            with pytest.raises(HTTPException) as exc_info:
                await phase_a_decline_via_token(token=token, body=body)
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail["code"] == (
                "decline_reason_category_invalid"
            )
            # Allowed list is echoed back for client-side recovery.
            assert "too_expensive" in exc_info.value.detail["allowed"]
            doc = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert doc["status"] == "sent", doc
        finally:
            await _cleanup(db, tid)

    run_test(_run)
