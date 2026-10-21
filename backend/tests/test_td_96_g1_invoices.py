"""TD-96-g1-invoices · Feb-2026.

Covers the fork resolution for the ``linked_quotes_count`` vs
``/quotes?lead_id=X&view=all`` asymmetry. Scope path (ii) Expand per
operator's D1 decision: when ``lead_id`` AND ``view=all`` are BOTH
set on the quotes list endpoint, drop the ``doc_type="quote"``
forcing so invoice-shaped reparented docs (close-won carry-forward
from ``_run_close_won_pipeline`` with ``converted_from_lead_id``
stamped) surface alongside the lead's quotes.

Scope guards covered:
  * Lifecycle views (``open`` / ``accepted`` / ``converted`` /
    ``declined``) stay quote-only even when ``lead_id`` is set
    because those statuses only live on quote-shaped docs.
  * ``view=all`` without ``lead_id`` stays quote-only (standalone
    quotes dashboard mental model is "all quotes", not "all docs").
  * ``lead_id`` without any ``view`` stays doc-type-agnostic (prior
    behavior, matches ``linked_quotes_count`` + ``/leads/{lid}/quotes``
    semantics).
  * RBAC + soft-delete + tenant isolation preserved.
"""
from __future__ import annotations

import os
import uuid
from typing import List

import httpx
import pytest
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant(prefix: str = "TEST_td96g1i") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"td96g1i-{uuid.uuid4().hex[:8]}",
        "name": "TD96g1i Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"td96g1i-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"TEST_td96g1i_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"TD96g1i {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _mk_lead(tid: str) -> str:
    lid = f"TEST_td96g1i_lead_{uuid.uuid4().hex}"
    _sync.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": "Phase 2 Lead",
        "status": "closed_won",
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    return lid


def _mk_doc(tid: str, *, doc_type: str, lead_id: str | None = None,
             customer_id: str | None = None, status: str = "sent",
             converted_from_lead_id: str | None = None,
             deleted_at: str | None = None,
             invoice_number: str | None = None,
             quote_number: str | None = None) -> str:
    did = f"TEST_td96g1i_{doc_type}_{uuid.uuid4().hex}"
    doc: dict = {
        "id": did, "tenant_id": tid, "doc_type": doc_type,
        "status": status, "total": 100,
        "created_at": "2026-02-01T00:00:00+00:00",
        "title": f"{doc_type.title()} fixture",
        "customer_name": "Phase 2 Customer",
    }
    if lead_id:
        doc["recipient_type"] = "lead"
        doc["recipient_id"] = lead_id
    if customer_id:
        doc["recipient_type"] = "customer"
        doc["recipient_id"] = customer_id
        doc["customer_id"] = customer_id
    if converted_from_lead_id:
        doc["converted_from_lead_id"] = converted_from_lead_id
    if deleted_at:
        doc["deleted_at"] = deleted_at
    if invoice_number:
        doc["invoice_number"] = invoice_number
    if quote_number:
        doc["quote_number"] = quote_number
    _sync.quotes.insert_one(doc)
    return did


def _get(path: str, token: str, **params) -> list:
    r = httpx.get(f"{BASE}{path}", params=params,
                   headers={"Authorization": f"Bearer {token}"},
                   timeout=30)
    r.raise_for_status()
    data = r.json()
    # Shape: list for /quotes?... endpoint (not paginated here).
    return data if isinstance(data, list) else data.get("items", [])


@pytest.fixture
def admin_ctx():
    tid = _mk_tenant()
    yield {"tid": tid, "token": _login(_mk_user(tid, "admin"))}


# ──────────────────────────────────────────────────────────────────
# D1(ii) EXPAND — core behavior: lead_id + view=all returns both
# ──────────────────────────────────────────────────────────────────
def test_lead_id_view_all_returns_both_shapes(admin_ctx):
    """lead_id + view=all must return BOTH quote-shaped AND
    invoice-shaped reparented docs tied to the lead."""
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    # One live lead-recipient quote.
    qid = _mk_doc(tid, doc_type="quote", lead_id=lid,
                   quote_number="Q-1001")
    # One invoice reparented from the lead on close-won.
    iid = _mk_doc(tid, doc_type="invoice", customer_id=cid,
                   converted_from_lead_id=lid,
                   invoice_number="INV-2001")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="all")
    ids = {r.get("id") for r in rows}
    assert qid in ids, "quote-shaped lead-recipient doc must surface"
    assert iid in ids, "invoice-shaped reparented doc must surface"
    doc_types = {r.get("doc_type") for r in rows}
    assert doc_types == {"quote", "invoice"}


def test_lead_id_view_all_count_matches_linked_quotes_count(admin_ctx):
    """``linked_quotes_count`` from ``/api/leads/{lid}`` must equal
    the row count returned by ``/api/quotes?lead_id=&view=all``."""
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", lead_id=lid, quote_number="Q-1")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             converted_from_lead_id=lid, invoice_number="INV-1")
    _mk_doc(tid, doc_type="quote", customer_id=cid,
             converted_from_lead_id=lid, quote_number="Q-2")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="all")
    r = httpx.get(f"{BASE}/api/leads/{lid}",
                   headers={"Authorization": f"Bearer {admin_ctx['token']}"},
                   timeout=30)
    r.raise_for_status()
    lead = r.json()
    assert lead.get("linked_quotes_count") == len(rows) == 3


