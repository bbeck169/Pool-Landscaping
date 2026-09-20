"""Phase I1.7.b · Feb-2026 — Extended secret-storage guarantees.

Covers the invariants specific to messaging providers (JSON-blob
plaintext + belt-and-braces plaintext-never-in-DB check).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = _shared_db()
from services.messaging._helpers import (  # noqa: E402
    load_provider_config,
    save_provider_config,
)
from services.messaging.email.registry import get_email_provider, reset_cache_for_tests  # noqa: E402
from services.messaging.models import InvalidProviderConfig  # noqa: E402


TENANT = f"i17b-storage-{uuid.uuid4().hex[:8]}"


def _run(coro):
    return asyncio.run(coro)


def _drive(fn):
    async def wrap():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await fn(db)
        finally:
            client.close()
    return asyncio.run(wrap())


@pytest.fixture(autouse=True)
def _clean():
    reset_cache_for_tests()
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})
    yield
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})


def test_multi_field_config_roundtrips_through_encryption():
    provider = get_email_provider("smtp")
    schema = provider.config_fields
    original = {
        "host": "smtp.example.com", "port": 587,
        "username": "hello@example.com",
        "password": "super-sneaky-pw-DO-NOT-LEAK-9876",
        "from_addr": "hello@example.com",
        "use_tls": True,
    }
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key="smtp",
        config=original, schema=schema, db=db,
    ))
    loaded = _drive(lambda db: load_provider_config(
        tenant_id=TENANT, provider_key="smtp", db=db,
    ))
    assert loaded == original


def test_plaintext_password_never_present_in_stored_document():
    provider = get_email_provider("smtp")
    schema = provider.config_fields
    marker = f"MARKER_PLAINTEXT_{uuid.uuid4().hex}"
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key="smtp",
        config={
            "host": "smtp.example.com", "port": 587,
            "username": "u", "password": marker,
            "from_addr": "hello@example.com",
        },
        schema=schema, db=db,
    ))
    row = _sync.tenant_secrets.find_one({"tenant_id": TENANT, "provider_key": "smtp"})
    # Scan every stringifiable field for the marker.
    serialised = json.dumps(row, default=str)
    assert marker not in serialised, "plaintext leaked into stored document"


def test_missing_required_field_raises_invalid_config():
    provider = get_email_provider("smtp")
    schema = provider.config_fields
    with pytest.raises(InvalidProviderConfig) as ei:
        _drive(lambda db: save_provider_config(
            tenant_id=TENANT, provider_key="smtp",
            config={"host": "smtp.example.com"},  # missing everything else
            schema=schema, db=db,
        ))
    # Error message names each missing field but NOT any provided value.
    msg = str(ei.value)
    for field in ("port", "username", "password", "from_addr"):
        assert field in msg
    assert "smtp.example.com" not in msg  # provided values never echoed


def test_rotation_overwrites_prior_plaintext():
    provider = get_email_provider("smtp")
    schema = provider.config_fields
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key="smtp",
        config={"host": "h", "port": 587, "username": "u",
                "password": "old-secret", "from_addr": "a@example.com"},
        schema=schema, db=db,
    ))
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key="smtp",
        config={"host": "h", "port": 587, "username": "u",
                "password": "new-secret", "from_addr": "a@example.com"},
        schema=schema, db=db,
    ))
    loaded = _drive(lambda db: load_provider_config(
        tenant_id=TENANT, provider_key="smtp", db=db,
    ))
    assert loaded["password"] == "new-secret"
    row = _sync.tenant_secrets.find_one({"tenant_id": TENANT, "provider_key": "smtp"})
    assert "old-secret" not in json.dumps(row, default=str)
