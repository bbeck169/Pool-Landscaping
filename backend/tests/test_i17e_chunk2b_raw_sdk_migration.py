"""Phase I1.7.e · Chunk 2.b · Feb-2026 — raw-SDK AI callsite migration
regression suite.

Guards the 21 backend files (transactional + cron) that were migrated
off the raw ``emergentintegrations.llm.chat.LlmChat`` SDK and onto the
central AI chokepoint (``services.llm_provider.call_llm_with_fallback``).

Invariants asserted:

1. **AST guard — no raw-SDK imports remain** on any migrated file. Any
   future re-introduction of ``from emergentintegrations.llm.chat
   import LlmChat`` on a migrated file is a hard regression.
2. **AST guard — chokepoint import present** on every migrated file
   that emitted at least one migrated callsite.  A migration that
   left the file unable to reach the chokepoint is a regression.
3. **Cap-exceeded posture** — every migrated callsite is either:
     * transactional → raises ``HTTPException(429)`` via
       ``raise_if_ai_cap_exceeded(result)``, OR
     * scheduled / best-effort → inspects the result with
       ``is_ai_cap_exceeded(result)`` and degrades to a mocked / stub
       shape (never crashes the cron / never leaks the raw HTTP 500).
   The guard is a source scan: every migrated file MUST reference
   either ``raise_if_ai_cap_exceeded`` or ``is_ai_cap_exceeded``.
4. **§3.3 plumbing-only** — the chemistry / service_reports files
   changed the AI callsite ONLY.  No new endpoints, no schema
   surface changes.  AST-verified by comparing the pre-migration
   route table (frozen at Feb-2026) against the current router.
5. **P0 checklist invariant sibling** — reasserts the checklist load
   path has NO chokepoint dispatch (mirror of the Chunk 2 guard so
   the invariant survives even if the chunk 2 file is removed).

Runs entirely offline. No API keys required.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Iterable

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ── Frozen scope: the 21 files approved in the §3 scope audit ──────────
_SCOPE_31_MAIN = [
    "routers/admin.py",
    "routers/ai_brain.py",
    "routers/ai_employees.py",
    "routers/ai_ops.py",
    "routers/ai_visibility.py",
    "routers/business_os.py",
    "routers/cfo.py",
    "routers/churn.py",
    "routers/gbp.py",
    "routers/gbp_posts.py",
    "routers/marketing_studio.py",
    "routers/phase11.py",
    "routers/portal.py",
    "routers/reviews_ai_reply.py",
    "routers/seo.py",
    "routers/seo_agentic.py",
    "routers/seo_content_refresh.py",
    "routers/seo_phase17c.py",
    "routers/social.py",
]

_SCOPE_32_BASE64_VISION = [
    "routers/estimator.py",
    "services/ai/estimate_from_media.py",
]

_SCOPE_33_CHEM_SERVICE_REPORTS = [
    "routers/chemicals.py",
    "routers/service_reports.py",
]

_ALL_MIGRATED_FILES = (
    _SCOPE_31_MAIN + _SCOPE_32_BASE64_VISION + _SCOPE_33_CHEM_SERVICE_REPORTS
)


def _read(rel: str) -> str:
    return (BACKEND_ROOT / rel).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# 1. AST guard — no raw-SDK imports remain on any migrated file
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", _ALL_MIGRATED_FILES)
def test_no_raw_sdk_import_remains(rel: str):
    """Any ``from emergentintegrations.llm.chat import ...`` line on a
    migrated file is a hard regression.  Substring-in-comment references
    (docstrings, migration comments) are permitted — we ONLY reject
    real ``import`` statements."""
    tree = ast.parse(_read(rel), filename=rel)

    def _walk(node: ast.AST) -> Iterable[ast.AST]:
        yield node
        for child in ast.iter_child_nodes(node):
            yield from _walk(child)

    for node in _walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("emergentintegrations.llm.chat"):
                names = ", ".join(a.name for a in node.names)
                pytest.fail(
                    f"REGRESSION in {rel}: raw-SDK import at line "
                    f"{node.lineno}: from {mod} import {names}. "
                    f"Route through services.llm_provider.call_llm_with_fallback "
                    f"instead."
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("emergentintegrations.llm.chat"):
                    pytest.fail(
                        f"REGRESSION in {rel}: raw-SDK import at line "
                        f"{node.lineno}: import {alias.name}"
                    )


# ─────────────────────────────────────────────────────────────────────
# 2. AST guard — no naked LlmChat( or UserMessage( calls
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", _ALL_MIGRATED_FILES)
def test_no_naked_llmchat_construction(rel: str):
    """A migrated file MUST NOT construct ``LlmChat(...)`` or send
    ``UserMessage(...)`` directly.  Comments / docstrings are allowed
    (some migration notes reference the class name) — we scan
    ``ast.Call`` nodes so string references never trip this guard."""
    tree = ast.parse(_read(rel), filename=rel)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Handle ``LlmChat(...)`` and ``ext.LlmChat(...)``
        if isinstance(func, ast.Name) and func.id in ("LlmChat", "UserMessage"):
            pytest.fail(
                f"REGRESSION in {rel}: naked {func.id}(...) call at "
                f"line {node.lineno}. Route through "
                f"services.llm_provider.call_llm_with_fallback."
            )
        if isinstance(func, ast.Attribute) and func.attr in (
            "LlmChat", "UserMessage",
        ):
            pytest.fail(
                f"REGRESSION in {rel}: naked .{func.attr}(...) call at "
                f"line {node.lineno}."
            )


# ─────────────────────────────────────────────────────────────────────
# 3. Chokepoint import present on every migrated file
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", _ALL_MIGRATED_FILES)
def test_chokepoint_import_present(rel: str):
    """Every migrated file MUST reference the chokepoint. The import
    can be module-level OR inline (some files inline it inside the
    handler to keep the module lightweight for the checklist load
    path).  Either shape satisfies the guard."""
    src = _read(rel)
    assert "call_llm_with_fallback" in src, (
        f"MIGRATION INCOMPLETE in {rel}: file no longer imports the "
        f"raw SDK but also does not reference "
        f"``services.llm_provider.call_llm_with_fallback``. Every "
        f"migrated AI callsite MUST route through the chokepoint."
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Cap-exceeded posture — every migrated file references a cap helper
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", _ALL_MIGRATED_FILES)
def test_cap_helper_referenced(rel: str):
    """Transactional callsites use ``raise_if_ai_cap_exceeded`` (429
    for cap-exceeded).  Scheduled / best-effort callsites use
    ``is_ai_cap_exceeded`` (degrade to stub / mocked shape).  A
    migrated file with NO cap helper reference is a regression — it
    means a cap-exceeded response would silently pass through the
    handler's downstream JSON parse and 500 the request.
    """
    src = _read(rel)
    assert (
        "raise_if_ai_cap_exceeded" in src or "is_ai_cap_exceeded" in src
    ), (
        f"REGRESSION in {rel}: migrated file has no cap-exceeded "
        f"check. Add ``raise_if_ai_cap_exceeded(result)`` (transactional) "
        f"or ``if is_ai_cap_exceeded(result): return <stub>`` (scheduled)."
    )


# ─────────────────────────────────────────────────────────────────────
# 5. §3.3 files are plumbing-only — no new / removed public routes
# ─────────────────────────────────────────────────────────────────────
# Frozen route lists captured Feb-2026 before Chunk 2.b landed. If a
# migration accidentally added / removed a public route on chemistry
# or service_reports the diff surfaces here.
_FROZEN_CHEMICALS_ROUTES = {
    ("GET", "/chemicals/catalog"),
    ("POST", "/chemicals/dosing-recommendation"),
}
# service_reports.py has ~30 endpoints; we assert the small subset that
# would break the tech mobile flow if renamed.  A full route-diff test
# lives in test_routes_registry.py.
_FROZEN_SERVICE_REPORT_ANCHOR_ROUTES = {
    ("GET", "/jobs/{jid}/service-report"),
    ("PATCH", "/jobs/{jid}/service-report"),
    ("POST", "/jobs/{jid}/service-report/submit"),
    ("POST", "/service-report/analyze-water-photo"),
    ("POST", "/service-report/recommend-chemicals"),
}


def _collect_routes(module_name: str) -> set[tuple[str, str]]:
    from importlib import import_module

    mod = import_module(module_name)
    router = getattr(mod, "router", None)
    assert router is not None, f"module {module_name} has no `router`"
    out: set[tuple[str, str]] = set()
    for r in router.routes:
        methods = getattr(r, "methods", None) or set()
        path = getattr(r, "path", "")
        for m in methods:
            if m == "HEAD":
                continue
            out.add((m, path))
    return out


def test_chemicals_routes_unchanged_plumbing_only():
    """Chunk 2.b §3.3 — the chemicals router migration touched ONLY
    the internal LLM callsite.  The public route table must match the
    frozen list exactly (no added, renamed, or removed routes)."""
    got = _collect_routes("routers.chemicals")
    assert got == _FROZEN_CHEMICALS_ROUTES, (
        f"§3.3 REGRESSION: chemicals router route table drifted.\n"
        f"  missing:  {_FROZEN_CHEMICALS_ROUTES - got}\n"
        f"  extra:    {got - _FROZEN_CHEMICALS_ROUTES}\n"
        f"Chunk 2.b was approved as plumbing-only for this file."
    )


def test_service_reports_anchor_routes_present():
    """Chunk 2.b §3.3 — service_reports migration is plumbing-only.
    The 5 tech-facing anchor routes MUST still exist verbatim so the
    mobile flow (bootstrap → autosave → submit → water-photo → dose
    recommender) doesn't regress."""
    got = _collect_routes("routers.service_reports")
    missing = _FROZEN_SERVICE_REPORT_ANCHOR_ROUTES - got
    assert not missing, (
        f"§3.3 REGRESSION: service_reports anchor routes missing: "
        f"{missing}. Chunk 2.b was approved as plumbing-only."
    )