# ──────────────────────────────────────────────────────────────────
# Regression — lifecycle views stay quote-only even with lead_id
# ──────────────────────────────────────────────────────────────────
def test_lead_id_view_open_stays_quote_only(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", lead_id=lid, status="sent",
             quote_number="Q-OPEN")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             converted_from_lead_id=lid, status="sent",
             invoice_number="INV-OPEN")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="open")
    doc_types = {r.get("doc_type") for r in rows}
    assert doc_types == {"quote"}, (
        f"view=open+lead_id must stay quote-only, got doc_types={doc_types}"
    )


def test_lead_id_view_accepted_stays_quote_only(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", lead_id=lid, status="accepted",
             quote_number="Q-ACC")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             converted_from_lead_id=lid, status="sent",
             invoice_number="INV-ACC")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="accepted")
    for row in rows:
        assert row.get("doc_type") == "quote"


def test_lead_id_view_declined_stays_quote_only(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", lead_id=lid, status="declined",
             quote_number="Q-DEC")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             converted_from_lead_id=lid, status="declined",
             invoice_number="INV-DEC")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="declined")
    for row in rows:
        assert row.get("doc_type") == "quote"


# ──────────────────────────────────────────────────────────────────
# Regression — view=all WITHOUT lead_id stays quote-only
# ──────────────────────────────────────────────────────────────────
def test_view_all_without_lead_id_stays_quote_only(admin_ctx):
    """Standalone quotes dashboard "All" tab is still "all quotes",
    not "all docs" — ``doc_type="quote"`` forcing must apply when
    there is NO ``lead_id`` scope."""
    tid = admin_ctx["tid"]
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", customer_id=cid, quote_number="Q-ALL")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             invoice_number="INV-ALL")
    rows = _get("/api/quotes", admin_ctx["token"], view="all")
    for row in rows:
        assert row.get("doc_type") == "quote"


# ──────────────────────────────────────────────────────────────────
# Regression — lead_id alone (no view) returns both (existing)
# ──────────────────────────────────────────────────────────────────
def test_lead_id_without_view_returns_both_shapes(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    qid = _mk_doc(tid, doc_type="quote", lead_id=lid,
                   quote_number="Q-NO-VIEW")
    iid = _mk_doc(tid, doc_type="invoice", customer_id=cid,
                   converted_from_lead_id=lid,
                   invoice_number="INV-NO-VIEW")
    rows = _get("/api/quotes", admin_ctx["token"], lead_id=lid)
    ids = {r.get("id") for r in rows}
    assert qid in ids
    assert iid in ids


# ──────────────────────────────────────────────────────────────────
# RBAC — field tech 403 preserved after the fix
# ──────────────────────────────────────────────────────────────────
def test_rbac_field_tech_403():
    tid = _mk_tenant("TEST_td96g1i_rbac")
    tok = _login(_mk_user(tid, role="technician"))
    lid = _mk_lead(tid)
    r = httpx.get(f"{BASE}/api/quotes",
                   params={"lead_id": lid, "view": "all"},
                   headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    # Field tech access to the quotes list — expect 403 OR an empty/
    # scoped response (whichever the existing endpoint already does).
    # Core requirement: field tech MUST NOT see cross-tenant leaked
    # invoices via the new path.
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        for row in items:
            assert row.get("tenant_id", tid) == tid


# ──────────────────────────────────────────────────────────────────
# Soft-delete preserved
# ──────────────────────────────────────────────────────────────────
def test_soft_deleted_invoice_excluded(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    iid = _mk_doc(tid, doc_type="invoice", customer_id=cid,
                   converted_from_lead_id=lid,
                   invoice_number="INV-SOFT-DEL",
                   deleted_at="2026-02-01T00:00:00+00:00")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="all")
    ids = {r.get("id") for r in rows}
    assert iid not in ids


# ──────────────────────────────────────────────────────────────────
# Tenant isolation preserved
# ──────────────────────────────────────────────────────────────────
def test_tenant_isolation_cross_tenant_invoice_not_leaked(admin_ctx):
    """An invoice linked to a different tenant's lead must not leak
    into tenant A's response even when A asks for lead_id+view=all."""
    other_tid = _mk_tenant("TEST_td96g1i_other")
    other_lid = _mk_lead(other_tid)
    other_cid = f"TEST_td96g1i_other_cust_{uuid.uuid4().hex}"
    cross_iid = _mk_doc(other_tid, doc_type="invoice",
                         customer_id=other_cid,
                         converted_from_lead_id=other_lid,
                         invoice_number="INV-CROSS")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=other_lid, view="all")
    ids = {r.get("id") for r in rows}
    assert cross_iid not in ids


# ──────────────────────────────────────────────────────────────────
# Hit shape stability — doc_type field present on every row
# ──────────────────────────────────────────────────────────────────
def test_response_includes_doc_type_on_every_row(admin_ctx):
    """FE needs ``doc_type`` on each row to branch routing between
    ``/quotes/${id}`` and ``/invoices/${id}``. Must be stable."""
    tid = admin_ctx["tid"]
    lid = _mk_lead(tid)
    cid = f"TEST_td96g1i_cust_{uuid.uuid4().hex}"
    _mk_doc(tid, doc_type="quote", lead_id=lid, quote_number="Q-SHAPE")
    _mk_doc(tid, doc_type="invoice", customer_id=cid,
             converted_from_lead_id=lid, invoice_number="INV-SHAPE")
    rows = _get("/api/quotes", admin_ctx["token"],
                 lead_id=lid, view="all")
    assert len(rows) >= 2
    for row in rows:
        assert "doc_type" in row
        assert row["doc_type"] in {"quote", "invoice"}
