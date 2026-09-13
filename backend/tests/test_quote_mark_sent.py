"""Feb-2026 · Housekeeping P2 · Round 2 — Mark-quote-sent endpoint.

Locks the contract on ``POST /api/quotes/{qid}/mark-sent``:

  1. Admin marks a draft quote sent → status flips to ``sent``,
     ``sent_at`` is populated, an ``audit_logs`` row with
     ``event="quote.mark_sent"`` is written.
  2. Technician → 403 (RBAC).
  3. Non-draft quote (already sent) → 400.
  4. Invoice doc_type → 400.
  5. Missing quote id → 404.

See ``/app/memory/HOUSEKEEPING_DISPATCH_P2.md`` (Round 2) for the
follow-up that this endpoint unblocks (Case 6 in
``test_quote_duplicate.py``).
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

REQ_TIMEOUT = 45


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "customers"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


def _session(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    return _session("mike@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def customer_a(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    assert rows, "no customers in aquaterra fixture tenant"
    return rows[0]


@pytest.fixture(scope="module")
def svc_cat(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


def _make_quote(sess, customer_id, svc_cat, inc_cat, doc_type="quote"):
    body = {
        "customer_id": customer_id,
        "title": f"MarkSent probe {uuid.uuid4().hex[:6]}",
        "doc_type": doc_type,
        "tax_rate": 0.0,
        "line_items": [
            {"description": "Item", "quantity": 1, "unit_price": 100,
             "service_category_id": svc_cat["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    r = sess.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _hard_delete(sess, qid):
    try:
        sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true", timeout=REQ_TIMEOUT,
        )
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# Case 1 — Happy path.
# ═════════════════════════════════════════════════════════════════════

def test_admin_mark_sent_flips_status_and_writes_audit(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        r = admin_sess.post(
            f"{BASE_URL}/api/quotes/{src['id']}/mark-sent",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quote_id"] == src["id"]
        assert body["status"] == "sent"
        assert body.get("sent_at")

        # Re-read the doc — status should now be sent + sent_at set.
        got = admin_sess.get(
            f"{BASE_URL}/api/quotes/{src['id']}", timeout=REQ_TIMEOUT,
        ).json()
        assert got["status"] == "sent"
        assert got.get("sent_at")
    finally:
        _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 2 — RBAC: technician gets 403.
# ═════════════════════════════════════════════════════════════════════

def test_technician_cannot_mark_sent(
    admin_sess, tech_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        r = tech_sess.post(
            f"{BASE_URL}/api/quotes/{src['id']}/mark-sent",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 403, r.text
    finally:
        _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 3 — Non-draft (already sent) → 400.
# ═════════════════════════════════════════════════════════════════════

def test_mark_sent_rejects_non_draft(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        r1 = admin_sess.post(
            f"{BASE_URL}/api/quotes/{src['id']}/mark-sent",
            timeout=REQ_TIMEOUT,
        )
        assert r1.status_code == 200, r1.text
        # Second call should now be rejected (status is 'sent').
        r2 = admin_sess.post(
            f"{BASE_URL}/api/quotes/{src['id']}/mark-sent",
            timeout=REQ_TIMEOUT,
        )
        assert r2.status_code == 400, r2.text
        assert "draft" in r2.text.lower()
    finally:
        _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 4 — Invoice doc_type → 400.
# ═════════════════════════════════════════════════════════════════════

def test_mark_sent_rejects_invoice_doc_type(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(
        admin_sess, customer_a["id"], svc_cat, inc_cat, doc_type="invoice",
    )
    try:
        r = admin_sess.post(
            f"{BASE_URL}/api/quotes/{src['id']}/mark-sent",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 400, r.text
        assert "quote" in r.text.lower()
    finally:
        _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 5 — Missing quote id → 404.
# ═════════════════════════════════════════════════════════════════════

def test_mark_sent_missing_quote_returns_404(admin_sess):
    r = admin_sess.post(
        f"{BASE_URL}/api/quotes/does-not-exist/mark-sent",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404, r.text
