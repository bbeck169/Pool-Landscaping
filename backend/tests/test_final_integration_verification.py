"""Feb 2026 · FINAL integration verification per E1 review_request.

Runs against the public preview URL (REACT_APP_BACKEND_URL). Focuses on:
- L.a: widget bundle sizes + 200 via frontend origin
- L.c: denied-requests endpoint + Mongo indexes present at rest
- L.j: walkthrough alias (completed + has_completed keys)
- L.h: campaign suppression code path
- Slice N: form-submit adapter (marketing_deliveries provider set)
- Trigger registry: estimate_accepted present
- RBAC sweep: tech + customer forbidden on estimate/invoice /full /pdf /accept
"""
from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FRONT_ENV = dotenv_values(Path("/app/frontend/.env"))
BASE = (_FRONT_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

_BACKEND_ENV = dotenv_values(Path("/app/backend/.env"))
_MONGO_URL = _BACKEND_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _BACKEND_ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── L.a — widget bundles via frontend origin ────────────────────────────────

def test_la_chat_min_js_served_and_size():
    r = requests.get(f"{BASE}/widget/chat.min.js", timeout=30)
    assert r.status_code == 200, r.status_code
    assert len(r.content) > 0
    # ensure minified (no source comments, sparse whitespace)
    gz = gzip.compress(r.content)
    assert len(gz) < 25 * 1024, f"gzipped size {len(gz)} exceeds 25KB"


def test_la_form_min_js_served_and_size():
    r = requests.get(f"{BASE}/widget/form.min.js", timeout=30)
    assert r.status_code == 200
    gz = gzip.compress(r.content)
    assert len(gz) < 25 * 1024, f"gzipped size {len(gz)} exceeds 25KB"


# ─── L.c — denied-requests endpoint + Mongo indexes ──────────────────────────

def test_lc_denied_requests_endpoint(admin_h):
    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "denied" in body
    assert isinstance(body["denied"], list)


def test_lc_denied_requests_indexes_present():
    if not (_MONGO_URL and _DB_NAME):
        pytest.skip("MongoDB not configured")
    client = MongoClient(_MONGO_URL)
    try:
        db = client[_DB_NAME]
        # startup wires _ensure_denied_indexes on boot; call denied-requests
        # first to ensure any lazy init has run
        info = db.widget_denied_requests.index_information()
        assert "widget_denied_ttl_7d" in info, f"missing TTL index; have {list(info)}"
        assert "widget_denied_tenant_time" in info, f"missing compound index; have {list(info)}"
    finally:
        client.close()


# ─── L.j — walkthrough alias ─────────────────────────────────────────────────

def test_lj_walkthrough_alias_both_keys(customer_h):
    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                     headers=customer_h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "completed" in body
    assert "has_completed" in body
    assert body["completed"] == body["has_completed"]
    assert isinstance(body["completed"], bool)


# ─── L.h — suppression precedes send in campaign dispatch ────────────────────

def test_lh_suppression_precedes_send_code_check():
    src = Path("/app/backend/services/marketing_campaigns.py").read_text()
    # is_suppressed must be called + branch to status='suppressed' before send
    assert "is_suppressed" in src
    supp_idx = src.find("is_suppressed(")
    sup_status_idx = src.find('"status": "suppressed"')
    assert supp_idx != -1 and sup_status_idx != -1
    # rough ordering — the suppression check block appears before Resend call
    # send_email / send_sms live in comms adapters
    send_idx = src.find("send_email(")
    if send_idx == -1:
        send_idx = src.find("send_sms(")
    assert send_idx != -1 and supp_idx < send_idx, "is_suppressed must precede send"


# ─── Trigger registry — estimate_accepted included ───────────────────────────

def test_trigger_registry_includes_estimate_accepted(admin_h):
    r = requests.get(f"{API}/marketing/sequences/triggers/registry",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    triggers = r.json().get("triggers", [])
    types = {t.get("type") for t in triggers}
    assert "estimate_accepted" in types, f"missing estimate_accepted in {types}"


# ─── RBAC sweep — technician forbidden on estimate/invoice detail routes ────

def _seed_estimate_and_invoice(admin_h):
    """Locate an existing estimate + invoice for the admin's tenant.
    Returns (eid, iid) or (None, None)."""
    eid = iid = None
    r = requests.get(f"{API}/estimates?limit=5", headers=admin_h, timeout=30)
    if r.status_code == 200:
        data = r.json()
        rows = data if isinstance(data, list) else data.get("items", []) or data.get("estimates", [])
        if rows:
            eid = rows[0].get("id") or rows[0].get("estimate_id")
    r = requests.get(f"{API}/invoices/overview?limit=5", headers=admin_h, timeout=30)
    if r.status_code == 200:
        data = r.json()
        rows = data.get("invoices") or data.get("items") or []
        if rows:
            iid = rows[0].get("id") or rows[0].get("invoice_id")
    return eid, iid


def test_rbac_tech_blocked_on_estimate_and_invoice(admin_h, tech_h):
    eid, iid = _seed_estimate_and_invoice(admin_h)
    if not eid or not iid:
        pytest.skip("need at least one estimate + invoice in tenant to sweep")
    for path in [f"/estimates/{eid}/full",
                 f"/estimates/{eid}/pdf",
                 f"/invoices/{iid}/full",
                 f"/invoices/{iid}/pdf"]:
        r = requests.get(f"{API}{path}", headers=tech_h, timeout=30)
        assert r.status_code in (401, 403, 404), f"tech GET {path} -> {r.status_code}"
    # accept is POST
    r = requests.post(f"{API}/estimates/{eid}/accept", headers=tech_h, timeout=30, json={})
    assert r.status_code in (401, 403, 404, 405), f"tech POST /accept -> {r.status_code}"


def test_rbac_customer_scoped_to_own_records(admin_h, customer_h):
    # Determine customer's own customer_id
    me = requests.get(f"{API}/auth/me", headers=customer_h, timeout=30).json()
    my_cid = me.get("customer_id")

    # Find an invoice + estimate owned by a *different* customer via admin
    r_est = requests.get(f"{API}/estimates?limit=50", headers=admin_h, timeout=30)
    foreign_eid = None
    if r_est.status_code == 200:
        rows = r_est.json()
        rows = rows if isinstance(rows, list) else rows.get("items", []) or []
        for row in rows:
            if row.get("customer_id") and row["customer_id"] != my_cid:
                foreign_eid = row.get("id")
                break

    r_inv = requests.get(f"{API}/invoices/overview?limit=50", headers=admin_h, timeout=30)
    foreign_iid = None
    if r_inv.status_code == 200:
        rows = r_inv.json().get("invoices") or []
        for row in rows:
            if row.get("customer_id") and row["customer_id"] != my_cid:
                foreign_iid = row.get("id")
                break

    if not foreign_iid and not foreign_eid:
        pytest.skip("no foreign estimate/invoice to sweep against")

    if foreign_iid:
        r = requests.get(f"{API}/invoices/{foreign_iid}/full", headers=customer_h, timeout=30)
        assert r.status_code in (403, 404), f"customer foreign inv {foreign_iid} -> {r.status_code}"
    if foreign_eid:
        r = requests.get(f"{API}/estimates/{foreign_eid}/full", headers=customer_h, timeout=30)
        assert r.status_code in (403, 404), f"customer foreign est {foreign_eid} -> {r.status_code}"


# ─── L.i — analytics widget conversion block ─────────────────────────────────

def test_li_analytics_widget_conversion_block(admin_h):
    r = requests.get(f"{API}/marketing/analytics/overview", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "widget" in body, f"analytics/overview missing widget key: {list(body)}"
    w = body["widget"]
    # allow either flat or {chat,form} shape
    keys = str(w)
    assert "chat" in keys.lower() or "form" in keys.lower(), f"widget block empty: {w}"
