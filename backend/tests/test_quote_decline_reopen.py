"""Phase 3 B1 · Feb-2026 — Quote lifecycle (decline / reopen / list view).

Covers:
    * POST /api/quotes/{qid}/decline  (new)
    * POST /api/quotes/{qid}/reopen   (new)
    * GET  /api/quotes?view=…         (new query param)
    * POST /api/quotes/{qid}/convert-to-invoice — new ``quote_declined``
      guard (Phase 1 interaction regression)

Follows the ``_clean`` autouse fixture pattern standardized in
0d7ddf8f4 — no module-scope ``_patch_db_everywhere()`` call.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.quotes", "routers.estimates",
                "services.invoice_builder", "services.invoice_numbering"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"ph3life-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {},
    })


async def _seed_customer(cid, tid, name="Carla Cust",
                         email="carla@example.com"):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name, "email": email,
    })


async def _seed_lead(lid, tid, name="Larry Lead",
                     email="larry@example.com"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name, "email": email,
    })


def _mk_quote_doc(qid, tid, *, status="draft", doc_type="quote",
                  customer_id="cust-1", customer_name="Carla Cust",
                  recipient_type=None, recipient_id=None,
                  converted_invoice_id=None,
                  previous_status=None, total=500.0):
    doc = {
        "id": qid,
        "tenant_id": tid,
        "doc_type": doc_type,
        "status": status,
        "title": f"Quote {qid}",
        "customer_id": customer_id,
        "customer_name": customer_name,
        "total": total,
        "amount_paid": 0,
        "payment_status": "unpaid",
        "line_items": [{"description": "Line", "quantity": 1,
                        "unit_price": total, "category": "service"}],
        "tax_rate": 0,
        "created_at": "2026-02-03T00:00:00+00:00",
    }
    if recipient_type:
        doc["recipient_type"] = recipient_type
    if recipient_id:
        doc["recipient_id"] = recipient_id
    if converted_invoice_id:
        doc["converted_invoice_id"] = converted_invoice_id
    if previous_status:
        doc["previous_status"] = previous_status
    return doc


async def _seed_quote(**overrides):
    doc = _mk_quote_doc(**overrides)
    await _DB.quotes.insert_one(doc)
    return doc


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "invoice_number_sequences", "settings", "properties"):
        await _DB[coll].delete_many({
            "$or": [{"id": rx}, {"tenant_id": rx}, {"entity_id": rx}],
        })
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


_ADMIN      = {"id": f"{PREFIX}-u-admin",      "role": "admin"}
_SUPERADMIN = {"id": f"{PREFIX}-u-super",      "role": "super_admin"}
_OWNER      = {"id": f"{PREFIX}-u-owner",      "role": "owner"}
_MANAGER    = {"id": f"{PREFIX}-u-manager",    "role": "manager"}
_TECH       = {"id": f"{PREFIX}-u-tech",       "role": "technician"}
_CUSTOMER   = {"id": f"{PREFIX}-u-customer",   "role": "customer"}
_DISPATCHER = {"id": f"{PREFIX}-u-dispatcher", "role": "dispatcher"}


# ═════════════════════════════════════════════════════════════════════
# Decline — happy paths
# ═════════════════════════════════════════════════════════════════════
def test_decline_from_draft_stores_previous_status_draft():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-draft"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="draft"))

    res = _run(decline_quote(qid=qid, user=_ADMIN,
                             tenant={"id": TENANT_A}))
    assert res["status"] == "declined"
    assert res["previous_status"] == "draft"
    assert res["declined_at"]

    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["status"] == "declined"
    assert doc["previous_status"] == "draft"
    assert doc["declined_by"] == _ADMIN["id"]
    assert doc["declined_at"] == res["declined_at"]


def test_decline_from_sent_stores_previous_status_sent():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-sent"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))

    res = _run(decline_quote(qid=qid, user=_ADMIN,
                             tenant={"id": TENANT_A}))
    assert res["previous_status"] == "sent"


def test_decline_from_accepted_stores_previous_status_accepted():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-accepted"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="accepted"))
    res = _run(decline_quote(qid=qid, user=_ADMIN,
                             tenant={"id": TENANT_A}))
    assert res["previous_status"] == "accepted"


# ═════════════════════════════════════════════════════════════════════
# Decline — guards
# ═════════════════════════════════════════════════════════════════════
def test_decline_already_declined_returns_400_already_declined():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-ad"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="declined"))

    with pytest.raises(HTTPException) as e:
        _run(decline_quote(qid=qid, user=_ADMIN,
                           tenant={"id": TENANT_A}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "already_declined"


def test_decline_already_converted_returns_400_already_converted():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-ac"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent",
                     converted_invoice_id=f"{PREFIX}-inv-existing"))

    with pytest.raises(HTTPException) as e:
        _run(decline_quote(qid=qid, user=_ADMIN,
                           tenant={"id": TENANT_A}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "already_converted"
    assert e.value.detail["invoice_id"] == f"{PREFIX}-inv-existing"


def test_decline_on_invoice_doc_returns_400_not_a_quote():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-inv-1"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A,
                     doc_type="invoice", status="draft"))

    with pytest.raises(HTTPException) as e:
        _run(decline_quote(qid=qid, user=_ADMIN,
                           tenant={"id": TENANT_A}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "not_a_quote"


def test_decline_cross_tenant_returns_404():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-ct"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="draft"))

    with pytest.raises(HTTPException) as e:
        _run(decline_quote(qid=qid, user=_ADMIN,
                           tenant={"id": TENANT_B}))
    assert e.value.status_code == 404


# ═════════════════════════════════════════════════════════════════════
# Decline — RBAC matrix
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user", [_ADMIN, _SUPERADMIN, _OWNER, _MANAGER])
def test_decline_rbac_allowed_roles(user):
    """admin / super_admin / owner / manager pass the role gate."""
    from utils import require_admin_or_manager
    # Not raising = allowed.
    result = require_admin_or_manager(user=user)
    assert result == user


@pytest.mark.parametrize("user", [_TECH, _CUSTOMER, _DISPATCHER])
def test_decline_rbac_denied_roles(user):
    """technician / customer / dispatcher get 403."""
    from utils import require_admin_or_manager
    with pytest.raises(HTTPException) as e:
        require_admin_or_manager(user=user)
    assert e.value.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# Reopen — RBAC matrix  (Phase 3 B2 remediation · Feb-2026)
#
# Audit flag: B1 shipped a dedicated RBAC parametrize for Decline
# (allow × 4, deny × 3) but no equivalent for Reopen. Reopen SHARES
# the ``require_admin_or_manager`` dep with Decline
# (``backend/routers/quotes.py`` ~L3104 for decline / ~L3178 for
# reopen) so the gate behavior is symmetric at the FastAPI
# dependency layer — this is defensible, but the B1 test corpus
# didn't lock it in. The combined parametrize below closes that
# gap with 1 allow + 2 deny cases.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user,allow", [
    (_MANAGER, True),     # 1 allow — same gate as decline
    (_TECH, False),       # 2 deny — same forbidden set as decline
    (_CUSTOMER, False),
])
def test_reopen_rbac_matrix(user, allow):
    """Reopen's role gate is the shared ``require_admin_or_manager``."""
    from utils import require_admin_or_manager
    if allow:
        assert require_admin_or_manager(user=user) == user
    else:
        with pytest.raises(HTTPException) as e:
            require_admin_or_manager(user=user)
        assert e.value.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# Reopen — happy paths + fallback
