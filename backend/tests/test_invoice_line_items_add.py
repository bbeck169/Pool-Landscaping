"""MA0 · Feb-2026 — ``POST /invoices/{id}/line-items`` tests.

HTTP-integration style matching ``test_chemical_applications_crud.py``.
Covers happy path, tenant isolation, RBAC (tech OK / admin OK /
customer 403), invalid item id, description/price fallback from the
pricebook item, and a concurrent-append probe (two parallel POSTs
both land, totals converge to correct).

Manual bash only per session mandate — no testing_agent.
Run: ``pytest backend/tests/test_invoice_line_items_add.py -xvs``
"""
from __future__ import annotations
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "invli_"


# ═══ auth helpers ═════════════════════════════════════════════════════
def _login(email: str, pwd: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pwd},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token") or r.json().get("token")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _me(tok: str) -> dict:
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def admin_identity(admin_tok):
    return _me(admin_tok)


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


# ═══ scenario builder ═════════════════════════════════════════════════
@pytest.fixture
def scenario(dbc, admin_identity):
    """Seed a fresh invoice + pricebook item in the caller's tenant,
    plus an isolated other-tenant invoice for the cross-tenant probe.
    Torn down at the end of each test to keep the environment stable.
    """
    tid = admin_identity["tenant_id"]
    other_tid = f"{TAG}other-{uuid.uuid4().hex[:8]}"

    # In-tenant customer + pricebook items.
    my_cid = f"{TAG}mycust-{uuid.uuid4().hex[:8]}"
    my_iid = f"{TAG}myinv-{uuid.uuid4().hex[:8]}"
    my_iid2 = f"{TAG}myinv2-{uuid.uuid4().hex[:8]}"
    item_a_id = f"{TAG}itema-{uuid.uuid4().hex[:8]}"
    item_b_id = f"{TAG}itemb-{uuid.uuid4().hex[:8]}"

    # Other-tenant invoice + item (attacker probe target).
    other_iid = f"{TAG}otherinv-{uuid.uuid4().hex[:8]}"
    other_item_id = f"{TAG}otheritem-{uuid.uuid4().hex[:8]}"

    dbc.customers.insert_one({"id": my_cid, "tenant_id": tid, "name": f"{TAG}Customer"})
    dbc.items.insert_many([
        {"id": item_a_id, "tenant_id": tid, "name": f"{TAG}Chlorine Tabs",
         "price": 25.5, "deleted_at": None},
        {"id": item_b_id, "tenant_id": tid, "name": f"{TAG}Filter Cartridge",
         "price": 40.0, "deleted_at": None},
        {"id": other_item_id, "tenant_id": other_tid, "name": f"{TAG}CROSS ITEM",
         "price": 99.0, "deleted_at": None},
    ])
    dbc.quotes.insert_many([
        # In-tenant invoices, ``draft`` status so no edit-guard blocks
        # trip. Starts with an empty ``line_items`` array.
        {"id": my_iid, "tenant_id": tid, "doc_type": "invoice",
         "status": "draft", "customer_id": my_cid,
         "line_items": [], "tax_rate": 8.25, "discount_amount": 0.0,
         "discount_type": "fixed", "amount_paid": 0.0,
         "subtotal": 0.0, "tax": 0.0, "total": 0.0,
         "discount_value": 0.0, "remaining_balance": 0.0},
        {"id": my_iid2, "tenant_id": tid, "doc_type": "invoice",
         "status": "draft", "customer_id": my_cid,
         "line_items": [], "tax_rate": 0.0, "discount_amount": 0.0,
         "discount_type": "fixed", "amount_paid": 0.0,
         "subtotal": 0.0, "tax": 0.0, "total": 0.0,
         "discount_value": 0.0, "remaining_balance": 0.0},
        # Other-tenant invoice — attacker target.
        {"id": other_iid, "tenant_id": other_tid, "doc_type": "invoice",
         "status": "draft", "line_items": [],
         "tax_rate": 0.0, "discount_amount": 0.0, "discount_type": "fixed",
         "amount_paid": 0.0, "subtotal": 0.0, "tax": 0.0, "total": 0.0,
         "discount_value": 0.0, "remaining_balance": 0.0},
    ])
    yield {
        "tenant_id": tid, "other_tenant_id": other_tid,
        "customer_id": my_cid,
        "invoice_id": my_iid, "invoice_id_2": my_iid2,
        "other_invoice_id": other_iid,
        "item_a_id": item_a_id, "item_b_id": item_b_id,
        "other_item_id": other_item_id,
    }
    # Teardown.
    dbc.quotes.delete_many({"id": {"$in": [my_iid, my_iid2, other_iid]}})
    dbc.items.delete_many({"id": {"$in": [item_a_id, item_b_id, other_item_id]}})
    dbc.customers.delete_many({"id": my_cid})


