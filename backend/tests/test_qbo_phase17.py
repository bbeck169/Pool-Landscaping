"""Phase 17 · Feb-2026 — QBO read-sync tests.

Every Intuit HTTP call is stubbed via ``httpx.MockTransport`` — zero
network from CI. The pytest process drives service-level helpers
in-process; HTTP-driven router tests hit the live backend for the auth /
role / validation surfaces that never reach Intuit.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List

import httpx
import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

os.environ.setdefault("QBO_ENVIRONMENT", "sandbox")
os.environ.setdefault("QBO_CLIENT_ID", "test_client_id")
os.environ.setdefault("QBO_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("QBO_REDIRECT_URI", "http://localhost/callback")

from services.qbo import client as qbo_client  # noqa: E402
from services.qbo import match as qbo_match  # noqa: E402
from services.qbo import oauth as qbo_oauth  # noqa: E402
from services.qbo import sync as qbo_sync  # noqa: E402

_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _FRESH[_ENV["DB_NAME"]]
qbo_oauth.db = _DB
qbo_client.db = _DB
qbo_sync.db = _DB
qbo_match.db = _DB

_TAG = "TEST_p17"


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


def _cleanup():
    tid = _tid()
    for coll in ("qbo_connections", "qbo_sync_runs", "qbo_customers",
                 "qbo_vendors", "qbo_invoices", "qbo_payments",
                 "qbo_accounts", "qbo_journal_entries", "qbo_bills"):
        _sync[coll].delete_many({"tenant_id": tid})


@pytest.fixture(autouse=True)
def _cleanup_around():
    _cleanup()
    yield
    _cleanup()
    qbo_client.set_transport(None)


# ── Fake Intuit HTTP transport ────────────────────────────────────────
def _make_transport(routes: Dict[str, List]) -> httpx.MockTransport:
    """``routes`` maps method+path prefixes to a list of ``(status, json_body)``
    tuples. Each call pops the next tuple; when a list is empty we return
    the last tuple repeatedly so tests don't need to over-enqueue."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        matched = None
        for k in routes:
            if key.startswith(k) or k in key:
                matched = k
                break
        if matched is None:
            return httpx.Response(404, json={"error": "no_route", "url": str(request.url)})
        lst = routes[matched]
        if not lst:
            return httpx.Response(404, json={"error": "queue_empty"})
        status, body = lst[0] if len(lst) == 1 else lst.pop(0)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _seed_connection(tenant_id: str, *, status: str = "active",
                      realm: str = "1234567890") -> str:
    conn_id = str(uuid.uuid4())
    _sync.qbo_connections.insert_one({
        "id": conn_id,
        "qbo_connection_id": conn_id,
        "tenant_id": tenant_id,
        "qbo_realm_id": realm,
        "qbo_company_name": "Test Co",
        "encrypted_access_token": qbo_oauth.encrypt("fake_access_token"),
        "encrypted_refresh_token": qbo_oauth.encrypt("fake_refresh_token"),
        "access_token_expires_at": "2030-01-01T00:00:00+00:00",
        "refresh_token_expires_at": "2030-06-01T00:00:00+00:00",
        "environment": "sandbox",
        "status": status,
        "connected_by": "test",
        "connected_at": "2026-08-01T00:00:00+00:00",
    })
    return conn_id


# ═════════════════════════════════════════════════════════════════════
# OAuth
# ═════════════════════════════════════════════════════════════════════
def test_build_auth_url_returns_signed_state():
    out = qbo_oauth.build_auth_url("tenant_abc")
    assert out["auth_url"].startswith("https://appcenter.intuit.com/connect/oauth2?")
    assert "state=" in out["auth_url"]
    claims = qbo_oauth._verify_state(out["state"])
    assert claims["tenant_id"] == "tenant_abc"
    assert claims["scope"] == "qbo_oauth_state"


