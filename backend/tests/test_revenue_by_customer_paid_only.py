"""Phase 4a · Feb-2026 — Revenue by Customer paid-only guard.

Locks the strict ``payment_status == "paid"`` + ``doc_type == "invoice"``
+ ``account_correction != true`` contract on both callsites that feed
the Revenue by Customer report:

  * ``GET /api/reports/revenue-by-customer``
    (dedicated route · ``backend/routers/reports.py``)
  * ``GET /api/reports/kpi/revenue_by_customer``
    (KPI metric · ``backend/services/reporting/metrics/revenue_by_customer.py``)

Both are driven by the same backing collection (``db.quotes``, which
stores invoices + quotes side-by-side distinguished by ``doc_type``).
The dedicated route already filters to ``doc_type="invoice"`` via
``_fetch_paid``; the KPI metric previously used the shared
``build_lens_filter`` which did NOT scope to invoices AND did NOT
require ``payment_status=="paid"`` on its default ``invoiced`` lens.

Seed strategy mirrors ``test_account_correction_parity.py`` — a fresh
tenant is spun up per test, docs are inserted directly through the
shared Mongo singleton, and the Revenue by Customer response is asked
to surface exactly ``$X`` for the test customer.  Each test asserts
either a specific amount or absence of the row.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid, email, tid, role):
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token, tenant_id):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant_id}


# ──────────────────────────────────────────────────────────────────
#  Seed helpers — all write DIRECTLY to Mongo so we control exact
#  ``payment_status`` / ``doc_type`` / ``account_correction`` values
#  without the payment_reconciler clamping anything.
# ──────────────────────────────────────────────────────────────────

def _seed_admin(tenant_id):
    uid = f"adm-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p4a.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "P4a admin", "email": email,
    })
    return {
        "id": uid, "email": email, "tenant_id": tenant_id,
        "token": _tok(uid, email, tenant_id, "admin"),
    }


def _seed_customer(tenant_id, name, *, account_correction=False):
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "first_name": name.split()[0] if " " in name else name,
        "last_name":  "T",
        "created_at": "2026-01-01T00:00:00+00:00",
        "is_active":  True,
    }
    if account_correction:
        doc["account_correction"] = True
        doc["account_correction_at"] = "2026-02-01T00:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _seed_doc(tenant_id, customer_id, customer_name, *,
              total, payment_status, doc_type="invoice",
              amount_paid=None,
              paid_at_iso="2026-02-15T12:00:00+00:00",
              created_at_iso="2026-02-10T12:00:00+00:00"):
    """Insert a quote-or-invoice doc directly.  Caller controls
    every discriminator field so each test exercises exactly one
    axis of the paid-only guard."""
    did = f"doc-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id":             did,
        "tenant_id":      tenant_id,
        "doc_type":       doc_type,
        "customer_id":    customer_id,
        "customer_name":  customer_name,
        "total":          float(total),
        "amount_paid":    (float(amount_paid)
                            if amount_paid is not None
                            else (float(total) if payment_status == "paid"
                                  else 0.0)),
        "payment_status": payment_status,
        "status":         payment_status,
        "paid_at":        paid_at_iso if payment_status == "paid" else None,
        "paid_date":      (paid_at_iso.split("T")[0]
                            if payment_status == "paid" and paid_at_iso
                            else None),
        "created_at":     created_at_iso,
    })
    return did


@pytest.fixture
def tenant_id():
    tid = f"p4a-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": "P4a smoke", "slug": tid, "active": True,
    })
    yield tid
    for col in ("tenants", "users", "customers", "quotes",
                "customer_account_correction_audit"):
        _sync[col].delete_many({"tenant_id": tid})


def _get_row(headers, cid):
    r = requests.get(f"{API}/reports/revenue-by-customer",
                     headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    for row in r.json().get("rows", []):
        if row.get("customer_id") == cid:
            return row
    return None


def _get_kpi_row(headers, cid, lens="collected"):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer"
        f"?period=custom&start=2026-02-01&end=2026-02-28"
        f"&lens={lens}&limit=500",
        headers=headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    for row in r.json().get("rows", []):
        if row.get("customer_id") == cid:
            return row
    return None


# ══════════════════════════════════════════════════════════════════
#  Unit tests — pure Python, lock the filter shape even when the
#  integration path is unavailable.
# ══════════════════════════════════════════════════════════════════

def test_build_doc_match_invoiced_lens_has_doc_type_invoice_and_paid_filter():
    from services.reporting.metrics.revenue_by_customer import (
        _build_doc_match,
    )
    m = _build_doc_match("invoiced", "2026-02-01", "2026-02-28")
    cs = m["$and"]
    assert {"doc_type": "invoice"} in cs, (
        f"invoiced lens must hard-filter to doc_type=invoice; got {cs}"
    )
    # ``PAID_STATUS_FILTER`` is {"$or": [{"amount_paid":{"$gt":0}},
    #                                   {"payment_status":"paid"}]}.
    assert any(
        c.get("$or") and any(
            isinstance(sub, dict) and sub.get("payment_status") == "paid"
            for sub in c["$or"]
        )
        for c in cs
    ), f"invoiced lens must require payment_status=paid; got {cs}"


def test_build_doc_match_collected_lens_has_doc_type_invoice_and_paid_filter():
    from services.reporting.metrics.revenue_by_customer import (
        _build_doc_match,
    )
    m = _build_doc_match("collected", "2026-02-01", "2026-02-28")
    cs = m["$and"]
    assert {"doc_type": "invoice"} in cs
    assert any(
        c.get("$or") and any(
            isinstance(sub, dict) and sub.get("payment_status") == "paid"
            for sub in c["$or"]
        )
        for c in cs
    )


def test_shared_build_lens_filter_is_no_longer_called_by_the_metric():
    """Regression lock — the metric must NOT reach back into the
    shared ``build_lens_filter`` which permits unpaid rows on the
    ``invoiced`` lens.  We inspect the module's code object rather
    than its docstring so an informational mention stays allowed."""
    import services.reporting.metrics.revenue_by_customer as mod
    # 1. Must not be imported into the module namespace.
    assert not hasattr(mod, "build_lens_filter"), (
        "revenue_by_customer must not import ``build_lens_filter`` "
        "from the shared helper — use the local ``_build_doc_match`` "
        "instead so payment_status==paid is always required."
    )
    # 2. Must not appear in any function's bytecode names.
    import types as _types
    for name, obj in vars(mod).items():
        if isinstance(obj, _types.FunctionType):
            co_names = set(obj.__code__.co_names)
            assert "build_lens_filter" not in co_names, (
                f"function ``{name}`` in revenue_by_customer still "
                f"calls ``build_lens_filter``"
            )


# ══════════════════════════════════════════════════════════════════
#  Integration — dedicated ``/reports/revenue-by-customer`` route.
# ══════════════════════════════════════════════════════════════════

def test_paid_invoice_is_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Alpha")
    _seed_doc(tenant_id, cid, "Alpha", total=137.50, payment_status="paid")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is not None, "paid invoice must surface the customer row"
    assert row["amount"] == pytest.approx(137.50, abs=0.01)
    assert row["invoices"] == 1


def test_partial_invoice_is_not_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Bravo")
    _seed_doc(tenant_id, cid, "Bravo", total=500.0,
              payment_status="partial", amount_paid=50.0)
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, (
        f"partial-paid invoice must NOT surface the customer row; got {row}"
    )


def test_open_invoice_is_not_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Charlie")
    _seed_doc(tenant_id, cid, "Charlie", total=200.0,
              payment_status="open")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, f"open invoice must NOT surface; got {row}"


def test_sent_invoice_is_not_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Delta")
    _seed_doc(tenant_id, cid, "Delta", total=75.0,
              payment_status="sent")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, f"sent invoice must NOT surface; got {row}"


def test_paid_but_account_correction_customer_is_not_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Echo", account_correction=True)
    _seed_doc(tenant_id, cid, "Echo", total=999.0, payment_status="paid")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, (
        f"account_correction customer must be excluded; got {row}"
    )


def test_quote_doc_is_not_counted(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Foxtrot")
    # Even with ``payment_status="paid"``, a doc_type="quote" row
    # must NEVER contribute — quotes are not revenue.
    _seed_doc(tenant_id, cid, "Foxtrot", total=10_000.0,
              payment_status="paid", doc_type="quote")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, (
        f"doc_type=quote must never contribute; got {row}"
    )


def test_two_paid_invoices_sum_on_one_row(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Golf")
    _seed_doc(tenant_id, cid, "Golf", total=120.0, payment_status="paid")
    _seed_doc(tenant_id, cid, "Golf", total=80.5,  payment_status="paid")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is not None
    assert row["amount"] == pytest.approx(200.5, abs=0.01)
    assert row["invoices"] == 2


def test_customer_with_only_unpaid_and_quotes_returns_zero(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Hotel")
    _seed_doc(tenant_id, cid, "Hotel", total=100.0,  payment_status="open")
    _seed_doc(tenant_id, cid, "Hotel", total=250.0,  payment_status="partial",
              amount_paid=25.0)
    _seed_doc(tenant_id, cid, "Hotel", total=5000.0, payment_status="paid",
              doc_type="quote")
    row = _get_row(_auth(adm["token"], tenant_id), cid)
    assert row is None, (
        f"customer with ONLY unpaid+quote docs must not surface; got {row}"
    )


# ══════════════════════════════════════════════════════════════════
#  Integration — KPI metric path (same contract, different handler).
# ══════════════════════════════════════════════════════════════════

def test_kpi_metric_only_counts_paid_invoices(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "India")
    _seed_doc(tenant_id, cid, "India", total=345.0, payment_status="paid")
    _seed_doc(tenant_id, cid, "India", total=777.0, payment_status="open")
    _seed_doc(tenant_id, cid, "India", total=10_000.0,
              payment_status="paid", doc_type="quote")
    for lens in ("collected", "invoiced"):
        row = _get_kpi_row(_auth(adm["token"], tenant_id), cid, lens=lens)
        assert row is not None, (
            f"KPI lens={lens} did not return a row for the seeded "
            f"paid invoice"
        )
        assert row["revenue"] == pytest.approx(345.0, abs=0.01), (
            f"KPI lens={lens} returned inflated revenue (expected "
            f"345.0 for paid-only): {row}"
        )


def test_kpi_metric_excludes_account_correction_customer(tenant_id):
    adm = _seed_admin(tenant_id)
    cid = _seed_customer(tenant_id, "Juliet", account_correction=True)
    _seed_doc(tenant_id, cid, "Juliet", total=999.0, payment_status="paid")
    for lens in ("collected", "invoiced"):
        row = _get_kpi_row(_auth(adm["token"], tenant_id), cid, lens=lens)
        assert row is None, (
            f"KPI lens={lens}: account_correction customer must be "
            f"excluded; got {row}"
        )
