"""Feb-2026 · Pricebook × Profit-Reporting Phase 2 — Line-item
admin overrides on estimates + invoices.

Coverage:
  * PUT /api/quotes/{qid} persists the 4 new override fields on a
    ``line_items[i]`` mutation.
  * Snapshot fields (``retail_price_snapshot``,
    ``wholesale_price_snapshot``, ``labor_cost_snapshot``) are
    NEVER mutated by an override write.
  * Setting an override to ``null`` clears it (reset flow).
  * Customer-facing viewer strips the 4 override fields (magic
    link + full path).
  * Lock-bypass edit path preserves overrides for non-draft docs
    (sent / accepted / paid) — Editable Sent Docs regression.
  * Invoice line-item overrides survive the invoice PATCH path.
"""
from __future__ import annotations

import os
import uuid
import jwt
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]
_CACHE: dict = {}
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = os.environ.get("JWT_ALGO", "HS256")


def _login(email: str = "admin@aquaterra.com") -> str:
    if _CACHE.get(email):
        return _CACHE[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    _CACHE[email] = r.json()["access_token"]
    return _CACHE[email]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant() -> str:
    tok = _login()
    me = requests.get(f"{API}/auth/me", headers=_headers(tok), timeout=15).json()
    return me["tenant_id"]


@pytest.fixture(scope="module")
def seed_quote_with_snapshots():
    tid = _tenant()
    cust = f"pb2-cust-{uuid.uuid4()}"
    qid = f"pb2-quote-{uuid.uuid4()}"
    # Seed two service/income categories to reference from overrides.
    svc_a = f"pb2-svc-a-{uuid.uuid4()}"
    svc_b = f"pb2-svc-b-{uuid.uuid4()}"
    inc_a = f"pb2-inc-a-{uuid.uuid4()}"
    inc_b = f"pb2-inc-b-{uuid.uuid4()}"
    _db.service_categories.insert_many([
        {"id": svc_a, "tenant_id": tid, "name": "PB2 Svc A", "is_archived": False},
        {"id": svc_b, "tenant_id": tid, "name": "PB2 Svc B", "is_archived": False},
    ])
    _db.income_categories.insert_many([
        {"id": inc_a, "tenant_id": tid, "name": "PB2 Inc A", "is_archived": False},
        {"id": inc_b, "tenant_id": tid, "name": "PB2 Inc B", "is_archived": False},
    ])
    _db.customers.insert_one({
        "id": cust, "tenant_id": tid, "name": "PB2 Cust",
        "email": "pb2@example.com",
    })
    _db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": "quote",
        "customer_id": cust,
        "status": "draft",
        "title": "PB2 quote",
        "total": 500.0, "amount_paid": 0.0, "currency": "usd",
        "line_items": [{
            "id": "li-1",
            "description": "Cleaning service",
            "quantity": 2, "unit_price": 100.0,
            "retail_price_snapshot": 100.0,
            "wholesale_price_snapshot": 30.0,
            "labor_cost_snapshot": 20.0,
            "service_category_id": svc_a,
            "income_category_id": inc_a,
        }],
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {
        "tenant_id": tid, "customer_id": cust,
        "quote_id": qid,
        "svc_a": svc_a, "svc_b": svc_b,
        "inc_a": inc_a, "inc_b": inc_b,
    }
    _db.quotes.delete_one({"id": qid})
    _db.customers.delete_one({"id": cust})
    _db.service_categories.delete_many({"id": {"$in": [svc_a, svc_b]}})
    _db.income_categories.delete_many({"id": {"$in": [inc_a, inc_b]}})


# ─── 1. PUT persists overrides + snapshots stay immutable ────
def test_put_accepts_four_overrides(seed_quote_with_snapshots):
    s = seed_quote_with_snapshots
    tok = _login()
    r = requests.put(
        f"{API}/quotes/{s['quote_id']}",
        headers=_headers(tok),
        json={"line_items": [{
            "id": "li-1",
            "description": "Cleaning service",
            "quantity": 2, "unit_price": 100.0,
            # Overrides
            "wholesale_cost_override": 35.5,
            "labor_cost_override": 22.75,
            "service_category_id_override": s["svc_b"],
            "income_category_id_override": s["inc_b"],
            # Base category must still be present (K71 rule).
            "service_category_id": s["svc_a"],
            "income_category_id": s["inc_a"],
        }]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = _db.quotes.find_one({"id": s["quote_id"]}, {"_id": 0})
    line = got["line_items"][0]
    assert line["wholesale_cost_override"] == 35.5
    assert line["labor_cost_override"] == 22.75
    assert line["service_category_id_override"] == s["svc_b"]
    assert line["income_category_id_override"] == s["inc_b"]
    # Snapshots untouched.
    assert line["retail_price_snapshot"] == 100.0
    assert line["wholesale_price_snapshot"] == 30.0
    assert line["labor_cost_snapshot"] == 20.0


def test_null_override_clears(seed_quote_with_snapshots):
    """Sending explicit null on an override clears it (reset flow)."""
    s = seed_quote_with_snapshots
    tok = _login()
    r = requests.put(
        f"{API}/quotes/{s['quote_id']}",
        headers=_headers(tok),
        json={"line_items": [{
            "id": "li-1",
            "description": "Cleaning service",
            "quantity": 2, "unit_price": 100.0,
            "wholesale_cost_override": None,
            "labor_cost_override": None,
            "service_category_id_override": None,
            "income_category_id_override": None,
            "service_category_id": s["svc_a"],
            "income_category_id": s["inc_a"],
        }]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = _db.quotes.find_one({"id": s["quote_id"]}, {"_id": 0})
    line = got["line_items"][0]
    assert line.get("wholesale_cost_override") is None
    assert line.get("labor_cost_override") is None
    assert line.get("service_category_id_override") is None
    assert line.get("income_category_id_override") is None
    # Snapshots still untouched.
    assert line["wholesale_price_snapshot"] == 30.0
    assert line["labor_cost_snapshot"] == 20.0


# ─── 2. Customer serializer strips overrides ────────────────
def test_customer_payload_strips_overrides(seed_quote_with_snapshots):
    s = seed_quote_with_snapshots
    tok = _login()
    # Re-apply overrides so we can assert strip.
    requests.put(
        f"{API}/quotes/{s['quote_id']}",
        headers=_headers(tok),
        json={"line_items": [{
            "id": "li-1",
            "description": "Cleaning service",
            "quantity": 2, "unit_price": 100.0,
            "wholesale_cost_override": 40.0,
            "labor_cost_override": 25.0,
            "service_category_id_override": s["svc_b"],
            "income_category_id_override": s["inc_b"],
            "service_category_id": s["svc_a"],
            "income_category_id": s["inc_a"],
        }]},
        timeout=15,
    )
    # Mint a magic-link token → customer path (uses eid/cid/tid claims
    # per estimate_viewer._sign_estimate_token).
    tok_magic = jwt.encode(
        {
            "sub": "est",
            "eid": s["quote_id"],
            "cid": s["customer_id"],
            "tid": s["tenant_id"],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGO,
    )
    r = requests.get(
        f"{API}/portal/quotes/via-token",
        params={"token": tok_magic},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload.get("as_customer") is True
    banned = {
        "wholesale_cost_override", "labor_cost_override",
        "income_category_id_override", "service_category_id_override",
        "wholesale_price_snapshot", "labor_cost_snapshot",
        "retail_price_snapshot",
    }
    for li in payload.get("line_items", []):
        leaked = banned & set(li.keys())
        assert not leaked, f"Customer payload leaked admin fields: {leaked}"


def test_admin_payload_still_includes_overrides(seed_quote_with_snapshots):
    """Admin path is authoritative — overrides must round-trip."""
    s = seed_quote_with_snapshots
    tok = _login()
    r = requests.get(
        f"{API}/quotes/{s['quote_id']}/full",
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload.get("as_customer") is False
    li = payload["line_items"][0]
    assert li.get("wholesale_cost_override") == 40.0
    assert li.get("labor_cost_override") == 25.0
    assert li.get("service_category_id_override") == s["svc_b"]
    assert li.get("income_category_id_override") == s["inc_b"]


# ─── 3. Lock-bypass edit flow on locked invoices ────────────
@pytest.mark.parametrize("locked_status", ["sent", "accepted", "paid", "partial"])
def test_lock_bypass_override_edit(seed_quote_with_snapshots, locked_status):
    """Locked INVOICES (sent/accepted/paid/partial) require the
    ``acknowledged_lock_bypass`` flag. Overrides must still write
    correctly on that path — Editable Sent Docs regression guard."""
    s = seed_quote_with_snapshots
    tid = s["tenant_id"]
    cust = s["customer_id"]
    iid = f"pb2-locked-{locked_status}-{uuid.uuid4()}"
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": cust,
        "status": locked_status,
        "title": f"PB2 {locked_status}",
        "invoice_number": f"PB2-{locked_status.upper()}-001",
        "total": 100.0,
        "amount_paid": 100.0 if locked_status == "paid" else (
            50.0 if locked_status == "partial" else 0.0
        ),
        "currency": "usd",
        "line_items": [{
            "id": "li-1", "description": "X",
            "quantity": 1, "unit_price": 100.0,
            "retail_price_snapshot": 100.0,
            "wholesale_price_snapshot": 40.0,
            "labor_cost_snapshot": 10.0,
            "service_category_id": s["svc_a"],
            "income_category_id": s["inc_a"],
        }],
    })
    tok = _login()
    try:
        # Without ack — must be blocked by lock gate (409).
        r = requests.put(
            f"{API}/quotes/{iid}",
            headers=_headers(tok),
            json={"line_items": [{
                "id": "li-1", "description": "X",
                "quantity": 1, "unit_price": 100.0,
                "wholesale_cost_override": 45.0,
                "service_category_id": s["svc_a"],
                "income_category_id": s["inc_a"],
            }]},
            timeout=15,
        )
        assert r.status_code == 409, \
            f"Locked doc must gate line-item PATCH; got {r.status_code}: {r.text}"
        # With ack — must succeed and persist the override.
        r = requests.put(
            f"{API}/quotes/{iid}",
            headers=_headers(tok),
            json={
                "acknowledged_lock_bypass": True,
                "line_items": [{
                    "id": "li-1", "description": "X",
                    "quantity": 1, "unit_price": 100.0,
                    "wholesale_cost_override": 45.0,
                    "service_category_id": s["svc_a"],
                    "income_category_id": s["inc_a"],
                }],
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        got = _db.quotes.find_one({"id": iid}, {"_id": 0})
        assert got["line_items"][0]["wholesale_cost_override"] == 45.0
        # Snapshot untouched even under lock-bypass.
        assert got["line_items"][0]["wholesale_price_snapshot"] == 40.0
    finally:
        _db.quotes.delete_one({"id": iid})


# ─── 4. Invoice PATCH path also carries overrides ────────────
def test_invoice_line_item_overrides_persist(seed_quote_with_snapshots):
    s = seed_quote_with_snapshots
    tid = s["tenant_id"]
    cust = s["customer_id"]
    iid = f"pb2-inv-{uuid.uuid4()}"
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": cust,
        "status": "draft",
        "title": "PB2 invoice",
        "total": 200.0, "amount_paid": 0.0, "currency": "usd",
        "invoice_number": "PB2-INV-001",
        "line_items": [{
            "id": "li-1", "description": "Chem service",
            "quantity": 1, "unit_price": 200.0,
            "retail_price_snapshot": 200.0,
            "wholesale_price_snapshot": 50.0,
            "labor_cost_snapshot": 30.0,
            "service_category_id": s["svc_a"],
            "income_category_id": s["inc_a"],
        }],
        "payment_status": "unpaid",
    })
    tok = _login()
    try:
        r = requests.put(
            f"{API}/quotes/{iid}",
            headers=_headers(tok),
            json={"line_items": [{
                "id": "li-1", "description": "Chem service",
                "quantity": 1, "unit_price": 200.0,
                "wholesale_cost_override": 55.0,
                "labor_cost_override": 32.5,
                "service_category_id_override": s["svc_b"],
                "income_category_id_override": s["inc_b"],
                "service_category_id": s["svc_a"],
                "income_category_id": s["inc_a"],
            }]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        got = _db.quotes.find_one({"id": iid}, {"_id": 0})
        line = got["line_items"][0]
        assert line["wholesale_cost_override"] == 55.0
        assert line["labor_cost_override"] == 32.5
        assert line["service_category_id_override"] == s["svc_b"]
        assert line["income_category_id_override"] == s["inc_b"]
        assert line["wholesale_price_snapshot"] == 50.0
        assert line["labor_cost_snapshot"] == 30.0
    finally:
        _db.quotes.delete_one({"id": iid})