# ─────────────────────────────────────────────────────────────────────
# 6. Base64-vision files use image_b64s kwarg (not raw ImageContent)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", _SCOPE_32_BASE64_VISION + [
    # service_reports.py's analyze-water-photo also does base64 vision.
    "routers/service_reports.py",
    # social.py's alt-text endpoint fetches + b64-encodes.
    "routers/social.py",
])
def test_base64_vision_uses_image_b64s(rel: str):
    """§3.2 base64-vision sub-pass — the migrated files that used
    ``ImageContent(image_base64=...)`` MUST now pass ``image_b64s=``
    to the chokepoint. If the kwarg is missing on a file that we
    KNOW passes photos, the migration didn't complete."""
    src = _read(rel)
    assert "image_b64s" in src, (
        f"§3.2 REGRESSION in {rel}: base64 vision migration did not "
        f"plumb ``image_b64s`` through to the chokepoint. Photos "
        f"are being dropped silently."
    )


# ─────────────────────────────────────────────────────────────────────
# 7. Chokepoint itself supports the new kwargs
# ─────────────────────────────────────────────────────────────────────
def test_chokepoint_supports_image_b64s_parse_json_max_tokens():
    """The chokepoint's signature MUST accept ``image_b64s``,
    ``parse_json``, and ``max_tokens``. Removing any of these three
    would silently break the §3.2 base64-vision callers and the
    ``max_tokens``-bound callers (churn.py, business_os.py, cfo.py,
    reviews_ai_reply.py, gbp_posts.py, service_reports dosing).
    """
    from services.llm_provider import call_llm_with_fallback

    sig = inspect.signature(call_llm_with_fallback)
    for kw in ("image_b64s", "parse_json", "max_tokens", "tenant_id"):
        assert kw in sig.parameters, (
            f"Chokepoint signature regression: kwarg {kw!r} missing "
            f"from call_llm_with_fallback(). Chunk 2.b callers depend "
            f"on it."
        )


