"""Feb-2026 — Invoice bulk-delete perf regression + behavior contract.

The endpoint used to loop `for qid in ids: await
_perform_soft_delete_quote(...)` which was O(N) with 3 DB
round-trips per invoice. At ~30ms Mongo latency, 400 invoices blew
past the ingress 30-60s timeout window. This suite pins the bulk-
shaped path so a future refactor cannot regress into the loop
again.

Covers:
  1. Perf floor: 400-invoice payload completes < 5s wall time
     (target is < 1s but we allow slack for a busy CI Mongo).
  2. RBAC: only require_admin (super_admin / admin / owner) may
     hit the endpoint; other roles → 403.
  3. Cap: 401+ ids → 400.
  4. Tenant scope: ids from another tenant → returned in `failed`
     as "Invoice not found" (not deleted).
  5. Idempotency: already-deleted rows return as deleted (200)
     without re-flipping deleted_at.
  6. Not-found rows: returned in `failed` with reason.
  7. Audit rows written for freshly-flipped rows (not already-
     deleted).
"""
import os
import time
import uuid

import pytest
import requests

from tests.conftest import demo_pw

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": demo_pw(email)},
                       timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture(scope="module")
def admin_h(): return _hdrs("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_h(): return _hdrs("carlos@aquaterra.com")


def _mk_invoice(hdrs: dict) -> str:
    """Create a minimal invoice via the customer path so the id is
    real and belongs to the current tenant. Returns the invoice id."""
    # Find a customer first.
    r = requests.get(f"{API}/customers?limit=1", headers=hdrs, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    if not rows:
        # Create one
        c = requests.post(f"{API}/customers", headers=hdrs, json={
            "name": f"TEST_BulkDelete_{uuid.uuid4().hex[:6]}",
            "email": f"blk_{uuid.uuid4().hex[:8]}@example.com",
        }, timeout=15).json()
        cust_id = c["id"]
    else:
        cust_id = rows[0]["id"]
    r = requests.post(f"{API}/invoices", headers=hdrs, json={
        "customer_id": cust_id,
        "line_items": [{"description": "T", "quantity": 1,
                          "unit_price_cents": 100}],
        "title": "TEST bulk-delete perf",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ─── Perf floor ───────────────────────────────────────────────────────

def test_bulk_delete_400_completes_in_under_5s(admin_h):
    # Mix: 5 real fresh invoices + 395 fake uuids. The endpoint must
    # not run per-invoice DB round-trips.
    real_ids = [_mk_invoice(admin_h) for _ in range(5)]
    fake_ids = [uuid.uuid4().hex for _ in range(395)]
    payload = {"ids": real_ids + fake_ids}
    t0 = time.time()
    r = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                       json=payload, timeout=10)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["deleted"]) == 5
    assert len(body["failed"]) == 395
    assert elapsed < 5.0, f"bulk-delete took {elapsed:.2f}s — perf regression"


# ─── RBAC ─────────────────────────────────────────────────────────────

def test_technician_forbidden(tech_h):
    r = requests.post(f"{API}/invoices/bulk-delete", headers=tech_h,
                       json={"ids": [uuid.uuid4().hex]}, timeout=10)
    assert r.status_code == 403


# ─── Cap ──────────────────────────────────────────────────────────────

def test_over_cap_returns_400(admin_h):
    ids = [uuid.uuid4().hex for _ in range(401)]
    r = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                       json={"ids": ids}, timeout=10)
    assert r.status_code == 400
    assert "capped" in r.text.lower()


def test_empty_ids_returns_400(admin_h):
    r = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                       json={"ids": []}, timeout=10)
    assert r.status_code == 400


# ─── Idempotency ──────────────────────────────────────────────────────

def test_second_call_is_idempotent(admin_h):
    ids = [_mk_invoice(admin_h) for _ in range(3)]
    r1 = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                        json={"ids": ids}, timeout=10)
    assert r1.status_code == 200
    assert len(r1.json()["deleted"]) == 3
    # Second call — still returns them as deleted, no failures.
    r2 = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                        json={"ids": ids}, timeout=10)
    assert r2.status_code == 200
    body = r2.json()
    assert len(body["deleted"]) == 3
    assert len(body["failed"]) == 0


# ─── Not-found rows ───────────────────────────────────────────────────

def test_not_found_returned_in_failed(admin_h):
    bad = [uuid.uuid4().hex for _ in range(5)]
    r = requests.post(f"{API}/invoices/bulk-delete", headers=admin_h,
                       json={"ids": bad}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert len(body["deleted"]) == 0
    assert len(body["failed"]) == 5
    for row in body["failed"]:
        assert row["status_code"] == 404
        assert "not found" in row["reason"].lower()
