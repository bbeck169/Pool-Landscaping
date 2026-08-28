"""Feb-2026 · Chemical Cost Report — backend suite."""
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


def _seed_pricebook_chemical(tid: str, name: str,
                              category: str = "Chemical",
                              wholesale_cost: float = 5.0) -> str:
    iid = f"{_PREFIX}-pb-{uuid.uuid4().hex[:6]}"
    _sync.items.insert_one({
        "id": iid, "tenant_id": tid, "name": name,
        "category": category, "unit": "gal",
        "unit_price": 20.0, "wholesale_cost": wholesale_cost,
    })
    return iid


def _seed_paid_invoice(*, tid: str, customer_id: str,
                        line_items: list, job_id: str | None = None) -> str:
    iid = f"{_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    total = sum(li.get("quantity", 0) * li.get("unit_price", 0)
                  for li in line_items)
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": f"INV-2026-{uuid.uuid4().int % 900000 + 100000}",
        "customer_id": customer_id, "customer_name": "Test Cust",
        "job_id": job_id,
        "payment_status": "paid", "amount_paid": total,
        "total": total, "subtotal": total,
        "created_at": now, "paid_at": now,
        "paid_method": "manual_cash",
        "line_items": line_items,
    })
    return iid


def _seed_job(tid: str, technician_id: str | None = None) -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "Cost report test job",
        "customer_id": "seed", "customer_name": "Seed",
        "service_type": "Pool Cleaning",
        "scheduled_date": "2026-08-31",
        "status": "completed",
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup():
    _sync.items.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.quotes.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module): _cleanup()
def teardown_module(module): _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Aggregate returns total_wholesale_cost using wholesale_cost_snapshot.
# ══════════════════════════════════════════════════════════════════════
def test_aggregate_uses_wholesale_cost_snapshot():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    pb_id = _seed_pricebook_chemical(tid, "TEST Chlorine")
    inv_id = _seed_paid_invoice(tid=tid, customer_id="c1",
        line_items=[{"item_id": pb_id, "description": "TEST Chlorine",
                        "quantity": 5, "unit_price": 20.0,
                        "wholesale_cost_snapshot": 4.5}])
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?chemical_ids={pb_id}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totals"]["total_wholesale_cost"] == 22.5   # 5 × 4.5
        assert body["totals"]["total_qty"] == 5.0
        assert body["by_chemical"][0]["chemical_id"] == pb_id
        assert body["by_chemical"][0]["total_cost"] == 22.5
    finally:
        _sync.items.delete_one({"id": pb_id})
        _sync.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# 2 · Non-chemical line items are skipped.
# ══════════════════════════════════════════════════════════════════════
def test_non_chemical_line_items_are_skipped():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    chem_id = _seed_pricebook_chemical(tid, "TEST Salt")
    labor_id = _seed_pricebook_chemical(tid, "TEST Labor",
                                          category="Labor",
                                          wholesale_cost=15.0)
    inv_id = _seed_paid_invoice(tid=tid, customer_id="c2",
        line_items=[
            {"item_id": chem_id, "quantity": 2, "unit_price": 20.0,
              "wholesale_cost_snapshot": 5.0},
            {"item_id": labor_id, "quantity": 1, "unit_price": 100.0,
              "wholesale_cost_snapshot": 25.0},
        ])
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200
        by = {c["chemical_id"]: c for c in r.json()["by_chemical"]}
        assert chem_id in by
        assert labor_id not in by
        assert by[chem_id]["total_cost"] == 10.0    # 2 × 5.0
    finally:
        _sync.items.delete_many({"id": {"$in": [chem_id, labor_id]}})
        _sync.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# 3 · Unpaid invoices are excluded.
# ══════════════════════════════════════════════════════════════════════
def test_unpaid_invoices_are_excluded():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    chem_id = _seed_pricebook_chemical(tid, "TEST Muriatic")
    now = datetime.now(timezone.utc).isoformat()
    inv_id = f"{_PREFIX}-inv-unpaid-{uuid.uuid4().hex[:6]}"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "c3", "payment_status": "unpaid",
        "total": 40.0, "subtotal": 40.0,
        "created_at": now,
        "line_items": [{"item_id": chem_id, "quantity": 2,
                          "unit_price": 20.0,
                          "wholesale_cost_snapshot": 5.0}],
    })
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs?chemical_ids={chem_id}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        by = {c["chemical_id"]: c for c in r.json()["by_chemical"]}
        # Unpaid invoice must not contribute.
        assert chem_id not in by
    finally:
        _sync.items.delete_one({"id": chem_id})
        _sync.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# 4 · Customer filter narrows aggregation.
# ══════════════════════════════════════════════════════════════════════
def test_customer_filter_narrows_aggregation():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    chem_id = _seed_pricebook_chemical(tid, "TEST Algaecide")
    inv_a = _seed_paid_invoice(tid=tid, customer_id="cust-A",
        line_items=[{"item_id": chem_id, "quantity": 3, "unit_price": 20.0,
                        "wholesale_cost_snapshot": 5.0}])
    inv_b = _seed_paid_invoice(tid=tid, customer_id="cust-B",
        line_items=[{"item_id": chem_id, "quantity": 7, "unit_price": 20.0,
                        "wholesale_cost_snapshot": 5.0}])
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs?customer_id=cust-A&chemical_ids={chem_id}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        by = {c["chemical_id"]: c for c in r.json()["by_chemical"]}
        assert by[chem_id]["qty_used"] == 3.0
        assert by[chem_id]["total_cost"] == 15.0
    finally:
        _sync.items.delete_one({"id": chem_id})
        _sync.quotes.delete_many({"id": {"$in": [inv_a, inv_b]}})


# ══════════════════════════════════════════════════════════════════════
# 5 · Tech RBAC — 403.
# ══════════════════════════════════════════════════════════════════════
def test_tech_forbidden():
    tok, _ = _login("mike@aquaterra.com")
    r = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# 6 · Manager can access.
# ══════════════════════════════════════════════════════════════════════
def test_manager_can_access():
    tok, _ = _login("manager@aquaterra.com")
    r = requests.get(
        f"{API}/reports/chemical-costs",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# 7 · Tech filter narrows aggregation via job join.
# ══════════════════════════════════════════════════════════════════════
def test_tech_filter_narrows_via_job_join():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    chem_id = _seed_pricebook_chemical(tid, "TEST Shock")
    # Two jobs, one with tech-alpha, one with tech-beta
    job_alpha = _seed_job(tid, technician_id="tech-alpha")
    job_beta = _seed_job(tid, technician_id="tech-beta")
    inv_a = _seed_paid_invoice(tid=tid, customer_id="c1",
        job_id=job_alpha,
        line_items=[{"item_id": chem_id, "quantity": 4, "unit_price": 20.0,
                        "wholesale_cost_snapshot": 5.0}])
    inv_b = _seed_paid_invoice(tid=tid, customer_id="c1",
        job_id=job_beta,
        line_items=[{"item_id": chem_id, "quantity": 9, "unit_price": 20.0,
                        "wholesale_cost_snapshot": 5.0}])
    try:
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?tech_id=tech-alpha&chemical_ids={chem_id}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        by = {c["chemical_id"]: c for c in r.json()["by_chemical"]}
        assert by[chem_id]["qty_used"] == 4.0
    finally:
        _sync.items.delete_one({"id": chem_id})
        _sync.jobs.delete_many({"id": {"$in": [job_alpha, job_beta]}})
        _sync.quotes.delete_many({"id": {"$in": [inv_a, inv_b]}})
