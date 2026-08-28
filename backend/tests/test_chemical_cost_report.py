"""Feb-2026 · Chemical Cost Report — backend suite (Option 2 rewrite).

The report now aggregates from ``chemical_usage_events`` instead of
invoice line items. Tests seed events directly (mirroring what
``snapshot_chemical_usage`` writes at submit time), plus a paid
``db.quotes`` doc keyed on ``job_id`` so the "paid work only" gate
lets the events through.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"
_TOK: dict = {}


def _login(email: str) -> tuple[str, dict]:
    if email in _TOK:
        return _TOK[email]
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": "password123"},
                        timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=30).json()
    _TOK[email] = (tok, me)
    return tok, me


_PREFIX = f"chcost-{uuid.uuid4().hex[:8]}"


def _seed_catalog_chemical(tid: str, slug: str, name: str,
                             cost_per_unit_cents: int = 500,
                             unit_kind: str = "gal") -> None:
    """Seed a ``chemical_costs`` catalog row so ``product_slug`` →
    display name / unit resolves in the report."""
    _sync.chemical_costs.update_one(
        {"tenant_id": tid, "chemical_slug": slug},
        {"$set": {
            "tenant_id": tid, "chemical_slug": slug, "name": name,
            "cost_per_unit_cents": cost_per_unit_cents,
            "unit_kind": unit_kind,
        }},
        upsert=True,
    )


def _seed_event(*, tid: str, job_id: str, service_report_id: str,
                 customer_id: str | None, product_slug: str,
                 name: str, qty: float, unit_cost_cents: int,
                 unit_kind: str = "gal",
                 water_body_id: str | None = None,
                 water_body_type: str | None = None,
                 water_body_label: str | None = None,
                 occurred_at: str | None = None) -> str:
    eid = f"{_PREFIX}-ev-{uuid.uuid4().hex[:6]}"
    occurred = occurred_at or datetime.now(timezone.utc).isoformat()
    _sync.chemical_usage_events.insert_one({
        "id": eid, "tenant_id": tid,
        "job_id": job_id, "service_report_id": service_report_id,
        "customer_id": customer_id,
        "product_slug": product_slug, "name": name,
        "quantity_used": qty, "unit": unit_kind,
        "unit_cost_at_time_cents": unit_cost_cents,
        "total_cost_cents": int(round(qty * unit_cost_cents)),
        "water_body_id":    water_body_id,
        "water_body_type":  water_body_type,
        "water_body_label": water_body_label,
        "occurred_at": occurred, "created_at": occurred,
    })
    return eid


def _seed_paid_invoice_for_job(*, tid: str, job_id: str,
                                 customer_id: str,
                                 amount: float = 150.0) -> str:
    iid = f"{_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": f"INV-2026-{uuid.uuid4().int % 900000 + 100000}",
        "customer_id": customer_id, "customer_name": "Test Cust",
        "job_id": job_id,
        "payment_status": "paid", "amount_paid": amount,
        "total": amount, "subtotal": amount,
        "created_at": now, "paid_at": now,
        "paid_method": "manual_cash",
        "line_items": [{
            "description": "Service", "quantity": 1, "unit_price": amount,
        }],
    })
    return iid


def _seed_job(tid: str, customer_id: str = "seed-cust",
               technician_id: str | None = None) -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "Cost report test job",
        "customer_id": customer_id, "customer_name": "Seed",
        "service_type": "Pool Cleaning",
        "scheduled_date": "2026-08-31",
        "status": "completed",
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup():
    _sync.chemical_usage_events.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.quotes.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.chemical_costs.delete_many({"chemical_slug": {"$regex": f"^{_PREFIX}-"}})


def setup_module(module): _cleanup()
def teardown_module(module): _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Aggregate from chemical_usage_events (Option 2 canonical path).
# ══════════════════════════════════════════════════════════════════════
def test_aggregate_from_chemical_usage_events():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-chlorine"
    _seed_catalog_chemical(tid, slug, "TEST Chlorine",
                            cost_per_unit_cents=450, unit_kind="gal")
    jid = _seed_job(tid, customer_id="c1")
    inv = _seed_paid_invoice_for_job(tid=tid, job_id=jid, customer_id="c1")
    ev = _seed_event(tid=tid, job_id=jid, service_report_id="sr1",
                       customer_id="c1", product_slug=slug,
                       name="TEST Chlorine", qty=5.0,
                       unit_cost_cents=450, unit_kind="gal")
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs?chemical_ids={slug}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totals"]["total_wholesale_cost"] == 22.5   # 5 × 4.50
        assert body["totals"]["total_qty"] == 5.0
        row = next(c for c in body["by_chemical"] if c["product_slug"] == slug)
        assert row["chemical_name"] == "TEST Chlorine"
        assert row["total_cost"] == 22.5
        assert row["job_count"] == 1
        # by_water_body has a "legacy" bucket for events with wb_id=None.
        legacy = [b for b in body["by_water_body"] if b["body_type"] == "legacy"]
        assert len(legacy) == 1
        assert legacy[0]["total_wholesale_cost"] == 22.5
    finally:
        _sync.chemical_usage_events.delete_one({"id": ev})
        _sync.jobs.delete_one({"id": jid})
        _sync.quotes.delete_one({"id": inv})


# ══════════════════════════════════════════════════════════════════════
# 2 · Unpaid invoices are excluded (payment gate preserved).
# ══════════════════════════════════════════════════════════════════════
def test_unpaid_invoice_excludes_events():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-muriatic"
    _seed_catalog_chemical(tid, slug, "TEST Muriatic",
                            cost_per_unit_cents=500)
    jid = _seed_job(tid, customer_id="c3")
    # Note: invoice NOT paid.
    now = datetime.now(timezone.utc).isoformat()
    inv_id = f"{_PREFIX}-inv-unpaid-{uuid.uuid4().hex[:6]}"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "c3", "job_id": jid,
        "payment_status": "unpaid",
        "total": 40.0, "subtotal": 40.0, "created_at": now,
    })
    ev = _seed_event(tid=tid, job_id=jid, service_report_id="sr2",
                       customer_id="c3", product_slug=slug,
                       name="TEST Muriatic", qty=2.0,
                       unit_cost_cents=500)
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs?chemical_ids={slug}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert not [c for c in body["by_chemical"] if c["product_slug"] == slug]
    finally:
        _sync.chemical_usage_events.delete_one({"id": ev})
        _sync.jobs.delete_one({"id": jid})
        _sync.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# 3 · include_unpaid=true bypasses the payment gate.
# ══════════════════════════════════════════════════════════════════════
def test_include_unpaid_flag_bypasses_gate():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-unpaid-flag"
    _seed_catalog_chemical(tid, slug, "TEST Unpaid Flag",
                            cost_per_unit_cents=200)
    jid = _seed_job(tid, customer_id="c-uf")
    ev = _seed_event(tid=tid, job_id=jid, service_report_id="sr-uf",
                       customer_id="c-uf", product_slug=slug,
                       name="TEST Unpaid Flag", qty=3.0,
                       unit_cost_cents=200)
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?chemical_ids={slug}&include_unpaid=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        body = r.json()
        row = next(c for c in body["by_chemical"] if c["product_slug"] == slug)
        assert row["qty_used"] == 3.0
        assert row["total_cost"] == 6.0
    finally:
        _sync.chemical_usage_events.delete_one({"id": ev})
        _sync.jobs.delete_one({"id": jid})


# ══════════════════════════════════════════════════════════════════════
# 4 · Customer filter narrows aggregation.
# ══════════════════════════════════════════════════════════════════════
def test_customer_filter_narrows_aggregation():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-algaecide"
    _seed_catalog_chemical(tid, slug, "TEST Algaecide",
                            cost_per_unit_cents=500)
    job_a = _seed_job(tid, customer_id="cust-A")
    job_b = _seed_job(tid, customer_id="cust-B")
    inv_a = _seed_paid_invoice_for_job(tid=tid, job_id=job_a,
                                          customer_id="cust-A")
    inv_b = _seed_paid_invoice_for_job(tid=tid, job_id=job_b,
                                          customer_id="cust-B")
    ev_a = _seed_event(tid=tid, job_id=job_a, service_report_id="sr-a",
                         customer_id="cust-A", product_slug=slug,
                         name="TEST Algaecide", qty=3.0,
                         unit_cost_cents=500)
    ev_b = _seed_event(tid=tid, job_id=job_b, service_report_id="sr-b",
                         customer_id="cust-B", product_slug=slug,
                         name="TEST Algaecide", qty=7.0,
                         unit_cost_cents=500)
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?customer_id=cust-A&chemical_ids={slug}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        row = next(c for c in r.json()["by_chemical"]
                    if c["product_slug"] == slug)
        assert row["qty_used"] == 3.0
        assert row["total_cost"] == 15.0
    finally:
        _sync.chemical_usage_events.delete_many(
            {"id": {"$in": [ev_a, ev_b]}})
        _sync.jobs.delete_many({"id": {"$in": [job_a, job_b]}})
        _sync.quotes.delete_many({"id": {"$in": [inv_a, inv_b]}})


# ══════════════════════════════════════════════════════════════════════
# 5 · Tech filter narrows via jobs.technician_id join.
# ══════════════════════════════════════════════════════════════════════
def test_tech_filter_narrows_via_job_join():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-shock"
    _seed_catalog_chemical(tid, slug, "TEST Shock",
                            cost_per_unit_cents=500)
    job_alpha = _seed_job(tid, technician_id="tech-alpha")
    job_beta = _seed_job(tid, technician_id="tech-beta")
    inv_a = _seed_paid_invoice_for_job(tid=tid, job_id=job_alpha,
                                          customer_id="c1")
    inv_b = _seed_paid_invoice_for_job(tid=tid, job_id=job_beta,
                                          customer_id="c1")
    ev_a = _seed_event(tid=tid, job_id=job_alpha, service_report_id="srA",
                         customer_id="c1", product_slug=slug,
                         name="TEST Shock", qty=4.0, unit_cost_cents=500)
    ev_b = _seed_event(tid=tid, job_id=job_beta, service_report_id="srB",
                         customer_id="c1", product_slug=slug,
                         name="TEST Shock", qty=9.0, unit_cost_cents=500)
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?tech_id=tech-alpha&chemical_ids={slug}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        row = next(c for c in r.json()["by_chemical"]
                    if c["product_slug"] == slug)
        assert row["qty_used"] == 4.0
    finally:
        _sync.chemical_usage_events.delete_many(
            {"id": {"$in": [ev_a, ev_b]}})
        _sync.jobs.delete_many({"id": {"$in": [job_alpha, job_beta]}})
        _sync.quotes.delete_many({"id": {"$in": [inv_a, inv_b]}})


# ══════════════════════════════════════════════════════════════════════
# 6 · Tech RBAC — 403.
# ══════════════════════════════════════════════════════════════════════
def test_tech_forbidden():
    tok, _ = _login("mike@aquaterra.com")
    r = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# 7 · Manager can access.
# ══════════════════════════════════════════════════════════════════════
def test_manager_can_access():
    tok, _ = _login("manager@aquaterra.com")
    r = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# 8 · chemical_ids filter accepts pricebook item ids (backward compat).
# ══════════════════════════════════════════════════════════════════════
def test_chemical_ids_accepts_pricebook_item_id_alias():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-clarifier"
    _seed_catalog_chemical(tid, slug, "TEST Clarifier",
                            cost_per_unit_cents=250, unit_kind="oz")
    # Pricebook items row keyed by NAME to the catalog slug.
    pb_id = f"{_PREFIX}-pb-{uuid.uuid4().hex[:6]}"
    _sync.items.insert_one({
        "id": pb_id, "tenant_id": tid, "name": "TEST Clarifier",
        "category": "Chemical", "unit": "oz",
    })
    jid = _seed_job(tid, customer_id="cA")
    inv = _seed_paid_invoice_for_job(tid=tid, job_id=jid, customer_id="cA")
    ev = _seed_event(tid=tid, job_id=jid, service_report_id="sr-clar",
                       customer_id="cA", product_slug=slug,
                       name="TEST Clarifier", qty=8.0,
                       unit_cost_cents=250)
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs?chemical_ids={pb_id}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        body = r.json()
        row = next(c for c in body["by_chemical"] if c["product_slug"] == slug)
        assert row["qty_used"] == 8.0
        assert row["total_cost"] == 20.0
    finally:
        _sync.chemical_usage_events.delete_one({"id": ev})
        _sync.items.delete_one({"id": pb_id})
        _sync.jobs.delete_one({"id": jid})
        _sync.quotes.delete_one({"id": inv})