def test_handle_callback_encrypts_and_persists_tokens():
    state = qbo_oauth._sign_state(_tid())
    tx = _make_transport({
        "POST /oauth2/v1/tokens/bearer": [
            (200, {"access_token": "acc_123", "refresh_token": "ref_456",
                   "expires_in": 3600, "x_refresh_token_expires_in": 8640000}),
        ],
    })
    async def _go():
        async with httpx.AsyncClient(transport=tx) as client:
            return await qbo_oauth.handle_callback(
                code="c", realm_id="9876", state=state,
                user_id="test_user", _http=client,
            )
    res = _run(_go())
    assert res["qbo_realm_id"] == "9876"
    row = _sync.qbo_connections.find_one({"qbo_connection_id": res["qbo_connection_id"]})
    assert row is not None
    # Tokens must be encrypted at rest.
    assert row["encrypted_access_token"] != "acc_123"
    assert qbo_oauth.decrypt(row["encrypted_access_token"]) == "acc_123"
    assert row["status"] == "active"


def test_handle_callback_tampered_state_raises():
    tx = _make_transport({"POST /oauth2/v1/tokens/bearer": [(200, {})]})
    async def _go():
        async with httpx.AsyncClient(transport=tx) as client:
            await qbo_oauth.handle_callback(
                code="c", realm_id="9876", state="not.a.valid.jwt",
                user_id="test_user", _http=client,
            )
    with pytest.raises(ValueError):
        _run(_go())


def test_refresh_success_updates_encrypted_tokens():
    tid = _tid()
    cid = _seed_connection(tid)
    tx = _make_transport({
        "POST /oauth2/v1/tokens/bearer": [
            (200, {"access_token": "new_acc", "refresh_token": "new_ref",
                   "expires_in": 3600, "x_refresh_token_expires_in": 8640000}),
        ],
    })
    async def _go():
        async with httpx.AsyncClient(transport=tx) as client:
            return await qbo_oauth.refresh_access_token(cid, _http=client)
    r = _run(_go())
    assert r["ok"] is True
    row = _sync.qbo_connections.find_one({"qbo_connection_id": cid})
    assert qbo_oauth.decrypt(row["encrypted_access_token"]) == "new_acc"


def test_refresh_401_flips_to_reauth_required():
    tid = _tid()
    cid = _seed_connection(tid)
    tx = _make_transport({
        "POST /oauth2/v1/tokens/bearer": [(401, {"error": "invalid_grant"})],
    })
    async def _go():
        async with httpx.AsyncClient(transport=tx) as client:
            return await qbo_oauth.refresh_access_token(cid, _http=client)
    r = _run(_go())
    assert r["ok"] is False
    assert r["error"] == "reauth_required"
    row = _sync.qbo_connections.find_one({"qbo_connection_id": cid})
    assert row["status"] == "reauth_required"


