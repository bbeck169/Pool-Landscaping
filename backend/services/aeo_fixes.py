"""Phase 5b · Feb-2026 — LLM-generated AEO fix suggestions.

Reads the last AEO signals off a completed SEO scan and turns each
low sub-signal into an actionable suggestion via the Emergent LLM
key. schema + llms_txt fall through to the Phase 5a generators so we
never re-implement JSON-LD or llmstxt.org emission.

Phase I1.7.e · chunk 2.c · Feb-2026 — LLM calls now route through
``services.llm_provider.call_llm_with_fallback`` with the caller's
``tenant_id`` threaded through, so per-tenant BYO AI provider
routing + monthly cap enforcement fire before the platform key is
consulted. Cap-exceeded is a HARD BLOCK: the fix generator surfaces
``{"cap_exceeded": True}`` in its return dict so the transactional
HTTP router raises 429 via
:func:`services.ai.cap_http.raise_if_ai_cap_exceeded`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, Dict, List, Optional

from config import db, logger
from services.aeo_generators import generate_jsonld, generate_llms_txt

_LOW_THRESHOLD = 70
_ALL_SIGNALS = ["schema", "faq", "passages", "entity_clarity", "llms_txt"]

# Sentinel marker string embedded in the returned suggestion text
# when the LLM call is short-circuited by a tenant BYO cap-exceeded.
# The public :func:`generate_fixes` inspects for this marker and
# lifts ``cap_exceeded`` to the top-level return dict so the router
# can raise HTTP 429.
_CAP_MARKER = "__AI_CAP_EXCEEDED__"


def _make_llm_call(tenant_id: Optional[str]) -> Callable[[str], Awaitable[str]]:
    """Build a ``prompt -> text`` LLM caller bound to ``tenant_id``.

    Threads the tenant's BYO provider (if any) into every LLM call
    made during fix generation. When the tenant's monthly BYO cap
    is exceeded the returned callable emits :data:`_CAP_MARKER`
    verbatim; :func:`generate_fixes` translates that into a
    top-level ``cap_exceeded=True`` return value.
    """
    async def _call(prompt: str) -> str:
        from services.llm_provider import call_llm_with_fallback
        r = await call_llm_with_fallback(
            system_prompt=("You are an AEO (Answer Engine Optimization) "
                            "consultant. Return short, actionable Markdown "
                            "recommendations tailored to a local-services "
                            "business. Never invent facts about the business."),
            user_text=prompt, provider="anthropic",
            model="claude-sonnet-4-5",
            tenant_id=tenant_id,
        )
        if r.get("cap_exceeded"):
            return _CAP_MARKER
        if r.get("error"):
            return f"_LLM error: {r['error']}_"
        raw = r.get("raw") or r
        if isinstance(raw, dict):
            return (raw.get("answer") or raw.get("text") or str(raw))[:4000]
        return str(raw)[:4000]
    return _call


async def _default_llm_call(prompt: str) -> str:
    """Legacy platform-only entrypoint — kept for backwards compat
    with tests that override this symbol. New callers should thread
    ``tenant_id`` via :func:`generate_fixes`."""
    return await _make_llm_call(None)(prompt)


def _priority_from_score(score: int) -> str:
    if score < 30:
        return "high"
    if score < 55:
        return "med"
    return "low"


def _find_long_paragraphs(html_bytes: bytes, top_n: int = 3) -> List[str]:
    from bs4 import BeautifulSoup
    if not html_bytes:
        return []
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="replace"),
                          "html.parser")
    for j in soup.find_all(["script", "style", "noscript"]):
        j.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p]
    paras.sort(key=lambda t: len(t.split()), reverse=True)
    return paras[:top_n]


async def generate_fixes(scan_id: str, tenant: Dict[str, Any],
                            requested_signals: Optional[List[str]] = None,
                            llm_call: Optional[Callable[[str], Awaitable[str]]] = None,
                            tenant_id: Optional[str] = None,
                            ) -> Dict[str, Any]:
    """Load the scan, build LLM prompts per low sub-signal, return
    ``{fixes: [...]}`` and persist to ``aeo_fixes``.

    Phase I1.7.e · chunk 2.c · Feb-2026 — ``tenant_id`` is threaded
    into every underlying ``call_llm_with_fallback`` invocation for
    tenant-BYO routing + cap enforcement. When ``tenant_id`` is
    omitted it defaults to ``tenant.get('id') or tenant.get('tenant_id')``.
    On BYO cap-exceeded the function short-circuits and returns
    ``{"fixes": [...partial...], "cap_exceeded": True, "error":
    "ai_spend_cap_exceeded"}`` so the router can raise HTTP 429."""
    # Resolve effective tenant_id for BYO routing.
    effective_tid = tenant_id or tenant.get("id") or tenant.get("tenant_id")
    if llm_call is None:
        llm_call = _make_llm_call(effective_tid)

    scan = await db.seo_scans.find_one({"id": scan_id},
                                          {"_id": 0}) or {}
    if not scan:
        return {"fixes": [], "error": "scan_not_found"}
    aeo = ((scan.get("results") or {}).get("aeo_signals") or {}) or {}
    if not aeo:
        return {"fixes": [], "error": "no_aeo_signals"}

    # Which sub-signals to work on.
    if requested_signals:
        signals = [s for s in requested_signals if s in _ALL_SIGNALS]
    else:
        signals = [s for s in _ALL_SIGNALS
                   if (aeo.get(s) or {}).get("score", 0) < _LOW_THRESHOLD]

    tenant_name = tenant.get("name") or tenant.get("business_name") or "Your business"
    city = ((tenant.get("address") or {}).get("city")
             if isinstance(tenant.get("address"), dict)
             else tenant.get("city")) or ""
    service_types = ", ".join(tenant.get("service_types") or ["pool", "landscaping"])
    fixes: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for sig in signals:
        sub = aeo.get(sig) or {}
        priority = _priority_from_score(int(sub.get("score") or 0))
        content_extra: Dict[str, Any] = {}

        if sig == "schema":
            # Route to Phase 5a generator for LocalBusiness + FAQPage.
            gen = generate_jsonld(
                types=["LocalBusiness", "FAQPage"],
                business_profile={
                    "name": tenant_name,
                    "url": tenant.get("url") or "",
                    "phone": tenant.get("phone") or "",
                    "address": tenant.get("address") or {},
                    "service_areas": tenant.get("service_areas") or [],
                },
                faqs=(tenant.get("faqs") or [])[:5],
            )
            content_extra["generated_content"] = gen["combined_script"]
            suggestion = (
                f"## Add JSON-LD schema\n\n"
                f"Missing recommended types: **"
                f"{', '.join(sub.get('types_missing_recommended') or ['LocalBusiness', 'FAQPage'])}**.\n\n"
                f"Copy the block below into your `<head>` on the home page. "
                f"It follows the schema.org spec and passes Google's Rich "
                f"Results test.\n"
            )
        elif sig == "llms_txt":
            g = generate_llms_txt(tenant, style="concise",
                                     include_faqs=True)
            content_extra["generated_content"] = g["content"]
            suggestion = (
                f"## Add an `/llms.txt` file\n\n"
                f"AI answer engines (ChatGPT, Perplexity, Gemini) look for "
                f"`/llms.txt` at your site root as a canonical summary of "
                f"your business. Save the content below at "
                f"`{tenant.get('url') or 'https://your-site.com'}/llms.txt`."
            )
        elif sig == "faq":
            prompt = (
                f"Generate 5 concise FAQ Q&A pairs for a local {service_types} "
                f"services business named \"{tenant_name}\" in {city}. "
                f"Each answer must be under 40 words, plain-spoken, and "
                f"directly useful to a homeowner searching AI answer "
                f"engines. Return Markdown with `### Q` headings."
            )
            suggestion = await llm_call(prompt)
            if suggestion == _CAP_MARKER:
                # Cap-exceeded on the first LLM-driven signal — bail
                # early with whatever we've already assembled.
                return {"fixes": fixes,
                         "cap_exceeded": True,
                         "error": "ai_spend_cap_exceeded"}
        elif sig == "passages":
            html = (((scan.get("results") or {}).get("on_page") or {})
                     .get("raw_html_bytes") or b"")
            longs = _find_long_paragraphs(
                html if isinstance(html, bytes)
                else str(html).encode("utf-8", errors="replace"))
            if longs:
                joined = "\n\n".join(f"- {p[:400]}" for p in longs[:3])
                prompt = (
                    f"You are rewriting long, wandering website paragraphs "
                    f"for AI answer engines. Rewrite each of the three "
                    f"passages below into ≤60 words, active voice, direct "
                    f"answer first. Return Markdown with an H3 label "
                    f"'Rewritten passage N:' per item.\n\n{joined}"
                )
                suggestion = await llm_call(prompt)
                if suggestion == _CAP_MARKER:
                    return {"fixes": fixes,
                             "cap_exceeded": True,
                             "error": "ai_spend_cap_exceeded"}
            else:
                suggestion = (
                    "## Shorten your long paragraphs\n\n"
                    f"Your median paragraph is **{sub.get('median_words', 0)} "
                    f"words** with **{sub.get('over_90_words', 0)} paragraphs "
                    f"over 90 words**. AI answer engines prefer short, "
                    f"direct passages — aim for ≤ 60 words and put the "
                    f"answer first."
                )
        elif sig == "entity_clarity":
            same_as = tenant.get("same_as") or tenant.get("social_links") or []
            prompt = (
                f"Write a meta description (max 155 characters) and an H1 "
                f"tagline for a {service_types} business named "
                f"\"{tenant_name}\" in {city}. Then list 3 sameAs URLs "
                f"(Facebook, LinkedIn, Yelp) that reinforce the entity. "
                f"Return Markdown."
            )
            suggestion = await llm_call(prompt)
            if suggestion == _CAP_MARKER:
                return {"fixes": fixes,
                         "cap_exceeded": True,
                         "error": "ai_spend_cap_exceeded"}
            if same_as:
                suggestion += (
                    f"\n\n**Existing sameAs on file:**\n"
                    + "\n".join(f"- {u}" for u in same_as)
                )
        else:
            continue

        fix_doc = {
            "tenant_id": tenant.get("id") or tenant.get("tenant_id"),
            "scan_id": scan_id, "sub_signal": sig,
            "priority": priority,
            "suggestion_markdown": suggestion,
            "generated_content": content_extra.get("generated_content"),
            "generated_at": now_iso,
            "applied": False,
        }
        # Idempotency-ish: mark any prior pending fix for the same
        # (scan, sub_signal) as superseded.
        await db.aeo_fixes.update_many(
            {"tenant_id": fix_doc["tenant_id"], "scan_id": scan_id,
              "sub_signal": sig, "applied": False,
              "superseded": {"$in": [False, None]}},
            {"$set": {"superseded": True}},
        )
        r = await db.aeo_fixes.insert_one(fix_doc)
        fix_doc["_id"] = str(r.inserted_id)
        fixes.append({
            "sub_signal": sig, "priority": priority,
            "suggestion_markdown": suggestion,
            "generated_content": content_extra.get("generated_content"),
            "score": int(sub.get("score") or 0),
        })
    return {"fixes": fixes}
