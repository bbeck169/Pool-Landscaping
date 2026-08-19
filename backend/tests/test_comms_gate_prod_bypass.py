"""Feb-2026 P0 · Comms gate production-bypass tests.

Covers the revised policy in ``services/comms/gate.py::is_comm_allowed``:
  * ``APP_ENV=production`` → gate returns True (real customers are
    the intended recipients).
  * Any other ``APP_ENV`` → whitelist rule stays active
    (``is_demo_account=True`` required).
  * ``is_comm_allowed_sync`` is safe to call from within an already-
    running event loop (the previous ``asyncio.new_event_loop`` +
    ``run_until_complete`` pattern silently fail-closed).

Tests are self-contained — no external HTTP, no login flow. They
seed / clean up their own throwaway ``customers`` doc so the
existing conftest ``TEST_``-prefix purge sweeps it after the run.
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
_MONGO_URL = _ENV["MONGO_URL"]
_DB_NAME = _ENV["DB_NAME"]


def _fresh_db():
    """Return a Motor db bound to the current event loop.

    Each test that touches Mongo builds its own client because the
    conftest ``pytest_runtest_setup`` hook rebinds the shared Motor
    loop between tests; a per-test client sidesteps that dance
    entirely.
    """
    loop = asyncio.get_event_loop()
    client = AsyncIOMotorClient(_MONGO_URL, io_loop=loop)
    return client[_DB_NAME], client


TENANT_ID = "TEST_gate_bypass_tenant"


async def _seed_customer(db, *, email: str, is_demo: bool) -> str:
    cid = f"TEST_gate_bypass_{uuid.uuid4().hex[:8]}"
    await db.customers.insert_one({
        "id": cid,
        "tenant_id": TENANT_ID,
        "email": email,
        "name": f"TEST_gate_bypass {cid}",
        "is_demo_account": is_demo,
    })
    return cid


async def _cleanup(db) -> None:
    await db.customers.delete_many({"tenant_id": TENANT_ID})
    # Suppression rows written by the gate under our tenant.
    await db.comms_suppression_log.delete_many({"tenant_id": TENANT_ID})


@pytest.fixture(autouse=True)
def _restore_app_env(monkeypatch):
    """Ensure APP_ENV is restored between tests. The conftest env
    guard reads APP_ENV lazily on every call, so monkeypatching per
    test is safe."""
    original = os.environ.get("APP_ENV")
    yield
    if original is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = original


def test_preview_env_non_demo_customer_blocked(monkeypatch):
    """Preview env + is_demo_account=False → gate blocks (whitelist active)."""
    monkeypatch.setenv("APP_ENV", "preview")

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            cid = await _seed_customer(
                db, email=f"nondemo-{uuid.uuid4().hex[:6]}@example.com",
                is_demo=False,
            )
            # Reload gate module so is_production() reads fresh env.
            # (Not strictly needed — is_production reads os.environ
            # on every call — but exercise the import path.)
            from services.comms.gate import is_comm_allowed, current_gate_policy
            assert current_gate_policy() == "demo_only"
            allowed = await is_comm_allowed(
                recipient_identifier={"customer_id": cid,
                                       "email": "nondemo@example.com"},
                comm_type="email",
                tenant_id=TENANT_ID,
                provider="resend",
                trigger_action="unit_test",
            )
            assert allowed is False
        finally:
            await _cleanup(db)
            client.close()
    asyncio.get_event_loop().run_until_complete(_drive())


def test_preview_env_demo_customer_allowed(monkeypatch):
    """Preview env + is_demo_account=True → gate allows."""
    monkeypatch.setenv("APP_ENV", "preview")

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            cid = await _seed_customer(
                db, email=f"demo-{uuid.uuid4().hex[:6]}@example.com",
                is_demo=True,
            )
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier={"customer_id": cid},
                comm_type="email",
                tenant_id=TENANT_ID,
                provider="resend",
                trigger_action="unit_test",
            )
            assert allowed is True
        finally:
            await _cleanup(db)
            client.close()
    asyncio.get_event_loop().run_until_complete(_drive())


def test_production_env_non_demo_customer_allowed_prod_bypass(monkeypatch):
    """Production env + is_demo_account=False → gate allows (prod bypass)."""
    monkeypatch.setenv("APP_ENV", "production")

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            cid = await _seed_customer(
                db, email=f"real-{uuid.uuid4().hex[:6]}@example.com",
                is_demo=False,
            )
            from services.comms.gate import is_comm_allowed, current_gate_policy
            assert current_gate_policy() == "prod_bypass"
            allowed = await is_comm_allowed(
                recipient_identifier={"customer_id": cid,
                                       "email": "real@example.com"},
                comm_type="email",
                tenant_id=TENANT_ID,
                provider="resend",
                trigger_action="unit_test",
            )
            assert allowed is True
            # And confirm NO suppression row was written for the
            # prod-bypass path.
            n_suppr = await db.comms_suppression_log.count_documents(
                {"tenant_id": TENANT_ID}
            )
            assert n_suppr == 0
        finally:
            await _cleanup(db)
            client.close()
    asyncio.get_event_loop().run_until_complete(_drive())


def test_production_env_demo_customer_allowed(monkeypatch):
    """Production env + is_demo_account=True → gate allows (bypass hits
    before whitelist would even be consulted)."""
    monkeypatch.setenv("APP_ENV", "production")

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            cid = await _seed_customer(
                db, email=f"demo-{uuid.uuid4().hex[:6]}@example.com",
                is_demo=True,
            )
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier={"customer_id": cid},
                comm_type="email",
                tenant_id=TENANT_ID,
                provider="resend",
                trigger_action="unit_test",
            )
            assert allowed is True
        finally:
            await _cleanup(db)
            client.close()
    asyncio.get_event_loop().run_until_complete(_drive())


def test_sync_wrapper_safe_within_async_context(monkeypatch):
    """``is_comm_allowed_sync`` must NOT fail closed when called from
    within an already-running event loop (the prior
    ``asyncio.new_event_loop()`` implementation raised RuntimeError
    and the bare ``except`` returned False, silently blocking
    legitimate demo-account sends via the Resend SDK monkey-patch).

    We use ``APP_ENV=production`` so the gate short-circuits without
    a Mongo point-read (prod bypass path). This exercises the new
    worker-thread pattern end-to-end without depending on a seeded
    demo customer.
    """
    monkeypatch.setenv("APP_ENV", "production")

    from services.comms.gate import is_comm_allowed_sync

    async def _driver_running_loop():
        # We are inside a running loop right now. The sync wrapper
        # MUST still work here — this is the exact scenario the
        # Resend SDK monkey-patch triggers on any legacy caller that
        # ``await``s upstream and then reaches
        # ``resend.Emails.send(...)`` inline.
        return is_comm_allowed_sync(
            recipient_identifier="real@example.com",
            comm_type="email",
            tenant_id=TENANT_ID,
            provider="resend",
            trigger_action="unit_test_sync",
        )

    result = asyncio.get_event_loop().run_until_complete(
        _driver_running_loop()
    )
    assert result is True
