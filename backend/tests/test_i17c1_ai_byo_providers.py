"""Phase I1.7.c.1 · Feb-2026 — Tenant AI BYO Providers · 12 cases.

Uses ``AI_TESTMODE_MOCK=true`` so adapters short-circuit without an
outbound HTTP call. Endpoint-level cases hit the live backend on
``localhost:8001``.

Covered cases (12 total):
  01. Registry lists all three providers (openai, anthropic, gemini)
  02. Save AI provider via PUT — response never leaks plaintext
  03. Saved secret is retrievable via provider adapter (roundtrip)
  04. ``last_4`` reflects the api_key tail (not the JSON blob tail)
  05. Encryption at rest — raw Mongo row has ciphertext, not plaintext
  06. Delete removes BOTH the secret row AND the tenant_ai_provider row
  07. ``dispatch_ai_completion`` uses BYO when configured
  08. ``dispatch_ai_completion`` falls back to platform when no BYO
  09. Cap semantics: null = unlimited (default)
  10. Cap semantics: soft warn (>= 80% used) surfaces in /usage
  11. Cap semantics: hard block raises 429 — NO platform fallback
  12. Cap semantics: cap = 0 blocks immediately (kill switch)
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ── Shared event-loop plumbing (mirrors I1.7.b tests) ─────────────
_LOOP: asyncio.AbstractEventLoop | None = None
_MOTOR_DB = None


def _setup_loop():
    global _LOOP, _MOTOR_DB
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _MOTOR_DB = _client[os.environ["DB_NAME"]]
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB   # type: ignore
        import services.ai.usage as _usage_mod
        _usage_mod._default_db = lambda: _MOTOR_DB  # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, db = _setup_loop()
    return loop.run_until_complete(coro_factory(db))


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _clean_and_flag(monkeypatch):
    monkeypatch.setenv("AI_TESTMODE_MOCK", "true")
    from services.ai.registry import reset_cache_for_tests
    reset_cache_for_tests()
    yield


TENANT_LOCAL = f"i17c1-ai-{uuid.uuid4().hex[:8]}"


def _cleanup_tenant(tid: str) -> None:
    _sync.tenant_secrets.delete_many({"tenant_id": tid,
                                        "provider_key": {"$regex": r"^ai_"}})
    _sync.tenant_ai_provider.delete_many({"tenant_id": tid})
    _sync.tenant_ai_usage.delete_many({"tenant_id": tid})


# ── Case 01 — Registry lists all three providers ───────────────
def test_01_registry_lists_all_three_providers():
    from services.ai.registry import (
        list_registered_ai_provider_keys, list_short_names,
    )
    keys = set(list_registered_ai_provider_keys())
    shorts = set(list_short_names())
    assert keys == {"ai_openai", "ai_anthropic", "ai_gemini"}
    assert shorts == {"openai", "anthropic", "gemini"}


# ── Case 02 — PUT via HTTP · no plaintext in response ──────────
def test_02_put_ai_provider_masks_secret_in_response():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"OPENAI-KEY-{uuid.uuid4().hex}"
        r = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker,
                              "default_model": "gpt-4o-mini"},
                    "monthly_token_cap": 5000},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["saved"] is True
        assert body["provider_key"] == "ai_openai"
        assert marker not in json.dumps(body)
        # List endpoint also must not leak.
        lst = requests.get(f"{API}/tenants/me/integrations",
                              headers=_hdrs(tok), timeout=15).json()
        assert marker not in json.dumps(lst)
        row = next((r for r in lst["integrations"]
                     if r["provider_key"] == "ai_openai"), None)
        assert row is not None and row["connected"] is True
    finally:
        _cleanup_tenant(tid)


# ── Case 03 — Roundtrip: adapter decrypts saved config ─────────
def test_03_secret_roundtrip_via_adapter():
    from services.ai._helpers import save_provider_config, load_provider_config
    from services.ai.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    schema = provider.config_fields

    async def _work(db):
        _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_openai",
            config={"api_key": "sk-abcdefghijklmnopqrst", "default_model": "gpt-4o"},
            schema=schema,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        cfg = await load_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_openai", db=db,
        )
        return cfg
    cfg = _drive(_work)
    assert cfg is not None
    assert cfg["api_key"] == "sk-abcdefghijklmnopqrst"
    assert cfg["default_model"] == "gpt-4o"
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})


# ── Case 04 — ``last_4`` reflects api_key tail ─────────────────
def test_04_last_4_reflects_api_key_tail_not_json_tail():
    from services.ai._helpers import save_provider_config
    from services.ai.openai_provider import OpenAIProvider
    from services.secrets import connection_summary

    provider = OpenAIProvider()

    async def _work(db):
        _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_openai",
            config={"api_key": "sk-veryrealisticapikey_ZZ99"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        return await connection_summary(TENANT_LOCAL, "ai_openai", db=db)
    summary = _drive(_work)
    assert summary is not None
    # Ends with the api_key's last 4 chars — NOT ``"}`` from the JSON
    # blob tail (regression guard from I1.7.b.fix).
    assert summary.last_4 == "ZZ99"
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})


# ── Case 05 — Encryption at rest ───────────────────────────────
def test_05_encryption_at_rest_ciphertext_not_plaintext():
    from services.ai._helpers import save_provider_config
    from services.ai.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider()
    marker = f"ANTHROPIC-{uuid.uuid4().hex}"

    async def _work(db):
        _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_anthropic",
            config={"api_key": marker},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
    _drive(_work)
    row = _sync.tenant_secrets.find_one({"tenant_id": TENANT_LOCAL,
                                            "provider_key": "ai_anthropic"})
    assert row is not None
    # Marker must never appear anywhere on the raw row.
    assert marker not in json.dumps(row, default=str)
    assert "encrypted_blob" in row and len(row["encrypted_blob"]) > 0
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT_LOCAL})


# ── Case 06 — DELETE removes secret + provider metadata ────────
def test_06_delete_removes_secret_and_metadata():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        put_r = requests.put(
            f"{API}/tenants/me/integrations/ai_gemini",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "gm-abc123xyz",
                              "default_model": "gemini-1.5-flash"},
                    "monthly_token_cap": None},
        )
        assert put_r.status_code == 200
        assert _sync.tenant_secrets.count_documents(
            {"tenant_id": tid, "provider_key": "ai_gemini"}) == 1
        assert _sync.tenant_ai_provider.count_documents(
            {"tenant_id": tid, "provider": "gemini"}) == 1

        del_r = requests.delete(
            f"{API}/tenants/me/integrations/ai_gemini",
            headers=_hdrs(tok), timeout=15,
        )
        assert del_r.status_code == 200
        assert del_r.json()["removed"] is True
        # BOTH collections must be cleaned.
        assert _sync.tenant_secrets.count_documents(
            {"tenant_id": tid, "provider_key": "ai_gemini"}) == 0
        assert _sync.tenant_ai_provider.count_documents(
            {"tenant_id": tid, "provider": "gemini"}) == 0
    finally:
        _cleanup_tenant(tid)


# ── Case 07 — dispatcher uses BYO when configured ──────────────
def test_07_dispatcher_uses_byo_when_configured():
    from services.ai import dispatch_ai_completion
    from services.ai._helpers import save_provider_config
    from services.ai.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_anthropic",
            config={"api_key": "sk-ant-fake123", "default_model": "claude-3-5-sonnet-latest"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        return await dispatch_ai_completion(
            tenant_id=TENANT_LOCAL,
            system_prompt="you are helpful",
            user_text="Hello world",
            db=db,
        )
    result = _drive(_work)
    assert result.provider_used == "tenant:anthropic"
    assert result.tokens_total > 0
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 08 — dispatcher falls back to platform when no BYO ────
def test_08_dispatcher_falls_back_to_platform_when_no_byo():
    from services.ai import dispatch_ai_completion

    fresh_tid = f"i17c1-no-byo-{uuid.uuid4().hex[:8]}"

    async def _work(db):
        _sync.tenant_secrets.delete_many({"tenant_id": fresh_tid})
        return await dispatch_ai_completion(
            tenant_id=fresh_tid,
            system_prompt="s",
            user_text="u",
            db=db,
        )
    result = _drive(_work)
    assert result.provider_used == "platform:emergent"
    assert result.provider_key == "emergent"


# ── Case 09 — cap = None (unlimited) never blocks ──────────────
def test_09_cap_none_means_unlimited():
    from services.ai import dispatch_ai_completion
    from services.ai._helpers import save_provider_config
    from services.ai.openai_provider import OpenAIProvider
    from services.ai.usage import upsert_provider_meta, record_usage

    provider = OpenAIProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_openai",
            config={"api_key": "sk-1234567890XY", "default_model": "gpt-4o-mini"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        # No cap in meta → unlimited.
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="openai",
            monthly_token_cap=None, default_model="gpt-4o-mini", db=db,
        )
        # Pre-record a ridiculously large usage total.
        await record_usage(
            tenant_id=TENANT_LOCAL, provider="openai",
            tokens_prompt=999_999, tokens_completion=999_999, db=db,
        )
        return await dispatch_ai_completion(
            tenant_id=TENANT_LOCAL, system_prompt="s", user_text="u", db=db,
        )
    result = _drive(_work)
    assert result.provider_used == "tenant:openai"
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 10 — soft warn at >= 80% cap ──────────────────────────
def test_10_soft_warn_surfaces_at_80_pct_via_usage_endpoint():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        # Configure BYO w/ cap=1000, then pre-populate usage=900 (90%).
        r = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "sk-warntest_XY", "default_model": "gpt-4o-mini"},
                    "monthly_token_cap": 1000},
        )
        assert r.status_code == 200
        from services.ai.usage import record_usage as _rec

        async def _seed(db):
            await _rec(tenant_id=tid, provider="openai",
                        tokens_prompt=500, tokens_completion=400, db=db)
        _drive(_seed)
        usage = requests.get(
            f"{API}/tenants/me/integrations/ai/usage",
            headers=_hdrs(tok), timeout=15,
        ).json()
        oai = next((p for p in usage["providers"] if p["provider"] == "openai"), None)
        assert oai is not None
        assert oai["tokens_total"] == 900
        assert oai["monthly_token_cap"] == 1000
        assert oai["status"] == "warn"
        assert abs(oai["pct_used"] - 0.9) < 1e-6
    finally:
        _cleanup_tenant(tid)


# ── Case 11 — hard block at cap == used raises 429 · no fallback
def test_11_hard_block_raises_and_does_not_fallback():
    from services.ai import (
        dispatch_ai_completion, TenantAIUsageCapExceeded,
    )
    from services.ai._helpers import save_provider_config
    from services.ai.openai_provider import OpenAIProvider
    from services.ai.usage import upsert_provider_meta, record_usage

    provider = OpenAIProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_openai",
            config={"api_key": "sk-blocktest_ZZ", "default_model": "gpt-4o-mini"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="openai",
            monthly_token_cap=100, default_model="gpt-4o-mini", db=db,
        )
        await record_usage(
            tenant_id=TENANT_LOCAL, provider="openai",
            tokens_prompt=60, tokens_completion=40, db=db,   # exactly at cap
        )
        # Must raise; must NOT silently fall back to Emergent.
        try:
            await dispatch_ai_completion(
                tenant_id=TENANT_LOCAL,
                system_prompt="s", user_text="u", db=db,
            )
            return "no_raise"
        except TenantAIUsageCapExceeded as e:
            return e
    result = _drive(_work)
    assert isinstance(result, TenantAIUsageCapExceeded)
    assert result.cap == 100
    assert result.used == 100
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 12 — cap == 0 is the explicit kill-switch ─────────────
def test_12_cap_zero_blocks_immediately():
    from services.ai import (
        dispatch_ai_completion, TenantAIUsageCapExceeded,
    )
    from services.ai._helpers import save_provider_config
    from services.ai.gemini_provider import GeminiProvider
    from services.ai.usage import upsert_provider_meta

    provider = GeminiProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="ai_gemini",
            config={"api_key": "gm-killswitchZZ", "default_model": "gemini-1.5-flash"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        # Cap = 0 → block all, even at 0 tokens used.
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="gemini",
            monthly_token_cap=0, default_model="gemini-1.5-flash", db=db,
        )
        try:
            await dispatch_ai_completion(
                tenant_id=TENANT_LOCAL,
                system_prompt="s", user_text="u", db=db,
            )
            return "no_raise"
        except TenantAIUsageCapExceeded as e:
            return e
    result = _drive(_work)
    assert isinstance(result, TenantAIUsageCapExceeded)
    assert result.cap == 0
    assert result.used == 0
    _cleanup_tenant(TENANT_LOCAL)


# ── Post-tester fix (2026-02) · preserve stored secrets on partial edit ──
def _current_cipher(tid: str, pk: str) -> str:
    row = _sync.tenant_secrets.find_one({"tenant_id": tid, "provider_key": pk})
    return (row or {}).get("encrypted_blob", "")


def test_cap_only_edit_preserves_stored_secret():
    """Connected provider · PUT with only monthly_token_cap change →
    200, ``last_4`` unchanged, cap updated, stored secret still
    decrypts to the ORIGINAL api_key."""
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"sk-original_{uuid.uuid4().hex}"[:32]
        put1 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker, "default_model": "gpt-4o-mini"},
                    "monthly_token_cap": 10000},
        )
        assert put1.status_code == 200, put1.text
        lst_a = requests.get(f"{API}/tenants/me/integrations",
                                headers=_hdrs(tok), timeout=15).json()
        row_a = next(r for r in lst_a["integrations"] if r["provider_key"] == "ai_openai")
        last4_before = row_a["last_4"]
        # Edit ONLY the cap — no api_key in payload.
        put2 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"default_model": "gpt-4o-mini"},
                    "monthly_token_cap": 20000},
        )
        assert put2.status_code == 200, put2.text
        assert put2.json()["saved"] is True
        # last_4 must be identical → primary secret unchanged.
        lst_b = requests.get(f"{API}/tenants/me/integrations",
                                headers=_hdrs(tok), timeout=15).json()
        row_b = next(r for r in lst_b["integrations"] if r["provider_key"] == "ai_openai")
        assert row_b["last_4"] == last4_before
        # Cap updated in sidecar / /usage response.
        usage = requests.get(f"{API}/tenants/me/integrations/ai/usage",
                                headers=_hdrs(tok), timeout=15).json()
        oai = next(p for p in usage["providers"] if p["provider"] == "openai")
        assert oai["monthly_token_cap"] == 20000
        # Adapter still decrypts to the ORIGINAL api_key.
        from services.ai._helpers import load_provider_config

        async def _work(db):
            return await load_provider_config(
                tenant_id=tid, provider_key="ai_openai", db=db,
            )
        cfg = _drive(_work)
        assert cfg["api_key"] == marker
    finally:
        _cleanup_tenant(tid)


def test_model_only_edit_preserves_stored_secret():
    """Same shape as cap-only, different mutable field: switch the
    default_model without re-typing the api_key."""
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"sk-model-orig_{uuid.uuid4().hex}"[:32]
        r1 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker, "default_model": "gpt-4o-mini"},
                    "monthly_token_cap": None},
        )
        assert r1.status_code == 200
        r2 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"default_model": "gpt-4o"}},
        )
        assert r2.status_code == 200, r2.text
        usage = requests.get(f"{API}/tenants/me/integrations/ai/usage",
                                headers=_hdrs(tok), timeout=15).json()
        oai = next(p for p in usage["providers"] if p["provider"] == "openai")
        assert oai["default_model"] == "gpt-4o"
        # Secret unchanged: adapter still decrypts to the ORIGINAL key.
        from services.ai._helpers import load_provider_config

        async def _work(db):
            return await load_provider_config(
                tenant_id=tid, provider_key="ai_openai", db=db,
            )
        cfg = _drive(_work)
        assert cfg["api_key"] == marker
    finally:
        _cleanup_tenant(tid)


def test_missing_api_key_on_unconnected_provider_still_422():
    """Unconnected provider · no api_key in body → still refused
    (400) — you can't 'connect' without a key."""
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        r = requests.put(
            f"{API}/tenants/me/integrations/ai_anthropic",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"default_model": "claude-3-5-sonnet-latest"},
                    "monthly_token_cap": 5000},
        )
        assert r.status_code == 400, r.text
        assert "api_key" in r.text
    finally:
        _cleanup_tenant(tid)


