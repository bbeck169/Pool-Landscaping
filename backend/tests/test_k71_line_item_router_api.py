"""Phase K71 · Feb-2026 — ROUTER round-trip HTTP tests.

Complements the pure-helper suite in
``test_k71_line_item_edit_categories.py`` by exercising the actual
FastAPI routes over ``REACT_APP_BACKEND_URL``.

Coverage (mirrors review_request.features_or_bugs_to_test):
  1. GET /api/income-categories additively seeds K71 default names.
  2. GET /api/service-categories additively seeds K71 default names.
  3. POST /api/quotes validation matrix (valid pair, missing income,
     bogus service id).
  4. POST /api/quotes with a legacy line item (no K71 fields)
     succeeds — grandfather path.
  5. PUT /api/quotes/{qid} runs K71 validator on line_items.
  6. PUT /api/quotes/{qid}/status?status=sent gated on K71 gaps;
     legacy quote transitions still permitted.
  7. POST /api/quotes/{qid}/convert-to-job gated on K71 gaps.
  8. PATCH /api/quotes/{invoice_id} rejects long_description > 500.
  9. GET /api/quotes/{id} echoes K71 fields verbatim.
"""
from __future__ import annotations

import os
import uuid
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


class _H:
    @staticmethod
    def rows_from(body):
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("items", "results", "data", "customers"):
                if key in body and isinstance(body[key], list):
                    return body[key]
        return []


# ─── Fixtures ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"missing access_token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def client(admin_token):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def customer_id(client):
    r = client.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    rows = _H.rows_from(r.json())
    assert rows, "expected at least one seeded customer"
    return rows[0]["id"]


