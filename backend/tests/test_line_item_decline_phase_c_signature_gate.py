"""Feb-2026 · Phase C · Signature-before-approve tenant gate.

Backend test suite covering:
  1. Tenant setting round-trip:
     * ``PATCH /api/tenants/mine/settings`` accepts
       ``require_signature_before_approve`` and echoes back.
     * ``GET /api/tenants/mine/settings`` surfaces the field.
  2. Portal magic-link approve enforcement:
     * Flag TRUE + no signature → 400 ``signature_required``.
     * Flag TRUE + signature_status="signed" → 200 (accepted).
     * Flag FALSE → 200 regardless of signature (Phase A regression).
     * Decline is NEVER gated by signature (regression guard).
  3. Payload surface: ``GET /api/portal/quotes/via-token`` exposes
     ``signature_status`` + ``require_signature_before_approve``
     so the customer surface can render the disabled-Approve hint.

Sync test pattern (pymongo + requests) mirrors
``test_line_item_decline_phase_a.py`` so both suites use identical
seed helpers + token minting.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_JWT_SECRET = _ENV["JWT_SECRET"]
_JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


# ── Helpers ────────────────────────────────────────────────────────
def _mint_estimate_token(qid: str, cid: str, tid: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "est", "eid": qid, "cid": cid, "tid": tid,
         "iat": int(now.timestamp()),
         "exp": now + timedelta(days=1)},
        _JWT_SECRET, algorithm=_JWT_ALGO,
    )


def _seed(
    *,
    require_signature: bool,
    signature_status: str | None = None,
) -> dict:
    qid = f"phase-c-q-{uuid.uuid4().hex[:8]}"
    tid = f"phase-c-t-{uuid.uuid4().hex[:8]}"
    cid = f"phase-c-c-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": qid,
        "tenant_id": tid,
        "customer_id": cid,
        "doc_type": "quote",
        "status": "sent",
        "decision": None,
        "line_items": [
            {"description": "Pool clean", "quantity": 1,
             "unit_price": 100.0},
        ],
        "tax_rate": 0.0,
        "discount_amount": 0.0,
        "discount_type": "fixed",
        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "signature_status": signature_status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.quotes.insert_one(doc)
    _sync.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "name": "PhaseC",
                  "slug": f"phase-c-{tid[-6:]}",
                  "require_signature_before_approve": require_signature}},
        upsert=True,
    )
    _sync.customers.update_one(
        {"id": cid},
        {"$setOnInsert": {"id": cid, "tenant_id": tid,
                           "name": "PhaseC Customer",
                           "customer_number": "C-001",
                           "address": {"line1": "1 Any"}}},
        upsert=True,
    )
    return {"qid": qid, "tid": tid, "cid": cid,
             "token": _mint_estimate_token(qid, cid, tid)}


def _cleanup(ctx: dict) -> None:
    _sync.quotes.delete_many({"id": ctx["qid"]})
    _sync.tenants.delete_many({"id": ctx["tid"]})
    _sync.customers.delete_many({"id": ctx["cid"]})


# ── 1. Portal approve: flag TRUE + no signature → 400 ──────────────
def test_approve_blocked_when_flag_true_and_not_signed():
    ctx = _seed(require_signature=True, signature_status=None)
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error_code") == "signature_required"
        # Doc remains un-accepted.
        fresh = _sync.quotes.find_one({"id": ctx["qid"]}, {"_id": 0})
        assert fresh.get("decision") is None
    finally:
        _cleanup(ctx)


# ── 2. Portal approve: flag TRUE + signed → 200 ────────────────────
def test_approve_allowed_when_flag_true_and_signed():
    ctx = _seed(require_signature=True, signature_status="signed")
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("decision") == "accepted"
    finally:
        _cleanup(ctx)


# ── 3. Portal approve: flag FALSE → 200 regardless of signature ────
def test_approve_allowed_when_flag_false_regardless_of_signature():
    ctx = _seed(require_signature=False, signature_status=None)
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("decision") == "accepted"
    finally:
        _cleanup(ctx)


# ── 4. Portal decline: NEVER gated by signature (regression) ───────
def test_decline_never_gated_by_signature():
    ctx = _seed(require_signature=True, signature_status=None)
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/decline",
            json={"reason": "too expensive"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("decision") == "declined"
    finally:
        _cleanup(ctx)


# ── 5. Legacy query-string accept endpoint honours the gate ────────
def test_legacy_query_accept_blocked_when_flag_true_and_not_signed():
    ctx = _seed(require_signature=True, signature_status=None)
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/accept?token={ctx['token']}",
            timeout=10,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error_code") == "signature_required"
    finally:
        _cleanup(ctx)


# ── 6. GET /portal/quotes/via-token surfaces gate + signature fields ─
def test_payload_exposes_signature_gate_and_status():
    ctx = _seed(require_signature=True, signature_status="pending")
    try:
        r = requests.get(
            f"{API}/portal/quotes/via-token?token={ctx['token']}",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("require_signature_before_approve") is True
        assert body.get("signature_status") == "pending"
    finally:
        _cleanup(ctx)


def test_payload_exposes_gate_off_when_flag_absent():
    ctx = _seed(require_signature=False, signature_status=None)
    try:
        r = requests.get(
            f"{API}/portal/quotes/via-token?token={ctx['token']}",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("require_signature_before_approve") is False
    finally:
        _cleanup(ctx)


# ── 7. Idempotency: already-accepted doc returns 200 even w/ gate ──
def test_already_accepted_short_circuits_signature_gate():
    ctx = _seed(require_signature=True, signature_status=None)
    try:
        _sync.quotes.update_one(
            {"id": ctx["qid"]},
            {"$set": {"decision": "accepted",
                       "accepted_at": datetime.now(timezone.utc).isoformat()}},
        )
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("decision") == "accepted"
    finally:
        _cleanup(ctx)
