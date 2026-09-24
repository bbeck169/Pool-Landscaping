"""Phase P53 · Feb-2026 — Phase 10 behavior regression lockdown
(state-transition edition).

P53 explicitly does NOT modify the Phase-10 referral automation
(reward-on-30-day-paid-window). To keep the untouched machinery
truly untouched, we exercise the five critical invariants against
a real Mongo — every assertion inspects the collection state after
driving the SUT function, not the source text.

Invariants under lock:
  1. ``fire_referral_conversion_hook`` — on the default (non-legacy)
     branch, close-won flips ``referrals.status`` to
     ``pending_paid_window``; on the legacy-immediate branch, it
     flips to ``converted`` and mints a ``customer_credits`` ledger
     row with ``source == "referral_reward"``.
  2. ``_try_credit_referral`` — the status-guarded CAS transition
     (``pending_paid_window`` → ``crediting_in_progress``) blocks
     double credit issuance under concurrent invocation
     (``asyncio.gather``).
  3. Refund/dispute inside the 30-day window voids the referral
     BEFORE any credit is issued.
  4. Happy path writes to ``db.customer_credits`` with
     ``source == "referral_credit"``, increments
     ``db.customer_credits_balance``, and sets terminal status
     ``credited`` on the referral row.
  5. ``PAID_WINDOW_DAYS`` constant is 30. This ONE assertion stays as
     a constant check because 30 days IS the policy boundary — the
     literal is the contract.

Uses ``_phase34_asyncio.batch_safe_run`` for Motor loop consistency
(same pattern as ``test_p53_marketing_templates_upsert.py`` +
``test_p53_portal_my_referrals_count.py``).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from services.referral_watcher import (
    PAID_WINDOW_DAYS,
    _try_credit_referral,
)
from routers.referral_rewards import fire_referral_conversion_hook
from tests._phase34_asyncio import batch_safe_run as _run


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "p53_p10_"


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def scenario(dbc):
    """Yields a cleanup registry; teardown drops every P53-tagged row
    written during the test so we never leak state into the preview DB."""
    ids: dict = {
        "tenants": [], "customers": [], "referrals": [],
        "leads": [], "quotes": [], "stripe_events": [],
        "customer_credits": [], "customer_credits_balance": [],
        "promo_codes": [], "marketing_deliveries": [],
    }
    yield ids
    for coll, keys in ids.items():
        if not keys:
            continue
        # customer_credits_balance is keyed by (tenant_id, customer_id).
        if coll == "customer_credits_balance":
            for pair in keys:
                dbc[coll].delete_many({
                    "tenant_id": pair[0], "customer_id": pair[1],
                })
        else:
            dbc[coll].delete_many({"id": {"$in": keys}})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_tenant(dbc, scenario, *, legacy_immediate: bool = False) -> dict:
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid,
        "name": f"P53 Phase-10 Lock Test {tid}",
        "created_at": _now().isoformat(),
        "referral_reward_enabled": True,
        "referral_reward_amount": 25.00,
        "referral_reward_currency": "USD",
        "legacy_immediate_referral_credit": legacy_immediate,
    }
    dbc.tenants.insert_one(doc)
    scenario["tenants"].append(tid)
    return doc


def _seed_customer(dbc, scenario, *, tenant_id: str,
                    name: str, email: str = None,
                    phone: str = None) -> str:
    cid = f"{TAG}cust-{uuid.uuid4().hex[:8]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": name,
        "email": email,
        "phone": phone,
        "created_at": _now().isoformat(),
    })
    scenario["customers"].append(cid)
    return cid


def _seed_referral(dbc, scenario, *, tenant_id: str,
                    referrer_id: str, referred_id: str = None,
                    lead_id: str = None,
                    status: str = "pending_paid_window",
                    first_paid_days_ago: int = None,
                    friend_name: str = "Frankie Friend") -> str:
    rid = f"{TAG}ref-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": rid,
        "tenant_id": tenant_id,
        "referrer_customer_id": referrer_id,
        "referred_customer_id": referred_id,
        "converted_to_customer_id": referred_id,
        "lead_id": lead_id,
        "status": status,
        "friend_name": friend_name,
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    if first_paid_days_ago is not None:
        doc["first_paid_at"] = (
            _now() - timedelta(days=first_paid_days_ago)
        ).isoformat()
    dbc.referrals.insert_one(doc)
    scenario["referrals"].append(rid)
    return rid


def _seed_lead(dbc, scenario, *, tenant_id: str,
                referrer_id: str, email: str = "friend@x.test") -> str:
    lid = f"{TAG}lead-{uuid.uuid4().hex[:8]}"
    dbc.leads.insert_one({
        "id": lid,
        "tenant_id": tenant_id,
        "source": f"referral_from_customer:{referrer_id}",
        "email": email,
        "name": "Frankie Friend",
        "status": "closed_won",
        "created_at": _now().isoformat(),
    })
    scenario["leads"].append(lid)
    return lid


def _seed_paid_invoice(dbc, scenario, *, tenant_id: str,
                        customer_id: str,
                        paid_days_ago: int) -> str:
    qid = f"{TAG}quote-{uuid.uuid4().hex[:8]}"
    paid_at = (_now() - timedelta(days=paid_days_ago)).isoformat()
    dbc.quotes.insert_one({
        "id": qid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "status": "paid",
        "paid_at": paid_at,
        "created_at": paid_at,
    })
    scenario["quotes"].append(qid)
    return qid


def _seed_stripe_refund_event(dbc, scenario, *, tenant_id: str,
                                customer_id: str, at: datetime,
                                event_type: str = "charge.refunded") -> str:
    eid = f"{TAG}evt-{uuid.uuid4().hex[:8]}"
    dbc.stripe_events.insert_one({
        "id": eid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "event_type": event_type,
        "created_at": at.isoformat(),
    })
    scenario["stripe_events"].append(eid)
    return eid


def _drain_side_effect_ids(dbc, scenario, *, tenant_id: str,
                              referral_id: str) -> None:
    """After a SUT run, harvest ids of side-effect rows so cleanup
    catches them. Called at the end of each test after assertions."""
    for row in dbc.customer_credits.find(
        {"tenant_id": tenant_id, "referral_id": referral_id},
        {"_id": 0, "id": 1},
    ):
        scenario["customer_credits"].append(row["id"])
    for row in dbc.promo_codes.find(
        {"tenant_id": tenant_id, "metadata.referral_id": referral_id},
        {"_id": 0, "id": 1},
    ):
        scenario["promo_codes"].append(row["id"])
    for row in dbc.marketing_deliveries.find(
        {"tenant_id": tenant_id,
          "trigger_entity.referral_id": referral_id},
        {"_id": 0, "id": 1},
    ):
        scenario["marketing_deliveries"].append(row["id"])


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 1a — close-won hook, DEFAULT branch → pending_paid_window
# ═════════════════════════════════════════════════════════════════════
def test_close_won_hook_default_flips_referral_to_pending_paid_window(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario, legacy_immediate=False)
    referrer_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Rachel Referrer",
        email="rachel@example.test",
    )
    lead_id = _seed_lead(
        dbc, scenario, tenant_id=tenant["id"], referrer_id=referrer_id,
    )
    _seed_referral(
        dbc, scenario, tenant_id=tenant["id"],
        referrer_id=referrer_id, lead_id=lead_id,
        status="pending_conversion",  # pre-conversion state
    )
    new_cust_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Frankie Friend",
    )
    lead = dbc.leads.find_one({"id": lead_id}, {"_id": 0})

    res = _run(fire_referral_conversion_hook(
        tenant_id=tenant["id"], lead=lead, new_customer_id=new_cust_id,
    ))

    # Assert result payload.
    assert res.get("applied") is True or res.get("referral_id"), res
    # Assert Mongo state — the CRITICAL Phase-10 invariant.
    ref = dbc.referrals.find_one(
        {"tenant_id": tenant["id"], "lead_id": lead_id}, {"_id": 0},
    )
    assert ref is not None, "expected referral row to persist"
    assert ref["status"] == "pending_paid_window", (
        f"Phase-10 default branch regressed: got status={ref['status']!r}, "
        "expected pending_paid_window"
    )
    assert ref["converted_to_customer_id"] == new_cust_id
    assert ref["converted_at"], "converted_at must be stamped"
    # No ledger row should have been minted on the default branch.
    minted = dbc.customer_credits.count_documents({
        "tenant_id": tenant["id"], "referral_id": ref["id"],
    })
    assert minted == 0, (
        "default (non-legacy) branch minted a customer_credits row — "
        "this would double-credit against the 30-day watcher"
    )


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 1b — close-won hook, LEGACY branch → converted + ledger row
# ═════════════════════════════════════════════════════════════════════
def test_close_won_hook_legacy_branch_flips_to_converted_and_mints_ledger(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario, legacy_immediate=True)
    referrer_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Larry Legacy",
        email="larry@example.test",
    )
    lead_id = _seed_lead(
        dbc, scenario, tenant_id=tenant["id"], referrer_id=referrer_id,
    )
    _seed_referral(
        dbc, scenario, tenant_id=tenant["id"],
        referrer_id=referrer_id, lead_id=lead_id,
        status="pending_conversion",
    )
    new_cust_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Frankie Friend",
    )
    scenario["customer_credits_balance"].append(
        (tenant["id"], referrer_id),
    )
    lead = dbc.leads.find_one({"id": lead_id}, {"_id": 0})

    res = _run(fire_referral_conversion_hook(
        tenant_id=tenant["id"], lead=lead, new_customer_id=new_cust_id,
    ))

    ref = dbc.referrals.find_one(
        {"tenant_id": tenant["id"], "lead_id": lead_id}, {"_id": 0},
    )
    assert ref["status"] == "converted", (
        f"legacy_immediate branch regressed: got status={ref['status']!r}, "
        "expected converted"
    )
    assert ref.get("reward_applied_at"), (
        "legacy branch must stamp reward_applied_at when the tenant has "
        "referral_reward_enabled=True + amount>0"
    )
    # Ledger row minted with the legacy source tag.
    scenario["customer_credits"].append(ref["reward_transaction_id"])
    ledger = dbc.customer_credits.find_one(
        {"id": ref["reward_transaction_id"]}, {"_id": 0},
    )
    assert ledger is not None, "expected customer_credits row"
    assert ledger["source"] == "referral_reward"
    assert ledger["tenant_id"] == tenant["id"]
    assert ledger["customer_id"] == referrer_id
    assert ledger["referral_id"] == ref["id"]
    assert float(ledger["delta"]) == 25.00


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 2 — CAS guard blocks concurrent double-credit
# ═════════════════════════════════════════════════════════════════════
def test_watcher_cas_guard_blocks_concurrent_double_credit(dbc, scenario):
    tenant = _seed_tenant(dbc, scenario, legacy_immediate=False)
    referrer_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Rachel Referrer",
        email="rachel@example.test",
    )
    referred_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Frankie Friend",
    )
    rid = _seed_referral(
        dbc, scenario, tenant_id=tenant["id"],
        referrer_id=referrer_id, referred_id=referred_id,
        status="pending_paid_window",
        first_paid_days_ago=PAID_WINDOW_DAYS + 5,  # past the window
    )
    scenario["customer_credits_balance"].append(
        (tenant["id"], referrer_id),
    )

    async def _double_run():
        ref = await _fetch_ref(rid)
        # asyncio.gather cooperatively interleaves; Motor's update_one
        # is atomic on the server side, so exactly one of the two
        # coros will win the pending_paid_window→crediting_in_progress
        # CAS.
        return await asyncio.gather(
            _try_credit_referral(tenant, ref, 2500),
            _try_credit_referral(tenant, ref, 2500),
        )

    async def _fetch_ref(rid_: str):
        from config import db as _db
        return await _db.referrals.find_one({"id": rid_}, {"_id": 0})

    results = _run(_double_run())

    # Exactly one credited, one refused.
    credited_flags = [bool(r.get("credited")) for r in results]
    assert sum(credited_flags) == 1, (
        f"CAS guard regressed — got credited flags {credited_flags}; "
        f"full results: {results}"
    )
    losing = next(r for r in results if not r.get("credited"))
    assert losing.get("reason") in (
        "concurrent_or_already_credited", "waiting_window",
    ), f"unexpected loser reason: {losing}"

    # Exactly one ledger row minted.
    ledgers = list(dbc.customer_credits.find(
        {"tenant_id": tenant["id"], "referral_id": rid},
        {"_id": 0},
    ))
    assert len(ledgers) == 1, (
        f"CAS guard failed — {len(ledgers)} ledger rows minted for one "
        "referral (expected exactly 1)"
    )
    assert ledgers[0]["source"] == "referral_credit"

    # Referral terminal state.
    ref_after = dbc.referrals.find_one({"id": rid}, {"_id": 0})
    assert ref_after["status"] == "credited"

    _drain_side_effect_ids(
        dbc, scenario, tenant_id=tenant["id"], referral_id=rid,
    )


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 3 — refund inside 30-day window voids referral, no credit
# ═════════════════════════════════════════════════════════════════════
def test_refund_inside_window_voids_referral_and_blocks_credit(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario, legacy_immediate=False)
    referrer_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Rachel Referrer",
        email="rachel@example.test",
    )
    referred_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Frankie Friend",
    )
    rid = _seed_referral(
        dbc, scenario, tenant_id=tenant["id"],
        referrer_id=referrer_id, referred_id=referred_id,
        status="pending_paid_window",
        first_paid_days_ago=PAID_WINDOW_DAYS + 5,
    )
    # A refund landed 10 days after first_paid — INSIDE the 30-day
    # window.
    first_paid_dt = _now() - timedelta(days=PAID_WINDOW_DAYS + 5)
    refund_at = first_paid_dt + timedelta(days=10)
    _seed_stripe_refund_event(
        dbc, scenario, tenant_id=tenant["id"],
        customer_id=referred_id, at=refund_at,
        event_type="charge.refunded",
    )

    async def _drive():
        from config import db as _db
        ref = await _db.referrals.find_one({"id": rid}, {"_id": 0})
        return await _try_credit_referral(tenant, ref, 2500)

    res = _run(_drive())

    assert res.get("voided") is True, (
        f"F2 refund guard regressed — expected voided=True, got {res}"
    )
    assert res.get("reason") == "refunded"
    # Referral terminal state.
    ref_after = dbc.referrals.find_one({"id": rid}, {"_id": 0})
    assert ref_after["status"] == "voided"
    assert ref_after["voided_reason"] == "refunded"
    assert ref_after["voided_at"]
    # NO ledger row minted.
    minted = dbc.customer_credits.count_documents({
        "tenant_id": tenant["id"], "referral_id": rid,
    })
    assert minted == 0, (
        "refund guard failed — a customer_credits row was minted "
        "despite the refund inside the 30-day window"
    )
    # NO promo code minted either.
    promos = dbc.promo_codes.count_documents({
        "tenant_id": tenant["id"], "metadata.referral_id": rid,
    })
    assert promos == 0

    _drain_side_effect_ids(
        dbc, scenario, tenant_id=tenant["id"], referral_id=rid,
    )


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 4 — happy path writes ledger + balance + credited status
# ═════════════════════════════════════════════════════════════════════
def test_happy_path_writes_ledger_balance_and_flips_referral_to_credited(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario, legacy_immediate=False)
    referrer_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Rachel Referrer",
        email="rachel@example.test",
    )
    referred_id = _seed_customer(
        dbc, scenario, tenant_id=tenant["id"], name="Frankie Friend",
    )
    rid = _seed_referral(
        dbc, scenario, tenant_id=tenant["id"],
        referrer_id=referrer_id, referred_id=referred_id,
        status="pending_paid_window",
        first_paid_days_ago=PAID_WINDOW_DAYS + 5,
    )
    # Prime the balance cache so we can assert an increment.
    dbc.customer_credits_balance.update_one(
        {"tenant_id": tenant["id"], "customer_id": referrer_id},
        {"$set": {"balance_cents": 0, "balance": 0.0}},
        upsert=True,
    )
    scenario["customer_credits_balance"].append(
        (tenant["id"], referrer_id),
    )
    credit_cents = 2500  # $25.00

    async def _drive():
        from config import db as _db
        ref = await _db.referrals.find_one({"id": rid}, {"_id": 0})
        return await _try_credit_referral(tenant, ref, credit_cents)

    res = _run(_drive())

    assert res.get("credited") is True, (
        f"happy path regressed — {res}"
    )
    assert res.get("promo_code_id")
    assert res.get("ledger_id")

    # Ledger row shape.
    ledger = dbc.customer_credits.find_one({"id": res["ledger_id"]},
                                              {"_id": 0})
    assert ledger is not None, "expected the ledger row we just wrote"
    assert ledger["source"] == "referral_credit"
    assert ledger["tenant_id"] == tenant["id"]
    assert ledger["customer_id"] == referrer_id
    assert ledger["delta_cents"] == credit_cents
    assert ledger["referral_id"] == rid
    assert ledger["promo_code_id"] == res["promo_code_id"]

    # Balance incremented.
    bal = dbc.customer_credits_balance.find_one(
        {"tenant_id": tenant["id"], "customer_id": referrer_id},
        {"_id": 0},
    )
    assert bal["balance_cents"] == credit_cents
    assert abs(bal["balance"] - (credit_cents / 100.0)) < 1e-6

    # Referral row finalized.
    ref_after = dbc.referrals.find_one({"id": rid}, {"_id": 0})
    assert ref_after["status"] == "credited"
    assert ref_after["credited_at"]
    assert ref_after["credit_amount_cents"] == credit_cents
    assert ref_after["credited_promo_code_id"] == res["promo_code_id"]
    assert ref_after["eligible_at"]

    _drain_side_effect_ids(
        dbc, scenario, tenant_id=tenant["id"], referral_id=rid,
    )


# ═════════════════════════════════════════════════════════════════════
# INVARIANT 5 — 30-day window constant is the policy contract
# ═════════════════════════════════════════════════════════════════════
def test_paid_window_days_constant_is_30():
    """This ONE assertion intentionally stays a constant check
    because 30 days IS the policy boundary — the literal value is
    the contract with the F2 refund-protection window. If a future
    P-phase changes this, we WANT the test to fail so a human
    reviews the policy change."""
    assert PAID_WINDOW_DAYS == 30, (
        f"PAID_WINDOW_DAYS={PAID_WINDOW_DAYS} — Phase 10 F2 refund-"
        f"protection policy boundary changed (was 30). Requires "
        f"explicit human sign-off before merging."
    )