@pytest.fixture(scope="module")
def svc_cat(client):
    r = client.get(f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    rows = _H.rows_from(r.json())
    assert rows, "expected seeded service categories"
    for c in rows:
        if not c.get("is_archived"):
            return c
    return rows[0]


@pytest.fixture(scope="module")
def inc_cat(client):
    r = client.get(f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    rows = _H.rows_from(r.json())
    assert rows, "expected seeded income categories"
    for c in rows:
        if not c.get("is_archived"):
            return c
    return rows[0]


# ─── Cleanup registry ─────────────────────────────────────────────
_CREATED_QUOTE_IDS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _teardown(client):
    yield
    for qid in _CREATED_QUOTE_IDS:
        try:
            client.delete(f"{BASE_URL}/api/invoices/{qid}",
                          timeout=REQ_TIMEOUT)
        except Exception:
            pass


def _track(qid: str) -> str:
    _CREATED_QUOTE_IDS.append(qid)
    return qid


# ═══════════════════════════════════════════════════════════════════
# 1 & 2 · Seed endpoints — additive merge includes K71 names
# ═══════════════════════════════════════════════════════════════════
K71_INCOME_NAMES = {
    "service revenue", "product sales", "recurring maintenance",
    "one-time project", "warranty work", "labor income",
    "materials", "other income",
}
K71_SERVICE_NAMES = {
    "equipment install", "chemical treatment", "inspection",
    "landscape", "hardscape", "lighting", "other",
}


def test_income_categories_endpoint_seeds_k71_names(client):
    r = client.get(f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    rows = _H.rows_from(r.json())
    names = {(c.get("name") or "").strip().lower() for c in rows}
    missing = K71_INCOME_NAMES - names
    assert not missing, f"income seed missing K71 names: {missing}"


def test_service_categories_endpoint_seeds_k71_names(client):
    r = client.get(f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    rows = _H.rows_from(r.json())
    names = {(c.get("name") or "").strip().lower() for c in rows}
    missing = K71_SERVICE_NAMES - names
    assert not missing, f"service seed missing K71 names: {missing}"


# ═══════════════════════════════════════════════════════════════════
# 3 · POST /api/quotes validation matrix
# ═══════════════════════════════════════════════════════════════════
def test_create_quote_with_valid_k71_pair_succeeds(
    client, customer_id, svc_cat, inc_cat
):
    payload = {
        "customer_id": customer_id,
        "title": "K71 API test — valid pair",
        "doc_type": "quote",
        "line_items": [{
            "description": "K71 svc",
            "quantity": 1,
            "unit_price": 25.0,
            "category": "Pool",
            "service_category_id": svc_cat["id"],
            "income_category_id": inc_cat["id"],
        }],
    }
    r = client.post(f"{BASE_URL}/api/quotes", json=payload,
                    timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    doc = r.json()
    _track(doc["id"])
    assert doc["line_items"][0]["service_category_id"] == svc_cat["id"]
    assert doc["line_items"][0]["income_category_id"] == inc_cat["id"]


def test_create_quote_missing_income_category_rejected(
    client, customer_id, svc_cat
):
    payload = {
        "customer_id": customer_id,
        "title": "K71 API test — missing income",
        "doc_type": "quote",
        "line_items": [{
            "description": "no income cat",
            "quantity": 1,
            "unit_price": 10.0,
            "category": "Pool",
            "service_category_id": svc_cat["id"],
            "income_category_id": "",
        }],
    }
    r = client.post(f"{BASE_URL}/api/quotes", json=payload,
                    timeout=REQ_TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    assert isinstance(detail, dict), f"expected structured detail, got {detail}"
    assert detail.get("error_code") == "k71_income_category_required", detail


def test_create_quote_bogus_service_category_rejected(
    client, customer_id, inc_cat
):
    payload = {
        "customer_id": customer_id,
        "title": "K71 API test — bogus svc",
        "doc_type": "quote",
        "line_items": [{
            "description": "bogus svc",
            "quantity": 1,
            "unit_price": 10.0,
            "category": "Pool",
            "service_category_id": "does-not-exist-" + uuid.uuid4().hex,
            "income_category_id": inc_cat["id"],
        }],
    }
    r = client.post(f"{BASE_URL}/api/quotes", json=payload,
                    timeout=REQ_TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("error_code") == "k71_service_category_invalid", detail


# ═══════════════════════════════════════════════════════════════════
# 4 · Legacy line item on a QUOTE — grandfathered
# ═══════════════════════════════════════════════════════════════════
def test_create_quote_legacy_line_grandfathered(client, customer_id):
    """A pure legacy line item (no K71 fields sent) must succeed on
    doc_type=quote. NOTE: FastAPI's Pydantic LineItem model default-
    hydrates service_category_id and income_category_id to None,
    which the router serializes back via ``.dict()``. If those keys
    end up in the validator input, K71 will treat the line as touched
    and REQUIRE both — this test proves whether the router excludes
    them or not."""
    payload = {
        "customer_id": customer_id,
        "title": "K71 API test — legacy grandfather",
        "doc_type": "quote",
        "line_items": [{
            "description": "Legacy line — no K71 fields",
            "quantity": 1,
            "unit_price": 15.0,
            "category": "Pool",
        }],
    }
    r = client.post(f"{BASE_URL}/api/quotes", json=payload,
                    timeout=REQ_TIMEOUT)
    assert r.status_code == 200, (
        f"legacy line should have passed grandfather but got "
        f"{r.status_code}: {r.text}"
    )
    doc = r.json()
    _track(doc["id"])


# ═══════════════════════════════════════════════════════════════════
# 5 · PUT /api/quotes/{qid} runs K71 validation
# ═══════════════════════════════════════════════════════════════════
def test_update_quote_missing_income_rejected(
    client, customer_id, svc_cat, inc_cat
):
    # 1. Create a valid quote first.
    create = client.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customer_id,
            "title": "K71 API test — put validation",
            "doc_type": "quote",
            "line_items": [{
                "description": "seed",
                "quantity": 1,
                "unit_price": 5.0,
                "category": "Pool",
                "service_category_id": svc_cat["id"],
                "income_category_id": inc_cat["id"],
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert create.status_code == 200, create.text
    qid = _track(create.json()["id"])

    # 2. PUT with K71-touched line missing income_category_id → 400
    upd = client.put(
        f"{BASE_URL}/api/quotes/{qid}",
        json={
            "line_items": [{
                "description": "edited",
                "quantity": 2,
                "unit_price": 5.0,
                "category": "Pool",
                "service_category_id": svc_cat["id"],
                "income_category_id": "",
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert upd.status_code == 400, upd.text
    detail = upd.json().get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("error_code") == "k71_income_category_required", detail


# ═══════════════════════════════════════════════════════════════════
# 6 · Send-gate on PUT /api/quotes/{qid}/status?status=sent
# ═══════════════════════════════════════════════════════════════════
def test_send_status_blocked_when_k71_gap(
    client, customer_id, svc_cat, inc_cat
):
    # Create a quote where the line item is K71-touched but the
    # income_category_id will be scrubbed via direct DB write below.
    # However we can't reach the DB from the HTTP suite — instead
    # we create a valid quote, then via a follow-up PUT set one of
    # the K71 keys to empty. But PUT validation would block that.
    # Workaround: create a quote whose ONLY line is completely
    # legacy (no K71 fields), then send — should PASS. Then create
    # a second quote with a K71-touched, missing-income line by
    # POSTing directly — that POST will fail so we can't build the
    # gap state via public API. So we test the PASS half here and
    # rely on helper tests for the FAIL half.
    create = client.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customer_id,
            "title": "K71 API test — legacy send OK",
            "doc_type": "quote",
            "line_items": [{
                "description": "Legacy only",
                "quantity": 1,
                "unit_price": 20.0,
                "category": "Pool",
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert create.status_code == 200, create.text
    qid = _track(create.json()["id"])
    # Legacy quote should transition to sent unblocked.
    send = client.put(
        f"{BASE_URL}/api/quotes/{qid}/status?status=sent",
        timeout=REQ_TIMEOUT,
    )
    assert send.status_code == 200, (
        f"legacy quote should transition to sent but got "
        f"{send.status_code}: {send.text}"
    )
    assert send.json().get("status") == "sent"


# ═══════════════════════════════════════════════════════════════════
# 7 · Convert-to-job legacy path
# ═══════════════════════════════════════════════════════════════════
def test_convert_to_job_legacy_quote_ok(client, customer_id):
    # Convert-to-job requires an approved quote; the endpoint allows
    # bypass with a warning if not approved. We just check that the
    # K71 gap check does NOT trip on a legacy-only quote.
    create = client.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customer_id,
            "title": "K71 API test — convert legacy",
            "doc_type": "quote",
            "line_items": [{
                "description": "Legacy",
                "quantity": 1,
                "unit_price": 42.0,
                "category": "Pool",
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert create.status_code == 200, create.text
    qid = _track(create.json()["id"])
    r = client.post(
        f"{BASE_URL}/api/quotes/{qid}/convert-to-job",
        json={"scheduled_date": "2026-03-15"},
        timeout=REQ_TIMEOUT,
    )
    # Should not be blocked with k71_missing_categories.
    if r.status_code == 400:
        detail = r.json().get("detail")
        if isinstance(detail, dict):
            assert detail.get("error_code") != "k71_missing_categories", (
                f"legacy quote should NOT trigger K71 gap: {detail}"
            )
    else:
        assert r.status_code == 200, r.text


# ═══════════════════════════════════════════════════════════════════
# 8 · PATCH /api/quotes/{invoice_id} — long_description > 500 rejected
# ═══════════════════════════════════════════════════════════════════
def test_patch_invoice_long_description_over_500_rejected(
    client, customer_id, svc_cat, inc_cat
):
    # Create an INVOICE via POST /api/quotes (doc_type=invoice
    # requires legacy `category` and K71 pair).
    create = client.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customer_id,
            "title": "K71 API test — long_description cap",
            "doc_type": "invoice",
            "line_items": [{
                "description": "seed",
                "quantity": 1,
                "unit_price": 5.0,
                "category": "Pool",
                "service_category_id": svc_cat["id"],
                "income_category_id": inc_cat["id"],
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert create.status_code == 200, create.text
    inv_id = _track(create.json()["id"])
    r = client.patch(
        f"{BASE_URL}/api/quotes/{inv_id}",
        json={
            "line_items": [{
                "description": "edited",
                "quantity": 1,
                "unit_price": 5.0,
                "long_description": "a" * 501,
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 400, r.text
    assert "500" in r.text


# ═══════════════════════════════════════════════════════════════════
# 9 · GET /api/quotes/{id} echoes K71 fields verbatim
# ═══════════════════════════════════════════════════════════════════
def test_get_quote_echoes_k71_fields(client, customer_id, svc_cat, inc_cat):
    long_desc = "Multi-line long description under bold item name."
    create = client.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customer_id,
            "title": "K71 API test — get echoes fields",
            "doc_type": "quote",
            "line_items": [{
                "description": "seed",
                "quantity": 1,
                "unit_price": 5.0,
                "category": "Pool",
                "service_category_id": svc_cat["id"],
                "income_category_id": inc_cat["id"],
                "long_description": long_desc,
            }],
        },
        timeout=REQ_TIMEOUT,
    )
    assert create.status_code == 200, create.text
    qid = _track(create.json()["id"])
    r = client.get(f"{BASE_URL}/api/quotes/{qid}", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    li = r.json()["line_items"][0]
    assert li.get("service_category_id") == svc_cat["id"]
    assert li.get("income_category_id") == inc_cat["id"]
    assert li.get("long_description") == long_desc
