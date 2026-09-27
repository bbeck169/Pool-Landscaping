"""Task H0 · Feb-2026 — Historical Invoice Date Backfill.

Backend tests locking the ``created_at`` / ``paid_at`` optional
admin-only override contract on:

  * ``POST /quotes``                    (``QuoteIn.created_at``)
  * ``POST /quotes/{qid}/record-payment`` (``RecordPaymentIn.paid_at``)

Plus the PATCH-defense strip on ``PUT /quotes/{qid}`` guarding
the write-once historical-date contract.

Coverage matrix (10 tests · Commit 1 = 1-7 · Commit 2 = 8-10):

  Quote-create:
    1. Admin backfill → stored, override audit fields populated.
    2. Admin no-override → server-stamps now(), no audit fields.
    3. Non-admin (tech) sends override → silently ignored, no audit.
    4. Admin future date → 400 future_date_not_allowed.
    5. Admin ancient date (> 10y) → 400 date_too_old.
    6. Admin naive datetime → coerced to UTC.
    7. PATCH-defense: PUT with ``created_at`` → unchanged.

  Record-payment:
    8. Admin fully-paid + paid_at → applied, override audit stamped.
    9. Admin partial + paid_at → silently deferred (INFO trace).
    10. Admin future paid_at → 400 future_date_not_allowed.

Uses live Mongo + live HTTP against ``BASE`` — matches every
other integration-style test in this suite. Tenant scope is
AquaTerra (the seeded demo tenant); a synthetic customer is
inserted / deleted per-module so we never touch the real
customer records.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


# ── Fixtures ────────────────────────────────────────────────────
_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def h0_customer_id(dbc, aquaterra_id):
    """Fresh Task-H0-owned customer so the tests don't pollute the
    real AquaTerra seed rows. Torn down at module exit."""
    cid = f"cust-task-h0-{uuid.uuid4().hex[:12]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": aquaterra_id,
        "name": "Task-H0 Test Customer",
        "email": "h0-test@example.com",
        "phone": "555-0100",
        "address": "123 Task H0 Way",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    yield cid
    dbc.customers.delete_many({"id": cid})
    dbc.quotes.delete_many({"customer_id": cid})


def _login(email: str, password: str = "password123") -> Dict:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    tok = _login("admin@aquaterra.com")["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tech_h():
    tok = _login("mike@aquaterra.com")["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _make_quote_payload(customer_id: str, **extra) -> Dict:
    """Minimal well-formed ``QuoteIn`` payload — every mandatory
    line-item taxonomy field is present so the K71 + income-
    category validators don't 400 before the H0 override path is
    even reached."""
    payload = {
        "customer_id": customer_id,
        "title": f"Task H0 test quote {uuid.uuid4().hex[:6]}",
        "doc_type": "quote",
        "line_items": [{
            "description": "Pool cleaning — Task H0 test line",
            "quantity": 1,
            "unit_price": 100.0,
            "category": "Pool",
        }],
        "tax_rate": 0.0,
    }
    payload.update(extra)
    return payload


# ── 1) Admin backfill on quote create ──────────────────────────
def test_admin_created_at_backfill_applied(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    override = "2024-03-10T12:00:00+00:00"
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id, created_at=override),
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # The API round-trip normalises the ISO representation but the
    # underlying value must match.
    stored = dbc.quotes.find_one(
        {"id": body["id"], "tenant_id": aquaterra_id}, {"_id": 0},
    )
    assert stored is not None
    stored_dt = datetime.fromisoformat(stored["created_at"])
    override_dt = datetime.fromisoformat(override)
    assert stored_dt == override_dt, (
        f"created_at drifted — expected {override_dt}, got {stored_dt}"
    )
    assert stored.get("created_at_override_by"), (
        "created_at_override_by must be populated on admin backfill"
    )
    assert stored.get("created_at_override_at"), (
        "created_at_override_at must be populated on admin backfill"
    )


# ── 2) Admin no-override → server-stamps now() ─────────────────
def test_admin_no_override_stamps_now(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    before = datetime.now(timezone.utc)
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id),
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    stored = dbc.quotes.find_one(
        {"id": body["id"], "tenant_id": aquaterra_id}, {"_id": 0},
    )
    after = datetime.now(timezone.utc)
    stored_dt = datetime.fromisoformat(stored["created_at"])
    assert before - timedelta(seconds=2) <= stored_dt <= after + timedelta(seconds=2), (
        f"created_at not stamped from now() — got {stored_dt}"
    )
    assert "created_at_override_by" not in stored, (
        "override audit fields must NOT land on the no-override path"
    )
    assert "created_at_override_at" not in stored


# ── 3) Non-admin override silently dropped ─────────────────────
def test_non_admin_override_silently_dropped(
    tech_h, dbc, aquaterra_id,
):
    """A tech attempting to backfill still 403s on ``POST /quotes``
    (because the endpoint uses ``require_admin``), but the
    override-drop path is exercised by ``resolve_date_override``
    directly with a synthetic non-admin user dict so we can
    verify the silent-drop contract without needing a role that
    can bypass ``require_admin``. This is the cleanest way to
    test the "silent-drop" semantics without altering the
    endpoint's own auth gate."""
    from services.quotes.date_override import resolve_date_override

    tech_user = {
        "id": "test-tech-user-id",
        "role": "technician",
    }
    override = datetime(2022, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    before = datetime.now(timezone.utc)
    effective_iso, override_by, override_at = resolve_date_override(
        override, user=tech_user, tenant_id=aquaterra_id,
        field_name="created_at", entity_kind="quote", entity_id="<test>",
    )
    after = datetime.now(timezone.utc)

    # Effective timestamp must be now() — override silently dropped.
    stamped = datetime.fromisoformat(effective_iso)
    assert before - timedelta(seconds=2) <= stamped <= after + timedelta(seconds=2), (
        f"silent-drop path should return now() — got {stamped}"
    )
    # Both audit slots must be None on the drop path.
    assert override_by is None, override_by
    assert override_at is None, override_at


# ── 4) Future-dated override → 400 future_date_not_allowed ─────
def test_future_created_at_rejected(admin_h, h0_customer_id):
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id, created_at=future),
        timeout=20,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error") == "future_date_not_allowed", detail
        assert detail.get("field") == "created_at", detail
    else:
        assert "future" in str(detail).lower()


