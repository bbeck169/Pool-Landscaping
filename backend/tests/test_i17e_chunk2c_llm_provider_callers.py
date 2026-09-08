"""Phase I1.7.e · chunk 2.c · Feb-2026 — llm_provider chokepoint
caller migration regression suite.

Chunk 2.c migrates the 7 direct-``llm_provider`` callers so each
one:

1. Accepts an optional ``tenant_id`` kwarg (or already had one).
2. Threads that ``tenant_id`` through into
   ``services.llm_provider.call_llm_with_fallback`` for BYO
   provider routing + per-tenant monthly cap enforcement.
3. Honours the cap-exceeded contract:
     * transactional HTTP callers → propagate cap-exceeded so the
       router raises HTTP 429 via
       ``services.ai.cap_http.raise_if_ai_cap_exceeded``.
     * scheduled / cron callers → log ``skipped_cap_exceeded`` and
       return without raising so the batch continues.

The seven chokepoint callers covered by this suite:

    services/ai_estimator.py           (transactional HTTP)
    services/autopilot_copy.py         (transactional HTTP)
    services/aeo_fixes.py              (transactional HTTP)
    services/aeo_visibility.py         (dual — HTTP + cron)
    services/brand_mentions.py         (dual — sentiment is soft)
    services/response_drafts.py        (transactional HTTP)
    services/soshie/llm_moderation.py  (scheduled / autopilot gate)

Runs entirely offline. No API keys required. Uses the same
``call_llm_with_fallback`` monkeypatch pattern as
``test_i17e_chunk2_ai_callsite_migration.py`` so we exercise the
caller contract end-to-end without touching the real dispatcher.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_LOOP: Optional[asyncio.AbstractEventLoop] = None


from tests._phase34_asyncio import batch_safe_run as _run  # noqa: E402


def _direct_run(coro):
    """Legacy no-op preserved for readability."""
    return _run(coro)


@pytest.fixture(autouse=True)
def _disable_ai_testmode_by_default(monkeypatch):
    """Preview .env sets ``AI_TESTMODE_MOCK=true``; turn it off so
    the underlying provider probe fires in tests that want to see
    ``call_llm_with_fallback`` being invoked with ``tenant_id``."""
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")


# ─────────────────────────────────────────────────────────────────
# Signature checks (compile-time-ish) — every migrated public
# function MUST accept a ``tenant_id`` kwarg.
# ─────────────────────────────────────────────────────────────────
def _has_kwarg(func, name: str) -> bool:
    sig = inspect.signature(func)
    return name in sig.parameters


def test_all_seven_chokepoint_callers_accept_tenant_id_kwarg():
    """Static contract: each of the 7 chokepoint services exposes
    an entrypoint that takes an optional ``tenant_id`` kwarg. This
    is the migration handshake — every downstream caller (router,
    scheduler, cron) can opt into per-tenant BYO routing by
    passing one kwarg. Regressing the signature silently disables
    BYO for that service."""
    from services import (ai_estimator, autopilot_copy, aeo_fixes,
                            aeo_visibility, brand_mentions,
                            response_drafts)
    from services.soshie import llm_moderation

    assert _has_kwarg(ai_estimator.generate_estimate, "tenant_id")
    assert _has_kwarg(autopilot_copy.generate_copy, "tenant_id")
    assert _has_kwarg(aeo_fixes.generate_fixes, "tenant_id")
    assert _has_kwarg(aeo_visibility.run_probes, "tenant_id")
    assert _has_kwarg(brand_mentions.run_crawl, "tenant_id")
    assert _has_kwarg(response_drafts.create_or_get_draft, "tenant_id")
    # Moderator already threaded tenant_id positionally pre-migration
    # — the migration just teaches it to pass tenant_id through to
    # call_llm_with_fallback. Confirm the signature still exposes it.
    assert _has_kwarg(llm_moderation.moderate_post, "tenant_id")


# ─────────────────────────────────────────────────────────────────
# Runtime threading — each caller MUST pass ``tenant_id`` down into
# ``call_llm_with_fallback``. We monkeypatch the chokepoint and
# assert on the kwargs.
# ─────────────────────────────────────────────────────────────────
def _make_probe(captured: List[Dict[str, Any]],
                  *, cap_exceeded: bool = False,
                  answer_text: str = "hello world"):
    """Build a fake ``call_llm_with_fallback`` replacement that
    records every call and returns a canned response."""
    async def _probe(*, system_prompt: str, user_text: str,
                       photo_urls=None, provider="anthropic",
                       model="claude-sonnet-4-5",
                       tenant_id: Optional[str] = None):
        captured.append({
            "system_prompt": system_prompt,
            "user_text": user_text,
            "photo_urls": photo_urls,
            "provider": provider,
            "model": model,
            "tenant_id": tenant_id,
        })
        if cap_exceeded:
            return {"cap_exceeded": True, "http_status": 429,
                     "error": "ai_spend_cap_exceeded",
                     "provider": "tenant_byo"}
        return {"raw": {"text": answer_text, "answer": answer_text},
                "provider": "emergent"}
    return _probe


# ─────────────────────────────────────────────────────────────────
# Motor-free DB stand-in — every test that touches ``config.db`` or
# a module's captured ``db`` reference monkeypatches with this
# so we don't drag Motor into another test file's captured event
# loop. Chunk 2.c is a threading invariant; the DB layer is out
# of scope for this suite.
# ─────────────────────────────────────────────────────────────────
class _FakeCollection:
    """Motor-collection stand-in — every awaitable is a no-op."""
    async def find_one(self, *a, **k):
        return None

    async def insert_one(self, *a, **k):
        class _R:
            inserted_id = "fake-inserted-id"
        return _R()

    async def update_one(self, *a, **k):
        return None

    async def update_many(self, *a, **k):
        return None

    async def insert_many(self, *a, **k):
        return None

    async def count_documents(self, *a, **k):
        return 0

    async def delete_many(self, *a, **k):
        return None

    def find(self, *a, **k):
        return _EmptyCursor()


class _EmptyCursor:
    """Motor async cursor stand-in that yields nothing and supports
    the chained ``.sort()`` / ``.limit()`` / ``.skip()`` builders."""
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    # Motor cursor builders return ``self`` so the caller can await
    # the final ``async for``. No-op for our empty fixture.
    def limit(self, *_a, **_k):
        return self

    def sort(self, *_a, **_k):
        return self

    def skip(self, *_a, **_k):
        return self

    def batch_size(self, *_a, **_k):
        return self

    async def to_list(self, *_a, **_k):
        return []


class _FakeDB:
    def __getattr__(self, name):
        return _FakeCollection()


def _use_fake_db(monkeypatch, module):
    """Replace ``<module>.db`` with a Motor-free stand-in for the
    duration of one test. Isolates chunk 2.c invariants from the
    Motor loop-binding gymnastics in ``test_brand_mentions.py`` /
    ``test_response_drafts.py``."""
    monkeypatch.setattr(module, "db", _FakeDB(), raising=False)


# ─── 1. ai_estimator ────────────────────────────────────────────
def test_ai_estimator_generate_estimate_threads_tenant_id(monkeypatch):
    from services import ai_estimator
    from services import llm_provider

    _use_fake_db(monkeypatch, ai_estimator)
    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text=(
                            '{"line_items": [], "confidence": 0.9}')))

    _run(ai_estimator.generate_estimate(
        tenant_id="tenant-estimator-99",
        photo_urls=[], job_description="clean coping tile",
        options_mode="single", extras={},
    ))

    assert captured, "call_llm_with_fallback was never invoked"
    assert captured[0]["tenant_id"] == "tenant-estimator-99", (
        f"ai_estimator did not thread tenant_id — saw {captured[0]!r}"
    )


def test_ai_estimator_generate_estimate_returns_cap_exceeded(monkeypatch):
    """Transactional caller: cap-exceeded surfaces as
    ``{'error': 'ai_spend_cap_exceeded', 'cap_exceeded': True}`` so
    the ai_estimator router can raise HTTP 429."""
    from services import ai_estimator, llm_provider
    from services.ai.cap_http import (raise_if_ai_cap_exceeded,
                                         is_ai_cap_exceeded)
    from fastapi import HTTPException

    _use_fake_db(monkeypatch, ai_estimator)
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))

    out = _run(ai_estimator.generate_estimate(
        tenant_id="t-cap",
        photo_urls=[], job_description="d",
        options_mode="single", extras={},
    ))
    assert is_ai_cap_exceeded(out) is True
    with pytest.raises(HTTPException) as exc:
        raise_if_ai_cap_exceeded(out)
    assert exc.value.status_code == 429


# ─── 2. autopilot_copy ──────────────────────────────────────────
def test_autopilot_copy_threads_tenant_id(monkeypatch):
    from services import autopilot_copy, llm_provider

    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text=(
                            '{"subject": "Hi", "body_text": "Hello", '
                            '"body_sms": "Hi"}')))
    _run(autopilot_copy.generate_copy(
        trigger_event="job_completed", channel="email",
        tone="friendly", company_name="Acme Pools",
        tenant_id="tenant-autopilot-42",
    ))
    assert captured, "call_llm_with_fallback was never invoked"
    assert captured[0]["tenant_id"] == "tenant-autopilot-42"


def test_autopilot_copy_cap_exceeded_surface(monkeypatch):
    from services import autopilot_copy, llm_provider
    from services.ai.cap_http import is_ai_cap_exceeded

    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))
    out = _run(autopilot_copy.generate_copy(
        trigger_event="job_completed", channel="email",
        tone="friendly", company_name="Acme",
        tenant_id="t-cap",
    ))
    assert is_ai_cap_exceeded(out) is True


# ─── 3. aeo_fixes ───────────────────────────────────────────────
def _seed_fake_scan(scan_id: str, tenant_id: str) -> Any:
    """Return a fake DB stand-in whose ``seo_scans.find_one`` returns
    a scan doc with a LOW ``faq`` sub-signal so the LLM branch of
    :func:`services.aeo_fixes.generate_fixes` actually fires."""
    scan_doc = {
        "id": scan_id, "tenant_id": tenant_id,
        "results": {"aeo_signals": {
            "faq": {"score": 20},
            "schema": {"score": 90},
            "passages": {"score": 90},
            "entity_clarity": {"score": 90},
            "llms_txt": {"score": 90},
        }},
    }

    class _ScanCollection(_FakeCollection):
        async def find_one(self, *a, **k):
            return scan_doc

    class _FakeDBWithScan(_FakeDB):
        def __getattr__(self, name):
            if name == "seo_scans":
                return _ScanCollection()
            return _FakeCollection()

    return _FakeDBWithScan()


def test_aeo_fixes_generate_fixes_threads_tenant_id(monkeypatch):
    from services import aeo_fixes, llm_provider

    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text="ok"))
    monkeypatch.setattr(aeo_fixes, "db",
                        _seed_fake_scan("scan_chunk2c_fixes", "t-fixes"))

    tenant = {"id": "t-fixes", "name": "PoolCo",
                "address": {"city": "Phoenix"},
                "service_types": ["pool cleaning"]}
    _run(aeo_fixes.generate_fixes("scan_chunk2c_fixes", tenant,
                                    requested_signals=["faq"],
                                    tenant_id="t-fixes"))

    assert captured, "no llm call was made"
    assert captured[0]["tenant_id"] == "t-fixes"


def test_aeo_fixes_cap_exceeded_returns_marker(monkeypatch):
    from services import aeo_fixes, llm_provider
    from services.ai.cap_http import is_ai_cap_exceeded

    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))
    monkeypatch.setattr(aeo_fixes, "db",
                        _seed_fake_scan("scan_chunk2c_fixes_cap", "t-cap"))

    tenant = {"id": "t-cap", "name": "PoolCo",
                "address": {"city": "Phoenix"},
                "service_types": ["pool cleaning"]}
    out = _run(aeo_fixes.generate_fixes("scan_chunk2c_fixes_cap", tenant,
                                          requested_signals=["faq"],
                                          tenant_id="t-cap"))
    assert is_ai_cap_exceeded(out) is True


# ─── 4. aeo_visibility ──────────────────────────────────────────
def test_aeo_visibility_run_probes_threads_tenant_id(monkeypatch):
    from services import aeo_visibility, llm_provider

    _use_fake_db(monkeypatch, aeo_visibility)
    # Short-circuit the month-cost pre-check so we don't need a live
    # Motor client — chunk 2.c is about tenant_id threading, not
    # cost accounting.
    async def _no_cost(*a, **k):
        return 0.0
    monkeypatch.setattr(aeo_visibility, "month_cost_usd", _no_cost)

    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured))

    tenant = {"id": "t-vis", "name": "Aqua Pools",
                "url": "https://aquapools.example",
                "address": {"city": "Phoenix", "state": "AZ"}}
    _run(aeo_visibility.run_probes(
        tenant, templates=["Best in {city}?"],
        providers=[{"key": "openai_gpt", "provider": "openai",
                     "model": "gpt-4o"}],
        tenant_id="t-vis",
    ))

    assert captured, "no llm call was made"
    assert captured[0]["tenant_id"] == "t-vis"


def test_aeo_visibility_cap_exceeded_halts_and_surfaces(monkeypatch):
    from services import aeo_visibility, llm_provider
    from services.ai.cap_http import is_ai_cap_exceeded

    _use_fake_db(monkeypatch, aeo_visibility)
    async def _no_cost(*a, **k):
        return 0.0
    monkeypatch.setattr(aeo_visibility, "month_cost_usd", _no_cost)
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))

    tenant = {"id": "t-vis-cap", "name": "Aqua Pools",
                "url": "https://aquapools.example",
                "address": {"city": "Phoenix", "state": "AZ"}}
    out = _run(aeo_visibility.run_probes(
        tenant, templates=["Best in {city}?", "Cheapest in {city}?"],
        providers=[{"key": "openai_gpt", "provider": "openai",
                     "model": "gpt-4o"}],
        tenant_id="t-vis-cap",
    ))

    assert is_ai_cap_exceeded(out) is True
    assert out["summary"]["total"] == 0, (
        "cap-exceeded on first probe should short-circuit the loop"
    )


# ─── 5. brand_mentions ──────────────────────────────────────────
def test_brand_mentions_sentiment_threads_tenant_id(monkeypatch):
    from services import brand_mentions, llm_provider

    _use_fake_db(monkeypatch, brand_mentions)
    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text="positive"))

    tid = "t-mentions"
    _run(brand_mentions._sentiment(
        "Best pool company in Phoenix I've ever used, would recommend!!",
        tid,
    ))

    assert captured, "no llm call was made"
    assert captured[0]["tenant_id"] == tid


def test_brand_mentions_sentiment_cap_exceeded_returns_none(monkeypatch):
    """Sentiment is a soft field — on cap-exceeded, the classifier
    returns ``None`` and logs ``skipped_cap_exceeded``. The mention
    row still lands in the crawl output."""
    from services import brand_mentions, llm_provider

    _use_fake_db(monkeypatch, brand_mentions)
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))

    tid = "t-mentions-cap"
    out = _run(brand_mentions._sentiment(
        "Long snippet " * 20, tid,
    ))
    assert out is None


# ─── 6. response_drafts ─────────────────────────────────────────
def test_response_drafts_create_or_get_draft_threads_tenant_id(monkeypatch):
    from services import response_drafts, llm_provider

    _use_fake_db(monkeypatch, response_drafts)
    # response_drafts imports response_library lazily for examples —
    # short-circuit that too so the test doesn't hit Motor.
    async def _empty_examples(*a, **k):
        return []
    monkeypatch.setattr(
        "services.response_library.top_templates_for",
        _empty_examples, raising=False,
    )

    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text="Thanks for your review!"))

    tenant = {"id": "t-drafts", "name": "PoolCo"}
    mention = {"mention_id": "m_test_1", "domain": "google.com",
                 "url": "https://google.com/maps/reviews/x",
                 "snippet": "great service"}
    _run(response_drafts.create_or_get_draft(
        tenant=tenant, mention=mention, tone="empathetic",
        regenerate=True, user_id="",
        tenant_id="t-drafts",
    ))

    assert captured, "no llm call was made"
    assert captured[0]["tenant_id"] == "t-drafts"


def test_response_drafts_cap_exceeded_returns_marker(monkeypatch):
    from services import response_drafts, llm_provider
    from services.ai.cap_http import is_ai_cap_exceeded

    _use_fake_db(monkeypatch, response_drafts)
    async def _empty_examples(*a, **k):
        return []
    monkeypatch.setattr(
        "services.response_library.top_templates_for",
        _empty_examples, raising=False,
    )
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))
    tenant = {"id": "t-drafts-cap", "name": "PoolCo"}
    mention = {"mention_id": "m_cap_1", "domain": "google.com",
                 "url": "https://google.com/maps/reviews/x",
                 "snippet": "review"}
    out = _run(response_drafts.create_or_get_draft(
        tenant=tenant, mention=mention, tone="empathetic",
        regenerate=True, tenant_id="t-drafts-cap",
    ))
    assert is_ai_cap_exceeded(out) is True


# ─── 7. soshie/llm_moderation ───────────────────────────────────
def _stub_moderation_gates(monkeypatch):
    """Bypass the credit + cache gates + DB persistence so the
    migration invariant (thread tenant_id into
    ``call_llm_with_fallback``) actually runs. Both gates are
    orthogonal to chunk 2.c and covered by their own test suites."""
    from services.soshie import llm_moderation
    async def _no_cache(*a, **k):
        return None
    async def _healthy(*a, **k):
        return 999999
    async def _passthrough_store(**kwargs):
        # Return the row the real ``_store_result`` would have
        # written, minus the Motor round-trip.
        from datetime import datetime, timezone
        row = {
            "tenant_id": kwargs.get("tenant_id"),
            "post_id": kwargs.get("post_id"),
            "decision": kwargs.get("decision"),
            "reasons": list(kwargs.get("reasons") or []),
            "risk_level": kwargs.get("risk_level"),
            "error": kwargs.get("error"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return row
    monkeypatch.setattr(llm_moderation, "_find_cached",
                        _no_cache, raising=False)
    monkeypatch.setattr(llm_moderation, "_tenant_credit_balance",
                        _healthy, raising=False)
    monkeypatch.setattr(llm_moderation, "_store_result",
                        _passthrough_store, raising=False)


def test_soshie_moderation_threads_tenant_id(monkeypatch):
    from services.soshie import llm_moderation
    from services import llm_provider

    _stub_moderation_gates(monkeypatch)
    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe(captured, answer_text=(
                            '{"decision": "approve", "reasons": [], '
                            '"risk_level": "low"}')))

    tid = "t-mod"
    post_id = "p_test_1"
    _run(llm_moderation.moderate_post(
        tenant_id=tid, post_id=post_id,
        text="Hello, come book a pool cleaning appointment.",
        media_urls=[],
    ))

    assert captured, "no llm call was made"
    assert captured[0]["tenant_id"] == tid


def test_soshie_moderation_cap_exceeded_logs_skipped_and_flags(monkeypatch):
    """Scheduled path: cap-exceeded MUST NOT raise. Instead the
    moderation row lands with ``decision='flag'`` and reason
    ``skipped_cap_exceeded`` so autopilot queues it for human
    review — the safest posture when the LLM is unavailable."""
    from services.soshie import llm_moderation
    from services import llm_provider

    _stub_moderation_gates(monkeypatch)
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _make_probe([], cap_exceeded=True))

    tid = "t-mod-cap"
    post_id = "p_cap_1"
    result = _run(llm_moderation.moderate_post(
        tenant_id=tid, post_id=post_id,
        text="Long enough text to bypass the regex short-circuit "
               "and land in the LLM branch of the moderation gate.",
        media_urls=[],
    ))

    assert result["decision"] == "flag"
    assert "skipped_cap_exceeded" in (result.get("reasons") or []), (
        f"expected skipped_cap_exceeded reason, saw {result!r}"
    )


# ─────────────────────────────────────────────────────────────────
# P0 invariant guard — checklist load path must remain AI-free.
# ─────────────────────────────────────────────────────────────────
def test_checklist_load_path_has_no_llm_provider_call():
    """Chunk 2.c sibling of the chunk 1 checklist invariant. The
    two checklist load endpoints (``GET /api/jobs/{id}``,
    ``GET /api/jobs/{id}/service-report``) MUST NOT invoke any of
    the seven migrated llm_provider callers on the load path. A
    leak here would 429 mobile checklist opens whenever the
    tenant's monthly AI cap is exceeded — the same P0 shape."""
    import ast
    from routers import jobs as jobs_router
    src = inspect.getsource(jobs_router)

    forbidden = (
        "generate_estimate(", "generate_copy(", "generate_fixes(",
        "run_probes(", "run_crawl(", "create_or_get_draft(",
        "moderate_post(",
        "call_llm_with_fallback(",
    )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        name = node.name.lower()
        if "checklist" not in name and "service_report" not in name:
            continue
        if any(tok in name for tok in ("submit", "finalize",
                                         "create", "update", "delete")):
            continue
        body_src = ast.get_source_segment(src, node) or ""
        for f in forbidden:
            assert f not in body_src, (
                f"P0 REGRESSION: jobs router {node.name!r} calls {f!r} "
                f"— the checklist load path must not touch AI."
            )
