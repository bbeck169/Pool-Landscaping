"""Ticket LL · Feb-2026 — pytest suite for ``POST /api/ai/rewrite``.

In-process ``TestClient`` + ``monkeypatch`` on
``services.llm_provider.call_llm_with_fallback`` (the chokepoint).
Pattern byte-for-byte parity with
``backend/tests/test_ai_draft_reply.py`` so this suite doesn't need
a live Mongo / live Anthropic. No live LLM calls.

Covers:
  §1 happy path — payload shape (``rewritten`` + model + latency +
     token counts).
  §2 role gate — tech user → 403; admin / manager → 200.
  §3 minimum-length guard — <10 chars → 400 ``REWRITE_TOO_SHORT``.
  §4 2-second cooldown — second call within window → 429
     ``REWRITE_COOLDOWN`` + ``retry_after_seconds``.
  §5 hourly 20-call soft cap — 21st call in the same bucket → 429
     ``REWRITE_HOURLY_CAP`` + ``retry_after_seconds``.
  §6 upstream error → graceful 503 (not 500).
  §7 upstream empty result → graceful 503 ``REWRITE_EMPTY_RESULT``.
  §8 per-user isolation — user A hitting the cooldown doesn't
     affect user B.
  §9 whitespace-only text → 400 ``REWRITE_TOO_SHORT`` (defense-in-
     depth matches the FE ``value.trim().length`` gate).
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

# Ensure the backend package is importable before the server import.
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from server import app  # noqa: E402
from services.ai import draft_rate_limit, rewrite_hourly_cap  # noqa: E402

client = TestClient(app)

PFX = f"ll_rewrite_{uuid.uuid4().hex[:6]}_"
_DRAFT = "Hey can you let me know when the pool guy will be here"


# ─── Shared fixtures ─────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _wire_fakes():
    """Reset both rate-limit maps between cases so a prior test's
    stamp doesn't bleed into the next.  Mirrors the draft-reply
    suite's `_reset_for_tests` convention.
    """
    draft_rate_limit._reset_for_tests()
    rewrite_hourly_cap._reset_for_tests()
    yield


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _as(role: str, tenant_id: str = "tenant-A", user_id: str = "user-1"):
    """Install a dependency override so ``require_admin_or_manager``
    resolves to a canned user without touching the auth stack."""
    from utils import get_current_user
    user = {
        "id": user_id, "tenant_id": tenant_id, "role": role,
        "email": f"{role}@example.com",
    }
    app.dependency_overrides[get_current_user] = lambda: user
    return user


def _mock_llm(
    monkeypatch, *, text="Hello, please let me know when the technician "
    "will arrive.", err=None, cap=False,
):
    """Install a canned LLM response.  ``err`` triggers the empty-
    result path; ``cap`` triggers the cap-exceeded 429 translator;
    raising ``RuntimeError`` from within is tested separately via
    the chokepoint-raises monkeypatch below.
    """
    async def _fake(**kwargs):
        if cap:
            return {"error": "ai_spend_cap_exceeded", "cap_exceeded": True,
                    "http_status": 429}
        if err:
            return {"error": err}
        return {"raw": {"text": text, "prompt_tokens": 24,
                           "completion_tokens": 18},
                 "provider": "emergent"}
    from services import llm_provider
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _fake)


# ═══════════════ §1 · Happy path ═════════════════════════════════
def test_happy_path_returns_rewritten_payload(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch)
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["rewritten"] == (
        "Hello, please let me know when the technician will arrive."
    )
    assert j["model"] == "claude-sonnet-4-5-20250929"
    assert isinstance(j["latency_ms"], int) and j["latency_ms"] >= 0
    assert j["prompt_tokens"] == 24
    assert j["completion_tokens"] == 18


def test_manager_role_also_passes(monkeypatch):
    _as("manager")
    _mock_llm(monkeypatch)
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 200, r.text


# ═══════════════ §2 · Role gate — tech / customer → 403 ═════════
def test_tech_role_rejected():
    _as("technician")
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 403, r.text


# ═══════════════ §3 · Min-length guard ═══════════════════════════
def test_short_text_rejected(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch)
    r = client.post("/api/ai/rewrite", json={"text": "hi"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "REWRITE_TOO_SHORT"


def test_whitespace_only_text_rejected(monkeypatch):
    """Defense-in-depth parity with the FE ``value.trim().length``
    gate — a textarea of spaces must fail the length check even
    though pydantic's raw ``min_length=1`` accepts it."""
    _as("admin")
    _mock_llm(monkeypatch)
    r = client.post("/api/ai/rewrite", json={"text": "           "})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "REWRITE_TOO_SHORT"


# ═══════════════ §4 · 2-second cooldown ═════════════════════════
def test_cooldown_blocks_second_call(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch)
    r1 = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r2.status_code == 429, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "REWRITE_COOLDOWN"
    assert 0.0 < detail["retry_after_seconds"] <= 2.0


# ═══════════════ §5 · Hourly 20-call soft cap ═══════════════════
def test_hourly_cap_blocks_21st_call(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch)
    # Pre-populate the hourly counter with 20 "successful" stamps so
    # the next call is the 21st in the bucket.  Bypasses the 2-sec
    # cooldown map — the hourly cap check runs AFTER the cooldown
    # (both are in-process maps keyed on the same user).  We also
    # reset the cooldown map between stamps so our test loop can
    # reach the hourly cap without 429-ing on cooldown first.
    for _ in range(20):
        rewrite_hourly_cap.stamp(tenant_id="tenant-A", user_id="user-1")
    draft_rate_limit._reset_for_tests()
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 429, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "REWRITE_HOURLY_CAP"
    assert detail["retry_after_seconds"] > 0


# ═══════════════ §6 · Upstream chokepoint raises → 503 ══════════
def test_upstream_exception_returns_503(monkeypatch):
    _as("admin")

    async def _boom(**kwargs):
        raise RuntimeError("anthropic timeout")
    from services import llm_provider
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _boom)
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "REWRITE_UPSTREAM_UNAVAILABLE"


# ═══════════════ §7 · Upstream empty result → 503 ═══════════════
def test_upstream_empty_result_returns_503(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch, text="")  # empty text → fail-soft 503
    r = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "REWRITE_EMPTY_RESULT"


# ═══════════════ §8 · Per-user isolation ════════════════════════
def test_cooldown_is_per_user(monkeypatch):
    _as("admin", user_id="user-A")
    _mock_llm(monkeypatch)
    r1 = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r1.status_code == 200, r1.text
    # User A is now in cooldown.  Switch to user B — should pass.
    _as("admin", user_id="user-B")
    r2 = client.post("/api/ai/rewrite", json={"text": _DRAFT})
    assert r2.status_code == 200, r2.text


# ═══════════════ §9 · Pydantic max_length enforced ══════════════
def test_oversize_text_rejected(monkeypatch):
    _as("admin")
    _mock_llm(monkeypatch)
    r = client.post(
        "/api/ai/rewrite", json={"text": "x" * 4001},
    )
    assert r.status_code == 422, r.text  # pydantic validation
