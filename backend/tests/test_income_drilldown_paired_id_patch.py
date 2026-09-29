"""INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID PATCH round-trip.

Locks in the paired-ID commit contract that the ``DashboardDrillDownModal``
sends when the user changes a Category or Service Unit from the
dashboard drill-down:

* Business Unit (income-by-category variant): PATCH body carries BOTH
  ``business_unit`` (denormalized name) AND ``business_unit_id``
  (canonical income_categories FK).  Money-neutral ``$set`` write.
* Line-level Category + Service Unit (income-by-service variant): PATCH
  body's ``line_items`` array carries BOTH the canonical FK
  (``income_category_id`` / ``service_category_id``) and the
  denormalized display name (``category`` / ``service_category``).
* Read path — ``GET /api/dashboard/income/by-category/rows`` projects
  the three paired-ID hydration fields onto every row so the modal
  Selects render the saved value on reopen without a second round-trip.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()


# ── Auth helper (mirrors test_k48_business_unit_patch.py) ─────────
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
    tok = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tok}"},
        "tenant_id": me["tenant_id"],
    }


def _tenant_income_categories(ctx: dict) -> list[dict]:
    r = requests.get(
        f"{API}/income-categories",
        headers=ctx["headers"], timeout=15,
    )
    return r.json().get("items") or []


def _tenant_service_categories(ctx: dict) -> list[dict]:
    r = requests.get(
        f"{API}/service-categories",
        headers=ctx["headers"], timeout=15,
    )
    return r.json().get("items") or []


@pytest.fixture
def paid_invoice_with_line_item():
    """Seed a paid invoice with one line item whose category /
    service_category_id will be flipped by the paired-ID PATCH."""
    ctx = _admin_ctx()
    inv_id = f"TEST-inc-dd-{uuid.uuid4().hex[:10]}"
    invoice_number = f"TEST-INC-DD-{uuid.uuid4().hex[:6]}"
    ic = _tenant_income_categories(ctx)
    sc = _tenant_service_categories(ctx)
    if len(ic) < 2 or len(sc) < 2:
        pytest.skip("tenant seed lacks 2+ income + 2+ service categories")
    # Seed the invoice pointing at the FIRST option in each list; the
    # PATCH will flip to the SECOND to prove a mutation happened.
    seed_ic = ic[0]
    seed_sc = sc[0]
    line_id = f"li-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": inv_id,
        "tenant_id": ctx["tenant_id"],
        "customer_id": "TEST-cust-inc-dd",
        "customer_name": "TEST_inc_dd_cust",
        "invoice_number": invoice_number,
        "total": 100.0,
        "subtotal": 100.0,
        "tax": 0.0,
        "tax_rate": 0.0,
        "amount_paid": 100.0,
        "status": "paid",
        "payment_status": "paid",
        "currency": "USD",
        "title": "TEST_inc_dd_paid_invoice",
        "doc_type": "invoice",
        "line_items": [
            {
                "id": line_id,
                "description": "TEST_service",
                "quantity": 1,
                "unit_price": 100.0,
                "category": seed_ic["name"],
                "income_category_id": seed_ic["id"],
                "service_category_id": seed_sc["id"],
            },
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _db.quotes.insert_one(doc)
    try:
        yield {
            **ctx, "inv_id": inv_id, "invoice_number": invoice_number,
            "line_id": line_id,
            "seed_ic": seed_ic, "seed_sc": seed_sc,
            "next_ic": ic[1], "next_sc": sc[1],
        }
    finally:
        _db.quotes.delete_one({"id": inv_id})
        _db.invoice_edit_history.delete_many({"invoice_id": inv_id})


def _patch(inv_id: str, body: dict, headers: dict) -> requests.Response:
    return requests.patch(
        f"{API}/quotes/{inv_id}", json=body,
        headers=headers, timeout=15,
    )


# ═════════════════════════════════════════════════════════════════════
# 1) Paired BU PATCH — both name + id persist
# ═════════════════════════════════════════════════════════════════════
def test_paired_business_unit_patch_persists_both_fields(paid_invoice_with_line_item):
    ctx = paid_invoice_with_line_item
    r = _patch(ctx["inv_id"], {
        "business_unit": ctx["next_ic"]["name"],
        "business_unit_id": ctx["next_ic"]["id"],
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
        "reason": "TEST_paired_bu",
    }, ctx["headers"])
    assert r.status_code == 200, r.text
    doc = _db.quotes.find_one({"id": ctx["inv_id"]})
    assert doc is not None
    assert doc.get("business_unit") == ctx["next_ic"]["name"], (
        f"business_unit not persisted: got {doc.get('business_unit')!r}"
    )
    assert doc.get("business_unit_id") == ctx["next_ic"]["id"], (
        f"business_unit_id not persisted: got {doc.get('business_unit_id')!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 2) Invalid business_unit_id — still money-neutral, still persists
#     (backend does not FK-validate the id; the name still lands).
#     This locks in the "invalid ID doesn't 400" behaviour — invalid
#     writes just carry through to the DB and get caught at read time
#     when the modal fetches the income_categories list.
# ═════════════════════════════════════════════════════════════════════
def test_paired_business_unit_patch_accepts_id_even_when_unknown(paid_invoice_with_line_item):
    ctx = paid_invoice_with_line_item
    r = _patch(ctx["inv_id"], {
        "business_unit": "Unknown Bucket",
        "business_unit_id": "not-a-real-id",
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    # Money-neutral $set write — no FK enforcement on the invoice
    # doc; we accept it and let the modal's read-path resolver deal
    # with it.  This matches the pre-INCOME-DRILLDOWN-EDIT contract
    # for the ``business_unit`` name-only field.
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════
# 3) Line-level paired PATCH — service_category_id + service_category
#     round-trip through the ``line_items`` PATCH path.
# ═════════════════════════════════════════════════════════════════════
def test_line_level_paired_service_unit_round_trip(paid_invoice_with_line_item):
    ctx = paid_invoice_with_line_item
    # Fetch → mutate the target line item → PATCH the whole array
    # (mirrors what commitServiceUnit does on the frontend).
    before = _db.quotes.find_one({"id": ctx["inv_id"]})
    items = [dict(li) for li in before.get("line_items") or []]
    assert items, "seed line_items missing"
    items[0] = {
        **items[0],
        "service_category_id": ctx["next_sc"]["id"],
        "service_category": ctx["next_sc"]["name"],
    }
    r = _patch(ctx["inv_id"], {
        "line_items": items,
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    assert r.status_code == 200, r.text
    after = _db.quotes.find_one({"id": ctx["inv_id"]})
    after_line = (after.get("line_items") or [None])[0]
    assert after_line is not None
    assert after_line.get("service_category_id") == ctx["next_sc"]["id"], (
        f"service_category_id not persisted: got {after_line.get('service_category_id')!r}"
    )
    # ``service_category`` denormalized name is preserved as an extra
    # key by ``_validate_line_items`` (which passes unknown keys
    # through untouched).
    assert after_line.get("service_category") == ctx["next_sc"]["name"], (
        f"service_category (denorm name) not persisted: got {after_line.get('service_category')!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 4) Line-level paired PATCH — income_category_id + category
# ═════════════════════════════════════════════════════════════════════
def test_line_level_paired_income_category_round_trip(paid_invoice_with_line_item):
    ctx = paid_invoice_with_line_item
    before = _db.quotes.find_one({"id": ctx["inv_id"]})
    items = [dict(li) for li in before.get("line_items") or []]
    items[0] = {
        **items[0],
        "income_category_id": ctx["next_ic"]["id"],
        "category": ctx["next_ic"]["name"],
    }
    r = _patch(ctx["inv_id"], {
        "line_items": items,
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])
    assert r.status_code == 200, r.text
    after = _db.quotes.find_one({"id": ctx["inv_id"]})
    after_line = (after.get("line_items") or [None])[0]
    assert after_line is not None
    assert after_line.get("income_category_id") == ctx["next_ic"]["id"]
    assert after_line.get("category") == ctx["next_ic"]["name"]


# ═════════════════════════════════════════════════════════════════════
# 5) Read path — drill-down rows project the three paired-ID fields
#     so the modal Selects hydrate directly without a second call.
# ═════════════════════════════════════════════════════════════════════
def test_drilldown_rows_project_paired_id_hydration_fields(paid_invoice_with_line_item):
    ctx = paid_invoice_with_line_item
    # Write the BU tag so the invoice-level ``business_unit_id``
    # projects onto the row (line-level FKs are seeded in the fixture).
    _patch(ctx["inv_id"], {
        "business_unit": ctx["next_ic"]["name"],
        "business_unit_id": ctx["next_ic"]["id"],
        "confirm_edit_paid_invoice_number": ctx["invoice_number"],
    }, ctx["headers"])

    rows_r = requests.get(
        f"{API}/dashboard/income/by-category/rows",
        params={
            "category": ctx["seed_ic"]["name"],
            "from": "1970-01-01",
            "to": "2999-12-31",
            "limit": 200,
        },
        headers=ctx["headers"], timeout=30,
    )
    assert rows_r.status_code == 200, rows_r.text
    payload = rows_r.json()
    rows = payload.get("rows") or []
    matches = [r for r in rows if r.get("invoice_id") == ctx["inv_id"]]
    assert matches, (
        f"seeded invoice {ctx['inv_id']!r} not surfaced in "
        f"{ctx['seed_ic']['name']!r} bucket rows"
    )
    for r in matches:
        # All three paired-ID hydration fields must be projected.
        assert "business_unit_id" in r, (
            f"row missing business_unit_id projection: keys={list(r.keys())}"
        )
        assert "income_category_id" in r, (
            f"row missing income_category_id projection: keys={list(r.keys())}"
        )
        assert "service_category_id" in r, (
            f"row missing service_category_id projection: keys={list(r.keys())}"
        )
        assert r.get("business_unit_id") == ctx["next_ic"]["id"]
        assert r.get("income_category_id") == ctx["seed_ic"]["id"]
        assert r.get("service_category_id") == ctx["seed_sc"]["id"]