# ─────────────────────────────────────────────────────────────────────
# 8. P0 checklist invariant sibling — no chokepoint calls on load path
# ─────────────────────────────────────────────────────────────────────
def test_checklist_load_path_has_no_chokepoint_dispatch():
    """Mirror of the chunk 2 guard (kept here so the invariant survives
    even if the chunk 2 file is deleted). The two checklist load
    endpoints must NEVER invoke the chokepoint synchronously — that
    would 429 mobile checklist opens for AI-cap-exhausted tenants."""
    from routers import jobs as jobs_router

    src = inspect.getsource(jobs_router)
    forbidden = (
        "call_llm_with_fallback(",
        "dispatch_ai_completion(",
        "raise_if_ai_cap_exceeded(",
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
        for forbidden_tok in forbidden:
            assert forbidden_tok not in body_src, (
                f"P0 REGRESSION: jobs router function {node.name!r} "
                f"contains forbidden AI call {forbidden_tok!r}. The "
                f"checklist load path MUST NOT invoke the chokepoint."
            )


# ─────────────────────────────────────────────────────────────────────
# 9. Docstring guard — the chokepoint's cap-exceeded contract survives
# ─────────────────────────────────────────────────────────────────────
def test_chokepoint_cap_exceeded_doc_still_present():
    """Meta-guard: the chokepoint MUST still document that on
    ``TenantAIUsageCapExceeded`` it returns ``cap_exceeded=True`` +
    ``error="ai_spend_cap_exceeded"`` INSTEAD OF raising. Chunk 2.b
    callers depend on this contract to keep degrade paths simple
    (``if is_ai_cap_exceeded(result): return <stub>``)."""
    from services import llm_provider

    src = inspect.getsource(llm_provider.call_llm_with_fallback)
    # Either the docstring or an inline exception handler must
    # reference the cap-exceeded contract.
    assert (
        "cap_exceeded" in src
        or "TenantAIUsageCapExceeded" in src
        or "ai_spend_cap_exceeded" in src
    )


# ─────────────────────────────────────────────────────────────────────
# 10. BYO opt-in follow-up (Chunk 2.b · Feb-2026, second push)
# ─────────────────────────────────────────────────────────────────────
# The initial Chunk 2.b push migrated 21 files off the raw SDK but a
# handful of callers still passed ``tenant_id=None`` to preserve the
# "zero behavior change" invariant. This second push threads the real
# ``tenant["id"]`` down each of those 5 callsites so BYO keys +
# per-tenant cap actually kick in.
#
# The tests below patch ``call_llm_with_fallback`` and drive each
# migrated function to prove:
#
#   (a) the chokepoint receives a non-None ``tenant_id`` kwarg, AND
#   (b) the existing cap posture is preserved (transactional callers
#       raise / caller-side-map to 429; background / helper callers
#       degrade gracefully to the mocked shape).
#
# All tests are import + monkeypatch-only — no Mongo required, so
# they run even while preview Mongo is down.
import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock


def _make_ok_result(text: str = '{"score": 82, "critique": "ok"}') -> Dict[str, Any]:
    """A chokepoint result that mimics the ``parse_json=False`` shape
    the Chunk 2.b callers expect. Never cap-exceeded, never errored."""
    return {"raw": {"text": text}, "provider": "anthropic", "error": None}


def _make_cap_exceeded_result() -> Dict[str, Any]:
    """Cap-exceeded shape per the chokepoint's Chunk 2 contract."""
    return {"raw": None, "provider": None,
             "error": "ai_spend_cap_exceeded",
             "cap_exceeded": True}


# ── 1. business_os._ai_generate — best-effort helper (degrades) ──
def test_business_os_ai_generate_threads_tenant_id(monkeypatch):
    """``_ai_generate`` MUST forward the caller's ``tenant_id`` to the
    chokepoint. Cap-exceeded path degrades to a friendly stub — never
    raises — because SOP / huddle / retro drafters are non-blocking."""
    from routers import business_os

    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    monkeypatch.setattr(business_os, "EMERGENT_LLM_KEY", "test-key")

    captured: Dict[str, Any] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return _make_ok_result("Step 1. Suit up.\nStep 2. Test.")

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call,
    )

    out = asyncio.run(business_os._ai_generate(
        "system", "user prompt", max_tokens=600,
        tenant_id="tenant-abc-123",
    ))
    assert "Step 1" in out
    assert captured.get("tenant_id") == "tenant-abc-123", (
        "BYO regression: business_os._ai_generate did not forward "
        "tenant_id to call_llm_with_fallback. Per-tenant BYO keys / "
        "AI spend caps will not fire."
    )

    # Cap-exceeded posture — best-effort, degrades to stub, no raise.
    async def fake_call_cap(**kwargs):
        return _make_cap_exceeded_result()

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call_cap,
    )
    out = asyncio.run(business_os._ai_generate(
        "system", "user prompt", max_tokens=600,
        tenant_id="tenant-abc-123",
    ))
    assert "cap" in out.lower() or "unavailable" in out.lower(), (
        "Cap-exceeded posture regression: business_os._ai_generate "
        "should degrade to a friendly stub on cap-exceeded, not raise."
    )


