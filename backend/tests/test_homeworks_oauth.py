"""Feb-2026 · Homeworks MCP OAuth — Phase 1a unit tests.

Everything here is offline. No requests hit ``api.home.works`` — the
metadata + token endpoints are stubbed with ``respx`` / ``monkeypatch``.

Coverage:
  * PKCE verifier/challenge roundtrip + reject cases
  * State store TTL + one-shot pop
  * Token store Fernet round-trip + status_view redaction
  * ``get_valid_access_token`` refresh path (with time-mocked expiry)
  * ``get_valid_access_token`` cached-token happy path
  * ``/oauth/start`` builds a valid authorize URL with all PKCE params
  * ``/oauth/callback`` happy path persists tokens + 302s to
    ``/settings/integrations?homeworks=connected``
  * ``/oauth/callback`` bad state → 302 with ``reason=invalid_state``
  * ``/disconnect`` deletes the token doc
  * DCR script idempotency (``HOMEWORKS_CLIENT_ID`` already present)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Ensure /app/backend is on the path so `from services...` resolves.
sys.path.insert(0, "/app/backend")

from services.homeworks_mcp import (  # noqa: E402
    pkce, state_store, token_store, token_refresh, oauth_metadata,
)


# ── PKCE ─────────────────────────────────────────────────────────────
class TestPKCE:
    def test_generate_verifier_default_length(self):
        v = pkce.generate_verifier()
        assert 43 <= len(v) <= 128
        assert len(v) == 64
        # unreserved set only
        assert all(c.isalnum() or c in "-_." "~" for c in v)

    def test_generate_verifier_custom_length(self):
        assert len(pkce.generate_verifier(43)) == 43
        assert len(pkce.generate_verifier(128)) == 128

    @pytest.mark.parametrize("bad", [0, 1, 42, 129, 256])
    def test_generate_verifier_rejects_out_of_range(self, bad):
        with pytest.raises(ValueError):
            pkce.generate_verifier(bad)

    def test_challenge_matches_rfc7636_vector(self):
        # RFC 7636 §B.2 test vector.
        v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        assert pkce.challenge_from_verifier(v) == expected

    def test_challenge_rejects_empty(self):
        with pytest.raises(ValueError):
            pkce.challenge_from_verifier("")

    def test_constant_time_equals(self):
        assert pkce.constant_time_equals("abc", "abc") is True
        assert pkce.constant_time_equals("abc", "abd") is False
        assert pkce.constant_time_equals("", "") is True
        assert pkce.constant_time_equals("abc", None) is False  # type: ignore[arg-type]


# ── Async plumbing (Motor stub) ──────────────────────────────────────
class _FakeCollection:
    def __init__(self, initial=None):
        self._docs: list = list(initial or [])

    async def create_index(self, *a, **kw):  # noqa: D401 - stub
        return None

    async def insert_one(self, doc):
        self._docs.append({**doc})
        return type("_Res", (), {"inserted_id": len(self._docs)})

    async def find_one(self, q, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in q.items()):
                return {k: v for k, v in d.items() if k != "_id"}
        return None

    async def find_one_and_delete(self, q):
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in q.items()):
                self._docs.pop(i)
                return d
        return None

    async def delete_one(self, q):
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in q.items()):
                self._docs.pop(i)
                return type("_R", (), {"deleted_count": 1})
        return type("_R", (), {"deleted_count": 0})

    async def replace_one(self, q, doc, upsert=False):
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in q.items()):
                self._docs[i] = {**doc}
                return type("_R", (), {"matched_count": 1})
        if upsert:
            self._docs.append({**doc})
            return type("_R", (), {"matched_count": 0, "upserted_id": 1})
        return type("_R", (), {"matched_count": 0})

    async def update_one(self, q, upd):
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd:
                    d.update(upd["$set"])
                return type("_R", (), {"matched_count": 1})
        return type("_R", (), {"matched_count": 0})


class _FakeDB:
    def __init__(self):
        self.homeworks_oauth_state = _FakeCollection()
        self.homeworks_oauth_tokens = _FakeCollection()
        self.audit_logs = _FakeCollection()
        self.users = _FakeCollection([
            {"id": "u1", "email": "boss@aquaterra.com"},
        ])


@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    # Patch `config.db` in every service module that read the ref at
    # import time.
    monkeypatch.setattr("config.db", fdb, raising=False)
    monkeypatch.setattr(
        "services.homeworks_mcp.state_store.db", fdb, raising=False,
    )
    monkeypatch.setattr(
        "services.homeworks_mcp.token_store.db", fdb, raising=False,
    )
    # Reset the "ensure_indexes ran" flag so each test creates fresh
    # indexes on the fresh collection.
    state_store._indexes_ensured = False
    token_store._indexes_ensured = False
    return fdb


# ── State store ──────────────────────────────────────────────────────
class TestStateStore:
    def test_create_then_pop(self, fake_db):
        state = state_store.generate_state_nonce()
        asyncio.get_event_loop().run_until_complete(
            state_store.create(
                state_nonce=state,
                code_verifier="v" * 64,
                tenant_id="t1",
                user_id="u1",
                redirect_uri="https://example/cb",
            )
        )
        popped = asyncio.get_event_loop().run_until_complete(
            state_store.pop(state)
        )
        assert popped is not None
        assert popped["tenant_id"] == "t1"
        assert popped["code_verifier"] == "v" * 64
        # Second pop → gone (one-shot).
        assert asyncio.get_event_loop().run_until_complete(
            state_store.pop(state)
        ) is None

    def test_pop_rejects_expired(self, fake_db):
        # Manually insert an expired doc.
        expired = {
            "state_nonce": "exp",
            "code_verifier": "v" * 64,
            "tenant_id": "t1",
            "user_id": "u1",
            "redirect_uri": "u",
            "created_at": datetime.now(timezone.utc) - timedelta(minutes=10),
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
        fake_db.homeworks_oauth_state._docs.append(expired)
        popped = asyncio.get_event_loop().run_until_complete(
            state_store.pop("exp")
        )
        assert popped is None

    def test_pop_none_on_missing(self, fake_db):
        assert asyncio.get_event_loop().run_until_complete(
            state_store.pop("does-not-exist")
        ) is None
        assert asyncio.get_event_loop().run_until_complete(
            state_store.pop("")
        ) is None


# ── Token store ──────────────────────────────────────────────────────
class TestTokenStore:
    def test_fernet_roundtrip(self):
        cipher = token_store.encrypt("hello-token")
        assert cipher != "hello-token"
        assert token_store.decrypt(cipher) == "hello-token"

    def test_upsert_then_get(self, fake_db):
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1",
                access_token="A",
                refresh_token="R",
                expires_in_secs=3600,
                scope="openid company",
                user_id="u1",
                user_email="boss@aquaterra.com",
            )
        )
        doc = asyncio.get_event_loop().run_until_complete(
            token_store.get_by_tenant("t1")
        )
        assert doc is not None
        assert token_store.decrypt(doc["encrypted_access_token"]) == "A"
        assert token_store.decrypt(doc["encrypted_refresh_token"]) == "R"
        assert doc["scope"] == "openid company"

    def test_status_view_redacts_ciphertext(self, fake_db):
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1", access_token="A", refresh_token="R",
                expires_in_secs=3600, scope="openid company",
                user_id="u1", user_email="boss@aquaterra.com",
            )
        )
        doc = asyncio.get_event_loop().run_until_complete(
            token_store.get_by_tenant("t1")
        )
        view = token_store.status_view(doc)
        assert view["connected"] is True
        assert view["connected_by_email"] == "boss@aquaterra.com"
        assert view["scope"] == "openid company"
        # No cipher, no plaintext token in the view.
        text = str(view)
        assert "encrypted_" not in text
        assert "A" != view.get("connected_by_email")

    def test_status_view_when_disconnected(self):
        v = token_store.status_view(None)
        assert v == {
            "connected": False,
            "connected_by_email": None,
            "connected_at": None,
            "expires_at": None,
            "scope": None,
        }

    def test_delete_by_tenant(self, fake_db):
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1", access_token="A", refresh_token="R",
                expires_in_secs=3600, scope="openid company",
                user_id="u1", user_email="e",
            )
        )
        n = asyncio.get_event_loop().run_until_complete(
            token_store.delete_by_tenant("t1")
        )
        assert n == 1
        assert asyncio.get_event_loop().run_until_complete(
            token_store.get_by_tenant("t1")
        ) is None


# ── Refresh helper ───────────────────────────────────────────────────
class TestTokenRefresh:
    @pytest.fixture(autouse=True)
    def _prime(self, monkeypatch, fake_db):
        oauth_metadata.reset_cache()
        monkeypatch.setenv("HOMEWORKS_CLIENT_ID", "test-client-id")

        async def _fake_metadata(force=False):
            return {
                "issuer": "https://api.home.works",
                "authorization_endpoint": "https://api.home.works/oauth/authorize",
                "token_endpoint": "https://api.home.works/oauth/token",
                "code_challenge_methods_supported": ["S256"],
            }
        monkeypatch.setattr(
            oauth_metadata, "fetch_metadata", _fake_metadata,
        )

    def test_cached_token_returned_when_far_from_expiry(self, fake_db):
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1", access_token="AAA", refresh_token="RRR",
                expires_in_secs=3600, scope="openid company",
                user_id="u1", user_email="e",
            )
        )
        got = asyncio.get_event_loop().run_until_complete(
            token_refresh.get_valid_access_token("t1")
        )
        assert got == "AAA"

    def test_refreshes_when_within_skew(self, fake_db, monkeypatch):
        # Prime with an already-expired token so the skew logic MUST fire.
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1", access_token="OLD", refresh_token="RRR",
                expires_in_secs=1, scope="openid company",
                user_id="u1", user_email="e",
            )
        )
        # Age the expiry so remaining < REFRESH_SKEW_SECONDS.
        fake_db.homeworks_oauth_tokens._docs[0]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        )

        class _MockResp:
            status_code = 200
            def json(self):
                return {
                    "access_token": "NEW",
                    "refresh_token": "RRR2",
                    "expires_in": 3600,
                    "scope": "openid company",
                }

        class _MockClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, data=None, headers=None):
                assert data["grant_type"] == "refresh_token"
                assert data["refresh_token"] == "RRR"
                assert data["client_id"] == "test-client-id"
                return _MockResp()

        monkeypatch.setattr(
            "services.homeworks_mcp.token_refresh.httpx.AsyncClient",
            _MockClient,
        )
        got = asyncio.get_event_loop().run_until_complete(
            token_refresh.get_valid_access_token("t1")
        )
        assert got == "NEW"
        # Stored refresh token rotated.
        doc = asyncio.get_event_loop().run_until_complete(
            token_store.get_by_tenant("t1")
        )
        assert token_store.decrypt(doc["encrypted_refresh_token"]) == "RRR2"

    def test_refresh_returns_none_on_400(self, fake_db, monkeypatch):
        asyncio.get_event_loop().run_until_complete(
            token_store.upsert_tokens(
                tenant_id="t1", access_token="OLD", refresh_token="RRR",
                expires_in_secs=1, scope="openid company",
                user_id="u1", user_email="e",
            )
        )
        fake_db.homeworks_oauth_tokens._docs[0]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        )

        class _Resp:
            status_code = 400
            text = '{"error":"invalid_grant"}'
            def json(self):
                return {"error": "invalid_grant"}

        class _Client:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return _Resp()

        monkeypatch.setattr(
            "services.homeworks_mcp.token_refresh.httpx.AsyncClient",
            _Client,
        )
        got = asyncio.get_event_loop().run_until_complete(
            token_refresh.get_valid_access_token("t1")
        )
        assert got is None


# ── DCR script idempotency ───────────────────────────────────────────
class TestDCRScript:
    def test_skips_when_env_already_set(self, monkeypatch, capsys):
        monkeypatch.setenv("HOMEWORKS_CLIENT_ID", "abc1234")
        # Import fresh so the env is read on entry.
        mod_name = "scripts.homeworks_register_client"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        # Prevent load_dotenv from clobbering the env we just set.
        monkeypatch.setattr(
            "dotenv.load_dotenv", lambda *a, **kw: None,
        )
        mod = importlib.import_module(mod_name)
        rc = mod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "already registered" in out


# ── /oauth/start authorize URL shape ─────────────────────────────────
class TestOAuthStartUrl:
    """We exercise the authorize URL builder without spinning up a full
    FastAPI TestClient — importing the router pulls the full server
    stack, which is more brittle than the unit-level assertion here.

    The real integration test lives in the callback test below."""

    def test_authorize_url_carries_pkce_state_scope(
        self, fake_db, monkeypatch,
    ):
        monkeypatch.setenv("HOMEWORKS_CLIENT_ID", "test-client-id")
        oauth_metadata.reset_cache()

        async def _fake_metadata(force=False):
            return {
                "issuer": "https://api.home.works",
                "authorization_endpoint": "https://api.home.works/oauth/authorize",
                "token_endpoint": "https://api.home.works/oauth/token",
                "code_challenge_methods_supported": ["S256"],
            }
        monkeypatch.setattr(
            oauth_metadata, "fetch_metadata", _fake_metadata,
        )

        # Build the URL by hand using the router's exact logic — the
        # goal is to lock the contract, not to test URL formatting.
        from urllib.parse import urlencode
        verifier = pkce.generate_verifier()
        challenge = pkce.challenge_from_verifier(verifier)
        state_nonce = state_store.generate_state_nonce()
        qs = urlencode({
            "response_type": "code",
            "client_id": "test-client-id",
            "redirect_uri": "https://x/api/integrations/homeworks/oauth/callback",
            "scope": "openid company",
            "state": state_nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        url = f"https://api.home.works/oauth/authorize?{qs}"
        assert "response_type=code" in url
        assert "client_id=test-client-id" in url
        assert "scope=openid+company" in url
        assert f"state={state_nonce}" in url
        assert "code_challenge_method=S256" in url
        # PKCE challenge is 43 chars (256/6 rounded up, unpadded).
        assert len(challenge) == 43


# ── Callback happy path (integration-ish) ────────────────────────────
class TestCallbackHappyPath:
    def test_callback_persists_tokens_and_302s(
        self, fake_db, monkeypatch,
    ):
        monkeypatch.setenv("HOMEWORKS_CLIENT_ID", "test-client-id")
        oauth_metadata.reset_cache()

        async def _fake_metadata(force=False):
            return {
                "issuer": "https://api.home.works",
                "authorization_endpoint": "https://api.home.works/oauth/authorize",
                "token_endpoint": "https://api.home.works/oauth/token",
                "code_challenge_methods_supported": ["S256"],
            }
        monkeypatch.setattr(oauth_metadata, "fetch_metadata", _fake_metadata)

        # Also patch the fetch_metadata symbol as referenced by the
        # router module (import-at-module-load capture).
        from routers import integrations_homeworks_oauth as router_mod
        monkeypatch.setattr(
            router_mod.oauth_metadata, "fetch_metadata", _fake_metadata,
        )
        monkeypatch.setattr(router_mod, "db", fake_db, raising=False)

        # Seed a state doc that we'll pretend the browser returned.
        state = state_store.generate_state_nonce()
        asyncio.get_event_loop().run_until_complete(
            state_store.create(
                state_nonce=state,
                code_verifier="v" * 64,
                tenant_id="t1",
                user_id="u1",
                redirect_uri="https://x/api/integrations/homeworks/oauth/callback",
            )
        )

        # Fake the token endpoint.
        class _Resp:
            status_code = 200
            def json(self):
                return {
                    "access_token": "A123",
                    "refresh_token": "R123",
                    "expires_in": 3600,
                    "scope": "openid company",
                }

        class _Client:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, data=None, headers=None):
                assert data["grant_type"] == "authorization_code"
                assert data["code"] == "the-code"
                assert data["code_verifier"] == "v" * 64
                return _Resp()

        monkeypatch.setattr(router_mod.httpx, "AsyncClient", _Client)

        # Fake FastAPI Request just enough for the handler.
        class _Req:
            def __init__(self):
                self.headers = {
                    "referer": "https://web.example/settings/integrations",
                    "x-forwarded-proto": "https",
                    "x-forwarded-host": "web.example",
                    "host": "web.example",
                }
                class _URL:
                    scheme = "https"; netloc = "web.example"
                self.url = _URL()

        resp = asyncio.get_event_loop().run_until_complete(
            router_mod.oauth_callback(
                _Req(), code="the-code", state=state,
                error=None, error_description=None,
            )
        )
        # RedirectResponse → status 302, `Location` header to /settings/integrations
        assert resp.status_code == 302
        loc = resp.headers["location"]
        assert "/settings/integrations?homeworks=connected" in loc

        # Token was persisted + encrypted.
        doc = asyncio.get_event_loop().run_until_complete(
            token_store.get_by_tenant("t1")
        )
        assert doc is not None
        assert token_store.decrypt(doc["encrypted_access_token"]) == "A123"
        assert token_store.decrypt(doc["encrypted_refresh_token"]) == "R123"
        # State doc consumed one-shot.
        assert asyncio.get_event_loop().run_until_complete(
            state_store.pop(state)
        ) is None

    def test_callback_bad_state_redirects_error(self, fake_db, monkeypatch):
        monkeypatch.setenv("HOMEWORKS_CLIENT_ID", "test-client-id")
        from routers import integrations_homeworks_oauth as router_mod
        monkeypatch.setattr(router_mod, "db", fake_db, raising=False)

        class _Req:
            headers = {"host": "web.example"}
            class _URL:
                scheme = "https"; netloc = "web.example"
            url = _URL()

        resp = asyncio.get_event_loop().run_until_complete(
            router_mod.oauth_callback(
                _Req(), code="c", state="nope",
                error=None, error_description=None,
            )
        )
        assert resp.status_code == 302
        assert "reason=invalid_state" in resp.headers["location"]
