"""Phase K48 verify-hotfix · Feb-2026 — BU-only PATCH payload contract.

Tester reported that changing the Business Unit on a paid invoice
from the Revenue-by-Category drill-down 409'd with
``line_items[0].quantity/unit_price must be numeric``.  Root cause:
the frontend was spreading the row's ``line_items`` array into the
PATCH body, which triggered ``_validate_line_items`` upstream of the
paid-lock confirmation gate.

Fix (this hotfix):
1. Backend — add ``business_unit`` to ``InvoiceEditBody`` + the
   ``_EDITABLE_FIELDS`` audit list so a BU-only PATCH lands via
   ``$set`` without requiring ``line_items``.
2. Frontend — ``commitBusinessUnit`` now sends
   ``{business_unit, confirm_edit_sent?, confirm_edit_paid_invoice_number?}``
   and NEVER spreads ``line_items``.

This test suite exercises the backend contract only.  The frontend
payload shape is locked in by
``frontend/src/test/k48-drilldown-business-unit.test.jsx``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
# ── Auth helpers (mirror the pattern used in test_invoice_edit.py) ─
def _login(email: str) -> str:
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["access_token"]
        except requests.exceptions.RequestException:
            pass
    pytest.skip(f"login unavailable for {email}")


def _admin_ctx() -> dict:
    # invoice_edit._require_staff accepts admin / super_admin only.
    tok = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tok}"},
        "tenant_id": me["tenant_id"],
    }


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def paid_invoice():
    """Seed a paid invoice with a real numeric line-item so a naive
    "resend line_items unchanged" PATCH would still succeed shape-
    wise (the K48 fix must be observably distinct from that)."""
    ctx = _admin_ctx()
    inv_id = f"TEST-k48-{uuid.uuid4().hex[:10]}"
    invoice_number = f"TEST-PAID-K48-{uuid.uuid4().hex[:6]}"
    doc = {
        "id": inv_id,
        "tenant_id": ctx["tenant_id"],
        "customer_id": "TEST-cust-k48",
        "customer_name": "TEST_k48cust",
        "invoice_number": invoice_number,
        "total": 100.0,
        "subtotal": 100.0,
        "tax": 0.0,
        "tax_rate": 0.0,
        "amount_paid": 100.0,
        "status": "paid",
        # Read-path cursor filters on ``payment_status: "paid"``
        # (see ``_paid_invoice_cursor``).
        "payment_status": "paid",
        "currency": "USD",
        "title": "TEST_k48_paid_invoice",
        "doc_type": "invoice",
        "line_items": [
            {"description": "TEST_service", "quantity": 1,
             "unit_price": 100.0, "category": "Landscape"},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _db.quotes.insert_one(doc)
    try:
        yield {**ctx, "inv_id": inv_id, "invoice_number": invoice_number}
    finally:
        _db.quotes.delete_one({"id": inv_id})
        _db.invoice_edit_history.delete_many({"invoice_id": inv_id})


def _patch(inv_id: str, body: dict, headers: dict) -> requests.Response:
    return requests.patch(
        f"{API}/quotes/{inv_id}", json=body,
        headers=headers, timeout=15,
    )


# ═════════════════════════════════════════════════════════════════════
# 1) BU-only patch on paid invoice with correct confirmation → 200
# ═════════════════════════════════════════════════════════════════════
def test_k48_bu_only_patch_on_paid_invoice_returns_200(paid_invoice):
    """The K48 verify-hotfix contract: PATCHing a paid invoice with
    ``{business_unit, confirm_edit_paid_invoice_number}`` MUST NOT
    trigger the ``_validate_line_items`` numeric guard (which was
    the reported 409)."""
    ctx = paid_invoice
    r = _patch(ctx["inv_id"], {
        "business_unit": "Pool",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
        "reason": "TEST_k48_bu_reclass",
    }, ctx["headers"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["changed"] is True
    # No line-items validation error surfaces anywhere in the body.
    body_text = r.text
    assert "quantity/unit_price must be numeric" not in body_text


# ═════════════════════════════════════════════════════════════════════
# 2) BU-only patch persists to the DB doc
# ═════════════════════════════════════════════════════════════════════
def test_k48_bu_only_patch_mutates_business_unit_field(paid_invoice):
    ctx = paid_invoice
    _patch(ctx["inv_id"], {
        "business_unit": "Pool",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    doc = _db.quotes.find_one({"id": ctx["inv_id"]})
    assert doc is not None
    assert doc.get("business_unit") == "Pool", (
        f"expected business_unit='Pool', got {doc.get('business_unit')!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 3) BU-only patch is money-NEUTRAL — totals unchanged
# ═════════════════════════════════════════════════════════════════════
def test_k48_bu_only_patch_does_not_change_totals(paid_invoice):
    """subtotal / tax / total / remaining_balance MUST NOT be
    touched by a BU-only edit — the point of splitting BU out of
    ``line_items`` is to keep the money surface untouched."""
    ctx = paid_invoice
    before = _db.quotes.find_one({"id": ctx["inv_id"]})
    r = _patch(ctx["inv_id"], {
        "business_unit": "Pool",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    assert r.status_code == 200, r.text
    after = _db.quotes.find_one({"id": ctx["inv_id"]})
    for f in ("subtotal", "tax", "total", "amount_paid"):
        assert before.get(f) == after.get(f), (
            f"{f} changed: {before.get(f)} → {after.get(f)}"
        )


# ═════════════════════════════════════════════════════════════════════
# 4) Missing paid-confirmation still 409s (guard not bypassed)
# ═════════════════════════════════════════════════════════════════════
def test_k48_bu_only_patch_paid_missing_confirmation_returns_409(paid_invoice):
    """The BU-only field must NOT bypass the paid-lock guard —
    ``confirm_edit_paid_invoice_number`` is still required."""
    ctx = paid_invoice
    r = _patch(ctx["inv_id"], {
        "business_unit": "Pool",
    }, ctx["headers"])
    assert r.status_code == 409, r.text
    assert (
        r.json()["detail"]["error"] == "paid_edit_requires_invoice_number"
    )


# ═════════════════════════════════════════════════════════════════════
# 5) Regression guard — the reported 409 with numeric-shape message
# must NOT reappear for a BU-only payload
# ═════════════════════════════════════════════════════════════════════
def test_k48_bu_only_patch_never_triggers_numeric_line_item_guard(paid_invoice):
    """Explicit regression test for the exact tester-reported string
    ``line_items[0].quantity/unit_price must be numeric``.  A BU-only
    body carries NO ``line_items`` — the guard must not fire."""
    ctx = paid_invoice
    r = _patch(ctx["inv_id"], {
        "business_unit": "Pool",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    assert "quantity/unit_price must be numeric" not in r.text, (
        f"BU-only patch surfaced the tester-reported numeric guard: {r.text}"
    )


# ═════════════════════════════════════════════════════════════════════
# 6) K48 Round-4 — read path projects invoice.business_unit
# ═════════════════════════════════════════════════════════════════════
def test_k48_rows_endpoint_projects_business_unit_after_patch(paid_invoice):
    """K48 Round-4 read-path parity: after a BU-only PATCH, the
    drill-down rows endpoint (``GET /api/dashboard/income/by-category/rows``)
    must project ``invoice.business_unit`` onto each row so the
    modal Select hydrates the saved bucket on reopen.

    Bucket GROUPING (query-param bucket) is unchanged — still keyed
    on ``line_items.income_category_id`` per the deferred
    aggregation refactor.  This test asserts projection only.
    """
    ctx = paid_invoice
    # 1) Write the BU tag.
    r = _patch(ctx["inv_id"], {
        "business_unit": "Pool",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    assert r.status_code == 200, r.text

    # 2) Query the rows endpoint for the bucket the seed row lives
    # in (``Landscape``).  The endpoint requires ``bucket`` (name)
    # plus ``since`` / ``until`` window.  Use a very wide window
    # to catch the just-seeded row regardless of created_at drift.
    rows_r = requests.get(
        f"{API}/dashboard/income/by-category/rows",
        params={
            "category": "Landscape",
            "from": "1970-01-01",
            "to": "2999-12-31",
            "limit": 200,
        },
        headers=ctx["headers"], timeout=30,
    )
    assert rows_r.status_code == 200, rows_r.text
    payload = rows_r.json()
    rows = payload.get("rows") or payload.get("items") or []
    matches = [r for r in rows if r.get("invoice_id") == ctx["inv_id"]]
    assert matches, (
        f"seeded invoice {ctx['inv_id']!r} not surfaced in "
        f"Landscape bucket rows (got {len(rows)} rows total)"
    )
    for r in matches:
        assert r.get("business_unit") == "Pool", (
            f"row projection missing business_unit — "
            f"got {r.get('business_unit')!r} on row keys {list(r.keys())}"
        )