# ── 2. marketing_studio._ai_variant — best-effort helper (degrades) ──
def test_marketing_studio_ai_variant_threads_tenant_id(monkeypatch):
    """``_ai_variant`` / ``_ai_email`` / ``_ai_sms`` all accept
    ``tenant_id`` post-follow-up. Best-effort — cap-exceeded falls
    back to a deterministic stub."""
    from routers import marketing_studio

    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    monkeypatch.setattr(marketing_studio, "EMERGENT_LLM_KEY", "test-key")

    captured: Dict[str, Any] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return _make_ok_result(
            '{"copy": "Pool day!", "hashtags": "#pool", "cta": "Book now"}'
        )

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call,
    )

    brand = {"tone": "professional", "service_area": "Peoria",
              "service_zips": ["85383"]}
    out = asyncio.run(marketing_studio._ai_variant(
        "facebook", "spring cleanup", brand, tenant_id="tenant-mkt-77",
    ))
    assert out["channel"] == "facebook"
    assert captured.get("tenant_id") == "tenant-mkt-77", (
        "BYO regression: marketing_studio._ai_variant did not "
        "forward tenant_id to the chokepoint."
    )

    # Cap-exceeded — falls back to _stub_variant, no raise.
    async def fake_call_cap(**kwargs):
        return _make_cap_exceeded_result()

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call_cap,
    )
    out = asyncio.run(marketing_studio._ai_variant(
        "facebook", "spring cleanup", brand, tenant_id="tenant-mkt-77",
    ))
    # Stub variant returns the same schema shape; test that it didn't
    # raise + shape is preserved.
    assert isinstance(out, dict) and "copy" in out


