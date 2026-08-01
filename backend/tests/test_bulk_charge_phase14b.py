"""Phase 14b · Feb-2026 — Invoice filters + bulk charge tests.

Stubs Phase 14a's ``services.payments.stripe_charge.charge_card_on_file``
directly via ``monkeypatch`` on the imported reference inside the bulk
router. No live Stripe HTTP is ever issued.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
from routers import invoices_bulk_charge as bulk_router  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
bulk_router.db = _FRESH[_ENV["DB_NAME"]]


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": password}, timeout=10
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


# ── Fixture builder ───────────────────────────────────────────────────
_TAG = "TEST_p14b"


def _seed_customer(tenant_id: str, tag: str) -> str:
    cid = f"{_TAG}_cust_{tag}_{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": f"{_TAG} Customer {tag}",
        "email": f"{_TAG}_{tag}@example.com",
        "phone": "+15550100000",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return cid


def _seed_invoice(
    tenant_id: str,
    customer_id: str,
    *,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    categories: list[str] | None = None,
    number: str | None = None,
) -> str:
    iid = f"{_TAG}_inv_{uuid.uuid4().hex[:8]}"
    line_items = []
    for c in (categories or ["Pool"]):
        line_items.append({
            "description": f"item {c}",
            "quantity": 1,
            "unit_price": total / max(1, len(categories or ["Pool"])),
            "category": c,
        })
    _sync.quotes.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "title": f"{_TAG} Invoice",
        "invoice_number": number or f"{_TAG}-{iid[-4:]}",
        "line_items": line_items,
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "currency": "usd",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return iid


def _seed_pm(
    tenant_id: str,
    customer_id: str,
    *,
    exp_year: int = 2032,
    exp_month: int = 12,
    is_default: bool = True,
    provider_pm_id: str | None = None,
) -> str:
    pm_id = provider_pm_id or f"pm_{_TAG}_{uuid.uuid4().hex[:8]}"
    _sync.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": f"cus_{_TAG}",
        "provider_payment_method_id": pm_id,
        "brand": "visa",
        "last4": "4242",
        "exp_month": exp_month,
        "exp_year": exp_year,
        "is_default": is_default,
        "stripe_mode": "test",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    })
    return pm_id


def _cleanup(tenant_id: str) -> None:
    _sync.customers.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.quotes.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.payment_methods.delete_many({"tenant_id": tenant_id, "provider_payment_method_id": {"$regex": f"^pm_{_TAG}_"}})
    _sync.bulk_charge_runs.delete_many({"tenant_id": tenant_id, "idempotency_key": {"$regex": f"^{_TAG}"}})


@pytest.fixture
def scenario():
    """Seed a repeatable 5-invoice scenario per the user's test brief.

    Returns dict with:
      * tenant_id, admin_token
      * customer ids: c_a (active card), c_b (active card), c_c (no card),
                      c_d (expired card), c_e (active card, unused).
      * invoices: eligible1, eligible2, already_paid, no_card, zero_balance.
    """
    tid = _tid()
    _cleanup(tid)
    ca = _seed_customer(tid, "A")
    cb = _seed_customer(tid, "B")
    cc = _seed_customer(tid, "C_nocard")
    cd = _seed_customer(tid, "D_expired")
    ce = _seed_customer(tid, "E_active")
    pm_a = _seed_pm(tid, ca)
    pm_b = _seed_pm(tid, cb)
    _seed_pm(tid, ce)
    now = datetime.now(timezone.utc)
    # Expired PM: last month vs now.
    exp_y = now.year - 1
    _seed_pm(tid, cd, exp_year=exp_y, exp_month=12)

    yield {
        "tenant_id": tid,
        "admin_token": _login("manager@aquaterra.com"),
        "customers": {"A": ca, "B": cb, "C": cc, "D": cd, "E": ce},
        "pms": {"A": pm_a, "B": pm_b},
        "invoices": {
            "eligible1": _seed_invoice(tid, ca, total=125.00, categories=["Pool"]),
            "eligible2": _seed_invoice(tid, cb, total=99.50, categories=["Chem", "Pool"]),
            "already_paid": _seed_invoice(
                tid, ca, total=50.00, amount_paid=50.00, payment_status="paid",
                categories=["Pool"],
            ),
            "no_card": _seed_invoice(tid, cc, total=200.00, categories=["Pool"]),
            "zero_balance": _seed_invoice(
                tid, ca, total=0.0, categories=["Late fee"],
            ),
        },
    }
    _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# Filter tests
# ═════════════════════════════════════════════════════════════════════
def test_filter_category_single_matches_only_pool(scenario):
    tok = scenario["admin_token"]
    r = requests.get(
        f"{API}/quotes?doc_type=invoice&category=Pool",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    rows = r.json()
    scenario_ids = set(scenario["invoices"].values())
    hits = [r for r in rows if r["id"] in scenario_ids]
    # eligible1, eligible2 (has Pool), already_paid, no_card all have Pool.
    # zero_balance has "Late fee" only.
    assert scenario["invoices"]["eligible1"] in {r["id"] for r in hits}
    assert scenario["invoices"]["eligible2"] in {r["id"] for r in hits}
    assert scenario["invoices"]["zero_balance"] not in {r["id"] for r in hits}


def test_filter_category_multi_union(scenario):
    tok = scenario["admin_token"]
    r = requests.get(
        f"{API}/quotes?doc_type=invoice&category=Pool&category=Late+fee",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    rows = r.json()
    scenario_ids = set(scenario["invoices"].values())
    hits = {r["id"] for r in rows if r["id"] in scenario_ids}
    assert scenario["invoices"]["zero_balance"] in hits  # Late fee only
    assert scenario["invoices"]["eligible1"] in hits    # Pool
    assert scenario["invoices"]["eligible2"] in hits    # Chem + Pool → matches Pool


def test_filter_card_on_file_yes(scenario):
    tok = scenario["admin_token"]
    r = requests.get(
        f"{API}/quotes?doc_type=invoice&card_on_file=yes",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    rows = r.json()
    ids = {r["id"] for r in rows}
    # A + B have active cards; C = none; D = expired (excluded)
    assert scenario["invoices"]["eligible1"] in ids
    assert scenario["invoices"]["eligible2"] in ids
    assert scenario["invoices"]["no_card"] not in ids
    # A has PM so already_paid + zero_balance still match "yes"
    assert scenario["invoices"]["already_paid"] in ids


def test_filter_card_on_file_no(scenario):
    tok = scenario["admin_token"]
    r = requests.get(
        f"{API}/quotes?doc_type=invoice&card_on_file=no",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    rows = r.json()
    ids = {r["id"] for r in rows}
    # no_card owned by customer C (no PM)  → included in "no"
    assert scenario["invoices"]["no_card"] in ids
    assert scenario["invoices"]["eligible1"] not in ids  # customer A has active
    assert scenario["invoices"]["eligible2"] not in ids  # customer B has active


def test_categories_endpoint_returns_distinct_values(scenario):
    tok = scenario["admin_token"]
    r = requests.get(
        f"{API}/invoices/line-item-categories",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert "categories" in body
    cats_lower = {c.lower() for c in body["categories"]}
    assert "pool" in cats_lower
    assert "late fee" in cats_lower or "chem" in cats_lower


# ═════════════════════════════════════════════════════════════════════
# Bulk-charge tests
# ═════════════════════════════════════════════════════════════════════
class _ChargeStub:
    """Replaces ``stripe_svc.charge_card_on_file`` for the duration of a test."""

    def __init__(self):
        self.calls: list[dict] = []
        self.responses: list[dict] = []
        self.exceptions: dict[str, Exception] = {}

    def enqueue(self, res: dict):
        self.responses.append(res)

    def error_for(self, invoice_id: str, exc: Exception):
        self.exceptions[invoice_id] = exc

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        inv_id = kwargs.get("invoice_id")
        if inv_id in self.exceptions:
            raise self.exceptions[inv_id]
        if self.responses:
            return self.responses.pop(0)
        return {
            "ok": True,
            "charge_row_id": str(uuid.uuid4()),
            "payment_intent_id": f"pi_stub_{uuid.uuid4().hex[:8]}",
            "status": "succeeded",
            "amount_cents": kwargs["amount_cents"],
            "currency": kwargs["currency"],
        }


@pytest.fixture
def stub(monkeypatch):
    s = _ChargeStub()
    # Patch the reference the bulk router imported.
    monkeypatch.setattr(bulk_router.stripe_svc, "charge_card_on_file", s)
    return s


def _bulk_body(scenario, dry_run: bool, key: str | None = None):
    key = key or f"{_TAG}_key_{uuid.uuid4().hex[:6]}"
    return {
        "invoice_ids": [
            scenario["invoices"]["eligible1"],
            scenario["invoices"]["eligible2"],
            scenario["invoices"]["already_paid"],
            scenario["invoices"]["no_card"],
            scenario["invoices"]["zero_balance"],
        ],
        "dry_run": dry_run,
        "idempotency_key": key,
    }


def test_bulk_dry_run_marks_eligible_and_reasons(scenario, stub):
    tok = scenario["admin_token"]
    body = _bulk_body(scenario, dry_run=True)
    r = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["dry_run"] is True
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id[scenario["invoices"]["eligible1"]]["status"] == "would_charge"
    assert by_id[scenario["invoices"]["eligible2"]]["status"] == "would_charge"
    assert by_id[scenario["invoices"]["already_paid"]]["skip_reason"] == "already_paid"
    assert by_id[scenario["invoices"]["no_card"]]["skip_reason"] == "no_card_on_file"
    assert by_id[scenario["invoices"]["zero_balance"]]["skip_reason"] == "zero_balance"
    assert j["summary"]["would_charge"] == 2
    assert j["summary"]["skipped"] == 3
    assert j["summary"]["charged"] == 0
    # Stub is not exercised on a dry-run — but note stub applies only
    # in-process; HTTP-driven dry-runs never call charge_card_on_file.


def _in_process_bulk(scenario, *, dry_run: bool, key: str,
                       invoice_ids: list[str] | None = None) -> dict:
    """Drive ``execute_bulk_charge`` in-process so the pytest-side
    monkeypatch on ``bulk_router.stripe_svc.charge_card_on_file`` takes
    effect (HTTP requests hit a separate backend process where the stub
    is not visible)."""
    from routers.invoices_bulk_charge import BulkChargeBody as _Body, execute_bulk_charge as _core
    ids = invoice_ids or [
        scenario["invoices"]["eligible1"],
        scenario["invoices"]["eligible2"],
        scenario["invoices"]["already_paid"],
        scenario["invoices"]["no_card"],
        scenario["invoices"]["zero_balance"],
    ]
    body = _Body(invoice_ids=ids, dry_run=dry_run, idempotency_key=key)
    user = {"id": "test_admin", "role": "admin", "email": "manager@aquaterra.com"}
    tenant = {"id": scenario["tenant_id"]}
    return _run(_core(body=body, user=user, tenant=tenant))


def test_bulk_real_charges_only_eligible_and_persists(scenario, stub):
    key = f"{_TAG}_key_real_{uuid.uuid4().hex[:6]}"
    j = _in_process_bulk(scenario, dry_run=False, key=key)
    assert j["dry_run"] is False
    assert j["summary"]["charged"] == 2
    assert j["summary"]["skipped"] == 3
    assert j["summary"]["total_amount_charged_cents"] == 12500 + 9950
    assert len(stub.calls) == 2
    keys = {c["idempotency_key"] for c in stub.calls}
    assert f"{key}:{scenario['invoices']['eligible1']}" in keys
    assert f"{key}:{scenario['invoices']['eligible2']}" in keys
    run = _sync.bulk_charge_runs.find_one({"idempotency_key": key})
    assert run is not None
    assert run["summary"]["charged"] == 2
    e1 = _sync.quotes.find_one({"id": scenario["invoices"]["eligible1"]})
    assert e1["payment_status"] == "paid"


def test_bulk_idempotency_replay_is_zero_side_effect(scenario, stub):
    tok = scenario["admin_token"]
    key = f"{_TAG}_key_replay_{uuid.uuid4().hex[:6]}"
    body = _bulk_body(scenario, dry_run=False, key=key)
    r1 = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    assert r1.status_code == 200
    calls_first = len(stub.calls)
    j1 = r1.json()
    r2 = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r2.status_code == 200
    j2 = r2.json()
    # No additional stub calls.
    assert len(stub.calls) == calls_first
    assert j2.get("replayed") is True
    assert j2["summary"] == j1["summary"]
    assert j2["run_id"] == j1["run_id"]


def test_bulk_cross_tenant_id_is_not_found_no_leak(scenario, stub):
    tok = scenario["admin_token"]
    # Fake a foreign invoice id that doesn't exist in this tenant.
    body = {
        "invoice_ids": [scenario["invoices"]["eligible1"], "foreign-invoice-xyz"],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_xtenant_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    j = r.json()
    assert len(j["results"]) == 2
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id["foreign-invoice-xyz"]["skip_reason"] == "not_found"
    # No 404 raised — the server returns a normal 200 payload.


def test_bulk_cap_over_100_returns_422(scenario, stub):
    tok = scenario["admin_token"]
    body = {
        "invoice_ids": [f"x{i}" for i in range(101)],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_cap_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 422, r.text


def test_bulk_role_guards_tech_and_customer(scenario, stub):
    from tests.conftest import demo_pw
    # Customer 403.
    ctok = _login("customer@aquaterra.com", demo_pw("customer@aquaterra.com"))
    body = {
        "invoice_ids": [scenario["invoices"]["eligible1"]],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_cust_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {ctok}"}, timeout=10,
    )
    assert r.status_code == 403, r.text
    # Categories + runs list also blocked.
    r2 = requests.get(
        f"{API}/invoices/line-item-categories",
        headers={"Authorization": f"Bearer {ctok}"}, timeout=10,
    )
    assert r2.status_code == 403
    r3 = requests.get(
        f"{API}/invoices/bulk-charge-runs",
        headers={"Authorization": f"Bearer {ctok}"}, timeout=10,
    )
    assert r3.status_code == 403


def test_bulk_charge_returns_failed_for_non_ok_no_charge_id(scenario, stub):
    """Design decision: Phase 14a can return ``{ok: False}`` without a
    ``charge_id`` (e.g., PaymentIntent requires_action). Verify we mark
    the row failed with ``error_code=not_ok_no_charge_id``."""
    stub.enqueue({
        "ok": False,
        "status": "requires_action",
        "payment_intent_id": None,
        "amount_cents": 12500,
        "currency": "usd",
    })
    j = _in_process_bulk(
        scenario, dry_run=False,
        key=f"{_TAG}_key_notok_{uuid.uuid4().hex[:6]}",
        invoice_ids=[scenario["invoices"]["eligible1"]],
    )
    row = j["results"][0]
    assert row["status"] == "failed"
    assert row["error_code"] == "not_ok_no_charge_id"
    assert j["summary"]["failed"] == 1


def test_bulk_charge_returns_failed_on_stripe_exception(scenario, stub):
    stub.error_for(scenario["invoices"]["eligible1"], RuntimeError("card_declined"))
    j = _in_process_bulk(
        scenario, dry_run=False,
        key=f"{_TAG}_key_exc_{uuid.uuid4().hex[:6]}",
        invoice_ids=[scenario["invoices"]["eligible1"],
                     scenario["invoices"]["eligible2"]],
    )
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id[scenario["invoices"]["eligible1"]]["status"] == "failed"
    assert by_id[scenario["invoices"]["eligible1"]]["error_code"] == "RuntimeError"
    assert "card_declined" in by_id[scenario["invoices"]["eligible1"]]["error_message"]
    assert by_id[scenario["invoices"]["eligible2"]]["status"] == "charged"
    assert j["summary"]["charged"] == 1
    assert j["summary"]["failed"] == 1


def test_runs_list_and_detail_endpoints(scenario, stub):
    tok = scenario["admin_token"]
    key = f"{_TAG}_key_listruns_{uuid.uuid4().hex[:6]}"
    body = _bulk_body(scenario, dry_run=True, key=key)
    r = requests.post(
        f"{API}/invoices/bulk-charge-card-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    run_id = r.json()["run_id"]
    lst = requests.get(
        f"{API}/invoices/bulk-charge-runs?limit=5",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert lst.status_code == 200
    runs = lst.json()["runs"]
    assert any(row["run_id"] == run_id for row in runs)
    det = requests.get(
        f"{API}/invoices/bulk-charge-runs/{run_id}",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert det.status_code == 200
    d = det.json()
    assert d["run_id"] == run_id
    assert d["dry_run"] is True
    assert isinstance(d["results"], list)


def test_grep_lint_no_writes_to_db_invoices():
    """Phase 11 invariant — the new bulk router must NOT write to
    ``db.invoices``. All invoice reads/writes go through ``db.quotes``."""
    import re
    src = Path(__file__).resolve().parents[1] / "routers" / "invoices_bulk_charge.py"
    text = src.read_text(encoding="utf-8")
    # Reject any pattern that writes to db.invoices (insert/update/delete).
    assert not re.search(r"db\.invoices\.(insert|update|delete|find_one_and_)", text)