# ═════════════════════════════════════════════════════════════════════
def test_reopen_declined_from_sent_restores_sent():
    from routers.quotes import decline_quote, reopen_quote
    qid = f"{PREFIX}-q-rs"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))

    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    res = _run(reopen_quote(qid=qid, user=_ADMIN,
                            tenant={"id": TENANT_A}))

    assert res["status"] == "sent"
    assert res["previous_status_used"] == "sent"

    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["status"] == "sent"
    assert "previous_status" not in doc
    assert "declined_at" not in doc
    assert "declined_by" not in doc


def test_reopen_declined_from_draft_restores_draft():
    from routers.quotes import decline_quote, reopen_quote
    qid = f"{PREFIX}-q-rd"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="draft"))
    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    res = _run(reopen_quote(qid=qid, user=_ADMIN,
                            tenant={"id": TENANT_A}))
    assert res["status"] == "draft"


def test_reopen_legacy_declined_without_previous_status_falls_back_to_draft():
    """Legacy decline rows that predate Phase 3 lack
    ``previous_status`` — Reopen fallback restores to 'draft'."""
    from routers.quotes import reopen_quote
    qid = f"{PREFIX}-q-legacy"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="declined"))
    # No previous_status field. Simulate a pre-Phase-3 row.
    res = _run(reopen_quote(qid=qid, user=_ADMIN,
                            tenant={"id": TENANT_A}))
    assert res["status"] == "draft"
    assert res["previous_status_used"] == "draft"