# ── 3. seo_phase17c._claude_patch — transactional (OTTO generate) ──
def test_seo_phase17c_claude_patch_threads_tenant_id(monkeypatch):
    """OTTO ``_claude_patch`` is invoked from the transactional
    ``POST /otto/generate-fixes`` endpoint (user clicks button and
    waits). Cap-exceeded returns ``mocked=True`` + reason so the
    caller can still write the fix row — the endpoint aggregates
    per-issue outcomes and does not raise 429 mid-loop."""
    from routers import seo_phase17c

    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    monkeypatch.setattr(seo_phase17c, "EMERGENT_LLM_KEY", "test-key")

    captured: Dict[str, Any] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return _make_ok_result(
            '{"suggested_value": "Pool Cleaning Peoria AZ",'
            ' "patch_snippet": "<title>Pool Cleaning Peoria AZ</title>",'
            ' "rationale": "keyword-rich"}'
        )

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call,
    )

    out = asyncio.run(seo_phase17c._claude_patch(
        "TITLE_MISSING", "https://example.com", "",
        "Pool cleaning services in Peoria",
        tenant_id="tenant-seo-42",
    ))
    assert out["patch_snippet"].startswith("<title>")
    assert captured.get("tenant_id") == "tenant-seo-42", (
        "BYO regression: seo_phase17c._claude_patch did not forward "
        "tenant_id. Per-tenant cap on OTTO generate will not fire."
    )

    # Cap-exceeded — returns mocked=True (loop-safe), no raise.
    async def fake_call_cap(**kwargs):
        return _make_cap_exceeded_result()

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call_cap,
    )
    out = asyncio.run(seo_phase17c._claude_patch(
        "TITLE_MISSING", "https://example.com", "",
        "Pool cleaning services in Peoria",
        tenant_id="tenant-seo-42",
    ))
    assert out.get("mocked") is True
    assert out.get("rationale") == "ai_spend_cap_exceeded", (
        "Cap-exceeded posture regression: OTTO _claude_patch should "
        "surface 'ai_spend_cap_exceeded' in the rationale so the "
        "endpoint's aggregated response has an audit trail."
    )


