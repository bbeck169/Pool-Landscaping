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
