"""Phase KB2 · Feb-2026 — Copilot shares the RAG retriever.

Regression suite for the refactored ``_build_system_prompt`` in
``routers/ai_brain.py``.  The goal is to lock in that:

* ``query`` non-empty AND KB has matching rows → prompt contains
  ONLY the retriever's top-K snippets.  We verify by seeding the
  KB with 2 rows, calling ``_build_system_prompt`` with a query
  that matches one row, and asserting the OTHER row's ``content_md``
  is absent from the returned prompt.
* ``query`` non-empty but retrieval returns [] → prompt has the
  "no relevant knowledge found" preamble and does NOT contain any
  KB body substring.
* ``query`` None (legacy caller) → the full-concat fallback still
  works but is capped at the 16 000-char hard cap.
* Token-budget reality check — with a 20-row KB the query-scoped
  path fits in <5 000 chars while the fallback (uncapped)
  would have been >30 000 chars.  This locks in the KB1-audit
  savings.

The tests use the real retriever + a Motor-shaped in-memory stub
so we aren't secretly testing a mock's behaviour.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch


class _AsyncListCursor:
    def __init__(self, rows): self._rows = list(rows)
    def sort(self, *_a, **_kw): return self
    async def to_list(self, n=None):
        return list(self._rows) if n is None else list(self._rows)[:n]
    def __aiter__(self): self._i = 0; return self
    async def __anext__(self):
        if self._i >= len(self._rows): raise StopAsyncIteration
        r = self._rows[self._i]; self._i += 1; return r


class _Coll:
    def __init__(self, rows=None): self.rows = list(rows or [])
    def find(self, q=None, p=None):
        matched = [r for r in self.rows if _match(r, q or {})]
        return _AsyncListCursor(matched)


def _match(row, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(row, s) for s in v): return False
            continue
        rv = row.get(k)
        if isinstance(v, dict):
            if "$ne" in v and rv == v["$ne"]: return False
            if "$exists" in v and (k in row) != v["$exists"]: return False
        elif rv != v:
            return False
    return True


class _DB:
    def __init__(self, rows): self.ai_knowledge_base = _Coll(rows)


def _run(coro): return asyncio.run(coro)


def _seed_kb() -> List[Dict[str, Any]]:
    return [
        {"id": "kb-brand", "tenant_id": "t1",
         "kind": "company_profile", "title": "Brand voice",
         "content_md": "We speak in a professional, warm tone. Never use slang.",
         "tags": ["brand", "voice"],
         "is_active": True, "updated_at": "2026-02-01T10:00:00Z"},
        {"id": "kb-warranty", "tenant_id": "t1",
         "kind": "policy", "title": "Warranty terms",
         "content_md": "The pool warranty covers 5 years on the shell but 2 years on the pump.",
         "tags": ["warranty"],
         "is_active": True, "updated_at": "2026-02-01T10:00:00Z"},
    ]


def test_query_scoped_prompt_returns_only_matching_snippets():
    async def run():
        from routers import ai_brain
        stub_db = _DB(_seed_kb())
        with patch.object(ai_brain, "db", stub_db), \
             patch("services.ai_kb_retrieval.db", stub_db):
            prompt = await ai_brain._build_system_prompt(
                "t1", query="What is our brand voice tone?",
            )
        assert "Company knowledge" in prompt
        assert "Brand voice" in prompt, prompt
        # The unrelated warranty row's body must NOT be inlined.
        assert "5 years on the shell" not in prompt, (
            "retriever must NOT dump unrelated rows into the "
            "query-scoped Copilot prompt"
        )

    _run(run())


def test_no_matches_yields_no_kb_dump():
    async def run():
        from routers import ai_brain
        stub_db = _DB(_seed_kb())
        with patch.object(ai_brain, "db", stub_db), \
             patch("services.ai_kb_retrieval.db", stub_db):
            prompt = await ai_brain._build_system_prompt(
                "t1", query="What is the flight speed of a laden swallow?",
            )
        assert "No relevant knowledge base entries were found" in prompt
        # Neither row's body should be dumped.
        for kb in _seed_kb():
            assert kb["content_md"] not in prompt, (
                f"KB row {kb['id']} body leaked into the no-match prompt"
            )

    _run(run())


def test_legacy_no_query_path_still_works_and_is_capped():
    async def run():
        from routers import ai_brain
        # Force a big KB to make the cap meaningful.
        big_rows: List[Dict[str, Any]] = []
        for i in range(40):
            big_rows.append({
                "id": f"kb-{i}", "tenant_id": "t1",
                "kind": "custom", "title": f"Doc {i}",
                "content_md": "x" * 1000,   # 40 * 1000 = 40 000 chars > 16 000 cap
                "tags": [], "is_active": True,
                "updated_at": "2026-02-01T10:00:00Z",
            })
        stub_db = _DB(big_rows)
        with patch.object(ai_brain, "db", stub_db):
            prompt = await ai_brain._build_system_prompt(
                "t1", query=None,
            )
        # Legacy full-concat header is present.
        assert "Company knowledge" in prompt
        # Cap enforced — final prompt must be under the hard cap +
        # a small header allowance (say +200 chars).
        assert len(prompt) < 16_000 + 200, (
            f"legacy fallback exceeded its cap: {len(prompt)} chars"
        )
        # Empty-string query behaves the same as None (falsy).
        with patch.object(ai_brain, "db", stub_db):
            prompt2 = await ai_brain._build_system_prompt(
                "t1", query="   ",
            )
        assert prompt2 == prompt

    _run(run())


def test_query_scoped_prompt_dramatically_smaller_than_fallback():
    """The whole point of KB2 — 20-row KB, query prompt is <<< the
    legacy concat."""
    async def run():
        from routers import ai_brain
        rows: List[Dict[str, Any]] = []
        for i in range(20):
            rows.append({
                "id": f"kb-{i}", "tenant_id": "t1",
                "kind": "custom", "title": f"Doc {i}",
                # 1500 chars per row → 30 000 chars concatenated,
                # comfortably above the fallback's 16 000-char cap
                # AND representative of the KB1 audit's ~14k-token
                # estimate on the aquaterra tenant.
                "content_md": ("body " * 300) + f" · marker-{i}",
                "tags": [], "is_active": True,
                "updated_at": "2026-02-01T10:00:00Z",
            })
        # Guarantee at least one match for a query token so the
        # retriever produces snippets.
        rows[3]["content_md"] += " · SPECIALTOKEN"
        stub_db = _DB(rows)
        with patch.object(ai_brain, "db", stub_db), \
             patch("services.ai_kb_retrieval.db", stub_db):
            rag_prompt = await ai_brain._build_system_prompt(
                "t1", query="specialtoken",
            )
            legacy_prompt = await ai_brain._build_system_prompt(
                "t1", query=None,
            )
        # RAG path returns only the top-K snippets — expect < 5 000
        # chars regardless of KB size.
        assert len(rag_prompt) < 5_000, (
            f"RAG prompt unexpectedly large: {len(rag_prompt)} chars"
        )
        # Legacy fallback is capped but should be MUCH larger than
        # the RAG path (proves the savings are real).
        assert len(legacy_prompt) > len(rag_prompt) * 2, (
            f"legacy={len(legacy_prompt)} vs rag={len(rag_prompt)} — "
            "cap must still allow a meaningfully-larger fallback"
        )

    _run(run())