# ── 4. seo_agentic._llm_semantic — best-effort helper (degrades) ──
def test_seo_agentic_llm_semantic_threads_tenant_id(monkeypatch):
    """The semantic-relevance scorer is one input among 8 in the
    ``/seo/content-score`` breakdown. Cap-exceeded returns a mocked
    ``score=60`` so the composite score endpoint still succeeds."""
    from routers import seo_agentic

    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    monkeypatch.setattr(seo_agentic, "EMERGENT_LLM_KEY", "test-key")

    captured: Dict[str, Any] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return _make_ok_result('{"score": 88, "critique": "on-topic"}')

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call,
    )

    out = asyncio.run(seo_agentic._llm_semantic(
        "pool cleaning", "Weekly pool cleaning in Peoria AZ.",
        tenant_id="tenant-agentic-99",
    ))
    assert out["score"] == 88
    assert captured.get("tenant_id") == "tenant-agentic-99", (
        "BYO regression: seo_agentic._llm_semantic did not forward "
        "tenant_id to the chokepoint."
    )

    # Cap-exceeded — mocked score=60, no raise.
    async def fake_call_cap(**kwargs):
        return _make_cap_exceeded_result()

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call_cap,
    )
    out = asyncio.run(seo_agentic._llm_semantic(
        "pool cleaning", "Weekly pool cleaning in Peoria AZ.",
        tenant_id="tenant-agentic-99",
    ))
    assert out.get("mocked") is True
    assert out.get("score") == 60, (
        "Cap-exceeded posture regression: seo_agentic._llm_semantic "
        "should return score=60 (mocked stub) so the composite "
        "content-score endpoint still succeeds."
    )