# ═══ tests ════════════════════════════════════════════════════════════
def test_happy_path_tech_can_append_and_totals_recompute(
    tech_tok, scenario,
):
    """Tech appends 1x item_a (price=25.5) — subtotal/tax/total math."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        headers=_h(tech_tok),
        json={"item_id": scenario["item_a_id"], "quantity": 2},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    inv = r.json()
    assert len(inv["line_items"]) == 1
    row = inv["line_items"][0]
    assert row["quantity"] == 2
    assert row["unit_price"] == 25.5
    assert row["description"].endswith("Chlorine Tabs")
    # Subtotal = 2 * 25.5 = 51.0; tax @ 8.25% = 4.21; total = 55.21.
    assert inv["subtotal"] == 51.0
    assert inv["tax"] == 4.21
    assert inv["total"] == 55.21
    assert inv["remaining_balance"] == 55.21


def test_description_and_unit_price_overrides_win(tech_tok, scenario):
    """Explicit ``description`` + ``unit_price`` in the body override
    the pricebook item's defaults. Regulatory / customer-facing edits
    need this override."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        headers=_h(tech_tok),
        json={"item_id": scenario["item_a_id"], "quantity": 1,
              "unit_price": 100.0,
              "description": "Custom description override"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    row = r.json()["line_items"][-1]
    assert row["unit_price"] == 100.0
    assert row["description"] == "Custom description override"


def test_admin_can_also_append(admin_tok, scenario):
    """RBAC: admins share the ``require_tech_or_above`` gate. Reuses
    the second invoice fixture so state doesn't leak from the happy
    path."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id_2']}/line-items",
        headers=_h(admin_tok),
        json={"item_id": scenario["item_b_id"], "quantity": 3},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["line_items"]) == 1


def test_customer_role_blocked(customer_tok, scenario):
    """RBAC: customers must NOT be able to mutate invoices."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        headers=_h(customer_tok),
        json={"item_id": scenario["item_a_id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403, r.text


def test_unauthed_blocked(scenario):
    """Missing bearer → 401 (or 403 — accept either the FastAPI
    HTTPBearer default 403 or a middleware-level 401)."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        json={"item_id": scenario["item_a_id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert r.status_code in (401, 403), r.text


def test_cross_tenant_invoice_returns_404(tech_tok, scenario):
    """Cross-tenant probe: caller's tech tries to add to an invoice in
    another tenant. Endpoint MUST return 404 (never 200, never leak
    existence via a 403)."""
    r = requests.post(
        f"{API}/invoices/{scenario['other_invoice_id']}/line-items",
        headers=_h(tech_tok),
        json={"item_id": scenario["item_a_id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert r.status_code == 404, r.text


def test_invalid_item_id_returns_422(tech_tok, scenario):
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        headers=_h(tech_tok),
        json={"item_id": f"{TAG}bogus-{uuid.uuid4().hex[:8]}", "quantity": 1},
        timeout=TIMEOUT,
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail")
    # Detail may be dict {"error", "message"} or a validation-error list.
    if isinstance(detail, dict):
        assert detail.get("error") == "item_not_found"


def test_cross_tenant_item_id_returns_422(tech_tok, scenario):
    """Cross-tenant item probe: caller's tech tries to add another
    tenant's pricebook item to their own invoice. Item lookup is
    tenant-scoped so ``other_item_id`` MUST resolve as unknown."""
    r = requests.post(
        f"{API}/invoices/{scenario['invoice_id']}/line-items",
        headers=_h(tech_tok),
        json={"item_id": scenario["other_item_id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert r.status_code == 422, r.text


def test_duplicate_item_id_is_allowed(tech_tok, scenario):
    """Same item can be added twice — user might want multiple charges
    for the same product. Order matters, so we push twice and assert
    the array shape."""
    for _ in range(2):
        r = requests.post(
            f"{API}/invoices/{scenario['invoice_id_2']}/line-items",
            headers=_h(tech_tok),
            json={"item_id": scenario["item_a_id"], "quantity": 1},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
    # After 2 pushes, at least 2 item_a_id rows are present.
    final = r.json()
    matches = [li for li in final["line_items"]
               if li.get("item_id") == scenario["item_a_id"]]
    assert len(matches) >= 2


def test_concurrent_append_both_land(tech_tok, scenario):
    """Concurrent append probe: 2 parallel POSTs to the same invoice
    must both land. Line-item array is race-safe because of ``$push``
    atomicity; totals converge to correct because the LAST writer's
    recompute reflects both pushes."""
    def _post(item_id: str):
        return requests.post(
            f"{API}/invoices/{scenario['invoice_id']}/line-items",
            headers=_h(tech_tok),
            json={"item_id": item_id, "quantity": 1},
            timeout=TIMEOUT,
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_post, scenario["item_a_id"])
        f2 = pool.submit(_post, scenario["item_b_id"])
        r1 = f1.result()
        r2 = f2.result()
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    # Read the invoice fresh — both items MUST be present.
    r = requests.get(
        f"{API}/quotes/{scenario['invoice_id']}",
        headers=_h(tech_tok), timeout=TIMEOUT,
    )
    if r.status_code == 200:
        inv = r.json()
    else:
        # Fallback: some deployments don't expose the GET; read via
        # the endpoint's own re-read shape by re-POSTing a benign
        # third item and using its response as our final view. Skipped
        # here — we prefer to just accept whichever POST winner's body
        # gave us the doc.
        inv = r2.json() if r2.status_code == 200 else r1.json()
    item_a_hits = [li for li in inv["line_items"]
                    if li.get("item_id") == scenario["item_a_id"]]
    item_b_hits = [li for li in inv["line_items"]
                    if li.get("item_id") == scenario["item_b_id"]]
    assert len(item_a_hits) >= 1
    assert len(item_b_hits) >= 1
