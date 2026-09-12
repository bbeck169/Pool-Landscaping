"""Feb-2026 · Quote hard-delete — RBAC + invariants tests.

Locks the Feb-2026 hard-delete contract on
``DELETE /api/quotes/{qid}?hard=true``:

  1a — admin + super_admin both allowed
  2b — quote-owned inline subdocs cascade with the doc;
        ledger rows (``communication_sends``, ``outbound_emails``,
        ``marketing_deliveries``, ``audit_logs``) DO NOT cascade
  3a — refuse (409) only when the quote has been converted to an
        invoice via the auto-invoice pipeline
        (quote.scheduled_job_id == invoice.job_id)
  5  — NO ``audit_logs`` row emitted (zero-trace hard-delete)

Backwards-compat: the default DELETE call (no ``?hard=true``) still
soft-deletes via ``_perform_soft_delete_quote``.
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
def super_sess():
    return _session("super@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def customer_sess():
    return _session("customer@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    """Optional — skips if no technician demo user exists."""
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
def svc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/service-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/income-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


def _make_quote(sess, customer_id, svc_cat, inc_cat, title=None):
    body = {
        "customer_id": customer_id,
        "title": title or f"HardDel probe {uuid.uuid4().hex[:6]}",
        "doc_type": "quote",
        "line_items": [
            {"description": "Item A", "quantity": 2, "unit_price": 50,
             "service_category_id": svc_cat["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    r = sess.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _quote_still_present(sess, qid) -> bool:
    r = sess.get(f"{BASE_URL}/api/quotes/{qid}", timeout=REQ_TIMEOUT)
    return r.status_code == 200


# ═════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════

def test_admin_can_hard_delete_orphan_quote(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    r = admin_sess.delete(
        f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("hard_deleted") is True
    assert body.get("quote_id") == doc["id"]
    # Doc is gone — subsequent GET returns 404.
    g = admin_sess.get(
        f"{BASE_URL}/api/quotes/{doc['id']}", timeout=REQ_TIMEOUT,
    )
    assert g.status_code == 404


def test_super_admin_can_hard_delete_orphan_quote(
    super_sess, customer_id, svc_cat, inc_cat, admin_sess,
):
    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    r = super_sess.delete(
        f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200
    assert r.json().get("hard_deleted") is True


def test_non_admin_role_gets_403(
    tech_sess, admin_sess, customer_id, svc_cat, inc_cat,
):
    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    try:
        r = tech_sess.delete(
            f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 403, r.text
        # Quote must still be present.
        assert _quote_still_present(admin_sess, doc["id"])
    finally:
        # cleanup as admin
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )


def test_customer_role_gets_403_or_404(
    customer_sess, admin_sess, customer_id, svc_cat, inc_cat,
):
    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    try:
        r = customer_sess.delete(
            f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code in (403, 404), r.text
        assert _quote_still_present(admin_sess, doc["id"])
    finally:
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{doc['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )


# ═════════════════════════════════════════════════════════════════════
# Protection — invoice-conversion 409
# ═════════════════════════════════════════════════════════════════════

def test_hard_delete_refuses_when_quote_converted_to_invoice(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    """Directly stamp a matching invoice on ``db.quotes`` with
    ``job_id == quote.scheduled_job_id`` so the indirect-link check
    fires. Uses the same detection path production traffic uses.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = doc["id"]
    tid = doc["tenant_id"]
    job_id = "hd_probe_job_" + uuid.uuid4().hex[:8]
    invoice_id = "hd_probe_inv_" + uuid.uuid4().hex[:8]

    async def _seed_link():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        # Stamp the quote's scheduled_job_id and insert a matching
        # invoice pointing to that job.
        await d.quotes.update_one(
            {"id": qid}, {"$set": {"scheduled_job_id": job_id}},
        )
        await d.quotes.insert_one({
            "id": invoice_id, "tenant_id": tid,
            "doc_type": "invoice",
            "job_id": job_id,
            "customer_id": doc.get("customer_id"),
            "total": 100.0, "status": "issued",
        })
        client.close()

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        await d.quotes.delete_one({"id": invoice_id})
        client.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_seed_link())
        r = admin_sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 409, r.text
        detail = r.json().get("detail") or ""
        assert "converted to an invoice" in detail, detail
        assert "Delete the invoice first" in detail
        # Quote MUST still be present after the failed hard-delete.
        assert _quote_still_present(admin_sess, qid)
    finally:
        loop.run_until_complete(_cleanup())
        loop.close()
        # Best-effort cleanup of the probe quote (unlink and hard-del).
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true",
            timeout=REQ_TIMEOUT,
        )


# ═════════════════════════════════════════════════════════════════════
# Cascade + ledger preservation invariants
# ═════════════════════════════════════════════════════════════════════