# ── 5) Ancient override (> 50y post-Feb-2026 Sub-phase A) → 400 date_too_old ─
def test_ancient_created_at_rejected(admin_h, h0_customer_id):
    # Feb-2026 · PDF Importer Sub-phase A relaxed ``_ANCIENT_DAYS``
    # from 10 years to 50 years (ruling R6=B) so the H0 date
    # override can accept genuinely-old paper invoices.  Bump the
    # boundary sample here to 51 years so this test continues to
    # exercise the ancient-rejection path with the new limit.
    ancient = (datetime.now(timezone.utc) - timedelta(days=365 * 51)).isoformat()
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id, created_at=ancient),
        timeout=20,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error") == "date_too_old", detail
        assert detail.get("field") == "created_at", detail
    else:
        # Post-Feb-2026 · Sub-phase A the copy now reads "50 years";
        # the "too old" phrase covers both wordings.
        assert "too old" in str(detail).lower() or "50 years" in str(detail)


# ── 6) Naive datetime coerced to UTC ───────────────────────────
def test_naive_datetime_coerced_to_utc(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    # No trailing "Z" / offset — a naive Pydantic datetime.
    naive = "2024-06-15T08:30:00"
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id, created_at=naive),
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    stored = dbc.quotes.find_one(
        {"id": body["id"], "tenant_id": aquaterra_id}, {"_id": 0},
    )
    stored_dt = datetime.fromisoformat(stored["created_at"])
    # Coerced to UTC — the wallclock hour + minute survive, tzinfo
    # is now +00:00.
    assert stored_dt.tzinfo is not None
    assert stored_dt.utcoffset() == timedelta(0)
    assert stored_dt.hour == 8 and stored_dt.minute == 30, stored_dt


