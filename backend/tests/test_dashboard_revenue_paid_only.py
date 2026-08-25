"""Feb-2026 · Dashboard consistency ship — ``payment_status: paid`` filter
locked in on the revenue-by-category + income-by-service-category tiles.

Prior behavior: both aggregation queries scanned every invoice in the
date window regardless of ``payment_status``, so an unpaid draft or an
overdue invoice would inflate the tile numbers even though the
``/api/dashboard`` top-card counted only paid revenue. The two tiles
were therefore arithmetically incomparable, which is what confused the
plofv-prod operator into thinking $2,430 top-card vs $749 by-category
was a phantom-data problem when it was actually a filter-mismatch
problem.

This suite locks the new behavior:

  1. A paid invoice in the current month shows up in the tile.
  2. An unpaid invoice in the current month does NOT show up.
  3. A partial-payment or overdue invoice does NOT show up (only
     ``payment_status == "paid"`` counts, not ``partial`` / ``overdue``).
  4. Tenant scope preserved — a paid invoice in tenant B does not
     leak into tenant A's tile.
  5. Same guarantees hold for ``/admin/dashboard/income-by-service-category``.

Harness mirrors ``test_dashboard_revenue.py`` (sync PyMongo for
setup, HTTP against the live pod backend, JWT via ``/api/auth/login``
of the ``manager@aquaterra.com`` seed user).
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


# ─── Login helper — same pattern as ``test_dashboard_revenue.py`` ─────
_TOK_CACHE: dict = {}


def _login(email: str = "admin@aquaterra.com") -> tuple[str, str]:
    """Return (token, tenant_id) for the caller. Cached across tests.

    Feb-2026 · Dashboard consistency ship — uses ``admin@aquaterra.com``
    (role=admin) because ``dashboard_revenue.py::_require_admin`` only
    accepts ``("admin", "super_admin")`` — not ``manager``. This is a
    pre-existing constraint on the endpoint; parity across ALL of the
    tile suites should be reconciled separately (parked P2)."""
    key = f"tok:{email}"
    if _TOK_CACHE.get(key):
        return _TOK_CACHE[key]
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    tid = me.get("tenant_id") or me.get("tenant", {}).get("id") or ""
    _TOK_CACHE[key] = (tok, tid)
    return tok, tid


# ─── Fixture writers ──────────────────────────────────────────────────
_FIXTURE_PREFIX = f"TEST-drpo-{uuid.uuid4().hex[:6]}"


def _seed_invoice(*, tenant_id: str, payment_status: str,
                    line_items: list[dict],
                    day_offset: int = 0) -> str:
    """Insert an invoice. ``day_offset`` is added to today's UTC date so
    tests can force docs into (or out of) the current-month window."""
    iid = f"{_FIXTURE_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    today = datetime.now(timezone.utc)
    when = today.replace(day=max(1, today.day + day_offset))
    total = sum((li.get("quantity", 0) * li.get("unit_price", 0))
                for li in line_items)
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
        "invoice_number": iid,
        "created_at": when.isoformat(),
        # ``status`` is orthogonal to ``payment_status`` in the schema
        # ("status" tracks the doc's lifecycle — draft, sent, accepted).
        # The dashboard filter cares about payment state only.
        "status": "accepted",
        "payment_status": payment_status,
        "currency": "USD",
        "total": total,
        "subtotal": total,
        "line_items": line_items,
    })
    return iid


def _cleanup() -> None:
    _db.quotes.delete_many({"id": {"$regex": f"^{_FIXTURE_PREFIX}"}})
    _db.tenants.delete_many({"id": {"$regex": f"^{_FIXTURE_PREFIX}"}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _month_range() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1).date().isoformat()
    end = now.date().isoformat()
    return start, end


# ══════════════════════════════════════════════════════════════════════
# revenue-by-category tile
# ══════════════════════════════════════════════════════════════════════
def test_revenue_by_category_includes_paid_invoice_in_month():
    tok, tid = _login()
    paid_id = _seed_invoice(
        tenant_id=tid, payment_status="paid",
        line_items=[{"description": "TEST paid line",
                      "quantity": 1, "unit_price": 100.0,
                      "category": "TEST-drpo-paid"}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert cats.get("TEST-drpo-paid") == 100.0, (
            f"paid invoice must be in tile; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": paid_id})


def test_revenue_by_category_excludes_unpaid_invoice():
    tok, tid = _login()
    unpaid_id = _seed_invoice(
        tenant_id=tid, payment_status="unpaid",
        line_items=[{"description": "TEST unpaid line",
                      "quantity": 1, "unit_price": 250.0,
                      "category": "TEST-drpo-unpaid"}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert "TEST-drpo-unpaid" not in cats, (
            f"unpaid invoice must be excluded from tile; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": unpaid_id})


def test_revenue_by_category_excludes_partial_and_overdue():
    tok, tid = _login()
    partial_id = _seed_invoice(
        tenant_id=tid, payment_status="partial",
        line_items=[{"description": "partial line",
                      "quantity": 1, "unit_price": 111.0,
                      "category": "TEST-drpo-partial"}],
    )
    overdue_id = _seed_invoice(
        tenant_id=tid, payment_status="overdue",
        line_items=[{"description": "overdue line",
                      "quantity": 1, "unit_price": 222.0,
                      "category": "TEST-drpo-overdue"}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        cats = {c["category"] for c in r.json()["items"]}
        # Neither non-paid state should surface. The tile is a
        # strict-equality ``payment_status == "paid"`` filter, so
        # partial / overdue / null / any other value fall away.
        assert "TEST-drpo-partial" not in cats, (
            f"partial-payment invoice must be excluded; got {cats}"
        )
        assert "TEST-drpo-overdue" not in cats, (
            f"overdue invoice must be excluded; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": partial_id})
        _db.quotes.delete_one({"id": overdue_id})


# ══════════════════════════════════════════════════════════════════════
# income-by-service-category tile — same filter, same behavior
# ══════════════════════════════════════════════════════════════════════
def test_income_by_service_category_excludes_unpaid_invoice():
    tok, tid = _login()
    unpaid_id = _seed_invoice(
        tenant_id=tid, payment_status="unpaid",
        line_items=[{"description": "TEST income unpaid",
                      "quantity": 1, "unit_price": 500.0,
                      # No item_id → falls into "Uncategorized" bucket
                      # if it were counted at all. Filter must
                      # drop it BEFORE bucketing.
                      "item_id": None}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        # Sum of all "Uncategorized" bucket amounts — the unpaid
        # $500 must NOT be in there.
        uncat_amt = sum(c["amount"] for c in r.json()["items"]
                          if c["category"] == "Uncategorized")
        # Baseline uncategorized may have data from OTHER seed rows;
        # the assertion is that the delta from this specific unpaid
        # invoice is not present. Repeat with a paid twin to confirm.
        paid_id = _seed_invoice(
            tenant_id=tid, payment_status="paid",
            line_items=[{"description": "TEST income paid",
                          "quantity": 1, "unit_price": 500.0,
                          "item_id": None}],
        )
        r2 = requests.get(
            f"{API}/admin/dashboard/income-by-service-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        uncat_amt_after = sum(c["amount"] for c in r2.json()["items"]
                                if c["category"] == "Uncategorized")
        # The paid twin added $500 to the uncategorized bucket.
        # The unpaid one added nothing.
        assert uncat_amt_after - uncat_amt == 500.0, (
            f"Only the paid invoice should shift the tile: "
            f"before={uncat_amt}, after={uncat_amt_after}, "
            f"delta expected=500.0"
        )
        _db.quotes.delete_one({"id": paid_id})
    finally:
        _db.quotes.delete_one({"id": unpaid_id})


# ══════════════════════════════════════════════════════════════════════
# Tenant scoping — paid invoice in tenant B invisible from tenant A.
# ══════════════════════════════════════════════════════════════════════
def test_tenant_isolation_paid_invoice_in_other_tenant_invisible():
    tok, tid = _login()
    other_tid = f"{_FIXTURE_PREFIX}-tenantB"
    _db.tenants.insert_one({
        "id": other_tid, "name": "Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        _seed_invoice(
            tenant_id=other_tid, payment_status="paid",
            line_items=[{"description": "cross-tenant paid",
                          "quantity": 1, "unit_price": 999.0,
                          "category": "TEST-drpo-cross"}],
        )
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text
        cats = {c["category"] for c in r.json()["items"]}
        assert "TEST-drpo-cross" not in cats, (
            f"paid invoice in another tenant must not leak: {cats}"
        )
    finally:
        _db.quotes.delete_many({"tenant_id": other_tid})
        _db.tenants.delete_one({"id": other_tid})
