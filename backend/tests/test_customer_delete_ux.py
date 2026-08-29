"""Feb-2026 · Customer Delete UX overhaul — empirical proof suite.

Covers the 5 empirical proofs listed in the audit decision:
  (i)   DELETE ?mode=hard with an unpaid-invoice customer returns
        409 with the invoice ids in the body.
  (ii)  DELETE ?mode=hard with a clean customer returns 200 + a
        deletion_audit row is present carrying the full pre-delete
        snapshot (with ``password_hash`` scrubbed).
  (iii) POST-hard-delete, GET /jobs?... for jobs belonging to that
        customer_id returns 200 (not 500) and the orphan rows carry
        their snapshotted ``customer_name`` for the frontend to
        render "Unknown Customer" via ``formatCustomerName()``.
  (iv)  Admin (not super_admin) can call PATCH /customers/{cid}/
        restore after the role gate widening.
  (v)   ?status=inactive URL lands CustomersList on the Inactive
        tab — this proof is in the Vitest spec
        ``customer-delete-status-alias.test.jsx``.

Additional locks:
  * mode=bogus → 400 invalid_mode.
  * mode=soft is idempotent (re-run returns 200 already_deleted=true).
  * Single-row soft-delete writes ``audit_logs.customer.soft_delete``
    matching the bulk-soft-delete path (symmetry).
  * Hard-delete does NOT cascade into jobs / quotes /
    service_reports / recurring_job_templates.
  * ``deletion_audit.write_deletion_audit_entry`` now accepts
    ``resource_type="customer"``.
  * ``POST /customers/bulk`` action=delete emits a WARN and adds
    ``deprecated_until`` + ``use_instead`` to the response.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


# ═════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ═════════════════════════════════════════════════════════════════════
def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed_tenant():
    from utils import hash_password
    tid = f"TEST-cdel-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid, "slug": f"test-cdel-{uuid.uuid4().hex[:6]}",
        "name": "TEST_cdel", "active": True,
    })
    admin_email = f"cdel-admin-{uuid.uuid4().hex[:6]}@example.com"
    admin_uid = f"TEST-cdel-a-{uuid.uuid4().hex[:6]}"
    _db.users.insert_one({
        "id": admin_uid, "tenant_id": tid, "email": admin_email,
        "name": "TEST_cdel_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return tid, admin_uid, admin_email


def _seed_customer(tid: str, name: str = "TEST_cdel_cust") -> str:
    cid = f"TEST-cdel-c-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "email": f"{cid}@example.com", "phone": "+15551234567",
        "address": "123 Main St", "is_active": True,
        # Sensitive field that MUST be scrubbed from the audit snapshot.
        "password_hash": "$SCRUB_ME$fake-bcrypt-value$",
    })
    return cid


def _seed_invoice(tid: str, cid: str, *, paid: bool) -> str:
    iid = f"TEST-cdel-inv-{uuid.uuid4().hex[:6]}"
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "TEST_cdel_cust",   # snapshot survives hard-delete
        "doc_type": "invoice",
        "title": "Test invoice",
        "total": 100.00,
        "amount_paid": 100.00 if paid else 0.0,
        "payment_status": "paid" if paid else "unpaid",
        "line_items": [{"description": "X", "quantity": 1, "unit_price": 100.0}],
        "created_at": "2026-02-01T00:00:00Z",
    })
    return iid


def _seed_job(tid: str, cid: str, snapshot_name: str = "TEST_cdel_cust") -> str:
    jid = f"TEST-cdel-job-{uuid.uuid4().hex[:6]}"
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "customer_name": snapshot_name,
        "title": "Test job", "status": "scheduled",
        "created_at": "2026-02-01T00:00:00Z",
    })
    return jid


def _seed_recurring_template(tid: str, cid: str) -> str:
    rid = f"TEST-cdel-rjt-{uuid.uuid4().hex[:6]}"
    _db.recurring_job_templates.insert_one({
        "id": rid, "tenant_id": tid, "customer_id": cid,
        "service_type": "pool_service", "frequency": "weekly",
        "active": True, "created_at": "2026-02-01T00:00:00Z",
    })
    return rid


def _seed_service_report(tid: str, cid: str, jid: str) -> str:
    srid = f"TEST-cdel-sr-{uuid.uuid4().hex[:6]}"
    _db.service_reports.insert_one({
        "id": srid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "TEST_cdel_cust",
        "job_id": jid, "created_at": "2026-02-01T00:00:00Z",
    })
    return srid


def _cleanup(tid: str, admin_uid: str):
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_one({"id": tid})
    _db.customers.delete_many({"tenant_id": tid})
    _db.quotes.delete_many({"tenant_id": tid})
    _db.jobs.delete_many({"tenant_id": tid})
    _db.service_reports.delete_many({"tenant_id": tid})
    _db.recurring_job_templates.delete_many({"tenant_id": tid})
    _db.deletion_audit.delete_many({"tenant_id": tid})
    _db.audit_logs.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# Empirical proof (i) — hard-delete with unpaid invoice → 409
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_unpaid_invoice_returns_409_with_invoice_ids():
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    inv1 = _seed_invoice(tid, cid, paid=False)
    inv2 = _seed_invoice(tid, cid, paid=False)
    # Add a paid invoice too — it MUST NOT appear in the block list.
    inv_paid = _seed_invoice(tid, cid, paid=True)
    try:
        tok = _login(email)
        r = requests.delete(
            f"{API}/customers/{cid}?mode=hard",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 409, r.text
        body = r.json()["detail"]
        assert body["detail"] == "customer_has_unpaid_invoices"
        assert body["invoice_count"] == 2
        blocking = set(body["invoice_ids"])
        assert blocking == {inv1, inv2}, blocking
        assert inv_paid not in blocking
        # First-N summary shape.
        assert isinstance(body.get("invoices"), list)
        assert len(body["invoices"]) == 2
        for row in body["invoices"]:
            assert set(row.keys()) >= {"id", "invoice_number", "title",
                                       "total", "payment_status"}
        # Customer row still exists (nothing destructive on 409).
        assert _db.customers.count_documents({"id": cid}) == 1
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# Empirical proof (ii) — hard-delete of clean customer → 200 + audit
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_clean_customer_writes_deletion_audit_with_snapshot():
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    _seed_invoice(tid, cid, paid=True)          # paid → not blocking
    try:
        tok = _login(email)
        r = requests.delete(
            f"{API}/customers/{cid}?mode=hard",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["mode"] == "hard"
        assert body["customer_id"] == cid
        assert body.get("deleted_at")

        # Customer row is gone.
        assert _db.customers.count_documents({"id": cid}) == 0

        # deletion_audit row present with full snapshot.
        audit = _db.deletion_audit.find_one(
            {"tenant_id": tid, "resource_type": "customer",
             "resource_id": cid},
            {"_id": 0},
        )
        assert audit is not None, "expected deletion_audit row"
        assert audit["action"] == "delete"
        assert audit["cascade_deleted_ids"] == []
        snap = audit["snapshot"]
        assert snap["id"] == cid
        assert snap["name"] == "TEST_cdel_cust"
        assert snap["email"] == f"{cid}@example.com"
        assert snap["phone"] == "+15551234567"
        assert snap["address"] == "123 Main St"
        # Sensitive scrub.
        assert "password_hash" not in snap, \
            f"password_hash leaked into snapshot: {snap}"
        assert "password_reset_token" not in snap

        # audit_logs symmetric row.
        legacy = _db.audit_logs.find_one(
            {"tenant_id": tid, "event": "customer.hard_delete",
             "customer_id": cid},
            {"_id": 0},
        )
        assert legacy is not None, "expected audit_logs.customer.hard_delete row"
        assert legacy["actor_email"] == email
        assert legacy["customer_snapshot_name"] == "TEST_cdel_cust"
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# Empirical proof (iii) — no-cascade + orphan jobs still readable
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_does_not_cascade_and_orphan_jobs_still_read_ok():
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    jid = _seed_job(tid, cid)
    sr = _seed_service_report(tid, cid, jid)
    rjt = _seed_recurring_template(tid, cid)
    inv_paid = _seed_invoice(tid, cid, paid=True)
    try:
        tok = _login(email)
        # Hard-delete succeeds (no unpaid invoices).
        r = requests.delete(
            f"{API}/customers/{cid}?mode=hard",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text

        # Sibling collections UNCHANGED — the explicit no-cascade contract.
        assert _db.customers.count_documents({"id": cid}) == 0
        assert _db.jobs.count_documents({"id": jid}) == 1
        assert _db.service_reports.count_documents({"id": sr}) == 1
        assert _db.recurring_job_templates.count_documents({"id": rjt}) == 1
        assert _db.quotes.count_documents({"id": inv_paid}) == 1

        # Orphan snapshot survives — jobs list still readable.
        r2 = requests.get(f"{API}/jobs",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r2.status_code == 200, r2.text
        rows = [j for j in r2.json() if j.get("id") == jid]
        assert rows, "expected orphan job to still be listable"
        # Snapshot name intact for the frontend formatCustomerName()
        # helper to render (no "Unknown Customer" needed).
        assert rows[0].get("customer_name") == "TEST_cdel_cust"
        # The orphan carries the dangling customer_id — the frontend
        # will render "Unknown Customer" only when the snapshot is
        # ALSO missing (rare / legacy rows). Locked here so we notice
        # any accidental snapshot-scrub in a future refactor.
        assert rows[0].get("customer_id") == cid
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# Empirical proof (iv) — admin (not super_admin) can restore
# ═════════════════════════════════════════════════════════════════════
def test_admin_role_can_restore_soft_deleted_customer():
    tid, uid, email = _seed_tenant()                # role=admin
    cid = _seed_customer(tid)
    try:
        tok = _login(email)
        # Step 1 — soft-delete via ?mode=soft.
        r1 = requests.delete(
            f"{API}/customers/{cid}?mode=soft",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["mode"] == "soft"
        assert body.get("deleted_at")
        # Symmetric audit_logs entry.
        soft_audit = _db.audit_logs.find_one(
            {"tenant_id": tid, "event": "customer.soft_delete",
             "customer_id": cid},
            {"_id": 0},
        )
        assert soft_audit is not None, \
            "expected single-row soft-delete to write customer.soft_delete"

        # Step 2 — same admin token calls restore. Pre-Feb-2026 this
        # returned 403 (super_admin only); post-widening it must 200.
        r2 = requests.patch(
            f"{API}/customers/{cid}/restore",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["restored"] is True
        # Row is live again.
        fresh = _db.customers.find_one({"id": cid}, {"_id": 0})
        assert fresh is not None
        assert "deleted_at" not in fresh or fresh["deleted_at"] in (None, "")
        # audit_logs.customer_restore stamped by the P26 handler.
        rest_audit = _db.audit_logs.find_one(
            {"tenant_id": tid, "event": "customer_restore",
             "customer_id": cid},
            {"_id": 0},
        )
        assert rest_audit is not None
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# Soft-delete idempotency
# ═════════════════════════════════════════════════════════════════════
def test_soft_delete_is_idempotent():
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    try:
        tok = _login(email)
        h = {"Authorization": f"Bearer {tok}"}
        r1 = requests.delete(f"{API}/customers/{cid}?mode=soft",
                             headers=h, timeout=15)
        assert r1.status_code == 200
        assert r1.json().get("already_deleted") in (None, False)
        r2 = requests.delete(f"{API}/customers/{cid}?mode=soft",
                             headers=h, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["already_deleted"] is True
        # Only ONE audit row for the first soft-delete (idempotent
        # second call MUST NOT double-write).
        n = _db.audit_logs.count_documents(
            {"tenant_id": tid, "event": "customer.soft_delete",
             "customer_id": cid},
        )
        assert n == 1, f"expected 1 soft-delete audit row, got {n}"
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# Invalid mode → 400
# ═════════════════════════════════════════════════════════════════════
def test_invalid_mode_returns_400():
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    try:
        tok = _login(email)
        r = requests.delete(
            f"{API}/customers/{cid}?mode=bogus",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["detail"] == "invalid_mode"
        assert r.json()["detail"]["received"] == "bogus"
        # Customer untouched.
        assert _db.customers.count_documents({"id": cid}) == 1
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# deletion_audit.write_deletion_audit_entry accepts "customer"
# ═════════════════════════════════════════════════════════════════════
def test_deletion_audit_writer_accepts_customer_resource_type():
    """Direct unit-ish call to the writer to lock the schema
    extension. Ensures a future refactor doesn't drop the
    ``"customer"`` branch and silently start rejecting hard-delete
    audit writes.

    We exercise the writer through the live endpoint (a real hard-
    delete) rather than calling the async function directly — the
    motor client is bound to the running FastAPI event loop, so
    invoking ``write_deletion_audit_entry`` from a fresh Pytest loop
    hits a cross-loop Future error. The end-to-end call in
    ``test_hard_delete_clean_customer_writes_deletion_audit_with_snapshot``
    already verifies the row lands correctly; this test locks the
    ``ValueError`` guard on unsupported resource types too.
    """
    import asyncio
    from routers.deletion_audit import write_deletion_audit_entry

    # Positive-path is covered end-to-end by the hard-delete test.
    # Here we lock the negative-path: bogus resource_type raises.
    async def _bogus():
        await write_deletion_audit_entry(
            tenant_id="TEST-cdel-neg", resource_type="banana",
            resource_id="x", user={"id": "u"}, snapshot={},
        )

    raised = False
    try:
        asyncio.new_event_loop().run_until_complete(_bogus())
    except ValueError as exc:
        raised = True
        assert "banana" in str(exc)
    assert raised, "expected ValueError for unsupported resource_type"


# ═════════════════════════════════════════════════════════════════════
# POST /customers/bulk action=delete deprecation warning
# ═════════════════════════════════════════════════════════════════════
def test_customers_bulk_action_delete_returns_deprecation_metadata():
    """Legacy bulk hard-delete keeps working for one release but the
    response must self-advertise the retirement date + the
    recommended migration target so operators + logs can trace and
    cut over. Emits a structured WARN log too (checked by log
    inspection in ops, not this test)."""
    tid, uid, email = _seed_tenant()
    cid = _seed_customer(tid)
    try:
        tok = _login(email)
        r = requests.post(
            f"{API}/customers/bulk",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            json={"ids": [cid], "action": "delete"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("deleted") == 1
        assert body.get("deprecated") is True
        assert body.get("deprecated_until") == "2026-05-01"
        assert "bulk-delete" in body.get("use_instead", "")
        # Customer was hard-deleted (this is the legacy behaviour we're
        # deprecating, not changing).
        assert _db.customers.count_documents({"id": cid}) == 0
    finally:
        _cleanup(tid, uid)