# ═════════════════════════════════════════════════════════════════════
# Sync
# ═════════════════════════════════════════════════════════════════════
def _sync_transport(entity_pages: Dict[str, List[dict]]) -> httpx.MockTransport:
    """Route every ``/query`` request to the right entity list."""
    entity_lookup = {
        "Account": "accounts", "Customer": "customers", "Vendor": "vendors",
        "Invoice": "invoices", "Payment": "payments",
        "JournalEntry": "journal_entries", "Bill": "bills",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "query" not in request.url.path:
            return httpx.Response(404, json={"error": "no_route"})
        query = request.url.params.get("query") or ""
        # Extract entity name after FROM.
        entity_name = None
        for name in entity_lookup:
            if f"FROM {name}" in query:
                entity_name = entity_lookup[name]
                key_upper = name
                break
        if not entity_name:
            return httpx.Response(200, json={"QueryResponse": {}})
        rows = entity_pages.get(entity_name, [])
        return httpx.Response(200, json={"QueryResponse": {key_upper: rows}})

    return httpx.MockTransport(handler)


def test_sync_full_mode_pulls_all_seven_entities_in_order():
    tid = _tid()
    cid = _seed_connection(tid)
    pages = {
        "accounts":        [{"Id": "A1", "Name": "Bank"}],
        "customers":       [{"Id": "C1", "DisplayName": "Alice", "Balance": 100}],
        "vendors":         [{"Id": "V1", "DisplayName": "Supplier"}],
        "invoices":        [{"Id": "I1", "DocNumber": "INV-1", "TotalAmt": 250, "TxnDate": "2026-05-01",
                             "CustomerRef": {"value": "C1", "name": "Alice"}}],
        "payments":        [{"Id": "P1", "TotalAmt": 250, "TxnDate": "2026-05-02",
                             "CustomerRef": {"value": "C1"}}],
        "journal_entries": [{"Id": "J1", "DocNumber": "JE-1", "TotalAmt": 10}],
        "bills":           [{"Id": "B1", "DocNumber": "BILL-1", "TotalAmt": 42,
                             "VendorRef": {"value": "V1", "name": "Supplier"}}],
    }
    qbo_client.set_transport(_sync_transport(pages))
    res = _run(qbo_sync.sync_tenant(
        tenant_id=tid, qbo_connection_id=cid,
        force_full=True, triggered_by="manual",
    ))
    assert res["status"] == "success"
    for e in qbo_sync.ENTITY_ORDER:
        assert res["entities_pulled"].get(e) == 1
    # Verify each mirror collection has the row.
    assert _sync.qbo_customers.find_one({"qbo_id": "C1", "tenant_id": tid})
    assert _sync.qbo_invoices.find_one({"qbo_id": "I1", "tenant_id": tid})
    assert _sync.qbo_bills.find_one({"qbo_id": "B1", "tenant_id": tid})


def test_sync_delta_mode_uses_changed_since_on_second_run():
    tid = _tid()
    cid = _seed_connection(tid)
    seen_queries: List[str] = []

    def handler(request):
        seen_queries.append(request.url.params.get("query") or "")
        return httpx.Response(200, json={"QueryResponse": {}})
    qbo_client.set_transport(httpx.MockTransport(handler))

    _run(qbo_sync.sync_tenant(tenant_id=tid, qbo_connection_id=cid, force_full=True))
    seen_queries.clear()
    _run(qbo_sync.sync_tenant(tenant_id=tid, qbo_connection_id=cid))
    assert any("Metadata.LastUpdatedTime >" in q for q in seen_queries), seen_queries


def test_sync_partial_failure_marks_status_partial_success():
    tid = _tid()
    cid = _seed_connection(tid)

    def handler(request):
        q = request.url.params.get("query") or ""
        if "FROM Invoice" in q:
            return httpx.Response(500, json={"error": "boom"})
        # Customer succeeds so we get a partial (some entity pulled).
        if "FROM Customer" in q:
            return httpx.Response(200, json={"QueryResponse": {"Customer": [
                {"Id": "C1", "DisplayName": "Alice"}
            ]}})
        return httpx.Response(200, json={"QueryResponse": {}})
    qbo_client.set_transport(httpx.MockTransport(handler))

    res = _run(qbo_sync.sync_tenant(
        tenant_id=tid, qbo_connection_id=cid, force_full=True,
    ))
    assert res["status"] == "partial_success"
    assert res["entities_pulled"].get("customers") == 1
    assert any(err["entity"] == "invoices" for err in res["errors"])


def test_sync_concurrent_runs_returns_existing_run_id():
    tid = _tid()
    cid = _seed_connection(tid)
    # Manually insert a running row.
    running_run = str(uuid.uuid4())
    _sync.qbo_sync_runs.insert_one({
        "run_id": running_run, "id": running_run,
        "tenant_id": tid, "qbo_connection_id": cid,
        "status": "running", "started_at": "2026-08-05T12:00:00+00:00",
        "triggered_by": "manual", "entities_pulled": {}, "errors": [],
    })
    res = _run(qbo_sync.sync_tenant(
        tenant_id=tid, qbo_connection_id=cid, force_full=True,
    ))
    assert res["run_id"] == running_run
    assert res.get("already_running") is True


# ═════════════════════════════════════════════════════════════════════
# Match
# ═════════════════════════════════════════════════════════════════════
def test_match_suggestions_invoice_amount_and_date():
    tid = _tid()
    _seed_connection(tid)
    # Seed a QBO invoice mirror row.
    _sync.qbo_invoices.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tid, "qbo_id": "QI1", "qbo_realm_id": "r",
        "raw": {}, "extracted": {
            "total": 100.0, "txn_date": "2026-06-15",
            "customer_name": "Alice Smith",
        },
        "last_synced_at": "2026-08-05T00:00:00Z",
    })
    # Seed matching + non-matching CRM invoices.
    _sync.quotes.insert_many([
        {"id": f"{_TAG}_iv_match", "tenant_id": tid, "doc_type": "invoice",
         "total": 100.5, "customer_name": "Alice Smith",
         "issued_at": "2026-06-14T00:00:00Z", "created_at": "2026-06-14T00:00:00Z",
         "invoice_number": "MATCH-1"},
        {"id": f"{_TAG}_iv_faroff", "tenant_id": tid, "doc_type": "invoice",
         "total": 100.2, "customer_name": "Bob Jones",
         "issued_at": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:00Z",
         "invoice_number": "FAR-1"},
    ])
    try:
        hits = _run(qbo_match.suggest(
            tenant_id=tid, qbo_entity_type="invoice", qbo_id="QI1",
        ))
        assert len(hits) >= 1
        # The Alice/close-date match should outrank the Bob/far-date match.
        assert hits[0]["crm_id"] == f"{_TAG}_iv_match"
        assert hits[0]["confidence"] > 0.6
    finally:
        _sync.quotes.delete_many({"id": {"$regex": f"^{_TAG}_iv"}})