# ── 5. service_reports._llm_rephrase_reasons — best-effort helper ──
def test_service_reports_rephrase_threads_tenant_id(monkeypatch):
    """The dosing rephraser is best-effort — the underlying
    deterministic recs are ALREADY computed and returned; the LLM only
    prettifies the ``reason`` field. Cap-exceeded returns the recs
    untouched + an ``ai_spend_cap_exceeded`` error string."""
    from routers import service_reports

    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")
    import config
    monkeypatch.setattr(config, "EMERGENT_LLM_KEY", "test-key")

    captured: Dict[str, Any] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return _make_ok_result(
            '[{"chemical": "chlorine", "quantity": 2, "unit": "cups",'
            ' "reason": "Raise free chlorine to 3ppm target"}]'
        )

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call,
    )

    recs_in = [{"chemical": "chlorine", "quantity": 2, "unit": "cups",
                 "reason": "Bring FC up."}]
    recs_out, tokens, err = asyncio.run(service_reports._llm_rephrase_reasons(
        recs_in, tenant_id="tenant-svc-11",
    ))
    assert err is None
    assert recs_out[0]["reason"].startswith("Raise free chlorine")
    assert captured.get("tenant_id") == "tenant-svc-11", (
        "BYO regression: service_reports._llm_rephrase_reasons did "
        "not forward tenant_id to the chokepoint. Per-tenant BYO "
        "keys / cap enforcement on the dosing rephraser will not fire."
    )

    # Cap-exceeded — recs pass through unchanged + error string.
    async def fake_call_cap(**kwargs):
        return _make_cap_exceeded_result()

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", fake_call_cap,
    )
    recs_out, tokens, err = asyncio.run(service_reports._llm_rephrase_reasons(
        recs_in, tenant_id="tenant-svc-11",
    ))
    assert err == "ai_spend_cap_exceeded"
    assert recs_out == recs_in, (
        "Cap-exceeded posture regression: rephraser should pass "
        "recs through untouched when the AI cap is exceeded (the "
        "underlying deterministic recs are still valid)."
    )
    assert tokens == 0


# ── AST guard: every follow-up callsite explicitly threads tenant_id ──
_BYO_FOLLOWUP_CALLERS = [
    ("routers/business_os.py",
       ["_ai_generate(LANA_SYSTEM"]),
    ("routers/marketing_studio.py",
       ["_ai_variant(ch, goal, brand, session=session, tenant_id=tenant",
        "_ai_email(f\"{goal} — variant {i+1}\", goal, brand, session=session,",
        "_ai_sms(f\"{goal} — variant {i+1}\", goal, brand, session=session,",
        "_ai_variant(\"gbp\", goal, brand, session=session, tenant_id=tenant",
        "_ai_variant(ch, body.topic, brand, session=session,"]),
    ("routers/seo_phase17c.py",
       ["_claude_patch(code, page_url, current_value, page_context,"]),
    ("routers/seo_agentic.py",
       ["_llm_semantic(body.target_keyword,"]),
    ("routers/service_reports.py",
       ["_llm_rephrase_reasons(recs, tenant_id="]),
]


@pytest.mark.parametrize("rel,fragments", _BYO_FOLLOWUP_CALLERS)
def test_byo_followup_callers_thread_tenant_id_in_source(rel, fragments):
    """Compile-time AST guard: the five follow-up callsites MUST
    reference the migrated helper WITH a ``tenant_id=`` (or
    ``tenant["id"]``) argument at the callsite. Removing the
    ``tenant_id=`` on any of these callsites would silently regress
    BYO opt-in without breaking any runtime test."""
    src = _read(rel)
    for frag in fragments:
        assert frag in src, (
            f"BYO regression in {rel}: expected callsite fragment "
            f"{frag!r} not found. The follow-up migration threaded "
            f"tenant_id explicitly at each callsite — a callsite "
            f"that no longer passes it silently reverts BYO opt-in."
        )
    # Also assert every callsite fragment is followed within 200 chars
    # by ``tenant`` (either ``tenant_id=`` or ``tenant["id"]``).
    for frag in fragments:
        idx = src.find(frag)
        window = src[idx:idx + 500]
        assert (
            "tenant_id=tenant" in window
            or "tenant_id=admin" in window
            or "tenant_id=user" in window
            or "tenant[\"id\"]" in window
        ), (
            f"BYO regression in {rel} near fragment {frag!r}: "
            f"callsite does not thread a real tenant identifier "
            f"within 500 chars.  Threading ``tenant_id=None`` is "
            f"explicitly banned by the follow-up."
        )
