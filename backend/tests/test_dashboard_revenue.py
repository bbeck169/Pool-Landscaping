"""Admin dashboard revenue tiles · Feb-2026.

End-to-end HTTP tests against the running backend for
``/api/admin/dashboard/revenue-by-category`` and
``/api/admin/dashboard/revenue-forecast``.  Uses the ``TEST-`` prefix so
``conftest.py`` cleans everything at teardown.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]

_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                               json={"email": email, "password": "password123"},
                               timeout=30)
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _admin_ctx():
    if _CACHE.get("admin_ctx"):
        return _CACHE["admin_ctx"]
    # Feb-2026 · Dashboard consistency ship — was
    # ``manager@aquaterra.com`` but ``dashboard_revenue.py::_require_admin``
    # only accepts ("admin", "super_admin"), so the 3 revenue-by-
    # category tests were already 403'ing on main pre-this-PR. Swap to
    # admin@aquaterra.com to match the endpoint's contract.
    tok = _login("admin@aquaterra.com")
    me = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=15).json()
    _CACHE["admin_ctx"] = {"token": tok, "tenant_id": me.get("tenant_id")}
    return _CACHE["admin_ctx"]


def _customer_token():
    return _login("customer@aquaterra.com")


def _seed_isolated_tenant() -> str:
    """Create a fresh tenant + admin user + return {tid, tok, ids_to_cleanup}."""
    tid = f"TEST-drev-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid,
        "slug": f"test-drev-{uuid.uuid4().hex[:6]}",
        "name": "TEST_drev_tenant",
        "active": True,
    })
    return tid


def _seed_admin_for_tenant(tid: str) -> tuple[str, str, str]:
    """Return (user_id, email, token) for a fresh admin in the given tenant."""
    from utils import hash_password  # local import — session-scoped
    uid = f"TEST-drev-u-{uuid.uuid4().hex[:6]}"
    email = f"drev-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_drev_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return uid, email, _login(email)


def _cleanup_tenant(tid: str):
    _db.tenants.delete_one({"id": tid})


def _seed_invoice(tenant_id: str, *, created_at: str,
                    line_items: list[dict],
                    status: str = "paid") -> str:
    iid = f"TEST-drev-inv-{uuid.uuid4().hex[:8]}"
    total = sum((li.get("quantity", 0) * li.get("unit_price", 0))
                for li in line_items)
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
        "invoice_number": iid,
        "created_at": created_at,
        "status": status,
        # Feb-2026 · Dashboard consistency ship — the revenue-by-category
        # and income-by-service-category endpoints now filter on
        # ``payment_status == "paid"`` to agree with the top-card
        # lifetime paid number. Existing tests all use status="paid" as
        # the default, so stamp ``payment_status`` to match — an
        # explicit unpaid fixture (status="unpaid") gets payment_status
        # "unpaid" and is correctly excluded from the tile.
        "payment_status": "paid" if status == "paid" else "unpaid",
        "currency": "USD",
        "total": total,
        "subtotal": total,
        "line_items": line_items,
    })
    return iid


def _seed_job(tenant_id: str, *, scheduled_date: str,
                status: str = "scheduled", price: float = 250.0) -> str:
    jid = f"TEST-drev-job-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "TEST_drev_job",
        "customer_id": "TEST-drev-cust",
        "status": status,
        "scheduled_date": scheduled_date,
        "price": price,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _seed_billing_plan(tenant_id: str, *, amount: float,
                        frequency: str,
                        active: bool = True) -> str:
    pid = f"TEST-drev-plan-{uuid.uuid4().hex[:8]}"
    _db.billing_plans.insert_one({
        "id": pid, "tenant_id": tenant_id,
        "customer_id": "TEST-drev-cust",
        "amount": amount, "frequency": frequency,
        "active": active,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return pid


def _cleanup(ids: list[str]):
    _db.quotes.delete_many({"id": {"$in": ids}})
    _db.jobs.delete_many({"id": {"$in": ids}})
    _db.billing_plans.delete_many({"id": {"$in": ids}})


# ═══════════════════ 1. Category tests ═══════════════════
def test_revenue_by_category_admin_success():
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]
    inv1 = _seed_invoice(tid, created_at="2026-06-15T12:00:00+00:00",
                          line_items=[
                              {"description": "Weekly service", "quantity": 4,
                                "unit_price": 25.0, "category": "TESTCAT_Pool"},
                              {"description": "Chlorine", "quantity": 2,
                                "unit_price": 15.0, "category": "TESTCAT_Chem"},
                          ])
    inv2 = _seed_invoice(tid, created_at="2026-06-20T12:00:00+00:00",
                          line_items=[
                              {"description": "Salt", "quantity": 1,
                                "unit_price": 50.0, "category": "TESTCAT_Chem"},
                          ])
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category"
            f"?start=2026-06-01&end=2026-06-30",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        cats = {c["category"]: c for c in body["items"]}
        assert cats["TESTCAT_Pool"]["amount"] == 100.0
        assert cats["TESTCAT_Pool"]["count"] == 1
        assert cats["TESTCAT_Chem"]["amount"] == 80.0
        assert cats["TESTCAT_Chem"]["count"] == 2
        # Colors are hex.
        assert cats["TESTCAT_Pool"]["color"].startswith("#")
        # Total includes our seed and any pre-existing tenant data.
        assert body["total"] >= 180.0
    finally:
        _cleanup([inv1, inv2])


def test_revenue_by_category_customer_403():
    r = requests.get(
        f"{API}/admin/dashboard/revenue-by-category?start=2026-06-01&end=2026-06-30",
        headers={"Authorization": f"Bearer {_customer_token()}"}, timeout=15,
    )
    assert r.status_code == 403, r.text


def test_revenue_by_category_tenant_isolation():
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]
    other_tid = f"TEST-drev-tenant-{uuid.uuid4().hex[:6]}"
    inv_other = _seed_invoice(other_tid, created_at="2026-06-15T12:00:00+00:00",
                                line_items=[{"description": "Foreign",
                                              "quantity": 1, "unit_price": 9999.99,
                                              "category": "TESTCAT_ForeignTenant"}])
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category"
            f"?start=2026-06-01&end=2026-06-30",
            headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
        ).json()
        assert "TESTCAT_ForeignTenant" not in {c["category"] for c in r["items"]}, \
            "cross-tenant category leaked!"
    finally:
        _cleanup([inv_other])


def test_revenue_by_category_empty_range():
    ctx = _admin_ctx()
    r = requests.get(
        # A range far in the past — no invoices there.
        f"{API}/admin/dashboard/revenue-by-category?start=1999-01-01&end=1999-01-31",
        headers={"Authorization": f"Bearer {ctx['token']}"}, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


# ═══════════════════ 2. Forecast tests ═══════════════════
def test_revenue_forecast_admin_success_booked_only():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for_tenant(tid)
    j1 = _seed_job(tid, scheduled_date="2027-03-05", status="scheduled",
                    price=125.0)
    j2 = _seed_job(tid, scheduled_date="2027-03-20", status="confirmed",
                    price=75.0)
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-forecast"
            f"?start=2027-03-01&end=2027-03-31",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["booked"]["amount"] == 200.0
        assert body["booked"]["job_count"] == 2
        assert body["recurring"]["amount"] == 0
        assert body["recurring"]["subscription_count"] == 0
        assert body["combined_total"] == 200.0
    finally:
        _cleanup([j1, j2])
        _db.users.delete_one({"id": uid})
        _cleanup_tenant(tid)
        _CACHE.pop(f"tok:{email}", None)


def test_revenue_forecast_admin_success_recurring_only():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for_tenant(tid)
    p1 = _seed_billing_plan(tid, amount=200.0, frequency="monthly")
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-forecast"
            f"?start=2027-04-01&end=2027-04-30",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["booked"]["job_count"] == 0
        assert r["recurring"]["subscription_count"] == 1
        assert r["recurring"]["cycle_count"] == 1
        assert r["recurring"]["amount"] == 200.0
    finally:
        _cleanup([p1])
        _db.users.delete_one({"id": uid})
        _cleanup_tenant(tid)
        _CACHE.pop(f"tok:{email}", None)


def test_revenue_forecast_admin_success_combined():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for_tenant(tid)
    j1 = _seed_job(tid, scheduled_date="2027-05-10", price=300.0)
    p1 = _seed_billing_plan(tid, amount=150.0, frequency="monthly")
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-forecast"
            f"?start=2027-05-01&end=2027-05-31",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["booked"]["amount"] == 300.0
        assert r["recurring"]["amount"] == 150.0
        assert r["combined_total"] == 450.0
    finally:
        _cleanup([j1, p1])
        _db.users.delete_one({"id": uid})
        _cleanup_tenant(tid)
        _CACHE.pop(f"tok:{email}", None)


def test_revenue_forecast_customer_403():
    r = requests.get(
        f"{API}/admin/dashboard/revenue-forecast?start=2026-06-01&end=2026-06-30",
        headers={"Authorization": f"Bearer {_customer_token()}"}, timeout=15,
    )
    assert r.status_code == 403, r.text


def test_revenue_forecast_recurring_cycles_calculated_correctly():
    """A monthly $100 subscription over a 2-month range (61 inclusive
    days) should yield 2 cycles = $200."""
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for_tenant(tid)
    p1 = _seed_billing_plan(tid, amount=100.0, frequency="monthly")
    try:
        r = requests.get(
            f"{API}/admin/dashboard/revenue-forecast"
            f"?start=2027-07-01&end=2027-08-30",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["recurring"]["cycle_count"] == 2, r
        assert r["recurring"]["amount"] == 200.0, r
    finally:
        _cleanup([p1])
        _db.users.delete_one({"id": uid})
        _cleanup_tenant(tid)
        _CACHE.pop(f"tok:{email}", None)