def test_cap_zero_via_edit_only_saves_and_blocks_dispatch():
    """End-to-end kill-switch flow: connect provider, then edit only
    ``monthly_token_cap`` to 0 — the dispatcher must then hard-block
    without any platform fallback."""
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        r1 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "sk-killedZZ", "default_model": "gpt-4o-mini"},
                    "monthly_token_cap": 10000},
        )
        assert r1.status_code == 200
        # Cap-only edit → 0.
        r2 = requests.put(
            f"{API}/tenants/me/integrations/ai_openai",
            headers=_hdrs(tok), timeout=15,
            json={"config": {}, "monthly_token_cap": 0},
        )
        assert r2.status_code == 200, r2.text
        # /usage shows blocked.
        usage = requests.get(f"{API}/tenants/me/integrations/ai/usage",
                                headers=_hdrs(tok), timeout=15).json()
        oai = next(p for p in usage["providers"] if p["provider"] == "openai")
        assert oai["monthly_token_cap"] == 0
        assert oai["status"] == "blocked"
        # Dispatcher must hard-block WITHOUT platform fallback.
        from services.ai import (
            dispatch_ai_completion, TenantAIUsageCapExceeded,
        )

        async def _work(db):
            try:
                return await dispatch_ai_completion(
                    tenant_id=tid, system_prompt="s", user_text="u", db=db,
                )
            except TenantAIUsageCapExceeded as e:
                return e
        outcome = _drive(_work)
        assert isinstance(outcome, TenantAIUsageCapExceeded)
        assert outcome.cap == 0
    finally:
        _cleanup_tenant(tid)


def test_messaging_partial_edit_preserves_secret_uniformly():
    """Regression guard — the merge helper must apply uniformly to
    SMS/Email providers, not just AI. Connect twilio, then PUT only
    a new ``from_number`` → 200, auth_token unchanged at rest."""
    tok = _login()
    tid = _tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "twilio"})
    try:
        r1 = requests.put(
            f"{API}/tenants/me/integrations/twilio",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"account_sid": "ACaaaaaaaaaaaaaa",
                              "auth_token": "tok-original-XYZ99",
                              "from_number": "+15551234567"}},
        )
        assert r1.status_code == 200, r1.text
        # Edit ONLY the from_number.
        r2 = requests.put(
            f"{API}/tenants/me/integrations/twilio",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"from_number": "+15559990000"}},
        )
        assert r2.status_code == 200, r2.text
        # Stored auth_token still intact.
        from services.messaging._helpers import load_provider_config

        async def _work(db):
            return await load_provider_config(
                tenant_id=tid, provider_key="twilio", db=db,
            )
        cfg = _drive(_work)
        assert cfg["auth_token"] == "tok-original-XYZ99"
        assert cfg["from_number"] == "+15559990000"
    finally:
        _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "twilio"})
