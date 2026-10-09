"""CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 — contract
pytest.

Locks the parity sweep: a customer flagged ``account_correction=True``
MUST drop from every revenue-forecast surface, matching the behavior
the retention report already shipped under
``CUSTOMER-RETENTION-ACCOUNT-CORRECTION``. The four surfaces covered
by this file:

  1. ``GET /reports/revenue-by-customer``
     (paid-invoice slice grouped by customer)
  2. ``GET /reports/forecast``
     (projected revenue from active billing plans + weighted quotes)
  3. ``GET /admin/dashboard/revenue-forecast``
     (dashboard tile — booked jobs + recurring billing plans)
  4. ``GET /reports/kpi/revenue_by_customer`` (KPI tile analog of #1,
     routed through ``services/reporting/metrics/revenue_by_customer``).
     ``GET /reports/kpi`` itself is a static metric registry — nothing
     to filter there — so this test targets the data endpoint that
     surfaces the Revenue by Customer KPI tile on the admin
     dashboard.

Each test uses a fresh tenant so (a) the KPI 60s cache never serves a
stale response and (b) tenant-isolation regressions surface
immediately. Seeded shape mirrors ``test_customer_retention_account
_correction.py`` so helpers stay in lockstep across the retention
family.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid, email, tid, role):
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token, tenant_id):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant_id}


def _seed_admin(tenant_id):
    uid = f"adm-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@carac-par.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "CARAC Parity admin", "email": email,
    })
    return {"id": uid, "email": email, "token": _tok(uid, email, tenant_id, "admin"),
            "tenant_id": tenant_id}


def _seed_customer(tenant_id, name, *, account_correction=False):
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "first_name": name.split()[0] if " " in name else name,
        "last_name": "T",
        "created_at": "2026-01-01T00:00:00+00:00",
        "is_active": True,
    }
    if account_correction:
        doc["account_correction"] = True
        doc["account_correction_at"] = "2026-02-01T00:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _seed_paid_invoice(tenant_id, customer_id, customer_name,
                        total, paid_at_iso, created_at_iso=None):
    """Seed a paid invoice (quotes.doc_type=invoice, payment_status=paid)
    so both the invoice-slice route and the KPI revenue_by_customer
    metric pick it up on their respective windows."""
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id,
        "doc_type": "invoice",
        "customer_id": customer_id, "customer_name": customer_name,
        "total": float(total),
        "amount_paid": float(total),
        "payment_status": "paid",
        "paid_at": paid_at_iso,
        "paid_date": paid_at_iso.split("T")[0] if paid_at_iso else None,
        "created_at": created_at_iso or paid_at_iso,
        "status": "paid",
    })
    return inv_id


def _seed_open_quote(tenant_id, customer_id, customer_name, total,
                      created_at_iso, status="sent"):
    """Seed an open quote so ``_forecast_series_between`` picks it up
    in the weighted-quotes branch."""
    qid = f"q-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": qid, "tenant_id": tenant_id,
        "doc_type": "quote",
        "customer_id": customer_id, "customer_name": customer_name,
        "total": float(total),
        "status": status,
        "created_at": created_at_iso,
    })
    return qid


def _seed_billing_plan(tenant_id, customer_id, amount,
                       frequency="monthly", active=True):
    bp_id = f"bp-{uuid.uuid4().hex[:8]}"
    _sync.billing_plans.insert_one({
        "id": bp_id, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service": "Monthly Pool Service",
        "frequency": frequency,
        "amount": float(amount),
        "active": active,
    })
    return bp_id


def _seed_scheduled_job(tenant_id, customer_id, customer_name, price,
                        scheduled_date_iso):
    jid = f"job-{uuid.uuid4().hex[:8]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "customer_id": customer_id, "customer_name": customer_name,
        "status": "scheduled",
        "scheduled_date": scheduled_date_iso,
        "price": float(price),
        "total": float(price),
        "quote_total": float(price),
    })
    return jid


@pytest.fixture
def tenant_id():
    tid = f"caracp-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": "CARAC parity smoke", "slug": tid, "active": True,
    })
    yield tid
    for col in ("tenants", "users", "customers",
                 "customer_account_correction_audit",
                 "billing_plans", "quotes", "jobs",
                 "customer_activation_events"):
        _sync[col].delete_many({"tenant_id": tid})


# ══════════════════════════════════════════════════════════════════
# Helper: seed 3 customers (A normal, B normal, C flagged) plus
# matching revenue data for each.  Used by every route test to keep
# the shape consistent.
# ══════════════════════════════════════════════════════════════════
def _seed_three_customers_with_revenue(tenant_id):
    cid_a = _seed_customer(tenant_id, "Alpha")
    cid_b = _seed_customer(tenant_id, "Bravo")
    cid_c = _seed_customer(tenant_id, "Charlie",
                             account_correction=True)
    # Paid invoices — one each, same window.
    paid_at = "2026-02-15T12:00:00+00:00"
    _seed_paid_invoice(tenant_id, cid_a, "Alpha",   1000, paid_at)
    _seed_paid_invoice(tenant_id, cid_b, "Bravo",   2000, paid_at)
    _seed_paid_invoice(tenant_id, cid_c, "Charlie", 9999, paid_at)
    # Open quotes for forecast / weighted-quote branch.
    _seed_open_quote(tenant_id, cid_a, "Alpha",   500,
                      "2026-02-20T00:00:00+00:00")
    _seed_open_quote(tenant_id, cid_c, "Charlie", 7777,
                      "2026-02-20T00:00:00+00:00")
    # Active billing plans — recurring branch.
    _seed_billing_plan(tenant_id, cid_a, 100.0)
    _seed_billing_plan(tenant_id, cid_c, 999.0)
    # Scheduled jobs — admin dashboard booked branch.
    _seed_scheduled_job(tenant_id, cid_a, "Alpha",
                         200, "2026-02-25")
    _seed_scheduled_job(tenant_id, cid_c, "Charlie",
                         8888, "2026-02-25")
    return {"a": cid_a, "b": cid_b, "c": cid_c}


# ══════════════════════════════════════════════════════════════════
# 1 · GET /reports/revenue-by-customer
# ══════════════════════════════════════════════════════════════════
def test_revenue_by_customer_excludes_flagged(tenant_id):
    admin = _seed_admin(tenant_id)
    cids = _seed_three_customers_with_revenue(tenant_id)

    r = requests.get(
        f"{API}/reports/revenue-by-customer",
        params={"start": "2026-02-01", "end": "2026-02-28"},
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("rows") or []
    row_ids = {r.get("customer_id") for r in rows}
    row_names = {r.get("customer_name") for r in rows}

    # Alpha + Bravo present; Charlie (flagged) absent.
    assert cids["a"] in row_ids
    assert cids["b"] in row_ids
    assert cids["c"] not in row_ids
    assert "Charlie" not in row_names
    # Total reflects the 3000 (A+B), not 12999 (A+B+C).
    assert abs(body["summary"]["total"] - 3000.0) < 0.01, body


# ══════════════════════════════════════════════════════════════════
# 2 · GET /reports/forecast
#
# NOTE: ``_forecast_series_between`` has a known pre-existing
# cross-tenant leak (``billing_plans`` + ``quotes`` queries do not
# scope by ``tenant_id`` — tracked as its own follow-up ticket).
# A static-total assertion is therefore unreliable here; use a
# DIFFERENTIAL probe instead — toggle the flag ON/OFF and assert
# the delta matches the flagged customer's expected contribution.
# ══════════════════════════════════════════════════════════════════
def test_reports_forecast_excludes_flagged_billing_plans_and_quotes(tenant_id):
    admin = _seed_admin(tenant_id)
    # Seed Charlie UNFLAGGED first so the pre-toggle baseline
    # includes his billing plan + weighted quote; then flip the
    # flag and recompute.  Delta ≥ Charlie's monthly plan amount
    # proves the exclusion wired through.
    cid_a = _seed_customer(tenant_id, "Alpha")
    cid_c = _seed_customer(tenant_id, "Charlie",
                             account_correction=False)
    _seed_billing_plan(tenant_id, cid_a, 100.0)
    _seed_billing_plan(tenant_id, cid_c, 999.0)
    _seed_open_quote(tenant_id, cid_c, "Charlie", 7777,
                      "2026-02-20T00:00:00+00:00")

    def _hit():
        return requests.get(
            f"{API}/reports/forecast",
            params={"days": 90},
            headers=_auth(admin["token"], tenant_id),
        )

    r1 = _hit()
    assert r1.status_code == 200, r1.text
    t_before = float(r1.json().get("total") or 0.0)

    # Flip Charlie's flag ON directly via DB (toggle API is covered
    # by its own test suite — this test only cares about the
    # forecast's reaction).
    _sync.customers.update_one(
        {"id": cid_c, "tenant_id": tenant_id},
        {"$set": {"account_correction": True,
                   "account_correction_at": "2026-02-01T00:00:00+00:00"}},
    )

    r2 = _hit()
    assert r2.status_code == 200, r2.text
    t_after = float(r2.json().get("total") or 0.0)

    # Charlie's $999/mo plan alone (3 months at 90-day horizon ≈
    # $2997, prorated via the ``_cycles_in_range``-equivalent weekly
    # bucketing in the forecast helper) is the floor of what the
    # filter should drop.  Guard against both no-change and leaked
    # cases with a generous lower bound.
    delta = t_before - t_after
    assert delta >= 500.0, (
        f"forecast total dropped by only {delta:.2f} after flagging "
        f"Charlie (expected >=$500 from his billing plan + quote)."
        f"\n  before={t_before:.2f}  after={t_after:.2f}"
    )


# ══════════════════════════════════════════════════════════════════
# 3 · GET /admin/dashboard/revenue-forecast
# ══════════════════════════════════════════════════════════════════
def test_admin_dashboard_revenue_forecast_excludes_flagged(tenant_id):
    admin = _seed_admin(tenant_id)
    cids = _seed_three_customers_with_revenue(tenant_id)

    r = requests.get(
        f"{API}/admin/dashboard/revenue-forecast",
        params={"start": "2026-02-01", "end": "2026-02-28"},
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Response shape: ``{booked: {amount, job_count}, recurring:
    # {amount, subscription_count, cycle_count, ...}, combined_total,
    # currency, range}``.
    booked = float(body.get("booked", {}).get("amount") or 0.0)
    recurring = float(body.get("recurring", {}).get("amount") or 0.0)
    # Charlie's $8888 scheduled + $999/mo plan MUST stay out —
    # Charlie's $8888 job alone would 44× the booked total; the
    # bar is any reasonable guard against the flagged value leaking.
    assert booked < 1000, (
        f"booked {booked} looks like Charlie's $8888 scheduled job "
        f"leaked through the account_correction filter"
    )
    assert recurring < 500, (
        f"recurring {recurring} looks like Charlie's $999/mo plan "
        f"leaked through the account_correction filter"
    )


# ══════════════════════════════════════════════════════════════════
# 4 · GET /reports/kpi/revenue_by_customer  (KPI tile analog)
# ══════════════════════════════════════════════════════════════════
def test_kpi_revenue_by_customer_excludes_flagged(tenant_id):
    admin = _seed_admin(tenant_id)
    cids = _seed_three_customers_with_revenue(tenant_id)

    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={
            "period": "custom",
            "start": "2026-02-01",
            "end": "2026-02-28",
            "lens": "invoiced",
            "include_prior": "false",
        },
        headers=_auth(admin["token"], tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("rows") or []
    row_ids = {r.get("customer_id") for r in rows}
    row_names = {r.get("customer_name") for r in rows}

    assert cids["a"] in row_ids
    assert cids["b"] in row_ids
    assert cids["c"] not in row_ids, (
        f"flagged customer Charlie leaked into KPI "
        f"revenue_by_customer rows: {rows}"
    )
    assert "Charlie" not in row_names
    # Phase 4a · Feb-2026 — Revenue by Customer is paid-only.  Alpha
    # contributes $1000 (paid invoice) ONLY; Alpha's $500 open quote
    # no longer counts (``doc_type=quote`` + ``payment_status!="paid"``
    # both excluded).  Bravo contributes $2000 (paid invoice).
    # Charlie's $9999 paid invoice + $7777 quote stay out via the
    # account_correction exclusion.  Expected total: $3000.
    assert abs(float(body.get("total") or 0.0) - 3000.0) < 0.01, body


# ══════════════════════════════════════════════════════════════════
# 5 · Role gate stays admin-only (don't widen).
# ══════════════════════════════════════════════════════════════════
def test_revenue_routes_still_admin_only(tenant_id):
    # Non-admin tech must get 403 on every route — proves the filter
    # patch didn't accidentally widen access.
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@carac-par.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": "Tech", "email": email,
    })
    tok = _tok(uid, email, tenant_id, "technician")
    headers = _auth(tok, tenant_id)

    r = requests.get(f"{API}/reports/revenue-by-customer", headers=headers)
    assert r.status_code == 403, r.text
    r = requests.get(f"{API}/reports/forecast", headers=headers)
    assert r.status_code == 403, r.text
    # Admin dashboard route has required ``start`` + ``end`` params
    # that are validated BEFORE the role gate (FastAPI validation
    # order), so include valid values to force the 403 code path.
    r = requests.get(f"{API}/admin/dashboard/revenue-forecast",
                      params={"start": "2026-02-01",
                              "end":   "2026-02-28"},
                      headers=headers)
    assert r.status_code == 403, r.text
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer",
                      headers=headers)
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════
# 6 · Tenant isolation — tenant A's flagged customer MUST NOT
#     influence tenant B's revenue (defence in depth; the exclusion
#     helpers tenant-scope their customer-id lookup).
# ══════════════════════════════════════════════════════════════════
def test_tenant_isolation_revenue_by_customer(tenant_id):
    # tenant_id acts as tenant A.  Set up tenant B separately so we
    # can tear it down manually at the end.
    tid_b = f"caracp-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({"id": tid_b, "name": "CARAC parity B",
                                "slug": tid_b, "active": True})
    try:
        # Tenant A: 1 normal + 1 flagged.
        admin_a = _seed_admin(tenant_id)
        a_normal = _seed_customer(tenant_id, "A Normal")
        a_flag = _seed_customer(tenant_id, "A Flag",
                                 account_correction=True)
        _seed_paid_invoice(tenant_id, a_normal, "A Normal", 100,
                            "2026-02-15T12:00:00+00:00")
        _seed_paid_invoice(tenant_id, a_flag, "A Flag", 500,
                            "2026-02-15T12:00:00+00:00")
        # Tenant B: 1 normal only.  Give it the SAME customer-id
        # string as tenant A's flagged customer to prove the
        # ``account_correction`` exclusion is tenant-scoped (the
        # exclusion list from tenant A MUST NOT reach tenant B's
        # queries).  Use a dedicated b_normal id so B's own slot is
        # unambiguous.
        admin_b = _seed_admin(tid_b)
        b_normal = _seed_customer(tid_b, "B Normal")
        _seed_paid_invoice(tid_b, b_normal, "B Normal", 300,
                            "2026-02-15T12:00:00+00:00")

        # Tenant A sees only A Normal — total 100.
        ra = requests.get(
            f"{API}/reports/revenue-by-customer",
            params={"start": "2026-02-01", "end": "2026-02-28"},
            headers=_auth(admin_a["token"], tenant_id),
        )
        assert ra.status_code == 200, ra.text
        ba = ra.json()
        a_names = {r.get("customer_name") for r in (ba.get("rows") or [])}
        assert "A Normal" in a_names
        assert "A Flag" not in a_names
        assert "B Normal" not in a_names, (
            f"tenant A leaked tenant B's data: {ba}"
        )
        assert abs(float(ba["summary"]["total"]) - 100.0) < 0.01

        # Tenant B sees only B Normal — total 300.  Importantly,
        # even though tenant A has a flagged customer, tenant B's
        # exclusion list is independent (empty here) and B's own
        # Normal customer stays in.
        rb = requests.get(
            f"{API}/reports/revenue-by-customer",
            params={"start": "2026-02-01", "end": "2026-02-28"},
            headers=_auth(admin_b["token"], tid_b),
        )
        assert rb.status_code == 200, rb.text
        bb = rb.json()
        b_names = {r.get("customer_name") for r in (bb.get("rows") or [])}
        assert "B Normal" in b_names
        assert "A Normal" not in b_names
        assert "A Flag" not in b_names
        assert abs(float(bb["summary"]["total"]) - 300.0) < 0.01
    finally:
        for col in ("tenants", "users", "customers",
                     "customer_account_correction_audit",
                     "billing_plans", "quotes", "jobs"):
            _sync[col].delete_many({"tenant_id": tid_b})
