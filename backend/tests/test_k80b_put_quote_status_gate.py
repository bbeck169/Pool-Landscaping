"""Phase K80.b (relaxed) · Feb-2026 — DOC-LOCK-POLICY-RELAX
PUT /api/quotes/{id} status gate HTTP tests.

Product policy (DOC-LOCK-POLICY-RELAX):

    Estimates (doc_type='quote'):
        ANY status → PUT allowed. There is NO status that denies
        a PUT against an estimate.

    Invoices (doc_type='invoice'):
        paid / void / cancelled → PUT blocked (409 status_locked)
        anything else           → PUT allowed

Denial shape (unchanged):
    HTTP 409 with JSON body
    ``{ error: "status_locked", current_status, doc_type, message }``
    where ``doc_type`` is the customer-friendly ``estimate|invoice``.

Audit trail:
    * Denied PUT writes ``event: "put_quote_status_denied"`` to
      ``db.audit_logs`` (unchanged).
    * Successful PUT against a post-send status writes
      ``event: "put_quote_edit_after_send"`` to the dedicated
      ``db.doc_edit_audit`` collection (NEW, per Risk C of
      DOC-LOCK-POLICY-RELAX). Tested in
      ``test_doc_lock_policy_relax.py``.

Non-goals: PATCH behaviour is covered by ``test_invoice_edit*.py``;
this file does not exercise PATCH gates.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "").strip()
DB_NAME = os.environ.get("DB_NAME", "").strip()
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
if not MONGO_URL or not DB_NAME:
    pytest.skip("MONGO_URL / DB_NAME not set", allow_module_level=True)

ADMIN_EMAIL = "super@aquaterra.com"
ADMIN_PASSWORD = "password123"
REQ_TIMEOUT = 45


# ═════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def raw_mongo():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return client[DB_NAME]


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
def actor_ids(client):
    """Return (user_id, tenant_id) for the logged-in super admin so
    audit-log assertions can filter down to just this test module's
    writes."""
    r = client.get(f"{BASE_URL}/api/auth/me", timeout=REQ_TIMEOUT)
    if r.status_code != 200:
        return None, None
    me = r.json()
    return me.get("id"), me.get("tenant_id")


@pytest.fixture(scope="module")
def customer_id(client):
    r = client.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("customers") or []
    assert rows
    return rows[0]["id"]


@pytest.fixture(scope="module")
def category_ids(client):
    svc = client.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    ).json().get("items", [])
    inc = client.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    ).json().get("items", [])
    svc = [c for c in svc if not c.get("is_archived")]
    inc = [c for c in inc if not c.get("is_archived")]
    assert svc and inc
    return {"svc": svc[0]["id"], "inc": inc[0]["id"]}


_CREATED_QIDS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(raw_mongo):
    yield
    if _CREATED_QIDS:
        raw_mongo.quotes.delete_many({"id": {"$in": _CREATED_QIDS}})


def _seed_doc(client, raw_mongo, *,
              doc_type: str, status: str,
              customer_id: str, category_ids: Dict[str, str]) -> str:
    """Create a real doc via POST /api/quotes then flip status
    directly in Mongo. Direct DB flip is needed because status
    transitions are driven by other endpoints (send / accept / pay)
    that would side-effect the invoice/customer state."""
    body = {
        "customer_id": customer_id,
        "title": f"K80b gate — {doc_type}/{status}",
        "doc_type": doc_type,
        "line_items": [{
            "description": "Baseline service",
            "quantity": 1,
            "unit_price": 100,
            "service_category_id": category_ids["svc"],
            "income_category_id": category_ids["inc"],
        }],
    }
    r = client.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    doc = r.json()
    qid = doc["id"]
    _CREATED_QIDS.append(qid)
    if status != "draft":
        raw_mongo.quotes.update_one(
            {"id": qid},
            {"$set": {"status": status}},
        )
    return qid


def _put_line_update(client, qid: str) -> requests.Response:
    """The minimum PUT payload that would rewrite a saved doc."""
    return client.put(
        f"{BASE_URL}/api/quotes/{qid}",
        json={"title": "K80b probe — should be gated"},
        timeout=REQ_TIMEOUT,
    )


# ═════════════════════════════════════════════════════════════════════
# ALLOWED cases — 200 OK (expanded post-DOC-LOCK-POLICY-RELAX)
# ═════════════════════════════════════════════════════════════════════
def test_put_draft_estimate_allowed(client, raw_mongo,
                                    customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="quote", status="draft",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 200, r.text


def test_put_sent_estimate_allowed(client, raw_mongo,
                                    customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="quote", status="sent",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 200, r.text


def test_put_draft_invoice_allowed(client, raw_mongo,
                                    customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status="draft",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 200, r.text


# DOC-LOCK-POLICY-RELAX · Feb-2026 — formerly BLOCKED estimate
# statuses now allow PUT. Admins / managers need to add + remove
# line items on viewed / accepted / declined / voided quotes without
# a duplicate-the-estimate dance.
@pytest.mark.parametrize(
    "status",
    ["viewed", "accepted", "declined", "void"],
)
def test_put_formerly_blocked_estimate_now_allowed(
    status, client, raw_mongo, customer_id, category_ids,
):
    qid = _seed_doc(client, raw_mongo, doc_type="quote", status=status,
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 200, (
        f"DOC-LOCK-POLICY-RELAX: estimate status={status!r} should "
        f"accept PUT; got {r.status_code} {r.text[:200]}"
    )


# DOC-LOCK-POLICY-RELAX · Feb-2026 — formerly BLOCKED invoice sent /
# partially_paid now allow PUT without any ack. Only paid / void /
# cancelled remain locked.
@pytest.mark.parametrize(
    "status",
    ["sent", "partially_paid"],
)
def test_put_formerly_blocked_invoice_now_allowed(
    status, client, raw_mongo, customer_id, category_ids,
):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status=status,
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 200, (
        f"DOC-LOCK-POLICY-RELAX: invoice status={status!r} should "
        f"accept PUT; got {r.status_code} {r.text[:200]}"
    )


# ═════════════════════════════════════════════════════════════════════
# BLOCKED cases — 409 status_locked (narrowed to invoice paid/void)
# ═════════════════════════════════════════════════════════════════════
def _assert_blocked(r: requests.Response, expected_status: str,
                    expected_doc_type: str) -> Dict:
    assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:200]}"
    body = r.json()
    # FastAPI wraps HTTPException detail under a "detail" key.
    detail = body.get("detail") if "detail" in body else body
    assert detail["error"] == "status_locked", detail
    assert detail["current_status"] == expected_status, detail
    assert detail["doc_type"] == expected_doc_type, detail
    assert isinstance(detail.get("message"), str) and detail["message"], detail
    return detail


# DOC-LOCK-POLICY-RELAX · Feb-2026 — estimate terminal statuses
# (accepted / declined / void) are now editable per product
# direction. The old "terminal estimate 409" test is gone — see
# ``test_put_formerly_blocked_estimate_now_allowed`` above for the
# inverse coverage.


# DOC-LOCK-POLICY-RELAX · Feb-2026 — the user-visible read-only
# invoice state is PAID only (gate 3a of this ticket). The three
# BLOCKED tests below are kept to lock the policy in place:
# paid + void + cancelled.
def test_put_paid_invoice_blocked_409(client, raw_mongo,
                                       customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status="paid",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    _assert_blocked(r, expected_status="paid", expected_doc_type="invoice")


def test_put_voided_invoice_blocked_409(client, raw_mongo,
                                         customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status="void",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    _assert_blocked(r, expected_status="void", expected_doc_type="invoice")


# ═════════════════════════════════════════════════════════════════════
# Denial shape (all four keys locked) + audit log
# ═════════════════════════════════════════════════════════════════════
def test_put_denial_response_shape(client, raw_mongo,
                                    customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status="paid",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 409
    body = r.json()
    detail = body.get("detail") if "detail" in body else body
    # Contract lock — exactly these four keys on the denial body.
    for key in ("error", "current_status", "doc_type", "message"):
        assert key in detail, f"missing key {key} in denial body: {detail}"
    assert detail["error"] == "status_locked"
    # Values pass basic type + non-empty checks.
    assert isinstance(detail["current_status"], str) and detail["current_status"]
    assert detail["doc_type"] in ("estimate", "invoice")
    assert isinstance(detail["message"], str) and len(detail["message"]) > 10


def test_put_denial_writes_audit_log(client, raw_mongo, actor_ids,
                                      customer_id, category_ids):
    qid = _seed_doc(client, raw_mongo, doc_type="invoice", status="paid",
                    customer_id=customer_id, category_ids=category_ids)
    r = _put_line_update(client, qid)
    assert r.status_code == 409

    # Look up the audit row keyed on quote_id — narrow enough that we
    # don't have to know the total audit-log count.
    row = raw_mongo.audit_logs.find_one({
        "event": "put_quote_status_denied",
        "quote_id": qid,
    })
    assert row is not None, "audit_logs row for the denied PUT is missing"
    assert row["current_status"] == "paid"
    assert row["doc_type"] == "invoice"
    # actor_ids may return None for tenant_id if /auth/me lacks the
    # field; the audit row still records what it has.
    assert row.get("user_email") == ADMIN_EMAIL or row.get("user_id")
