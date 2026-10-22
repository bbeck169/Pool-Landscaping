"""TD-ai-phase1 · Oct-2026 — pytest suite for ``POST /api/ai/draft-reply``.

In-process ``TestClient`` + ``monkeypatch`` on
``services.llm_provider.call_llm_with_fallback``. Pattern matches
``test_i17e_chunk2c_llm_provider_callers.py``. No live LLM calls.

Covers:
  §1 happy path (email, sms, cache hit)
  §2 role gate (manager/admin/super_admin/owner pass; tech/customer 403)
  §3 PII redaction + context allowlist enforcement
  §4 rate-limit (429 with retry_after)
  §5 cap-exceeded (429 cap_exceeded flag)
  §6 fallback template on LLM error
  §7 tenant isolation (recipient from another tenant → 404)
  §8 audit log emission
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

# Ensure the backend package is importable before the server import.
import sys
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from server import app  # noqa: E402
from services.ai import draft_rate_limit, draft_cache  # noqa: E402

client = TestClient(app)

PFX = f"td_ai_draft_{uuid.uuid4().hex[:6]}_"


# ─── Fake async Mongo (chainable; just enough for the handler) ──────
class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.inserts: List[Dict[str, Any]] = []

    async def find_one(self, filt, projection=None, sort=None):
        for d in self.docs:
            if _matches(d, filt):
                return dict(d)
        return None

    def find(self, filt, projection=None):
        return _FakeCursor([d for d in self.docs if _matches(d, filt)])

    async def insert_one(self, doc):
        self.inserts.append(dict(doc))
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": "x"})

    async def update_one(self, filt, update, upsert=False):
        return type("R", (), {"matched_count": 1, "modified_count": 1})


def _matches(doc, filt):
    for k, v in filt.items():
        if isinstance(v, dict):
            if "$in" in v and doc.get(k) not in v["$in"]:
                return False
            if "$gte" in v and (doc.get(k) is None or doc.get(k) < v["$gte"]):
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _FakeDB:
    def __init__(self):
        self.customers = _FakeCollection()
        self.leads = _FakeCollection()
        self.jobs = _FakeCollection()
        self.tenant_ai_usage = _FakeCollection()
        self.ai_draft_calls = _FakeCollection()


# ─── Fixture: fresh state + fake DB wired across all consumer modules ─
@pytest.fixture(autouse=True)
def _wire_fakes(monkeypatch):
    draft_rate_limit._reset_for_tests()
    draft_cache._reset_for_tests()
    fake = _FakeDB()
    # Patch db everywhere the handler + context assembler + audit touch it.
    from routers import ai_draft_reply as _router
    from services.ai import compose_context as _ctx
    from services.ai import usage as _usage
    monkeypatch.setattr(_router, "db", fake, raising=False)
    monkeypatch.setattr(_usage, "_default_db", lambda: fake, raising=False)
    # compose_context takes db as a kwarg — nothing to patch there.
    # Auth override: all tests mint a user dict.
    yield fake


# ─── Auth override helper ────────────────────────────────────────────
def _as(role: str, tenant_id: str = "tenant-A", user_id: str = "user-1"):
    from utils import get_current_user
    user = {
        "id": user_id, "tenant_id": tenant_id, "role": role,
        "email": f"{role}@example.com",
    }
    app.dependency_overrides[get_current_user] = lambda: user
    return user


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ─── Monkeypatch helpers for the LLM chokepoint ──────────────────────
def _mock_llm(monkeypatch, *, text="Hi [FIRSTNAME], acknowledged.", cap=False, err=None,
                captured=None):
    async def _fake(**kwargs):
        if captured is not None:
            captured.append(kwargs)
        if cap:
            return {"error": "ai_spend_cap_exceeded", "cap_exceeded": True,
                    "http_status": 429}
        if err:
            return {"error": err}
        return {"raw": {"text": text, "prompt_tokens": 42,
                           "completion_tokens": 17},
                "provider": "emergent"}
    from services import llm_provider
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _fake)


def _seed_customer(fake, tenant_id="tenant-A", cid="cust-1",
                     first_name="Dana", service_type="weekly maintenance"):
    fake.customers.docs.append({
        "id": cid, "tenant_id": tenant_id,
        "first_name": first_name, "last_name": "SHOULD-NEVER-LEAK",
        "service_type": service_type,
        "email": "dana@secret.example", "phone": "+15125551234",
        "address": "123 Private Ln, Austin TX 78701",
        "ssn": "555-55-5555",
    })


# ═══════════════ §1 · Happy path ══════════════════════════════════════
def test_email_draft_happy_path(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, text=(
        "Subject: Quick note on your visit\n\n"
        "Hi [FIRSTNAME], confirming your next visit. Thanks."))
    r = client.post("/api/ai/draft-reply", json={
        "channel": "email", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["draft_subject"] == "Quick note on your visit"
    assert j["draft_body"].startswith("Hi Dana,")
    assert "SHOULD-NEVER-LEAK" not in j["draft_body"]
    assert j["model"] == "claude-sonnet-4-5-20250929"
    assert j["prompt_tokens"] == 42
    assert j["completion_tokens"] == 17
    assert j["cost_usd"] == 0.0
    assert j["cached"] is False


def test_sms_draft_happy_path(monkeypatch, _wire_fakes):
    _as("manager")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, text="Hi [FIRSTNAME], see you Tue.")
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["draft_subject"] is None
    assert j["draft_body"] == "Hi Dana, see you Tue."
    assert j["cached"] is False


def test_cache_hit_second_call_returns_cached_true(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    calls = []

    async def _fake(**kw):
        calls.append(1)
        return {"raw": {"text": "Hi [FIRSTNAME]."},
                "provider": "emergent"}
    from services import llm_provider
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _fake)

    r1 = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert len(calls) == 1
    # Second call with identical inputs → cache hit, no new LLM call.
    r2 = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert len(calls) == 1


# ═══════════════ §2 · Role gate ══════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "owner", "manager"])
def test_role_gate_allows(monkeypatch, _wire_fakes, role):
    _as(role)
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, text="ok [FIRSTNAME]")
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 200, (role, r.text)


@pytest.mark.parametrize("role", ["technician", "customer"])
def test_role_gate_blocks(monkeypatch, _wire_fakes, role):
    _as(role)
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 403, (role, r.text)


# ═══════════════ §3 · PII redaction + allowlist ══════════════════════
def test_prior_message_pii_is_redacted(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    captured = []
    _mock_llm(monkeypatch, text="ok [FIRSTNAME]", captured=captured)
    client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
        "prior_message": "Call me at 512-555-1234 or test@example.com",
    })
    assert captured, "LLM was never invoked"
    user_text = captured[0].get("user_text") or ""
    assert "512-555-1234" not in user_text
    assert "test@example.com" not in user_text


def test_allowlist_drops_pii_from_recipient_doc(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)  # seeds last_name/email/phone/address/ssn
    captured = []
    _mock_llm(monkeypatch, text="ok [FIRSTNAME]", captured=captured)
    client.post("/api/ai/draft-reply", json={
        "channel": "email", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert captured
    system = captured[0].get("system_prompt") or ""
    user = captured[0].get("user_text") or ""
    blob = system + "\n" + user
    for leaked in ("SHOULD-NEVER-LEAK", "dana@secret.example",
                      "+15125551234", "123 Private Ln", "555-55-5555",
                      "Dana"):  # Dana is substituted POST-generation only
        assert leaked not in blob, f"PII leaked: {leaked!r}"


# ═══════════════ §4 · Rate-limit ═════════════════════════════════════
def test_rate_limit_blocks_second_call_within_10s(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, text="ok [FIRSTNAME]")
    r1 = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r1.status_code == 200
    # Second call: different prompt (different intent) to bypass cache.
    r2 = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
        "intent_hint": "second call different intent",
    })
    assert r2.status_code == 429, r2.text
    body = r2.json()["detail"]
    assert body["retry_after_seconds"] > 0
    assert body["retry_after_seconds"] <= 10


# ═══════════════ §5 · Cap-exceeded ═══════════════════════════════════
def test_cap_exceeded_returns_429_cap_flag(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, cap=True)
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 429, r.text
    body = r.json()["detail"]
    assert body.get("cap_exceeded") is True


# ═══════════════ §6 · Fallback on LLM error ══════════════════════════
def test_fallback_template_on_llm_error(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, err="emergent_timeout")
    r = client.post("/api/ai/draft-reply", json={
        "channel": "email", "recipient_type": "customer",
        "recipient_id": "cust-1",
        "intent_hint": "check in about Tuesday",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["draft_body"].startswith("Hi Dana")
    assert "check in about Tuesday" in j["draft_body"]
    assert j["draft_subject"] == "Following up"


# ═══════════════ §7 · Tenant isolation ═══════════════════════════════
def test_recipient_from_other_tenant_returns_404(monkeypatch, _wire_fakes):
    _as("admin", tenant_id="tenant-A")
    fake = _wire_fakes
    # Customer belongs to tenant-B, not tenant-A.
    fake.customers.docs.append({
        "id": "cust-cross", "tenant_id": "tenant-B",
        "first_name": "Cross", "service_type": "whatever",
    })
    _mock_llm(monkeypatch, text="ok [FIRSTNAME]")
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-cross",
    })
    assert r.status_code == 404, r.text


# ═══════════════ §8 · Audit log emission ═════════════════════════════
def test_audit_record_usage_called_with_actor_recipient_hash(monkeypatch, _wire_fakes):
    _as("admin", user_id="u-audit-1")
    fake = _wire_fakes
    _seed_customer(fake)
    _mock_llm(monkeypatch, text="Hi [FIRSTNAME]")
    captured_usage = []

    async def _fake_record(**kw):
        captured_usage.append(kw)
        return {}
    from services.ai import usage as _usage
    monkeypatch.setattr(_usage, "record_usage", _fake_record)

    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "customer",
        "recipient_id": "cust-1",
    })
    assert r.status_code == 200
    assert captured_usage, "record_usage was never called"
    kw = captured_usage[0]
    assert kw.get("actor_user_id") == "u-audit-1"
    assert kw.get("recipient_type") == "customer"
    assert kw.get("recipient_id") == "cust-1"
    assert isinstance(kw.get("prompt_hash"), str)
    assert len(kw["prompt_hash"]) == 64  # SHA-256 hex


# ═══════════════ §9 · Lead recipient ══════════════════════════════════
def test_lead_recipient_resolves(monkeypatch, _wire_fakes):
    _as("admin")
    fake = _wire_fakes
    fake.leads.docs.append({
        "id": "lead-1", "tenant_id": "tenant-A",
        "first_name": "Lee", "interest": "pump repair",
    })
    _mock_llm(monkeypatch, text="Hi [FIRSTNAME]")
    r = client.post("/api/ai/draft-reply", json={
        "channel": "sms", "recipient_type": "lead",
        "recipient_id": "lead-1",
    })
    assert r.status_code == 200, r.text
    assert r.json()["draft_body"] == "Hi Lee"
