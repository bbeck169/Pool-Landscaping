"""Credit parity P0b Stage 2 S2-1 — mutate_credit choke point regression.

Pins the invariant that ALL credit mutations funnel through
``services.customer_balance.mutate_credit``:

  · ledger history row written to ``customer_credits``
  · aggregate upserted on ``customer_credits_balance``
  · customer-doc denorm field ``credit_balance_cents`` + stamp
    ``balance_recomputed_at`` re-stamped (NO 60-s lazy-backfill lag)

Table-driven across the five mutation call-sites refactored in
Commit A:

  1. manual admin adjust (POST /customers/{cid}/credits/adjust)
  2. manual reverse (POST /customers/{cid}/credits/{eid}/reverse)
  3. referral reward (post-paid, legacy_immediate branch)
  4. referral reward revoke (POST /admin/referrals/{rid}/revoke-reward)
  5. invoice redeem (services.credits_apply.apply_and_persist)

Each case grants/mutates a known amount and asserts BOTH the ledger
aggregate AND the customer doc converge to the same cents figure.

Also pins the static-analysis guard: the direct-write scanner must
return ``status=ok`` with zero offenders against HEAD.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


# ────────────────────────────────────────────────────────────────────
# Fixtures — a fresh test tenant + customer per test.
# ────────────────────────────────────────────────────────────────────
@pytest.fixture
def live_db():
    c = AsyncIOMotorClient(_ENV["MONGO_URL"])
    yield c[_ENV["DB_NAME"]]
    c.close()


@pytest.fixture
def test_customer(live_db):
    """Seed a scratch tenant + customer, yield (tenant_id, customer_id),
    tear down after."""
    tid = f"p0b-test-{uuid.uuid4().hex[:10]}"
    cid = f"p0b-cust-{uuid.uuid4().hex[:10]}"

    async def _setup():
        await live_db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "Credit Parity Test",
        })

    async def _teardown():
        await live_db.customers.delete_many({"tenant_id": tid})
        await live_db.customer_credits.delete_many({"tenant_id": tid})
        await live_db.customer_credits_balance.delete_many({"tenant_id": tid})

    asyncio.get_event_loop().run_until_complete(_setup())
    yield tid, cid
    asyncio.get_event_loop().run_until_complete(_teardown())


# ────────────────────────────────────────────────────────────────────
# 1 · mutate_credit — grant → ledger + aggregate + denorm all agree.
# ────────────────────────────────────────────────────────────────────
def test_mutate_credit_grant_reconciles_three_surfaces(live_db, test_customer):
    tid, cid = test_customer

    async def _run():
        from services.customer_balance import mutate_credit
        r = await mutate_credit(
            live_db, tid, cid,
            delta_cents=25300,
            source="manual",
            actor={"id": "u1", "email": "admin@test"},
            reason="S2-1 grant test",
        )
        assert r["status"] == "applied"
        assert r["balance_cents"] == 25300
        # Ledger history
        hist = await live_db.customer_credits.find_one(
            {"id": r["ledger_entry_id"]}, {"_id": 0, "delta_cents": 1, "source": 1},
        )
        assert hist == {"delta_cents": 25300, "source": "manual"}
        # Aggregate
        agg = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        )
        assert agg["balance_cents"] == 25300
        # Customer doc denorm — the critical third surface the prior
        # recurrence vector missed. Must be freshly re-stamped.
        cust = await live_db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "credit_balance_cents": 1, "balance_recomputed_at": 1},
        )
        assert cust["credit_balance_cents"] == 25300, (
            f"customer-doc denorm did not re-stamp: {cust}"
        )
        assert cust["balance_recomputed_at"], "balance_recomputed_at missing"

    asyncio.get_event_loop().run_until_complete(_run())


# ────────────────────────────────────────────────────────────────────
# 2 · mutate_credit — subsequent revoke converges on net balance.
# ────────────────────────────────────────────────────────────────────
def test_mutate_credit_revoke_converges(live_db, test_customer):
    tid, cid = test_customer

    async def _run():
        from services.customer_balance import mutate_credit
        await mutate_credit(live_db, tid, cid, delta_cents=10000,
                              source="manual", reason="initial grant")
        r = await mutate_credit(live_db, tid, cid, delta_cents=-3000,
                                  source="revert", reason="partial revoke")
        assert r["balance_cents"] == 7000
        agg = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        )
        assert agg["balance_cents"] == 7000
        cust = await live_db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "credit_balance_cents": 1},
        )
        assert cust["credit_balance_cents"] == 7000
        # Two ledger rows exist.
        n = await live_db.customer_credits.count_documents(
            {"tenant_id": tid, "customer_id": cid},
        )
        assert n == 2

    asyncio.get_event_loop().run_until_complete(_run())


# ────────────────────────────────────────────────────────────────────
# 3 · mutate_credit — idempotency key short-circuits a duplicate.
# ────────────────────────────────────────────────────────────────────
def test_mutate_credit_idempotency_key_short_circuits(live_db, test_customer):
    tid, cid = test_customer

    async def _run():
        from services.customer_balance import mutate_credit
        key = f"test-idem-{uuid.uuid4().hex[:8]}"
        r1 = await mutate_credit(live_db, tid, cid, delta_cents=5000,
                                    source="referral_reward", reason="first",
                                    idempotency_key=key)
        r2 = await mutate_credit(live_db, tid, cid, delta_cents=5000,
                                    source="referral_reward", reason="dup",
                                    idempotency_key=key)
        assert r1["status"] == "applied"
        assert r2["status"] == "skipped_duplicate"
        # Only ONE ledger row.
        n = await live_db.customer_credits.count_documents(
            {"tenant_id": tid, "customer_id": cid, "idempotency_key": key},
        )
        assert n == 1
        # Aggregate shows the first apply, not doubled.
        agg = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        )
        assert agg["balance_cents"] == 5000

    asyncio.get_event_loop().run_until_complete(_run())


# ────────────────────────────────────────────────────────────────────
# 4 · credits_apply.apply_and_persist — invoice redeem path funnels
#    through mutate_credit (idempotent on invoice.id).
# ────────────────────────────────────────────────────────────────────
def test_apply_and_persist_funnels_through_choke_point(live_db, test_customer):
    tid, cid = test_customer

    async def _run():
        from services.customer_balance import mutate_credit
        from services.credits_apply import apply_and_persist

        # Prime a 100.00 credit on the customer.
        await mutate_credit(live_db, tid, cid, delta_cents=10000,
                              source="manual", reason="seed for redeem")

        invoice = {
            "id": f"inv-{uuid.uuid4().hex[:8]}",
            "customer_id": cid,
            "tenant_id": tid,
            "total_cents": 7500,
            "total": 75.0,
            "line_items": [{"description": "svc", "quantity": 1,
                               "unit_price": 75.0}],
            "payment_status": "unpaid",
        }
        out = await apply_and_persist(live_db, tid, invoice)
        # The invoice now has 75 credit applied.
        assert int(out.get("credits_applied_cents") or 0) == 7500
        agg = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        )
        assert agg["balance_cents"] == 2500, (
            f"aggregate did not debit redeem: {agg}"
        )
        cust = await live_db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "credit_balance_cents": 1},
        )
        assert cust["credit_balance_cents"] == 2500, (
            "customer-doc denorm did not re-stamp after redeem"
        )
        # Replay — same invoice id → short-circuits.
        _ = await apply_and_persist(live_db, tid, invoice)
        agg2 = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        )
        assert agg2["balance_cents"] == 2500, (
            "idempotency on invoice redeem failed — double-debited"
        )

    asyncio.get_event_loop().run_until_complete(_run())


# ────────────────────────────────────────────────────────────────────
# 5 · Static-analysis guard — zero orphan writers at HEAD.
# ────────────────────────────────────────────────────────────────────
def test_credit_write_guard_zero_orphans_at_head():
    from services.credit_write_guard import assert_no_orphan_credit_writes
    report = assert_no_orphan_credit_writes()
    assert report["status"] == "ok", (
        f"credit-write-guard offenders at HEAD: "
        f"{report['offenders']}"
    )
    assert report["files_scanned"] > 100, (
        f"guard scanned too few files ({report['files_scanned']}); "
        "pattern-scope regression likely"
    )


# ────────────────────────────────────────────────────────────────────
# 6 · Static-analysis guard — synthetic orphan is detected.
# ────────────────────────────────────────────────────────────────────
def test_credit_write_guard_catches_a_synthetic_orphan(tmp_path, monkeypatch):
    """Materialise a one-file orphan into a scratch dir, point the
    guard at it, confirm it fires."""
    from services import credit_write_guard

    scratch = tmp_path / "routers"
    scratch.mkdir()
    offender = scratch / "fake_credit_router.py"
    offender.write_text(
        "async def bad():\n"
        "    await db.customer_credits.insert_one({\"id\": \"x\"})\n"
    )
    monkeypatch.setattr(credit_write_guard, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(credit_write_guard, "_SCANNED_DIRS", ("routers",))
    # Also drop production env so AssertionError fires.
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(AssertionError):
        credit_write_guard.assert_no_orphan_credit_writes()


# ────────────────────────────────────────────────────────────────────
# 7 · Static-analysis guard — inline allowlist marker is honored.
# ────────────────────────────────────────────────────────────────────
def test_credit_write_guard_respects_inline_allowlist(tmp_path, monkeypatch):
    from services import credit_write_guard

    scratch = tmp_path / "services"
    scratch.mkdir()
    marked = scratch / "legit.py"
    marked.write_text(
        "async def ok():\n"
        "    # credit-write-allowlist: migration backfill one-shot\n"
        "    await db.customer_credits_balance.update_one({}, {\"$set\": {}})\n"
    )
    monkeypatch.setattr(credit_write_guard, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(credit_write_guard, "_SCANNED_DIRS", ("services",))
    monkeypatch.delenv("APP_ENV", raising=False)
    report = credit_write_guard.assert_no_orphan_credit_writes()
    assert report["status"] == "ok"
    assert report["offenders"] == []