# ── 7) PATCH-path defense — created_at in body is stripped ─────
def test_patch_defense_created_at_stripped(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    # Create a quote first.
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json=_make_quote_payload(h0_customer_id),
        timeout=20,
    )
    assert r.status_code == 200
    qid = r.json()["id"]
    pre = dbc.quotes.find_one(
        {"id": qid, "tenant_id": aquaterra_id}, {"_id": 0},
    )
    pre_created_at = pre["created_at"]

    # Now PATCH with created_at + paid_at + the audit sentinels
    # in the body. Every one must be stripped by the H0 defense.
    r2 = requests.put(
        f"{API}/quotes/{qid}", headers=admin_h,
        json={
            "title": "PATCH defense test",
            "created_at": "2020-01-01T00:00:00+00:00",
            "paid_at": "2020-01-01T00:00:00+00:00",
            "created_at_override_by": "attacker-user-id",
            "created_at_override_at": "2020-01-01T00:00:00+00:00",
            "paid_at_override_by": "attacker-user-id",
            "paid_at_override_at": "2020-01-01T00:00:00+00:00",
        },
        timeout=20,
    )
    assert r2.status_code == 200, r2.text

    post = dbc.quotes.find_one(
        {"id": qid, "tenant_id": aquaterra_id}, {"_id": 0},
    )
    assert post["created_at"] == pre_created_at, (
        f"PATCH must not overwrite created_at — pre={pre_created_at}, post={post['created_at']}"
    )
    assert "paid_at" not in post or post.get("paid_at") is None, (
        f"paid_at should not be leaked via PATCH — got {post.get('paid_at')}"
    )
    assert "created_at_override_by" not in post, post.get("created_at_override_by")
    assert "created_at_override_at" not in post, post.get("created_at_override_at")
    assert "paid_at_override_by" not in post, post.get("paid_at_override_by")
    assert "paid_at_override_at" not in post, post.get("paid_at_override_at")
    # Title DID land — control assertion showing the PATCH itself
    # went through (only the H0 override keys were filtered).
    assert post["title"] == "PATCH defense test"


# ── 8) Record-payment: admin fully-paid + paid_at applied ──────
def test_admin_paid_at_backfill_full_payment_applied(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    # Create an invoice first.
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json={**_make_quote_payload(h0_customer_id), "doc_type": "invoice"},
        timeout=20,
    )
    assert r.status_code == 200
    qid = r.json()["id"]
    total = float(r.json()["total"])

    override = "2024-04-05T09:15:00+00:00"
    r2 = requests.post(
        f"{API}/quotes/{qid}/record-payment", headers=admin_h,
        json={"amount": total, "paid_at": override},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text

    stored = dbc.quotes.find_one(
        {"id": qid, "tenant_id": aquaterra_id}, {"_id": 0},
    )
    assert stored["payment_status"] == "paid"
    stored_dt = datetime.fromisoformat(stored["paid_at"])
    override_dt = datetime.fromisoformat(override)
    assert stored_dt == override_dt, (
        f"paid_at drifted — expected {override_dt}, got {stored_dt}"
    )
    assert stored.get("paid_at_override_by"), stored
    assert stored.get("paid_at_override_at"), stored


# ── 9) Record-payment: partial payment silently defers override ─
def test_admin_paid_at_backfill_partial_deferred(
    admin_h, h0_customer_id, dbc, aquaterra_id,
):
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json={**_make_quote_payload(h0_customer_id), "doc_type": "invoice"},
        timeout=20,
    )
    assert r.status_code == 200
    qid = r.json()["id"]
    total = float(r.json()["total"])

    override = "2024-04-05T09:15:00+00:00"
    partial = round(total / 2, 2)
    r2 = requests.post(
        f"{API}/quotes/{qid}/record-payment", headers=admin_h,
        json={"amount": partial, "paid_at": override},
        timeout=20,
    )
    # 200 — silent deferral, NOT a 400.
    assert r2.status_code == 200, r2.text

    stored = dbc.quotes.find_one(
        {"id": qid, "tenant_id": aquaterra_id}, {"_id": 0},
    )
    # partial-payment must NOT stamp paid_at at all (matches
    # pre-Task-H0 behaviour). The override drops silently.
    assert stored["payment_status"] == "partial"
    assert stored.get("paid_at") in (None, ""), stored.get("paid_at")
    assert "paid_at_override_by" not in stored
    assert "paid_at_override_at" not in stored


# ── 10) Record-payment: future paid_at rejected ────────────────
def test_future_paid_at_rejected(admin_h, h0_customer_id):
    r = requests.post(
        f"{API}/quotes", headers=admin_h,
        json={**_make_quote_payload(h0_customer_id), "doc_type": "invoice"},
        timeout=20,
    )
    assert r.status_code == 200
    qid = r.json()["id"]
    total = float(r.json()["total"])

    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r2 = requests.post(
        f"{API}/quotes/{qid}/record-payment", headers=admin_h,
        json={"amount": total, "paid_at": future},
        timeout=20,
    )
    assert r2.status_code == 400, r2.text
    detail = r2.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error") == "future_date_not_allowed", detail
        assert detail.get("field") == "paid_at", detail
    else:
        assert "future" in str(detail).lower()

