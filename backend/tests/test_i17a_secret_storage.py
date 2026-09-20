"""Phase I1.7.a · Feb-2026 — Encrypted secret storage contract lock.

Direct tests against ``services.secrets.{crypto,store}`` — the
encryption boundary. If any assertion in this file fails, the
plaintext-never-leaves-the-boundary contract is broken.
"""
from __future__ import annotations

import asyncio
import base64
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
from services.secrets import (  # noqa: E402
    connection_summary,
    get_secret,
    list_connections,
    log_error,
    put_secret,
    remove_secret,
)
from services.secrets.crypto import (  # noqa: E402
    EncryptedRecord,
    MasterKeyUnavailable,
    SecretCryptoError,
    decrypt,
    encrypt,
    last_4,
)
from services.secrets.models import ConnectionStatus, ConnectionType  # noqa: E402


def _drive(coro_factory):
    """Fresh motor client per event loop — see rationale in
    ``test_i15d_theme_migration``."""
    async def _wrap():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()
    return asyncio.run(_wrap())


# ── crypto.py ────────────────────────────────────────────────────
class TestCryptoPrimitives:
    def test_roundtrip_direct_kek(self):
        rec = encrypt("sk_test_deadbeef_supersecret_1234")
        assert isinstance(rec, EncryptedRecord)
        assert rec.encrypted_blob and rec.iv and rec.auth_tag
        # Sanity: base64 fields decode to right lengths.
        assert len(base64.b64decode(rec.iv)) == 12
        assert len(base64.b64decode(rec.auth_tag)) == 16
        # Direct-KEK path — no wrapped DEK.
        assert rec.dek_wrapped is None or rec.dek_wrapped == ""
        pt = decrypt(rec)
        assert pt == "sk_test_deadbeef_supersecret_1234"

    def test_ciphertext_differs_across_encryptions(self):
        """Nonce is fresh each time — ciphertext must differ."""
        a = encrypt("same-plaintext")
        b = encrypt("same-plaintext")
        assert a.encrypted_blob != b.encrypted_blob
        assert a.iv != b.iv
        # Both still decrypt.
        assert decrypt(a) == "same-plaintext"
        assert decrypt(b) == "same-plaintext"

    def test_tampered_ciphertext_raises(self):
        rec = encrypt("secret-payload")
        # Flip one byte in the ciphertext.
        raw = bytearray(base64.b64decode(rec.encrypted_blob))
        raw[0] ^= 0x01
        tampered = EncryptedRecord(
            encrypted_blob=base64.b64encode(bytes(raw)).decode(),
            iv=rec.iv, auth_tag=rec.auth_tag, dek_wrapped=rec.dek_wrapped,
        )
        with pytest.raises(SecretCryptoError):
            decrypt(tampered)

    def test_missing_kek_env_raises(self, monkeypatch):
        monkeypatch.delenv("SECRETS_MASTER_KEY", raising=False)
        with pytest.raises(MasterKeyUnavailable):
            encrypt("won't happen")

    def test_wrapped_dek_path_roundtrips(self, monkeypatch):
        monkeypatch.setenv("SECRETS_DIRECT_KEK", "0")
        rec = encrypt("wrapped-secret")
        assert rec.dek_wrapped, "wrapped-DEK mode should populate dek_wrapped"
        assert decrypt(rec) == "wrapped-secret"

    def test_last_4_never_returns_more_than_4(self):
        assert last_4("sk_test_abcdefghijklmnop") == "mnop"
        assert last_4("abc") == ""    # too short → empty (no partial leak)
        assert last_4("") == ""


# ── store.py ─────────────────────────────────────────────────────
@pytest.fixture
def temp_tenants():
    a = f"i17a-t-a-{uuid.uuid4().hex}"
    b = f"i17a-t-b-{uuid.uuid4().hex}"
    yield {"a": a, "b": b}
    _sync.tenant_secrets.delete_many({"tenant_id": {"$in": [a, b]}})


