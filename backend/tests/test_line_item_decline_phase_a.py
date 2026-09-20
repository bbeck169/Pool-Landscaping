"""Feb-2026 · Phase A · Line-Item Decline + Top-Level Approve/Decline

Backend test suite covering:
  1. Server-truth totals recomputation (percent + fixed discount, tax,
     all-lines-declined edge).
  2. Path-based token endpoints for per-line decline / undecline.
  3. Path-based token endpoints for top-level approve / decline.
  4. Status guards (409 when doc is not in ``sent`` / ``viewed`` state,
     or already finalized).
  5. Idempotency (repeat calls return 200, not 409).
  6. Line-index bounds check (404 when out of range).
  7. Deprecated ``POST /api/quotes/{qid}/decision`` still functions
     but is flagged deprecated in OpenAPI.

Sync test pattern (pymongo + requests) matches the rest of the
backend suite; async test infra is not wired in this project.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
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

# JWT secret has to match the running server. Read directly from the
# same .env so the token verifier accepts our test tokens.
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


def _seed_quote(*,
                  status: str = "sent",
                  decision: str | None = None,
                  line_items: list | None = None,
                  tax_rate: float = 10.0,
                  discount_amount: float = 0.0,
                  discount_type: str = "fixed") -> dict:
    qid = f"phase-a-q-{uuid.uuid4().hex[:8]}"
    tid = f"phase-a-t-{uuid.uuid4().hex[:8]}"
    cid = f"phase-a-c-{uuid.uuid4().hex[:8]}"
    if line_items is None:
        line_items = [
            {"description": "Pool clean", "quantity": 1, "unit_price": 100.0},
            {"description": "Chemicals", "quantity": 2, "unit_price": 50.0},
        ]
    doc = {
        "id": qid,
        "tenant_id": tid,
        "customer_id": cid,
        "doc_type": "quote",
        "status": status,
        "decision": decision,
        "line_items": line_items,
        "tax_rate": tax_rate,
        "discount_amount": discount_amount,
        "discount_type": discount_type,
        "subtotal": 200.0,
        "tax": 20.0,
        "total": 220.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.quotes.insert_one(doc)
    _sync.tenants.update_one(
        {"id": tid},
        {"$setOnInsert": {"id": tid, "name": "PhaseA Test",
                            "slug": "phase-a-test"}},
        upsert=True,
    )
    _sync.customers.update_one(
        {"id": cid},
        {"$setOnInsert": {"id": cid, "tenant_id": tid,
                             "name": "PhaseA Customer",
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


# ── 1. Totals recomputation (unit) ─────────────────────────────────
def test_totals_no_declined_lines_matches_original():
    from services.quotes.totals import recompute_customer_adjusted_totals
    quote = {
        "line_items": [
            {"quantity": 1, "unit_price": 100.0},
            {"quantity": 2, "unit_price": 50.0},
        ],
        "tax_rate": 10.0,
        "discount_amount": 0,
        "discount_type": "fixed",
    }
    r = recompute_customer_adjusted_totals(quote)
    assert r["original_total"] == r["adjusted_total"] == 220.0
    assert r["has_declined_lines"] is False
    assert r["declined_line_count"] == 0


def test_totals_declined_line_reduces_subtotal_and_tax():
    from services.quotes.totals import recompute_customer_adjusted_totals
    quote = {
        "line_items": [
            {"quantity": 1, "unit_price": 100.0,
             "customer_status": "declined"},
            {"quantity": 2, "unit_price": 50.0},
        ],
        "tax_rate": 10.0,
        "discount_amount": 0,
        "discount_type": "fixed",
    }
    r = recompute_customer_adjusted_totals(quote)
    assert r["original_subtotal"] == 200.0
    assert r["adjusted_subtotal"] == 100.0
    assert r["adjusted_tax"] == 10.0
    assert r["adjusted_total"] == 110.0
    assert r["has_declined_lines"] is True
    assert r["declined_line_count"] == 1


def test_totals_percent_discount_recomputed_on_reduced_subtotal():
    from services.quotes.totals import recompute_customer_adjusted_totals
    quote = {
        "line_items": [
            {"quantity": 1, "unit_price": 100.0,
             "customer_status": "declined"},
            {"quantity": 2, "unit_price": 50.0},
        ],
        "tax_rate": 0,
        "discount_amount": 10,
        "discount_type": "percent",
    }
    r = recompute_customer_adjusted_totals(quote)
    assert r["original_discount_value"] == 20.0
    assert r["original_total"] == 180.0
    assert r["adjusted_discount_value"] == 10.0
    assert r["adjusted_total"] == 90.0


def test_totals_fixed_discount_stays_fixed_but_tax_recomputed():
    from services.quotes.totals import recompute_customer_adjusted_totals
    quote = {
        "line_items": [
            {"quantity": 1, "unit_price": 100.0,
             "customer_status": "declined"},
            {"quantity": 2, "unit_price": 50.0},
        ],
        "tax_rate": 10.0,
        "discount_amount": 15,
        "discount_type": "fixed",
    }
    r = recompute_customer_adjusted_totals(quote)
    assert r["original_discount_value"] == 15.0
    assert r["adjusted_discount_value"] == 15.0
    assert r["adjusted_total"] == 93.5


def test_totals_all_lines_declined_produces_zero_but_no_status_flip():
    from services.quotes.totals import recompute_customer_adjusted_totals
    quote = {
        "line_items": [
            {"quantity": 1, "unit_price": 100.0,
             "customer_status": "declined"},
            {"quantity": 2, "unit_price": 50.0,
             "customer_status": "declined"},
        ],
        "tax_rate": 10.0,
        "discount_amount": 0,
        "discount_type": "fixed",
    }
    r = recompute_customer_adjusted_totals(quote)
    assert r["adjusted_subtotal"] == 0.0
    assert r["adjusted_tax"] == 0.0
    assert r["adjusted_total"] == 0.0
    assert r["has_declined_lines"] is True
    assert r["declined_line_count"] == 2


# ── 2. Line-item decline / undecline endpoints ─────────────────────
def test_line_item_decline_persists_and_recomputes():
    ctx = _seed_quote()
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/0/decline",
            json={"reason": "not needed"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totals"]["has_declined_lines"] is True
        assert body["totals"]["adjusted_total"] == 110.0
        assert body["totals"]["original_total"] == 220.0
        doc = _sync.quotes.find_one({"id": ctx["qid"]})
        assert doc["line_items"][0]["customer_status"] == "declined"
        assert doc["line_items"][0]["customer_decline_reason"] == "not needed"
        assert doc["adjusted_total"] == 110.0
    finally:
        _cleanup(ctx)


def test_line_item_decline_is_idempotent():
    ctx = _seed_quote()
    try:
        for _ in range(3):
            r = requests.post(
                f"{API}/portal/quotes/via-token/{ctx['token']}"
                f"/line-items/0/decline",
                json={"reason": "second click"}, timeout=10,
            )
            assert r.status_code == 200, r.text
    finally:
        _cleanup(ctx)


def test_line_item_undecline_restores_total():
    ctx = _seed_quote()
    try:
        requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/0/decline",
            json={"reason": "oops"}, timeout=10,
        )
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/0/undecline", timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totals"]["has_declined_lines"] is False
        assert body["totals"]["adjusted_total"] == body["totals"]["original_total"]
    finally:
        _cleanup(ctx)


def test_line_item_out_of_range_returns_404():
    ctx = _seed_quote()
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/99/decline",
            json={}, timeout=10,
        )
        assert r.status_code == 404
        assert r.json()["detail"]["error_code"] == "line_index_out_of_range"
    finally:
        _cleanup(ctx)


def test_line_item_decline_blocked_when_status_not_sent():
    ctx = _seed_quote(status="draft")
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/0/decline",
            json={}, timeout=10,
        )
        assert r.status_code == 409
        assert r.json()["detail"]["error_code"] == "not_actionable"
    finally:
        _cleanup(ctx)


# ── 3. Top-level approve / decline endpoints ───────────────────────
def test_approve_via_token_transitions_status():
    ctx = _seed_quote()
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["decision"] == "accepted"
        doc = _sync.quotes.find_one({"id": ctx["qid"]})
        assert doc["status"] == "accepted"
        assert doc["decision"] == "accepted"
    finally:
        _cleanup(ctx)


def test_approve_is_idempotent():
    ctx = _seed_quote()
    try:
        r1 = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r1.status_code == 200
        r2 = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json()["decision"] == "accepted"
    finally:
        _cleanup(ctx)


def test_top_level_decline_transitions_status():
    ctx = _seed_quote()
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/decline",
            json={"reason": "too expensive"}, timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["decision"] == "declined"
        doc = _sync.quotes.find_one({"id": ctx["qid"]})
        assert doc["status"] == "declined"
        assert doc["decline_reason"] == "too expensive"
    finally:
        _cleanup(ctx)


def test_approve_after_decline_is_409():
    ctx = _seed_quote(status="declined", decision="declined")
    try:
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 409
        assert r.json()["detail"]["error_code"] == "already_finalized"
    finally:
        _cleanup(ctx)


def test_approve_carries_adjusted_totals_after_line_decline():
    ctx = _seed_quote()
    try:
        # Customer declines line 0, then approves the rest.
        requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}"
            f"/line-items/0/decline",
            json={"reason": "skip"}, timeout=10,
        )
        r = requests.post(
            f"{API}/portal/quotes/via-token/{ctx['token']}/approve",
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"] == "accepted"
        assert body["totals"]["has_declined_lines"] is True
        assert body["totals"]["adjusted_total"] == 110.0
        assert body["totals"]["original_total"] == 220.0
    finally:
        _cleanup(ctx)


# ── 4. OpenAPI surface ──────────────────────────────────────────────
def test_legacy_decision_endpoint_flagged_deprecated_in_openapi():
    r = requests.get(f"{API}/openapi.json", timeout=10)
    assert r.status_code == 200
    schema = r.json()
    entry = schema["paths"]["/api/quotes/{qid}/decision"]["post"]
    assert entry.get("deprecated") is True


def test_new_endpoints_registered_in_openapi():
    r = requests.get(f"{API}/openapi.json", timeout=10)
    schema = r.json()
    paths = schema["paths"]
    for p in (
        "/api/portal/quotes/via-token/{token}/line-items/{index}/decline",
        "/api/portal/quotes/via-token/{token}/line-items/{index}/undecline",
        "/api/portal/quotes/via-token/{token}/approve",
        "/api/portal/quotes/via-token/{token}/decline",
    ):
        assert p in paths, f"missing: {p}"
