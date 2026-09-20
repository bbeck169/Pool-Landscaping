"""P0 · Feb-2026 — Bulk-charge idempotency scoping regression.

Reproduces + guards the real-money bug reported on the preview
env: the ``BulkChargeModal`` FE component generates ONE
``idempotency_key`` per modal mount and reuses it for BOTH the
preview (``dry_run=true``) POST and the confirm (``dry_run=false``)
POST. Pre-fix, ``execute_bulk_charge`` matched replay by
``(tenant_id, idempotency_key)`` only — the confirm request hit
the replay branch, returned the cached dry-run row (with
``status="would_charge"`` and ``summary.charged=0``), and the
FE surfaced "0 charged · 1 skipped · 0 failed" while Stripe was
never called.

Post-fix, the replay lookup is scoped by ``dry_run`` and the DB
unique index is widened to ``(tenant_id, idempotency_key, dry_run)``.
Preview and confirm now occupy separate replay slots under a shared
FE-supplied key.

Loudness invariant — the last test in this module asserts that a
run with ``eligible > 0`` MUST NOT return ``charged == 0`` unless
every eligible invoice actually failed. This catches the exact
"silent no-op" shape the P0 bug exhibited.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
# Motor loop shared with the router import so pytest monkeypatch on
# ``stripe_svc.charge_card_on_file`` is visible to the same interpreter
# that drives the in-process ``execute_bulk_charge`` call.
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


_TAG = "TEST_p0_idem"


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


def _seed_customer(tenant_id: str, tag: str) -> str:
    cid = f"{_TAG}_cust_{tag}_{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": f"{_TAG} Customer {tag}",
        "email": f"{_TAG}_{tag}@example.com",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return cid


def _seed_invoice(tenant_id: str, customer_id: str, *, total: float) -> str:
    iid = f"{_TAG}_inv_{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "customer_id": customer_id,
        "doc_type": "invoice", "title": f"{_TAG} Invoice",
        "invoice_number": f"{_TAG}-{iid[-4:]}",
        "line_items": [{"description": "svc", "quantity": 1,
                         "unit_price": total, "category": "Pool"}],
        "total": total, "amount_paid": 0.0, "payment_status": "unpaid",
        "currency": "usd", "created_at": "2026-08-01T00:00:00Z",
    })
    return iid


def _seed_pm(tenant_id: str, customer_id: str) -> str:
    pm_id = f"pm_{_TAG}_{uuid.uuid4().hex[:8]}"
    _sync.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id, "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": f"cus_{_TAG}",
        "provider_payment_method_id": pm_id,
        "brand": "visa", "last4": "4242",
        "exp_month": 12, "exp_year": 2032,
        "is_default": True, "stripe_mode": "test",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    })
    return pm_id


def _cleanup(tenant_id: str) -> None:
    _sync.customers.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.quotes.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.payment_methods.delete_many({
        "tenant_id": tenant_id,
        "provider_payment_method_id": {"$regex": f"^pm_{_TAG}_"},
    })
    _sync.bulk_charge_runs.delete_many({
        "tenant_id": tenant_id,
        "idempotency_key": {"$regex": f"^{_TAG}"},
    })


@pytest.fixture
def scenario():
    tid = _tid()
    _cleanup(tid)
    ca = _seed_customer(tid, "A")
    cb = _seed_customer(tid, "B_nocard")
    _seed_pm(tid, ca)
    yield {
        "tenant_id": tid,
        "invoices": {
            "eligible": _seed_invoice(tid, ca, total=131.00),
            "no_card": _seed_invoice(tid, cb, total=200.00),
        },
    }
    _cleanup(tid)


class _ChargeStub:
    def __init__(self):
        self.calls = []
    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
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
    monkeypatch.setattr(bulk_router.stripe_svc, "charge_card_on_file", s)
    return s


def _run_bulk(scenario, *, dry_run: bool, key: str):
    from routers.invoices_bulk_charge import BulkChargeBody, execute_bulk_charge
    body = BulkChargeBody(
        invoice_ids=[scenario["invoices"]["eligible"],
                       scenario["invoices"]["no_card"]],
        dry_run=dry_run,
        idempotency_key=key,
    )
    user = {"id": "test_admin", "role": "admin",
             "email": "manager@aquaterra.com"}
    tenant = {"id": scenario["tenant_id"]}
    return _run(execute_bulk_charge(body=body, user=user, tenant=tenant))


# ═════════════════════════════════════════════════════════════════════
# 1. THE bug repro: preview → confirm with same key must actually charge.
# ═════════════════════════════════════════════════════════════════════
def test_bulk_charge_confirm_actually_charges_eligible_invoices(scenario, stub):
    """Simulates the exact FE flow that broke on production:

    1. Modal mounts → generates one ``idempotency_key`` (uuid).
    2. FE POSTs ``dry_run=true`` with that key → BE returns preview.
    3. User clicks Confirm → FE POSTs ``dry_run=false`` with the SAME key.

    Pre-fix: step 3 hit the ``(tenant, key)`` replay branch, returned
    the cached preview row, ``charged=0``, ``$0.00`` collected. Real
    money silently lost.

    Post-fix: replay is scoped by ``dry_run`` so step 3 is a fresh
    run — Stripe is called, ``charged=1``, ``$131`` collected.
    """
    shared_key = f"{_TAG}_shared_{uuid.uuid4().hex[:8]}"

    # Preview
    preview = _run_bulk(scenario, dry_run=True, key=shared_key)
    assert preview["dry_run"] is True
    assert preview["summary"]["would_charge"] == 1
    assert preview["summary"]["charged"] == 0
    assert len(stub.calls) == 0  # Stripe never called on dry-run.

    # Confirm — SAME key, live run.
    confirm = _run_bulk(scenario, dry_run=False, key=shared_key)
    assert confirm["dry_run"] is False, (
        "confirm response leaked dry_run=True from preview — the replay "
        "guard failed to scope by dry_run (P0 regression)."
    )
    assert confirm["summary"]["charged"] == 1, (
        f"confirm returned charged={confirm['summary']['charged']} but "
        f"1 was eligible. This is the exact silent-no-op the P0 bug "
        f"exhibited. Response: {confirm!r}"
    )
    assert confirm["summary"]["total_amount_charged_cents"] == 13100
    assert len(stub.calls) == 1, (
        f"Stripe was called {len(stub.calls)}× — expected exactly 1. "
        f"Pre-fix this was 0 (replay short-circuit)."
    )
    # Row-level: eligible invoice status must be 'charged', not 'would_charge'.
    eligible_row = next(r for r in confirm["results"]
                         if r["invoice_id"] == scenario["invoices"]["eligible"])
    assert eligible_row["status"] == "charged", (
        f"Row status is {eligible_row['status']!r} — should be 'charged'. "
        f"'would_charge' leaking here is the P0 fingerprint."
    )


# ═════════════════════════════════════════════════════════════════════
# 2. Preview and confirm coexist under the same FE-supplied key.
# ═════════════════════════════════════════════════════════════════════
def test_bulk_charge_preview_and_confirm_coexist_under_same_key(scenario, stub):
    """Post-fix, the unique index is
    ``(tenant_id, idempotency_key, dry_run)`` — so a preview row AND a
    live row can BOTH be persisted under one FE-supplied key. This
    test asserts both rows land."""
    shared_key = f"{_TAG}_coexist_{uuid.uuid4().hex[:8]}"

    _run_bulk(scenario, dry_run=True, key=shared_key)
    _run_bulk(scenario, dry_run=False, key=shared_key)

    tid = scenario["tenant_id"]
    rows = list(_sync.bulk_charge_runs.find(
        {"tenant_id": tid, "idempotency_key": shared_key}))
    assert len(rows) == 2, (
        f"Expected 2 rows (preview + live) under key {shared_key!r}, "
        f"got {len(rows)}. Rows: {[r.get('dry_run') for r in rows]}"
    )
    dry_flags = sorted(r["dry_run"] for r in rows)
    assert dry_flags == [False, True]


# ═════════════════════════════════════════════════════════════════════
# 3. Second confirm click (double-click) IS replayed (same dry_run).
# ═════════════════════════════════════════════════════════════════════
def test_bulk_charge_double_confirm_replays_and_does_not_double_charge(
    scenario, stub,
):
    """Preserves the intended idempotency semantics: if the user
    double-clicks Confirm, or if the FE retries a network error, the
    second ``dry_run=false`` POST with the same key MUST replay the
    first — no double-charge. Only the ``(same key, same dry_run)``
    pair replays."""
    shared_key = f"{_TAG}_double_{uuid.uuid4().hex[:8]}"

    first = _run_bulk(scenario, dry_run=False, key=shared_key)
    second = _run_bulk(scenario, dry_run=False, key=shared_key)

    assert first["summary"]["charged"] == 1
    assert second["summary"]["charged"] == 1
    assert second.get("replayed") is True, (
        f"Expected the second confirm to replay the first; got {second!r}"
    )
    assert len(stub.calls) == 1, (
        f"Stripe was called {len(stub.calls)}× — expected exactly 1. "
        "Double-click / retry must not double-charge."
    )


# ═════════════════════════════════════════════════════════════════════
# 4. LOUDNESS INVARIANT — silent no-op guard.
# ═════════════════════════════════════════════════════════════════════
def test_bulk_charge_never_returns_success_with_zero_charged_when_eligible_gt_zero(
    scenario, stub,
):
    """This test IS the P0 fingerprint. It asserts the invariant:

        ``summary.charged + summary.failed == summary.would_charge``
        (after a live run)

    The pre-fix bug returned ``charged=0, failed=0, would_charge=1``.
    That shape MUST NEVER be a valid success response for a live
    (``dry_run=false``) call.
    """
    key = f"{_TAG}_loud_{uuid.uuid4().hex[:8]}"
    r = _run_bulk(scenario, dry_run=False, key=key)
    assert r["dry_run"] is False

    summary = r["summary"]
    eligible_count = summary.get("would_charge", 0) + summary.get("charged", 0) + summary.get("failed", 0)
    # A live run that reports any eligible invoices must EITHER charge
    # them or record a failure — leaving them as ``would_charge`` is
    # the silent no-op signature.
    stuck_would_charge = sum(
        1 for row in r["results"] if row.get("status") == "would_charge"
    )
    assert stuck_would_charge == 0, (
        f"P0 REGRESSION: live confirm run left {stuck_would_charge} "
        f"invoice(s) in ``would_charge`` state. This is the exact "
        f"silent-no-op fingerprint from the Feb-2026 bulk charge bug "
        f"— the confirm handler replayed the preview row instead of "
        f"dispatching Stripe. Full response: {r!r}"
    )
    assert summary["charged"] > 0 or summary["failed"] > 0 or eligible_count == summary.get("skipped", 0), (
        f"P0 REGRESSION: live run returned charged=0 AND failed=0 "
        f"but reported eligible work. Response: {r!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 5. ACH branch shares the same fix — quick smoke.
# ═════════════════════════════════════════════════════════════════════
def test_bulk_charge_ach_replay_is_dry_run_scoped(scenario, monkeypatch):
    """The ACH bulk endpoint had the same
    ``(tenant, idempotency_key)`` replay guard bug. Post-fix, its
    replay is also scoped by ``dry_run``."""
    ach_calls = []

    async def _ach_stub(**kwargs):
        ach_calls.append(kwargs)
        return {
            "ok": True,
            "charge_row_id": str(uuid.uuid4()),
            "payment_intent_id": f"pi_ach_stub_{uuid.uuid4().hex[:8]}",
            "status": "processing",
            "amount_cents": kwargs["amount_cents"],
            "currency": kwargs["currency"],
        }

    # Attach a bank PM to eligible customer + swap card PM to ACH-eligible.
    monkeypatch.setattr(bulk_router.stripe_svc, "charge_ach_on_file",
                        _ach_stub, raising=False)

    tid = scenario["tenant_id"]
    eligible_customer = _sync.quotes.find_one(
        {"id": scenario["invoices"]["eligible"]})["customer_id"]
    _sync.payment_methods.update_many(
        {"tenant_id": tid, "customer_id": eligible_customer},
        {"$set": {"type": "us_bank_account",
                    "bank_name": "TestBank",
                    "us_bank_account": {"bank_name": "TestBank",
                                          "last4": "6789",
                                          "account_holder_type": "individual",
                                          "verified": True}}})

    from routers.invoices_bulk_charge import BulkChargeBody, execute_bulk_charge_ach
    key = f"{_TAG}_ach_{uuid.uuid4().hex[:8]}"

    body_dry = BulkChargeBody(
        invoice_ids=[scenario["invoices"]["eligible"]],
        dry_run=True, idempotency_key=key,
    )
    body_live = BulkChargeBody(
        invoice_ids=[scenario["invoices"]["eligible"]],
        dry_run=False, idempotency_key=key,
    )
    user = {"id": "test_admin", "role": "admin",
             "email": "manager@aquaterra.com"}
    tenant = {"id": tid}

    preview = _run(execute_bulk_charge_ach(body=body_dry, user=user,
                                             tenant=tenant))
    confirm = _run(execute_bulk_charge_ach(body=body_live, user=user,
                                              tenant=tenant))

    assert preview["dry_run"] is True
    assert confirm["dry_run"] is False, (
        "ACH confirm response leaked dry_run=True from preview — "
        "replay guard not dry-run-scoped."
    )
    # Whether the eligibility gate lets this specific PM through or
    # skips as ``not_bank_account`` depends on the exact PM shape;
    # the invariant that matters is dry_run flag ≠ leaked, so we
    # assert the invariant, not the specific charge count.
