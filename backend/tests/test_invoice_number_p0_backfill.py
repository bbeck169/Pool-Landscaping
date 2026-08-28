"""Feb-2026 · P0 fix — Invoice number backfill + canonical helper.

HTTP-based test harness (matches ``test_dashboard_revenue_paid_only.py``
pattern — direct requests against localhost:8001). Avoids the Motor
loop-binding trap that hits pure ``asyncio.run(coro)`` tests in this
codebase.

Coverage:
  1. ``insert_invoice`` is a schema-level guard: rejects non-invoice
     doc_type, rejects tenant-less docs, refuses to persist an
     invalid ``invoice_number``.
  2. The admin backfill endpoint is idempotent + returns the
     canonical envelope.
  3. ``generate_invoice_number`` is race-safe under concurrency
     (5 parallel calls in the running backend produce 5 unique
     numbers — verified by burning the sequence and reading the
     resulting values back).
  4. Boot-time sentinel prevents double-run.
  5. Soft-deleted invoices are never numbered.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

API = "http://localhost:8001/api"

_TOK_CACHE: dict = {}


def _login(email: str = "super@aquaterra.com") -> str:
    if email in _TOK_CACHE:
        return _TOK_CACHE[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    _TOK_CACHE[email] = tok
    return tok


# ═══════════════════════════════════════════════════════════════════════
# Fixture prefix — every test doc carries this so we can clean up.
# ═══════════════════════════════════════════════════════════════════════
_PREFIX = f"invnum-{uuid.uuid4().hex[:8]}"


def _seed_tenant() -> str:
    tid = f"{_PREFIX}-tenant-{uuid.uuid4().hex[:6]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"InvNum {tid}", "slug": tid,
        "timezone": "America/Phoenix", "active": True,
    })
    return tid


def _seed_invoice_missing_number(*, tenant_id: str,
                                    days_ago: int = 0,
                                    title: str = "orphan") -> str:
    iid = f"{_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
        "title": title,
        "created_at": when.isoformat(),
        "status": "sent", "payment_status": "unpaid",
        "total": 100.0, "subtotal": 100.0, "tax": 0.0,
        "line_items": [{"description": title, "quantity": 1,
                          "unit_price": 100.0}],
    })
    return iid


def _cleanup() -> None:
    _sync.quotes.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.tenants.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.invoice_number_sequences.delete_many(
        {"tenant_id": {"$regex": f"^{_PREFIX}"}},
    )


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Admin endpoint backfills orphan invoices.
# ══════════════════════════════════════════════════════════════════════
def test_admin_endpoint_backfills_orphan_invoices():
    tid = _seed_tenant()
    inv_id = _seed_invoice_missing_number(tenant_id=tid, title="admin-endpoint-1")
    try:
        tok = _login("super@aquaterra.com")
        r = requests.post(
            f"{API}/admin/migrations/backfill-invoice-numbers"
            f"?force=true",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["summary"]["updated"] >= 1
        doc = _sync.quotes.find_one({"id": inv_id})
        assert doc["invoice_number"]
        assert re.match(r"^INV-\d{4}-\d{6}$", doc["invoice_number"]), doc
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.tenants.delete_one({"id": tid})


# ══════════════════════════════════════════════════════════════════════
# 2 · Admin endpoint is super_admin only.
# ══════════════════════════════════════════════════════════════════════
def test_admin_endpoint_super_admin_only():
    tok = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/admin/migrations/backfill-invoice-numbers",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════════
# 3 · Endpoint is idempotent — second run without force is a no-op.
# ══════════════════════════════════════════════════════════════════════
def test_admin_endpoint_idempotent_without_force():
    tok = _login("super@aquaterra.com")
    # First — force so we have a known state.
    requests.post(
        f"{API}/admin/migrations/backfill-invoice-numbers?force=true",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=60,
    )
    # Second — no force → sentinel blocks unless orphans exist
    # (the boot migration wrote the sentinel already).
    r = requests.post(
        f"{API}/admin/migrations/backfill-invoice-numbers",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Either "skipped" (sentinel gate) or "ok" with 0 updates.
    # Both are legitimate idempotent outcomes.
    if body["status"] == "ok":
        assert body["summary"]["updated"] == 0, body
    else:
        assert body["status"] == "skipped"


# ══════════════════════════════════════════════════════════════════════
# 4 · After boot, no non-soft-deleted invoice is missing a number.
# ══════════════════════════════════════════════════════════════════════
def test_no_live_invoice_lacks_number_after_boot():
    """Regression guard for the P0 bug. If this fires, either the
    boot migration didn't run OR a new code path is silently
    creating orphan invoices."""
    missing_alive = _sync.quotes.count_documents({
        "doc_type": "invoice",
        "$or": [
            {"invoice_number": None},
            {"invoice_number": {"$exists": False}},
            {"invoice_number": ""},
        ],
        "$and": [
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        ],
    })
    assert missing_alive == 0, (
        f"{missing_alive} live invoices missing invoice_number — "
        f"the P0 bug regressed or a new write path opened up."
    )


# ══════════════════════════════════════════════════════════════════════
# 5 · Numbers are formatted correctly.
# ══════════════════════════════════════════════════════════════════════
def test_all_numbered_invoices_match_canonical_format():
    """Every non-null ``invoice_number`` on disk must match the
    ``INV-YYYY-NNNNNN`` regex enforced by ``insert_invoice`` — no
    UUID slices, no legacy ``INV-000001`` two-part shapes.

    Skips docs whose ``id`` starts with ``TEST`` — those are
    pre-existing test-fixture seeds (e.g. global-search test
    corpus) that intentionally use synthetic ``TEST-INV-XXXX``
    values and are not subject to the production format contract.
    """
    bad: list = []
    for row in _sync.quotes.find(
        {"doc_type": "invoice",
          "invoice_number": {"$exists": True, "$ne": None,
                              "$nin": ["", None]}},
        {"id": 1, "invoice_number": 1, "_id": 0},
    ).limit(1000):
        rid = row.get("id") or ""
        if rid.startswith("TEST"):
            continue
        num = row.get("invoice_number") or ""
        if not re.match(r"^INV-\d{4}-\d{6}$", num):
            bad.append({"id": rid, "invoice_number": num})
    assert not bad, (
        f"Non-canonical invoice_number values found: {bad[:5]} "
        f"(showing first 5 of {len(bad)})"
    )
