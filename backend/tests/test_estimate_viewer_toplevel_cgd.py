"""
BUG REGRESSION · Feb-2026
=========================
Public estimate view at ``/e/e/{token}`` must respect
``customer_group_display``.

Pre-fix: ``_build_payload`` populated the field only at the nested
``payload.customer_view.customer_group_display``. The frontend
``EstimateView.jsx:373`` reads ``data?.customer_group_display`` at the
TOP level, finds ``undefined``, falls through its legacy default
("undefined → grouped") and ALWAYS renders grouped on the magic-link
customer page regardless of what the admin toggled.

Fix: lift the field to the top level of the ``_build_payload`` return
dict so the frontend reads the DB value verbatim.

This file locks the top-level contract. Uses the live HTTP harness
pattern (same as ``test_k79_toggle_estimate_viewer.py``) so the
"attached to a different loop" trap that in-process async calls hit
when modules cross-import their ``db`` binding doesn't bite.

Pat Kail lock: this file NEVER touches customer_id
``014ce6bb-1dbc-4067-998d-e05c16e7e342``. The seed path writes a
fresh quote with a UUID4-scoped customer_id each case and cleans up
on teardown.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values, load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 30

# ─── Local Mongo + JWT helpers (standalone — no cross-module imports)
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}

# Pat Kail LOCK — this file will NEVER seed, read, or touch this id.
PAT_KAIL_LOCKED = "014ce6bb-1dbc-4067-998d-e05c16e7e342"


def _mint_token(qid: str, tenant_id: str, cid: str) -> str:
    """Sign a magic-link JWT the same way the server mints them.

    Uses the raw ``JWT_SECRET`` / ``JWT_ALGO`` from the backend .env
    (same secret the server verifies with on
    ``_verify_estimate_token``).
    """
    import jwt
    secret = _ENV["JWT_SECRET"]
    algo = _ENV.get("JWT_ALGO") or "HS256"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "est",          # TOKEN_SUB in estimate_viewer.py
        "eid": qid,
        "tid": tenant_id,
        "cid": cid,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=1),
    }
    return jwt.encode(payload, secret, algorithm=algo)


def _seed_and_cleanup():
    """Mongo seed / teardown helpers via sync pymongo (safe to call
    from within pytest without crossing async loops)."""
    from pymongo import MongoClient
    mc = MongoClient(_ENV["MONGO_URL"])
    return mc[_ENV["DB_NAME"]]


@pytest.fixture
def seeded_quote():
    """Insert a fresh quote scoped by uuid4. Cleans up on teardown.

    Never collides with Pat Kail (asserted below).
    """
    db = _seed_and_cleanup()
    tenant_id = f"tenant-cgd-{uuid4()}"
    customer_id = f"customer-cgd-{uuid4()}"
    qid = f"quote-cgd-{uuid4()}"

    # Sanity: Pat Kail lock.
    assert customer_id != PAT_KAIL_LOCKED
    assert PAT_KAIL_LOCKED not in (tenant_id, customer_id, qid)

    db.tenants.insert_one({
        "id": tenant_id,
        "name": "Test tenant · toplevel-cgd regression",
    })
    db.customers.insert_one({
        "id": customer_id,
        "tenant_id": tenant_id,
        "name": "Test customer · toplevel-cgd",
    })
    # Minimal viable quote for the magic-link endpoint.
    base_doc = {
        "id": qid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "quote",
        "status": "sent",
        "title": "Toplevel-CGD regression test quote",
        "line_items": [
            {"description": "Item A", "quantity": 1,
             "unit_price": 100, "total": 100},
            {"description": "Item B", "quantity": 2,
             "unit_price": 50, "total": 100},
        ],
        "subtotal": 200, "tax": 0, "total": 200,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    yield {
        "qid": qid, "tenant_id": tenant_id, "customer_id": customer_id,
        "base_doc": base_doc, "db": db,
    }

    # Teardown — always runs.
    db.quotes.delete_many({"id": qid})
    db.customers.delete_many({"id": customer_id})
    db.tenants.delete_many({"id": tenant_id})


def _fetch_via_token(qid, tenant_id, customer_id):
    """Call ``GET /api/portal/quotes/via-token?token=…`` via the live
    preview backend and return the JSON payload."""
    tok = _mint_token(qid, tenant_id, customer_id)
    r = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token",
        params={"token": tok}, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, (
        f"HTTP {r.status_code} on /portal/quotes/via-token: "
        f"{r.text[:400]}"
    )
    return r.json()


# ═══════════════════════════════════════════════════════════════════
# Case 1 — DB customer_group_display=False → top-level == False
# This is the specific regression: pre-fix, this returned MISSING.
# ═══════════════════════════════════════════════════════════════════
def test_payload_exposes_top_level_customer_group_display_false(
    seeded_quote,
):
    doc = {**seeded_quote["base_doc"], "customer_group_display": False}
    seeded_quote["db"].quotes.insert_one(doc)

    payload = _fetch_via_token(
        seeded_quote["qid"], seeded_quote["tenant_id"],
        seeded_quote["customer_id"],
    )

    assert "customer_group_display" in payload, (
        "BUG REGRESSION: /portal/quotes/via-token payload is missing "
        "the top-level 'customer_group_display' field. "
        "EstimateView.jsx:373 reads data?.customer_group_display at "
        "the top level — when absent, it falls through the legacy "
        "'undefined → grouped' fallback and the customer page always "
        "renders grouped regardless of the admin toggle."
    )
    assert payload["customer_group_display"] is False, (
        f"Expected top-level False (admin's toggle), got "
        f"{payload['customer_group_display']!r}"
    )
    # Nested value should also still be False (defense in depth —
    # legacy consumers like the admin PDF path read from the nested
    # payload shape).
    nested = payload.get("customer_view", {}).get("customer_group_display")
    assert nested is False, (
        f"Nested customer_view.customer_group_display drifted — "
        f"expected False, got {nested!r}"
    )


# ═══════════════════════════════════════════════════════════════════
# Case 2 — DB customer_group_display=True → top-level == True
# ═══════════════════════════════════════════════════════════════════
def test_payload_exposes_top_level_customer_group_display_true(
    seeded_quote,
):
    doc = {**seeded_quote["base_doc"], "customer_group_display": True}
    seeded_quote["db"].quotes.insert_one(doc)

    payload = _fetch_via_token(
        seeded_quote["qid"], seeded_quote["tenant_id"],
        seeded_quote["customer_id"],
    )

    assert "customer_group_display" in payload
    assert payload["customer_group_display"] is True
    nested = payload.get("customer_view", {}).get("customer_group_display")
    assert nested is True


# ═══════════════════════════════════════════════════════════════════
# Case 3 — DB field absent (legacy quote) → top-level is None
# Legacy quotes default to grouped on the frontend because
# EstimateView.jsx:374 treats null/undefined as 'grouped'.
# Spec accepts either absent key OR present-with-None here.
# ═══════════════════════════════════════════════════════════════════
def test_payload_legacy_quote_without_customer_group_display(
    seeded_quote,
):
    # No customer_group_display key at all.
    doc = {**seeded_quote["base_doc"]}
    doc.pop("customer_group_display", None)
    seeded_quote["db"].quotes.insert_one(doc)

    payload = _fetch_via_token(
        seeded_quote["qid"], seeded_quote["tenant_id"],
        seeded_quote["customer_id"],
    )

    # Either absent, or present with None — both are acceptable per spec.
    sentinel = object()
    val = payload.get("customer_group_display", sentinel)
    assert val is None or val is sentinel, (
        f"Legacy quote should emit None at top level or omit the key, "
        f"got {val!r}"
    )
