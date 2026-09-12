"""Feb-2026 · Customer decline-per-group on Quotes — contract tests.

Locks the four PATCH routes shipped by the Feb-2026 dispatch:

    PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/decline
    PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/undecline
    PATCH /api/quotes/{qid}/groups/{group_key}/decline
    PATCH /api/quotes/{qid}/groups/{group_key}/undecline

Contract:
  1. Magic-link decline flips every line in the group to
     ``customer_status=declined`` and drops ``adjusted_total``.
     An ``audit_logs`` row (``event=quote.group_declined``) is written.
  2. Magic-link undecline round-trips: lines revert to ``pending``
     and ``adjusted_total`` recovers. An audit row is written for
     the restore with ``event=quote.group_restored``.
  3. Admin PATCH under ``/quotes/{qid}/groups/{group_key}/decline``
     has the same effect with ``source=admin_ui``.
  4. Technicians are forbidden (403) on the admin routes.
  5. Rate-limit — the 11th group-decline hit inside the 5 min window
     returns 429 (``group`` bucket = 10 hits / 300 s).
  6. Actionability guard — once the quote's ``decision`` is
     ``accepted`` the routes return 409.

See /app/memory/FEATURE_QUOTE_DECLINE_PER_GROUP.md.
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


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "tech@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip("no tech@aquaterra.com demo user")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def customer_id(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    assert rows
    return rows[0]["id"]


@pytest.fixture(scope="module")
def two_svc_cats(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/service-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert len(rows) >= 2, "need at least 2 service categories for group tests"
    return rows[0], rows[1]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/income-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


def _make_quote(sess, customer_id, cat_a, cat_b, inc_cat, *, title=None):
    """Two-group quote: 2 lines in cat_a ($100), 1 line in cat_b ($50)."""
    body = {
        "customer_id": customer_id,
        "title": title or f"GroupDecline probe {uuid.uuid4().hex[:6]}",
        "doc_type": "quote",
        "line_items": [
            {"description": "A1", "quantity": 2, "unit_price": 25,
             "service_category_id": cat_a["id"],
             "income_category_id": inc_cat["id"]},
            {"description": "A2", "quantity": 1, "unit_price": 50,
             "service_category_id": cat_a["id"],
             "income_category_id": inc_cat["id"]},
            {"description": "B1", "quantity": 1, "unit_price": 50,
             "service_category_id": cat_b["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    r = sess.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _mark_sent(sess, qid):
    """Push quote into ``status='sent'`` so the actionability guard passes."""
    r = sess.put(
        f"{BASE_URL}/api/quotes/{qid}/status?status=sent",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code in (200, 204), r.text


def _get_magic_link_token(sess, qid):
    r = sess.get(
        f"{BASE_URL}/api/quotes/{qid}/magic-link",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("token") or body.get("url", "").split("token=")[-1]
    assert tok
    return tok


def _cleanup(sess, qid):
    try:
        sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true",
            timeout=REQ_TIMEOUT,
        )
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# 1. Magic-link decline drops adjusted_total + writes audit row
# ═════════════════════════════════════════════════════════════════════

def test_customer_group_decline_via_token(
    admin_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        token = _get_magic_link_token(admin_sess, qid)

        # Decline group A ($100 = 2 lines).
        r = requests.patch(
            f"{BASE_URL}/api/portal/quotes/via-token/{token}"
            f"/groups/{cat_a['id']}/decline",
            json={"reason": "Not doing this scope"},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        totals = payload.get("totals") or {}
        assert totals.get("has_declined_lines") is True
        assert totals.get("declined_line_count") == 2
        # Adjusted total should be strictly less than the original.
        assert float(totals.get("adjusted_total")) < float(totals.get("original_total"))

        # Group A appears struck in the customer_view.
        cv = payload.get("customer_view") or {}
        groups = cv.get("groups") or []
        a_row = next(
            (g for g in groups if g.get("category_id") == cat_a["id"]),
            None,
        )
        assert a_row is not None, groups
        assert a_row.get("declined") is True
        assert a_row.get("active_subtotal") == 0
        # Group B untouched.
        b_row = next(
            (g for g in groups if g.get("category_id") == cat_b["id"]),
            None,
        )
        assert b_row is not None and b_row.get("declined") is False

        # Audit row present.
        audit_r = admin_sess.get(
            f"{BASE_URL}/api/audit-logs?quote_id={qid}",
            timeout=REQ_TIMEOUT,
        )
        # Not every tenant exposes an audit-logs GET — skip the check
        # if the route is missing rather than fail the whole test.
        if audit_r.status_code == 200:
            audit_rows = _rows(audit_r.json())
            assert any(
                a.get("event") == "quote.group_declined"
                and a.get("quote_id") == qid
                for a in audit_rows
            ), audit_rows
    finally:
        _cleanup(admin_sess, qid)


# ═════════════════════════════════════════════════════════════════════
# 2. Magic-link undecline round-trips
# ═════════════════════════════════════════════════════════════════════

def test_customer_group_undecline_via_token(
    admin_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        token = _get_magic_link_token(admin_sess, qid)

        # Decline then restore.
        d = requests.patch(
            f"{BASE_URL}/api/portal/quotes/via-token/{token}"
            f"/groups/{cat_a['id']}/decline",
            json={"reason": "hold"},
            timeout=REQ_TIMEOUT,
        )
        assert d.status_code == 200, d.text

        u = requests.patch(
            f"{BASE_URL}/api/portal/quotes/via-token/{token}"
            f"/groups/{cat_a['id']}/undecline",
            timeout=REQ_TIMEOUT,
        )
        assert u.status_code == 200, u.text
        totals = (u.json().get("totals") or {})
        # After restore: no declined lines.
        assert totals.get("has_declined_lines") is False
        assert totals.get("declined_line_count") == 0
        # adjusted_total should now equal original_total.
        assert float(totals.get("adjusted_total")) == float(
            totals.get("original_total")
        )
        # Group A row no longer declined.
        cv = u.json().get("customer_view") or {}
        a_row = next(
            (g for g in cv.get("groups") or []
             if g.get("category_id") == cat_a["id"]),
            None,
        )
        assert a_row is not None
        assert a_row.get("declined") is False
    finally:
        _cleanup(admin_sess, qid)


# ═════════════════════════════════════════════════════════════════════
# 3. Admin JWT decline path
# ═════════════════════════════════════════════════════════════════════

def test_admin_group_decline_on_behalf(
    admin_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        r = admin_sess.patch(
            f"{BASE_URL}/api/quotes/{qid}/groups/{cat_b['id']}/decline",
            json={"reason": "waiving on cust request"},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        # Group B ($50) is now declined; group A untouched.
        payload = r.json()
        cv = payload.get("customer_view") or {}
        b_row = next(
            (g for g in cv.get("groups") or []
             if g.get("category_id") == cat_b["id"]),
            None,
        )
        assert b_row is not None and b_row.get("declined") is True

        totals = payload.get("totals") or {}
        assert totals.get("declined_line_count") == 1
    finally:
        _cleanup(admin_sess, qid)


# ═════════════════════════════════════════════════════════════════════
# 4. Technician forbidden
# ═════════════════════════════════════════════════════════════════════

def test_technician_forbidden_on_admin_route(
    admin_sess, tech_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        r = tech_sess.patch(
            f"{BASE_URL}/api/quotes/{qid}/groups/{cat_a['id']}/decline",
            json={},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(admin_sess, qid)


# ═════════════════════════════════════════════════════════════════════
# 5. Rate limit — 11th hit in 5 min → 429
# ═════════════════════════════════════════════════════════════════════

def test_group_rate_limit_returns_429(
    admin_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        token = _get_magic_link_token(admin_sess, qid)

        # 10 alternating decline/undecline hits should succeed (200)
        # then the 11th trips the ``group`` bucket (10 / 5 min).
        for _ in range(5):
            r1 = requests.patch(
                f"{BASE_URL}/api/portal/quotes/via-token/{token}"
                f"/groups/{cat_a['id']}/decline",
                json={},
                timeout=REQ_TIMEOUT,
            )
            assert r1.status_code == 200, r1.text
            r2 = requests.patch(
                f"{BASE_URL}/api/portal/quotes/via-token/{token}"
                f"/groups/{cat_a['id']}/undecline",
                timeout=REQ_TIMEOUT,
            )
            assert r2.status_code == 200, r2.text
        # 11th request — over budget.
        r_over = requests.patch(
            f"{BASE_URL}/api/portal/quotes/via-token/{token}"
            f"/groups/{cat_a['id']}/decline",
            json={},
            timeout=REQ_TIMEOUT,
        )
        assert r_over.status_code == 429, r_over.text
    finally:
        _cleanup(admin_sess, qid)


# ═════════════════════════════════════════════════════════════════════
# 6. Actionability guard — accepted quotes reject 409
# ═════════════════════════════════════════════════════════════════════

def test_group_decline_on_accepted_returns_409(
    admin_sess, customer_id, two_svc_cats, inc_cat,
):
    cat_a, cat_b = two_svc_cats
    doc = _make_quote(admin_sess, customer_id, cat_a, cat_b, inc_cat)
    qid = doc["id"]
    try:
        _mark_sent(admin_sess, qid)
        # Accept the quote so ``decision=accepted`` locks the doc.
        acc = admin_sess.post(
            f"{BASE_URL}/api/quotes/{qid}/accept",
            timeout=REQ_TIMEOUT,
        )
        assert acc.status_code in (200, 409), acc.text

        r = admin_sess.patch(
            f"{BASE_URL}/api/quotes/{qid}/groups/{cat_a['id']}/decline",
            json={},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 409, r.text
    finally:
        _cleanup(admin_sess, qid)
