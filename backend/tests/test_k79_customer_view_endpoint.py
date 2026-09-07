"""Phase K79 · Feb-2026 — Customer-view endpoint HTTP round-trip.

Exercises:
  * GET /api/quotes/{qid}/customer-view returns the grouped payload.
  * long_description NEVER appears in the response body.
  * customer_group_display=false still returns the payload with
    the flag set to False — surface decides how to render.
  * ``customer_group_descriptions`` from the doc surfaces per-group.
  * New POST /api/quotes defaults customer_group_display=true.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

ADMIN_EMAIL = "admin@aquaterra.com"
ADMIN_PASSWORD = "password123"
REQ_TIMEOUT = 45

_LONG_DESC_SECRET = "INTERNAL notes only — must not leak on customer view"


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "customers"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


@pytest.fixture(scope="module")
def client():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def customer_id(client):
    r = client.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    assert rows
    return rows[0]["id"]


@pytest.fixture(scope="module")
def svc_cats(client):
    r = client.get(f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert len(rows) >= 2
    return rows[:2]


@pytest.fixture(scope="module")
def inc_cat(client):
    r = client.get(f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


_CREATED_QIDS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _teardown(client):
    yield
    for qid in _CREATED_QIDS:
        try:
            client.delete(f"{BASE_URL}/api/invoices/{qid}",
                          timeout=REQ_TIMEOUT)
        except Exception:
            pass


def _make_quote(client, customer_id, svc_cats, inc_cat, *,
                customer_group_display=None,
                customer_group_descriptions=None):
    a, b = svc_cats
    body = {
        "customer_id": customer_id,
        "title": "K79 endpoint test",
        "doc_type": "quote",
        "line_items": [
            {
                "description": "Pool cleaning weekly",
                "quantity": 4, "unit_price": 40,
                "service_category_id": a["id"],
                "income_category_id": inc_cat["id"],
                "long_description": _LONG_DESC_SECRET,
            },
            {
                "description": "Chlorine treatment",
                "quantity": 1, "unit_price": 60,
                "service_category_id": a["id"],
                "income_category_id": inc_cat["id"],
            },
            {
                "description": "Grout resealing",
                "quantity": 1, "unit_price": 200,
                "service_category_id": b["id"],
                "income_category_id": inc_cat["id"],
            },
        ],
    }
    if customer_group_display is not None:
        body["customer_group_display"] = customer_group_display
    if customer_group_descriptions is not None:
        body["customer_group_descriptions"] = customer_group_descriptions
    r = client.post(f"{BASE_URL}/api/quotes", json=body,
                    timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    doc = r.json()
    _CREATED_QIDS.append(doc["id"])
    return doc


# ═════════════════════════════════════════════════════════════════════
# Contract tests
# ═════════════════════════════════════════════════════════════════════
def test_new_quote_defaults_customer_group_display_true(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat)
    assert doc.get("customer_group_display") is True


def test_customer_view_endpoint_returns_grouped_payload(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat)
    qid = doc["id"]
    r = client.get(
        f"{BASE_URL}/api/quotes/{qid}/customer-view", timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    payload = r.json()

    assert payload["quote_id"] == qid
    assert payload["customer_group_display"] is True
    assert isinstance(payload["groups"], list)
    # Two service categories → 2 groups (each with 1-2 lines).
    assert len(payload["groups"]) == 2

    # Grouped subtotals sum to the doc-level subtotal.
    assert round(payload["grouped_subtotal"], 2) == round(
        payload["subtotal"], 2
    )


def test_customer_view_never_leaks_long_description(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat)
    qid = doc["id"]
    r = client.get(
        f"{BASE_URL}/api/quotes/{qid}/customer-view", timeout=REQ_TIMEOUT,
    )
    raw = r.text
    assert _LONG_DESC_SECRET not in raw, (
        "K71 long_description must NEVER surface in customer-view payload"
    )
    payload = r.json()
    for g in payload["groups"]:
        assert _LONG_DESC_SECRET not in json.dumps(g)


def test_customer_view_flag_persists_and_surfaces(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat,
                        customer_group_display=False)
    qid = doc["id"]
    r = client.get(
        f"{BASE_URL}/api/quotes/{qid}/customer-view", timeout=REQ_TIMEOUT,
    )
    payload = r.json()
    # Endpoint still returns the payload — surface decides render mode.
    assert payload["customer_group_display"] is False
    # Groups are still computed (client may want to preview both modes).
    assert isinstance(payload["groups"], list)


def test_customer_group_descriptions_persist_and_surface(
    client, customer_id, svc_cats, inc_cat,
):
    a, b = svc_cats
    descriptions = {
        a["id"]: "Weekly service package with chemistry balance.",
        b["id"]: "Wet-sealed after cure.",
    }
    doc = _make_quote(
        client, customer_id, svc_cats, inc_cat,
        customer_group_descriptions=descriptions,
    )
    r = client.get(
        f"{BASE_URL}/api/quotes/{doc['id']}/customer-view",
        timeout=REQ_TIMEOUT,
    )
    payload = r.json()
    by_id = {g["category_id"]: g for g in payload["groups"]}
    assert by_id[a["id"]]["description"] == descriptions[a["id"]]
    assert by_id[b["id"]]["description"] == descriptions[b["id"]]


def test_customer_view_endpoint_404_on_bad_id(client):
    r = client.get(
        f"{BASE_URL}/api/quotes/does-not-exist/customer-view",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404


def test_customer_view_endpoint_requires_auth(client):
    # Strip Authorization header and hit the endpoint.
    r = requests.get(
        f"{BASE_URL}/api/quotes/whatever/customer-view",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (401, 403), (r.status_code, r.text[:200])


def test_estimates_full_payload_embeds_customer_view_block(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat)
    r = client.get(
        f"{BASE_URL}/api/estimates/{doc['id']}/full", timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    cv = payload.get("customer_view")
    assert cv, "K79 customer_view block must be embedded in /full payload"
    assert isinstance(cv["groups"], list)
    assert cv["customer_group_display"] is True
    # long_description scrubbed in embedded block too.
    assert _LONG_DESC_SECRET not in json.dumps(cv)


def test_put_quote_accepts_customer_group_fields(
    client, customer_id, svc_cats, inc_cat,
):
    doc = _make_quote(client, customer_id, svc_cats, inc_cat)
    qid = doc["id"]
    a, _ = svc_cats
    r = client.put(
        f"{BASE_URL}/api/quotes/{qid}",
        json={
            "customer_group_display": False,
            "customer_group_descriptions": {
                a["id"]: "Bundled pool care package.",
            },
        },
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    fetched = r.json()
    assert fetched["customer_group_display"] is False
    assert fetched["customer_group_descriptions"][a["id"]] == \
        "Bundled pool care package."