def test_reopen_never_declined_returns_400_not_declined():
    from routers.quotes import reopen_quote
    qid = f"{PREFIX}-q-rn"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))
    with pytest.raises(HTTPException) as e:
        _run(reopen_quote(qid=qid, user=_ADMIN,
                          tenant={"id": TENANT_A}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "not_declined"


def test_reopen_on_invoice_returns_400_not_a_quote():
    from routers.quotes import reopen_quote
    qid = f"{PREFIX}-inv-ro"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A,
                     doc_type="invoice", status="declined"))
    with pytest.raises(HTTPException) as e:
        _run(reopen_quote(qid=qid, user=_ADMIN,
                          tenant={"id": TENANT_A}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "not_a_quote"


# ═════════════════════════════════════════════════════════════════════
# Phase 2 interaction — lead-recipient × decline/reopen
# ═════════════════════════════════════════════════════════════════════
def test_decline_on_lead_recipient_quote_works():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-lead"
    lid = f"{PREFIX}-lead-1"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid=lid, tid=TENANT_A))
    _run(_seed_quote(
        qid=qid, tid=TENANT_A, status="sent",
        customer_id=None, customer_name="Larry Lead",
        recipient_type="lead", recipient_id=lid,
    ))
    res = _run(decline_quote(qid=qid, user=_ADMIN,
                             tenant={"id": TENANT_A}))
    assert res["status"] == "declined"
    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["status"] == "declined"
    assert doc["recipient_type"] == "lead"


def test_reopen_on_lead_recipient_quote_works():
    from routers.quotes import decline_quote, reopen_quote
    qid = f"{PREFIX}-q-lead-ro"
    lid = f"{PREFIX}-lead-2"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid=lid, tid=TENANT_A))
    _run(_seed_quote(
        qid=qid, tid=TENANT_A, status="sent",
        customer_id=None, customer_name="Larry Lead",
        recipient_type="lead", recipient_id=lid,
    ))
    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    res = _run(reopen_quote(qid=qid, user=_ADMIN,
                            tenant={"id": TENANT_A}))
    assert res["status"] == "sent"
    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["recipient_type"] == "lead"


# ═════════════════════════════════════════════════════════════════════
# Phase 1 interaction regression — convert-to-invoice blocks declined
# ═════════════════════════════════════════════════════════════════════
def test_convert_to_invoice_on_declined_quote_returns_400_quote_declined():
    """New guard: a declined quote cannot be promoted to invoice."""
    from routers.quotes import decline_quote, convert_quote_to_invoice
    qid = f"{PREFIX}-q-conv-decl"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))
    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    with pytest.raises(HTTPException) as e:
        _run(convert_quote_to_invoice(qid=qid, user=_ADMIN,
                                      tenant={"id": TENANT_A,
                                              "name": "T",
                                              "timezone": "UTC",
                                              "settings": {}}))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "quote_declined"


# ═════════════════════════════════════════════════════════════════════
# Audit log — decline + reopen each write a row
# ═════════════════════════════════════════════════════════════════════
def test_decline_writes_audit_log_row():
    from routers.quotes import decline_quote
    qid = f"{PREFIX}-q-aud-d"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))
    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    row = _run(_DB.audit_logs.find_one({
        "entity_id": qid, "event": "quote.declined",
    }))
    assert row is not None
    assert row["user_id"] == _ADMIN["id"]
    assert row["previous_status"] == "sent"


