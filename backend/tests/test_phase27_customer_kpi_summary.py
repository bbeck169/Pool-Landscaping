"""Phase 27 · Feb-2026 — admin customer KPI summary endpoint tests.

Covers the new ``GET /customers/{cid}/kpi-summary`` endpoint that
powers the admin CustomerDetail dark-navy KPI tile grid.

Scenarios:
  1. Happy path — endpoint returns all six integer fields.
  2. Balance / past-due aggregation — one past-due unpaid invoice +
     one future-dated unpaid invoice + one paid invoice.  Totals
     match the balance / past-due slices.
  3. Overdue count matches the number of past-due open invoices.
  4. Pending estimates — one draft quote + one sent quote + one
     accepted quote.  Only the two pending ones count.
  5. Unread messages — one inbound unread + one inbound read + one
     outbound.  Only the inbound-unread counts.
  6. Credit cents — stored in ``customer_credits_balance``.  Mirror
     of the ``/customers/{cid}/credits`` endpoint value.
  7. Admin-role gate — technician role gets 403.
  8. Tenant isolation — tenant A's call sees ONLY tenant A's data,
     even if cid collides with a tenant B row.
  9. 404 on missing / cross-tenant customer.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _tenant_id() -> str:
    return f"test-phase27-{uuid.uuid4()}"


# ─── Happy path · all six fields present ──────────────────────────
def test_kpi_summary_returns_all_six_fields():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            # Pseudo-admin — the FastAPI handler reads ``user.role``;
            # we invoke the module function directly here.
            from routers.customers import get_customer_kpi_summary
            res = await get_customer_kpi_summary(
                cid=cid,
                user={"role": "admin", "id": "u-admin"},
                tenant={"id": tid},
            )
            for k in (
                "balance_due_cents", "past_due_cents", "credit_cents",
                "overdue_count", "pending_estimates_count",
                "unread_messages_count",
            ):
                assert k in res, f"missing field {k!r}"
                assert isinstance(res[k], int), (
                    f"{k} must be int, got {type(res[k]).__name__}")
            assert res["customer_id"] == cid
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})
            await db.messages.delete_many({"tenant_id": tid})
            await db.customer_credits_balance.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Balance + past-due aggregation ───────────────────────────────
def test_kpi_summary_balance_and_past_due_math():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            # Past-due unpaid — $200 total, $0 paid → $200 past-due.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "invoice",
                "payment_status": "unpaid", "status": "overdue",
                "due_date": "2020-01-01",  # firmly in the past
                "total": 200.00, "amount_paid": 0,
            })
            # Future-dated unpaid — $50 total, $0 paid → $50
            # balance_due but NOT past-due.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "invoice",
                "payment_status": "unpaid", "status": "sent",
                "due_date": "2099-01-01",
                "total": 50.00, "amount_paid": 0,
            })
            # Paid — should be excluded from both tallies.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "invoice",
                "payment_status": "paid", "status": "paid",
                "due_date": "2020-01-01",
                "total": 999.00, "amount_paid": 999.00,
            })
            # Partial payment, past-due — $100 total, $40 paid →
            # $60 balance, $60 past-due.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "invoice",
                "payment_status": "partial", "status": "overdue",
                "due_date": "2020-01-01",
                "total": 100.00, "amount_paid": 40.00,
            })

            from routers.customers import get_customer_kpi_summary
            res = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid})

            # $200 + $50 + $60 = $310 open → 31000 cents.
            assert res["balance_due_cents"] == 31000, res
            # $200 + $60 past-due = $260 → 26000 cents.
            assert res["past_due_cents"] == 26000, res
            # Two past-due open invoices.
            assert res["overdue_count"] == 2, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Pending estimates count ──────────────────────────────────────
def test_kpi_summary_pending_estimates_count():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            # Draft quote — counts.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "quote",
                "status": "draft",
            })
            # Sent quote — counts.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "quote",
                "status": "sent",
            })
            # Accepted quote — does NOT count.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "quote",
                "status": "accepted",
            })
            # Invoice — not an estimate, does NOT count.
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "doc_type": "invoice",
                "status": "draft",
            })

            from routers.customers import get_customer_kpi_summary
            res = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid})
            assert res["pending_estimates_count"] == 2, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Unread messages count ────────────────────────────────────────
def test_kpi_summary_unread_messages_count():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            # Inbound unread — counts.
            await db.messages.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "sender": "customer",
                "text": "Hi — need help", "read_by_staff": False,
            })
            # Inbound where field is absent — still counts
            # (the $or branch allows this).
            await db.messages.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "sender": "customer",
                "text": "legacy row — no read_by_staff key",
            })
            # Inbound read — does NOT count.
            await db.messages.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "sender": "customer",
                "text": "already seen", "read_by_staff": True,
            })
            # Outbound (staff → customer) — does NOT count.
            await db.messages.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "customer_id": cid, "sender": "staff",
                "text": "staff reply",
            })

            from routers.customers import get_customer_kpi_summary
            res = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid})
            assert res["unread_messages_count"] == 2, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.messages.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Credit cents mirrors the credits endpoint ────────────────────
def test_kpi_summary_credit_cents_mirror():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            await db.customer_credits_balance.insert_one({
                "tenant_id": tid, "customer_id": cid,
                "balance_cents": 2550,  # $25.50
            })

            from routers.customers import get_customer_kpi_summary
            res = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid})
            assert res["credit_cents"] == 2550, res
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.customer_credits_balance.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Role gate — technician blocked ───────────────────────────────
def test_kpi_summary_blocks_non_admin_roles():
    tid = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Phase 27 Cust",
            })
            from routers.customers import get_customer_kpi_summary
            from fastapi import HTTPException
            for bad_role in ("technician", "customer", ""):
                try:
                    await get_customer_kpi_summary(
                        cid=cid,
                        user={"role": bad_role},
                        tenant={"id": tid},
                    )
                    raise AssertionError(
                        f"expected HTTP 403 for role={bad_role!r}")
                except HTTPException as exc:
                    assert exc.status_code == 403, (
                        f"role={bad_role!r} got {exc.status_code}")
        finally:
            await db.customers.delete_many({"tenant_id": tid})

    run_test(_setup_and_run)


# ─── Tenant isolation ─────────────────────────────────────────────
def test_kpi_summary_tenant_isolation():
    tid_a = _tenant_id()
    tid_b = _tenant_id()
    cid = str(uuid.uuid4())

    async def _setup_and_run(db):
        try:
            # Same cid in both tenants.  Tenant B has an open
            # invoice; tenant A has none.  Query from tenant A
            # must NOT see tenant B's data.
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid_a, "name": "A"})
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid_b, "name": "B"})
            await db.quotes.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tid_b,
                "customer_id": cid, "doc_type": "invoice",
                "payment_status": "unpaid", "status": "sent",
                "due_date": "2099-01-01",
                "total": 777.00, "amount_paid": 0,
            })

            from routers.customers import get_customer_kpi_summary
            res_a = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid_a})
            assert res_a["balance_due_cents"] == 0, res_a
            res_b = await get_customer_kpi_summary(
                cid=cid, user={"role": "admin"}, tenant={"id": tid_b})
            assert res_b["balance_due_cents"] == 77700, res_b
        finally:
            await db.customers.delete_many(
                {"tenant_id": {"$in": [tid_a, tid_b]}})
            await db.quotes.delete_many(
                {"tenant_id": {"$in": [tid_a, tid_b]}})

    run_test(_setup_and_run)


# ─── 404 on missing / cross-tenant customer ──────────────────────
def test_kpi_summary_404_on_missing_customer():
    tid = _tenant_id()

    async def _setup_and_run(db):
        from routers.customers import get_customer_kpi_summary
        from fastapi import HTTPException
        try:
            await get_customer_kpi_summary(
                cid="never-existed",
                user={"role": "admin"},
                tenant={"id": tid},
            )
            raise AssertionError("expected HTTP 404")
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code

    run_test(_setup_and_run)