class TestSecretStore:
    def test_put_get_roundtrip(self, temp_tenants):
        tid = temp_tenants["a"]
        secret = f"sk_test_secret_{uuid.uuid4().hex}"
        _drive(lambda db: put_secret(
            tid, "stripe", secret,
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
            connected_account_id="acct_test_abc123",
            db=db))
        got = _drive(lambda db: get_secret(tid, "stripe", db=db, touch=False))
        assert got == secret

    def test_plaintext_never_persisted(self, temp_tenants):
        """The persisted row MUST NOT contain the plaintext anywhere.
        Scan every field — this is the highest-priority guardrail."""
        tid = temp_tenants["a"]
        secret = f"sk_test_never_persisted_{uuid.uuid4().hex}"
        _drive(lambda db: put_secret(
            tid, "stripe", secret,
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
            db=db))
        row = _sync.tenant_secrets.find_one({"tenant_id": tid})
        assert row is not None
        # Serialize the entire row and grep for the plaintext.
        import json
        blob = json.dumps({k: v for k, v in row.items() if k != "_id"})
        assert secret not in blob, "plaintext leaked into persisted row"
        # last_4 IS allowed (that's the whole point).
        assert row["last_4"] == secret[-4:]

    def test_rotation_overwrites_atomically(self, temp_tenants):
        tid = temp_tenants["a"]
        _drive(lambda db: put_secret(
            tid, "stripe", "old-secret-value-12345",
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT, db=db))
        # Grab the original blob to compare after rotation.
        row1 = _sync.tenant_secrets.find_one({"tenant_id": tid, "provider_key": "stripe"})
        assert row1["last_4"] == "2345"
        _drive(lambda db: put_secret(
            tid, "stripe", "new-secret-value-99999",
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT, db=db))
        row2 = _sync.tenant_secrets.find_one({"tenant_id": tid, "provider_key": "stripe"})
        # Same document id (upserted) but blob rotated.
        assert row2["id"] == row1["id"]
        assert row2["last_4"] == "9999"
        assert row2["encrypted_blob"] != row1["encrypted_blob"]
        # Cannot recover the old plaintext.
        got = _drive(lambda db: get_secret(tid, "stripe", db=db, touch=False))
        assert got == "new-secret-value-99999"

    def test_cross_tenant_isolation(self, temp_tenants):
        _drive(lambda db: put_secret(
            temp_tenants["a"], "stripe", "tenant-a-secret",
            connection_type=ConnectionType.API_KEY, db=db))
        _drive(lambda db: put_secret(
            temp_tenants["b"], "stripe", "tenant-b-secret",
            connection_type=ConnectionType.API_KEY, db=db))
        a = _drive(lambda db: get_secret(temp_tenants["a"], "stripe", db=db, touch=False))
        b = _drive(lambda db: get_secret(temp_tenants["b"], "stripe", db=db, touch=False))
        assert a == "tenant-a-secret"
        assert b == "tenant-b-secret"

    def test_remove_returns_true_only_on_hit(self, temp_tenants):
        tid = temp_tenants["a"]
        _drive(lambda db: put_secret(
            tid, "stripe", "will-be-removed",
            connection_type=ConnectionType.API_KEY, db=db))
        first = _drive(lambda db: remove_secret(tid, "stripe", db=db))
        second = _drive(lambda db: remove_secret(tid, "stripe", db=db))
        assert first is True
        assert second is False
        # get_secret now returns None.
        got = _drive(lambda db: get_secret(tid, "stripe", db=db, touch=False))
        assert got is None

    def test_list_connections_never_returns_plaintext(self, temp_tenants):
        tid = temp_tenants["a"]
        _drive(lambda db: put_secret(
            tid, "stripe", "supersecret-token-abcdef",
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
            connected_account_id="acct_abc123def456", db=db))
        summaries = _drive(lambda db: list_connections(tid, db=db))
        import json
        blob = json.dumps([s.model_dump() for s in summaries])
        assert "supersecret" not in blob
        assert "token-abcdef" not in blob
        # Summary shape — masked account id + last_4 + connected flag.
        s = summaries[0]
        assert s.provider_key == "stripe"
        assert s.connected is True
        assert s.last_4 == "cdef"
        assert s.connected_account_id_masked is not None
        assert "…" in (s.connected_account_id_masked or "")

    def test_log_error_marks_error_status_and_caps_log(self, temp_tenants):
        tid = temp_tenants["a"]
        _drive(lambda db: put_secret(
            tid, "stripe", "will-fail",
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT, db=db))
        # Push 25 errors → tail must be capped at 20.
        for i in range(25):
            _drive(lambda db, i=i: log_error(
                tid, "stripe", code=f"E{i}",
                message=f"failure #{i}", db=db))
        row = _sync.tenant_secrets.find_one({"tenant_id": tid, "provider_key": "stripe"})
        assert len(row["error_log"]) == 20
        # Last entry is the most recent.
        assert row["error_log"][-1]["code"] == "E24"
        assert row["connected_status"] == ConnectionStatus.ERROR.value
        # connection_summary reflects the tail error.
        s = _drive(lambda db: connection_summary(tid, "stripe", db=db))
        assert s.error_log_count == 20
        assert s.last_error is not None
        assert s.last_error["code"] == "E24"