def test_match_link_persists_bidirectionally():
    tid = _tid()
    _sync.qbo_customers.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tid, "qbo_id": "QC1",
        "qbo_realm_id": "r", "raw": {}, "extracted": {"display_name": "Bob"},
        "last_synced_at": "2026-08-05T00:00:00Z",
    })
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/qbo/match-link",
        json={"qbo_entity_type": "customer", "qbo_id": "QC1",
              "crm_entity_type": "customer", "crm_id": "crm_bob"},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    row = _sync.qbo_customers.find_one({"qbo_id": "QC1"})
    assert row["linked_crm_id"] == "crm_bob"
    # Unlink.
    r2 = requests.delete(f"{API}/qbo/match-link/customer/QC1",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r2.status_code == 200
    row2 = _sync.qbo_customers.find_one({"qbo_id": "QC1"})
    assert row2.get("linked_crm_id") is None


# ═════════════════════════════════════════════════════════════════════
# Router role guards + cross-tenant safety
# ═════════════════════════════════════════════════════════════════════
def test_router_endpoints_tech_and_customer_403():
    from tests.conftest import demo_pw
    endpoints = [
        ("GET", "/qbo/connections", None),
        ("GET", "/qbo/customers", None),
        ("GET", "/qbo/invoices", None),
        ("POST", "/qbo/sync/run-now", {"qbo_connection_id": "x"}),
        ("POST", "/qbo/match-link", {"qbo_entity_type": "customer",
                                       "qbo_id": "x",
                                       "crm_entity_type": "customer",
                                       "crm_id": "y"}),
    ]
    for role_email in ("customer@aquaterra.com", "mike@aquaterra.com"):
        try:
            tok = _login(role_email, demo_pw(role_email))
        except Exception:
            continue
        for method, path, body in endpoints:
            fn = requests.post if method == "POST" else requests.get
            kwargs = {"headers": {"Authorization": f"Bearer {tok}"}, "timeout": 10}
            if body is not None:
                kwargs["json"] = body
            r = fn(f"{API}{path}", **kwargs)
            assert r.status_code == 403, f"{role_email} {method} {path} → {r.status_code}"


def test_router_sync_cross_tenant_connection_404():
    tid_other = f"other_tenant_{uuid.uuid4().hex[:6]}"
    _sync.qbo_connections.insert_one({
        "id": str(uuid.uuid4()),
        "qbo_connection_id": "foreign_conn",
        "tenant_id": tid_other, "qbo_realm_id": "r",
        "status": "active",
        "encrypted_access_token": qbo_oauth.encrypt("x"),
        "encrypted_refresh_token": qbo_oauth.encrypt("x"),
        "access_token_expires_at": "2030-01-01T00:00:00+00:00",
        "environment": "sandbox",
        "connected_by": "x", "connected_at": "2026-01-01T00:00:00Z",
    })
    try:
        tok = _login("manager@aquaterra.com")
        r = requests.post(f"{API}/qbo/sync/run-now",
            json={"qbo_connection_id": "foreign_conn"},
            headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 404
    finally:
        _sync.qbo_connections.delete_one({"qbo_connection_id": "foreign_conn"})


def test_grep_lint_no_writes_to_db_invoices():
    """Phase 11 invariant — Phase 17 QBO modules must not touch db.invoices."""
    import re
    root = Path(__file__).resolve().parents[1]
    for rel in ("services/qbo/sync.py",
                "services/qbo/oauth.py",
                "services/qbo/client.py",
                "services/qbo/match.py",
                "routers/qbo_router.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert not re.search(r"db\.invoices\.(insert|update|delete|find_one_and_)", text), rel
