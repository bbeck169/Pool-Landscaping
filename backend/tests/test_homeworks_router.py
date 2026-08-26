"""Phase 0 POC · Feb-2026 — Homeworks BYO-creds router tests.

Verifies:
  * super_admin gate (non-super gets 403).
  * GET redacts secrets (never returns encrypted / plaintext).
  * PUT persists an encrypted client_secret (not plaintext).
  * POST /connect returns 400 when creds are missing.
  * POST /connect returns an authorize_url when creds are present.
  * POST /test returns 400 when not connected.
  * POST /disconnect clears tokens without deleting client creds.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

os.environ.setdefault(
    "FERNET_KEY",
    "f2DlHrLPFFiF2HxLFglFEegS2pvke90APrHBSU_YGus=",
)

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# ── Fake Motor DB with __getitem__ and attr-access support ─────────
class _FakeCollection:
    def __init__(self):
        self.docs: list = []

    async def create_index(self, *a, **kw):
        return None

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                out = {k: v for k, v in d.items() if k != "_id"}
                return out
        return None

    async def find_one_and_delete(self, q):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                return self.docs.pop(i)
        return None

    async def insert_one(self, doc):
        self.docs.append({**doc})
        return type("_R", (), {"inserted_id": len(self.docs)})

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd:
                    d.update(upd["$set"])
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        if upsert and "$set" in upd:
            new_doc = dict(q)
            new_doc.update(upd["$set"])
            self.docs.append(new_doc)
            return type("_R", (), {"matched_count": 0, "modified_count": 0, "upserted_id": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


class _FakeDB:
    def __init__(self):
        self._collections: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]

    def __getattr__(self, name: str) -> _FakeCollection:
        # Motor supports both. Return a collection for any attr access
        # that isn't already an instance member.
        return self.__getitem__(name)


# ── Fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    monkeypatch.setattr("config.db", fdb, raising=False)
    # Patch the ``db`` symbol as-imported in the module under test.
    import services.homeworks_mcp_client as hw_mod
    monkeypatch.setattr(hw_mod, "db", fdb, raising=False)
    return fdb


@pytest.fixture
def super_admin_user():
    return {"id": "u-super", "tenant_id": "t-poc", "role": "super_admin"}


@pytest.fixture
def admin_user():
    return {"id": "u-admin", "tenant_id": "t-poc", "role": "admin"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Auth gate ───────────────────────────────────────────────────────
class TestAuthGate:
    def test_non_super_admin_gets_403_on_get(self, fake_db, admin_user):
        from routers.homeworks_integration import get_integration
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(get_integration(user=admin_user))
        assert exc.value.status_code == 403

    def test_non_super_admin_gets_403_on_save(self, fake_db, admin_user):
        from routers.homeworks_integration import save_integration
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(save_integration(
                HomeworksIntegrationCredsInput(client_id="x"), user=admin_user,
            ))
        assert exc.value.status_code == 403

    def test_non_super_admin_gets_403_on_connect(self, fake_db, admin_user):
        from routers.homeworks_integration import connect
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(connect(user=admin_user))
        assert exc.value.status_code == 403


# ── GET redaction ───────────────────────────────────────────────────
class TestGetRedactsSecrets:
    def test_get_empty_config_returns_shape_with_defaults(
        self, fake_db, super_admin_user,
    ):
        from routers.homeworks_integration import get_integration
        result = _run(get_integration(user=super_admin_user))
        assert result["tenant_id"] == "t-poc"
        assert result["client_id"] == ""
        assert result["has_client_secret"] is False
        assert result["connection_status"] == "disconnected"
        assert result["mcp_server_url"].startswith("https://")
        assert result["has_access_token"] is False
        assert result["has_refresh_token"] is False

    def test_get_hides_encrypted_fields(self, fake_db, super_admin_user):
        # Seed a doc with encrypted values.
        import services.homeworks_mcp_client as hw
        fake_db["homeworks_byo_integrations"].docs.append({
            "tenant_id": "t-poc",
            "client_id": "cid-1",
            "client_secret_encrypted": hw.encrypt("super-secret"),
            "access_token_encrypted": hw.encrypt("at-1"),
            "authorize_url": "https://a",
            "token_url": "https://t",
            "redirect_uri": "https://r/cb",
            "scopes": ["read"],
            "mcp_server_url": "https://mcp",
            "connection_status": "connected",
        })
        from routers.homeworks_integration import get_integration
        result = _run(get_integration(user=super_admin_user))
        # No secret / cipher text anywhere.
        as_str = str(result)
        assert "super-secret" not in as_str
        assert "at-1" not in as_str
        assert result["client_id"] == "cid-1"
        assert result["has_client_secret"] is True
        assert result["has_access_token"] is True


# ── PUT stores encrypted secret ─────────────────────────────────────
class TestSaveEncrypts:
    def test_put_stores_encrypted_client_secret(
        self, fake_db, super_admin_user,
    ):
        from routers.homeworks_integration import save_integration
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        body = HomeworksIntegrationCredsInput(
            client_id="cli-1",
            client_secret="plain-secret-value",
            authorize_url="https://a/oauth/authorize",
            token_url="https://a/oauth/token",
            redirect_uri="https://cb.example/cb",
            scopes=["read:customers"],
            mcp_server_url="https://mcp.home.works/mcp",
        )
        result = _run(save_integration(body, user=super_admin_user))
        assert result["client_id"] == "cli-1"
        assert result["has_client_secret"] is True
        # Response never carries plaintext secret.
        assert "plain-secret-value" not in str(result)
        # DB never stores plaintext secret.
        stored = fake_db["homeworks_byo_integrations"].docs[0]
        assert "plain-secret-value" not in str(stored)
        assert stored.get("client_secret_encrypted")
        assert stored["client_secret_encrypted"] != "plain-secret-value"

    def test_put_empty_string_secret_keeps_existing(
        self, fake_db, super_admin_user,
    ):
        from routers.homeworks_integration import save_integration
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        import services.homeworks_mcp_client as hw
        # Seed a doc with an existing encrypted secret.
        original = hw.encrypt("existing-secret")
        fake_db["homeworks_byo_integrations"].docs.append({
            "tenant_id": "t-poc",
            "client_id": "cli-1",
            "client_secret_encrypted": original,
        })
        # Update with empty client_secret string → keep existing.
        body = HomeworksIntegrationCredsInput(
            client_id="cli-1-renamed", client_secret="",
        )
        _run(save_integration(body, user=super_admin_user))
        stored = fake_db["homeworks_byo_integrations"].docs[0]
        assert stored["client_id"] == "cli-1-renamed"
        assert stored["client_secret_encrypted"] == original


# ── /connect flow ───────────────────────────────────────────────────
class TestConnect:
    def test_connect_returns_400_when_no_creds(self, fake_db, super_admin_user):
        from routers.homeworks_integration import connect
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(connect(user=super_admin_user))
        assert exc.value.status_code == 400
        assert "missing_credentials" in exc.value.detail

    def test_connect_returns_400_when_partial_creds(
        self, fake_db, super_admin_user,
    ):
        # Save only client_id — missing authorize_url etc.
        from routers.homeworks_integration import save_integration, connect
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        from fastapi import HTTPException
        _run(save_integration(
            HomeworksIntegrationCredsInput(client_id="cid"),
            user=super_admin_user,
        ))
        with pytest.raises(HTTPException) as exc:
            _run(connect(user=super_admin_user))
        assert exc.value.status_code == 400
        assert "authorize_url" in exc.value.detail
        assert "token_url" in exc.value.detail
        assert "redirect_uri" in exc.value.detail

    def test_connect_returns_authorize_url_with_full_creds(
        self, fake_db, super_admin_user,
    ):
        from routers.homeworks_integration import save_integration, connect
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        _run(save_integration(HomeworksIntegrationCredsInput(
            client_id="cli-1",
            authorize_url="https://a/oauth/authorize",
            token_url="https://a/oauth/token",
            redirect_uri="https://cb.example/cb",
            scopes=["read"],
        ), user=super_admin_user))
        result = _run(connect(user=super_admin_user))
        assert "authorize_url" in result
        assert result["authorize_url"].startswith(
            "https://a/oauth/authorize?",
        )
        assert "client_id=cli-1" in result["authorize_url"]
        assert result["state"]
        # State was persisted for later callback consumption.
        states = fake_db["homeworks_byo_oauth_states"].docs
        assert any(s["state"] == result["state"] for s in states)


# ── /test smoke — not connected returns 400 ────────────────────────
class TestSmokeGate:
    def test_test_returns_400_when_no_creds(self, fake_db, super_admin_user):
        from routers.homeworks_integration import smoke_test
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(smoke_test(user=super_admin_user))
        assert exc.value.status_code == 400
        assert exc.value.detail == "not_connected"

    def test_test_returns_400_when_creds_but_no_tokens(
        self, fake_db, super_admin_user,
    ):
        from routers.homeworks_integration import save_integration, smoke_test
        from homeworks_integration_models import HomeworksIntegrationCredsInput
        from fastapi import HTTPException
        _run(save_integration(HomeworksIntegrationCredsInput(
            client_id="cli-1",
            authorize_url="https://a/oauth/authorize",
            token_url="https://a/oauth/token",
            redirect_uri="https://cb/cb",
        ), user=super_admin_user))
        with pytest.raises(HTTPException) as exc:
            _run(smoke_test(user=super_admin_user))
        assert exc.value.status_code == 400


# ── /disconnect clears tokens only ─────────────────────────────────
class TestDisconnect:
    def test_disconnect_clears_tokens_keeps_creds(
        self, fake_db, super_admin_user,
    ):
        import services.homeworks_mcp_client as hw
        # Seed a fully-connected doc.
        fake_db["homeworks_byo_integrations"].docs.append({
            "tenant_id": "t-poc",
            "client_id": "cli-1",
            "client_secret_encrypted": hw.encrypt("sec"),
            "authorize_url": "https://a",
            "token_url": "https://t",
            "access_token_encrypted": hw.encrypt("at-1"),
            "refresh_token_encrypted": hw.encrypt("rt-1"),
            "connection_status": "connected",
        })
        from routers.homeworks_integration import disconnect
        _run(disconnect(user=super_admin_user))
        stored = fake_db["homeworks_byo_integrations"].docs[0]
        # Creds preserved:
        assert stored["client_id"] == "cli-1"
        assert stored["client_secret_encrypted"]
        # Tokens cleared:
        assert stored["access_token_encrypted"] is None
        assert stored["refresh_token_encrypted"] is None
        assert stored["connection_status"] == "disconnected"
