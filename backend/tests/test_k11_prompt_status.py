"""Phase K11 · Feb-2026 — Portal payment-method prompt tests."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    for mod in ("routers.portal_payment_prompt",):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)[
        os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}


async def _seed_customer(tid: str, *, tag: str) -> Dict[str, Any]:
    from utils import now_iso
    cid = f"k11-cust-{tag}-{uuid.uuid4().hex[:6]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid, "name": f"K11 Cust {tag}",
        "email": f"{tag}@k11.example", "created_at": now_iso(),
    })
    return {"customer_id": cid,
             "user": {"id": f"k11-user-{tag}", "role": "customer",
                       "customer_id": cid, "name": f"K11 Cust {tag}",
                       "email": f"{tag}@k11.example", "tenant_id": tid}}


async def _seed_card_by_month(tid: str, cid: str, *,
                                exp_month: int, exp_year: int,
                                brand: str = "Visa",
                                last4: str = "4242") -> None:
    await _db().payment_methods.insert_one({
        "id": f"pm-{uuid.uuid4().hex[:8]}",
        "tenant_id": tid, "customer_id": cid,
        "provider": "stripe",
        "provider_payment_method_id": f"pm_test_{uuid.uuid4().hex[:12]}",
        "type": "card",
        "brand": brand, "last4": last4,
        "exp_month": exp_month, "exp_year": exp_year,
        "is_default": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _seed_ach(tid: str, cid: str) -> None:
    await _db().payment_methods.insert_one({
        "id": f"pm-ach-{uuid.uuid4().hex[:8]}",
        "tenant_id": tid, "customer_id": cid,
        "provider": "stripe",
        "provider_payment_method_id": f"pm_ach_{uuid.uuid4().hex[:12]}",
        "type": "us_bank_account",
        "bank_name": "Test Bank", "last4": "6789",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _drain(_tid: str) -> None:
    for coll in ("customers", "payment_methods",
                 "payment_prompt_snoozes"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k11-"}},
                {"customer_id": {"$regex": "^k11-cust-"}},
                {"id": {"$regex": "^pm-"}},
                {"id": {"$regex": "^pm-ach-"}},
            ],
        })


# 1. Zero cards → missing.
def test_k11_missing_when_no_cards():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="a")
        try:
            from routers.portal_payment_prompt import prompt_status
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "missing", r
            assert r["expiring_cards"] == []
            assert r["snoozed_until"] is None
        finally:
            await _drain(tid)
    _run(_go())


# 2. Card whose first-of-next-month is within 30 days → expiring
#    with a valid days count.  (Card exp_month = current month, exp_year
#    = current year → first-of-next-month is 1st of next month → 1-31
#    days out, always inside the 30-day window.)
def test_k11_expiring_when_card_within_30_days():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="b")
        try:
            today = datetime.now(timezone.utc).date()
            await _seed_card_by_month(tid, seed["customer_id"],
                                        exp_month=today.month,
                                        exp_year=today.year)
            from routers.portal_payment_prompt import prompt_status
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "expiring", r
            assert len(r["expiring_cards"]) == 1
            row = r["expiring_cards"][0]
            assert 0 < row["days_until_expiry"] <= 31, row
            assert row["brand"] == "Visa"
            assert row["last4"] == "4242"
        finally:
            await _drain(tid)
    _run(_go())


# 3. Card whose first-of-next-month is > 90 days away → none.
#    (Card exp_month = current month + 3 → first-of-next-month is ~4
#    months / ~120 days out.)
def test_k11_none_when_card_beyond_window():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="c")
        try:
            today = datetime.now(timezone.utc).date()
            year = today.year
            month = today.month + 3
            while month > 12:
                month -= 12
                year += 1
            await _seed_card_by_month(tid, seed["customer_id"],
                                        exp_month=month, exp_year=year)
            from routers.portal_payment_prompt import prompt_status
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "none", r
            assert r["expiring_cards"] == []
        finally:
            await _drain(tid)
    _run(_go())


# 4. ACH-only setup → missing (ACH is ignored for K11).
def test_k11_ach_only_counted_as_missing():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="d")
        try:
            await _seed_ach(tid, seed["customer_id"])
            from routers.portal_payment_prompt import prompt_status
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "missing", r
        finally:
            await _drain(tid)
    _run(_go())


# 5. Snooze POST creates a row with expires_at = snoozed_at + 24h.
def test_k11_snooze_creates_row():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="e")
        try:
            from routers.portal_payment_prompt import (
                prompt_snooze, SnoozeBody,
            )
            resp = await prompt_snooze(SnoozeBody(kind="missing"),
                                        user=seed["user"],
                                        tenant=await _tenant_dep(tid))
            row = await _db().payment_prompt_snoozes.find_one(
                {"customer_id": seed["customer_id"]}, {"_id": 0},
            )
            assert row is not None
            snoozed_at = datetime.fromisoformat(row["snoozed_at"])
            expires_at = datetime.fromisoformat(row["expires_at"])
            delta = (expires_at - snoozed_at).total_seconds()
            # 24h ± 1s tolerance for the microsecond drift between the
            # two ``datetime.now`` reads inside the router body.
            assert 86400 - 5 <= delta <= 86400 + 5, delta
            assert resp["snoozed_until"] == row["expires_at"]
            assert "via_impersonation" not in row
        finally:
            await _drain(tid)
    _run(_go())


# 6. After valid snooze, prompt-status returns none + snoozed_until.
def test_k11_snooze_silences_modal():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="f")
        try:
            from routers.portal_payment_prompt import (
                prompt_snooze, prompt_status, SnoozeBody,
            )
            snooze = await prompt_snooze(
                SnoozeBody(kind="missing"),
                user=seed["user"],
                tenant=await _tenant_dep(tid),
            )
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "none", r
            assert r["snoozed_until"] == snooze["snoozed_until"]
            assert r["original_prompt_kind"] == "missing"
        finally:
            await _drain(tid)
    _run(_go())


# 7. Expired snooze — status returns original evaluation.
def test_k11_expired_snooze_returns_original_kind():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="g")
        try:
            # Insert an already-expired snooze row directly.
            past = datetime.now(timezone.utc) - timedelta(hours=25)
            await _db().payment_prompt_snoozes.insert_one({
                "id": f"k11-snooze-{uuid.uuid4().hex[:6]}",
                "tenant_id": tid,
                "customer_id": seed["customer_id"],
                "kind": "missing",
                "snoozed_at": (past - timedelta(hours=24)).isoformat(),
                "expires_at": past.isoformat(),
            })
            from routers.portal_payment_prompt import prompt_status
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "missing", r
            assert r["snoozed_until"] is None
        finally:
            await _drain(tid)
    _run(_go())


# 8. Impersonation snooze — stamped with via_impersonation and does
#    NOT silence the real customer's own status.
def test_k11_impersonation_snooze_does_not_affect_real_customer():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed_customer(tid, tag="h")
        try:
            from routers.portal_payment_prompt import (
                prompt_snooze, prompt_status, SnoozeBody,
            )
            imp_user = dict(seed["user"])
            imp_user["is_impersonated"] = True
            imp_user["impersonator_id"] = "k11-admin-99"
            resp = await prompt_snooze(
                SnoozeBody(kind="missing"),
                user=imp_user,
                tenant=await _tenant_dep(tid),
            )
            assert resp["via_impersonation"] is True
            row = await _db().payment_prompt_snoozes.find_one(
                {"customer_id": seed["customer_id"]}, {"_id": 0},
            )
            assert row["via_impersonation"] is True
            assert row["acting_admin_id"] == "k11-admin-99"

            # Real customer session: status is still "missing" —
            # the impersonation snooze does not silence them.
            r = await prompt_status(user=seed["user"],
                                     tenant=await _tenant_dep(tid))
            assert r["prompt_kind"] == "missing", r
            assert r["snoozed_until"] is None
            assert r["is_impersonated"] is False

            # Meanwhile the impersonating admin's own session DOES see
            # the snooze so they don't get spammed while auditing.
            r_imp = await prompt_status(user=imp_user,
                                         tenant=await _tenant_dep(tid))
            assert r_imp["prompt_kind"] == "none"
            assert r_imp["snoozed_until"] == row["expires_at"]
            assert r_imp["is_impersonated"] is True
        finally:
            await _drain(tid)
    _run(_go())