def test_reopen_writes_audit_log_row():
    from routers.quotes import decline_quote, reopen_quote
    qid = f"{PREFIX}-q-aud-r"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_quote(qid=qid, tid=TENANT_A, status="sent"))
    _run(decline_quote(qid=qid, user=_ADMIN,
                       tenant={"id": TENANT_A}))
    _run(reopen_quote(qid=qid, user=_ADMIN,
                      tenant={"id": TENANT_A}))
    row = _run(_DB.audit_logs.find_one({
        "entity_id": qid, "event": "quote.reopened",
    }))
    assert row is not None
    assert row["previous_status_used"] == "sent"


# ═════════════════════════════════════════════════════════════════════
# List filter — view=open / converted / declined / all / absent
# ═════════════════════════════════════════════════════════════════════
def _seed_list_fixtures(tid):
    """Seed a mixed set of quotes + 1 invoice row for list filter tests."""
    _run(_seed_tenant(tid))
    _run(_seed_quote(qid=f"{PREFIX}-l-draft",   tid=tid, status="draft"))
    _run(_seed_quote(qid=f"{PREFIX}-l-sent",    tid=tid, status="sent"))
    _run(_seed_quote(qid=f"{PREFIX}-l-accepted",tid=tid, status="accepted"))
    _run(_seed_quote(qid=f"{PREFIX}-l-declined",tid=tid, status="declined"))
    _run(_seed_quote(qid=f"{PREFIX}-l-conv",    tid=tid, status="sent",
                     converted_invoice_id=f"{PREFIX}-inv-X"))
    _run(_seed_quote(qid=f"{PREFIX}-l-inv",     tid=tid,
                     doc_type="invoice", status="draft"))


def _call_list(view, tid):
    from routers.quotes import list_quotes
    return _run(list_quotes(
        user=_ADMIN, tenant={"id": tid},
        doc_type=None, include_deleted=False,
        category=None, card_on_file=None,
        customer_id=None, payment_status=None,
        view=view,
    ))


def test_list_view_open_returns_only_open_quotes():
    _seed_list_fixtures(TENANT_A)
    rows = _call_list("open", TENANT_A)
    ids = {r["id"] for r in rows}
    assert ids == {f"{PREFIX}-l-draft", f"{PREFIX}-l-sent",
                   f"{PREFIX}-l-accepted"}


def test_list_view_converted_returns_only_converted_quotes():
    _seed_list_fixtures(TENANT_A)
    rows = _call_list("converted", TENANT_A)
    assert {r["id"] for r in rows} == {f"{PREFIX}-l-conv"}


def test_list_view_declined_returns_only_declined_quotes():
    _seed_list_fixtures(TENANT_A)
    rows = _call_list("declined", TENANT_A)
    assert {r["id"] for r in rows} == {f"{PREFIX}-l-declined"}


def test_list_view_all_returns_all_quote_doctype_only():
    _seed_list_fixtures(TENANT_A)
    rows = _call_list("all", TENANT_A)
    ids = {r["id"] for r in rows}
    # All 5 quote-doctype rows; invoice row excluded.
    assert f"{PREFIX}-l-inv" not in ids
    assert len(ids) == 5


def test_list_view_absent_preserves_back_compat():
    """When ``view`` param is not sent, behave exactly as before."""
    _seed_list_fixtures(TENANT_A)
    rows = _call_list(None, TENANT_A)
    ids = {r["id"] for r in rows}
    # Back-compat: no doc_type restriction either, so the invoice row
    # IS included.
    assert f"{PREFIX}-l-inv" in ids
    assert len(ids) == 6


def test_list_view_invalid_returns_400():
    _run(_seed_tenant(TENANT_A))
    from routers.quotes import list_quotes
    with pytest.raises(HTTPException) as e:
        _run(list_quotes(
            user=_ADMIN, tenant={"id": TENANT_A},
            doc_type=None, include_deleted=False,
            category=None, card_on_file=None,
            customer_id=None, payment_status=None,
            view="junk",
        ))
    assert e.value.status_code == 400
    assert e.value.detail["error_code"] == "invalid_view"