def test_hard_delete_removes_inline_subdocs(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    """Quote with rich inline subdocs (line_items + signatures +
    terms + drafts) — hard-delete removes the WHOLE graph in one shot.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = doc["id"]

    async def _stamp_subdocs():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        await d.quotes.update_one(
            {"id": qid},
            {"$set": {
                "signatures": [{"signer": "cust", "signed_at": "2026-02-10"}],
                "terms": "Payment due on receipt.",
                "customer_group_descriptions": {"svc": "Weekly"},
            }},
        )
        client.close()

    async def _still_there_anywhere():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        # Anything left on ``db.quotes`` referencing this qid?
        remnant = await d.quotes.find_one({"id": qid}, {"_id": 0, "id": 1})
        client.close()
        return remnant

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_stamp_subdocs())
        r = admin_sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200
        remnant = loop.run_until_complete(_still_there_anywhere())
        assert remnant is None, f"quote doc still present: {remnant}"
    finally:
        loop.close()


def test_hard_delete_does_not_touch_ledger_rows(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    """Seed a ``communication_sends`` row with the quote_id, then
    hard-delete the quote. The ledger row MUST still exist with the
    same ``quote_id`` after the hard-delete (accepted compliance
    trade-off per user directive #2b).
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = doc["id"]
    tid = doc["tenant_id"]
    comm_id = "hd_probe_comm_" + uuid.uuid4().hex[:8]

    async def _seed_comm():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        await d.communication_sends.insert_one({
            "id": comm_id, "tenant_id": tid,
            "quote_id": qid,
            "channel": "email", "status": "delivered",
        })
        client.close()

    async def _read_comm():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        row = await d.communication_sends.find_one({"id": comm_id},
                                                       {"_id": 0})
        # Cleanup while we're here.
        await d.communication_sends.delete_one({"id": comm_id})
        client.close()
        return row

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_seed_comm())
        r = admin_sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true",
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200
        row = loop.run_until_complete(_read_comm())
        assert row is not None, (
            "communication_sends row was cascade-deleted — user "
            "directive #2b (ledger preservation) violated"
        )
        assert row.get("quote_id") == qid, (
            "communication_sends.quote_id was mutated by hard-delete"
        )
    finally:
        loop.close()


# ═════════════════════════════════════════════════════════════════════
# Zero-audit-trail invariant (#5)
# ═════════════════════════════════════════════════════════════════════

def test_hard_delete_emits_no_audit_row(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    import asyncio
    import re as _re
    from motor.motor_asyncio import AsyncIOMotorClient

    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = doc["id"]
    tid = doc["tenant_id"]

    r = admin_sess.delete(
        f"{BASE_URL}/api/quotes/{qid}?hard=true",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200

    async def _audit_count():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        # Check BOTH audit surfaces referenced elsewhere in the
        # codebase (legacy ``audit_log`` + Feb-2026 richer
        # ``deletion_audit``) so a future audit-write drift can't
        # sneak past this guard.
        count_audit = await d.audit_logs.count_documents({
            "tenant_id": tid,
            "event": _re.compile("quotes.hard_delete"),
        })
        count_audit_legacy = await d.audit_log.count_documents({
            "tenant_id": tid,
            "event": _re.compile("quotes.hard_delete"),
        })
        count_deletion = await d.deletion_audit.count_documents({
            "tenant_id": tid,
            "entity_id": qid,
        })
        client.close()
        return count_audit, count_audit_legacy, count_deletion

    loop = asyncio.new_event_loop()
    try:
        c1, c2, c3 = loop.run_until_complete(_audit_count())
        assert c1 == 0, (
            f"expected zero audit_logs rows for hard-delete, got {c1}"
        )
        assert c2 == 0, (
            f"expected zero legacy audit_log rows, got {c2}"
        )
        assert c3 == 0, (
            f"expected zero deletion_audit rows (user directive #5 — "
            f"no trace), got {c3}"
        )
    finally:
        loop.close()


# ═════════════════════════════════════════════════════════════════════
# Not-found + soft-delete regression
# ═════════════════════════════════════════════════════════════════════

def test_hard_delete_returns_404_for_nonexistent_quote(admin_sess):
    r = admin_sess.delete(
        f"{BASE_URL}/api/quotes/{uuid.uuid4().hex}?hard=true",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404


def test_soft_delete_still_works_regression(
    admin_sess, customer_id, svc_cat, inc_cat,
):
    """No ``?hard=true`` → falls through to the legacy soft-delete
    path. Doc stays in ``db.quotes`` but stamped with ``deleted_at``.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    doc = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = doc["id"]

    r = admin_sess.delete(
        f"{BASE_URL}/api/quotes/{qid}", timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200

    async def _lookup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = client[os.environ["DB_NAME"]]
        row = await d.quotes.find_one({"id": qid},
                                          {"_id": 0, "deleted_at": 1})
        # Clean up as hard-delete after the assertion.
        await d.quotes.delete_one({"id": qid})
        client.close()
        return row

    loop = asyncio.new_event_loop()
    try:
        row = loop.run_until_complete(_lookup())
        assert row is not None, "doc missing after soft-delete"
        assert row.get("deleted_at"), (
            "soft-delete didn't stamp ``deleted_at`` — regression"
        )
    finally:
        loop.close()
