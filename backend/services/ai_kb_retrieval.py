"""Phase Feb-2026 · AI Employees chat — ai_knowledge_base RAG retrieval.

Pure retrieval helper.  Given a tenant id + a user query, returns the
top-K relevant knowledge base documents so the AI Employees chat
router can prepend them to the system prompt.

Path chosen: **text search** (Path B in the phase spec).

Reason: an audit of the codebase found NO embedding fields on any
``ai_knowledge_base`` document, no ``embed`` / ``openai.embeddings``
call site in either ``services/`` or ``routers/``, and the only
current retrieval-adjacent surface (``ai_brain._build_system_prompt``)
concatenates every doc verbatim. Embedding ingestion is a separate
phase; text search is the cheapest useful starting point.

Ranking model
-------------
Case-insensitive word-token overlap.  Each token in the incoming query
that appears in a doc's title contributes ``TITLE_WEIGHT`` to the
score, each token that appears in ``content_md`` contributes
``BODY_WEIGHT``, and each token that appears in the ``tags`` array
contributes ``TAG_WEIGHT``.  Ties are broken by ``kind`` order
(``company_profile`` > ``policy`` > ``faq`` > ``custom``) then
``updated_at`` DESC so a recent policy always outranks an older FAQ.

Tenant isolation
----------------
Every query is filtered by ``tenant_id``; cross-tenant leakage is
impossible.  Soft-deleted rows (``is_deleted=True``) and inactive rows
(``is_active=False``) are excluded.

Returned shape
--------------
::

    [
      {"doc_id": <str>, "title": <str>, "snippet": <str>,
       "kind": <str>, "score": <float>},
      ...
    ]
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from config import db, logger

# ═════════════ tuning knobs ══════════════════════════════════════════
TOP_K = 5
SNIPPET_LEN = 200
TITLE_WEIGHT = 3.0
BODY_WEIGHT = 1.0
TAG_WEIGHT = 2.0
STOP_WORDS = frozenset({
    "a", "an", "the", "of", "for", "and", "or", "to", "in", "on",
    "is", "it", "we", "you", "i", "me", "my", "our", "your",
    "how", "what", "when", "where", "why", "who", "which",
    "does", "do", "did", "was", "are", "be", "been", "being",
    "with", "without", "at", "by", "from", "this", "that",
    "these", "those", "there", "their", "them", "they",
    "can", "could", "should", "would", "will", "shall",
    "have", "has", "had", "not", "no", "yes",
})
_KIND_ORDER = {"company_profile": 0, "policy": 1, "faq": 2, "custom": 3}
_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


def _tokenize(text: str) -> List[str]:
    """Return the deduplicated non-stopword tokens from a query."""
    if not text:
        return []
    seen: List[str] = []
    seen_set: set = set()
    for tok in _TOKEN_RE.findall(str(text).lower()):
        if len(tok) < 2 or tok in STOP_WORDS:
            continue
        if tok in seen_set:
            continue
        seen_set.add(tok)
        seen.append(tok)
    return seen


def _snippet_for(content: str, tokens: List[str], length: int = SNIPPET_LEN) -> str:
    """Return the first sub-window of ``content`` containing any of
    the query tokens; falls back to the first ``length`` chars."""
    if not content:
        return ""
    content = str(content)
    lower = content.lower()
    for tok in tokens:
        idx = lower.find(tok)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(content), start + length)
            frag = content[start:end].strip()
            if start > 0:
                frag = "…" + frag
            if end < len(content):
                frag = frag + "…"
            return frag
    return content[:length].strip() + ("…" if len(content) > length else "")


def _score(row: Dict[str, Any], tokens: List[str]) -> float:
    """Compute the ranking score for a single row + query tokens."""
    if not tokens:
        return 0.0
    title = str(row.get("title") or "").lower()
    body = str(row.get("content_md") or "").lower()
    tags = [str(t).lower() for t in (row.get("tags") or [])]
    score = 0.0
    for t in tokens:
        if t in title:
            score += TITLE_WEIGHT
        if t in body:
            score += BODY_WEIGHT
        if t in tags:
            score += TAG_WEIGHT
    return score


async def retrieve_kb_sources(
    tenant_id: str,
    query: str,
    top_k: int = TOP_K,
    db_handle: Any = None,
) -> List[Dict[str, Any]]:
    """Return the top-K relevant KB docs for a tenant/query pair.

    Empty list when the query has no usable tokens, when the tenant
    has no active KB docs, or when nothing matches.

    ``db_handle`` optionally overrides the module-level motor client.
    Tests inject a per-loop motor client here to avoid the
    ``event loop is closed`` trap that comes from sharing the app's
    process-wide client across pytest-anyio loops.

    Emits a debug log per call with retrieval timing + shape so future
    observability dashboards can chart RAG hit rate without new
    instrumentation.
    """
    tokens = _tokenize(query)
    if not tokens:
        logger.debug("[kb-rag] no tokens for tenant=%s", tenant_id)
        return []

    t0 = time.monotonic()
    coll = (db_handle if db_handle is not None else db).ai_knowledge_base
    q_filter: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "is_active": True,
        "$or": [
            {"is_deleted": {"$ne": True}},
            {"is_deleted": {"$exists": False}},
        ],
    }
    cur = coll.find(
        q_filter,
        {"_id": 0, "id": 1, "title": 1, "content_md": 1,
         "tags": 1, "kind": 1, "updated_at": 1},
    )
    rows: List[Dict[str, Any]] = await cur.to_list(1000)
    if not rows:
        logger.debug("[kb-rag] tenant=%s empty knowledge base", tenant_id)
        return []

    scored: List[Dict[str, Any]] = []
    for r in rows:
        s = _score(r, tokens)
        if s > 0:
            scored.append({"_row": r, "_score": s})
    if not scored:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.debug(
            "[kb-rag] tenant=%s tokens=%d no_matches retrieval_ms=%d",
            tenant_id, len(tokens), elapsed_ms,
        )
        return []

    scored.sort(key=lambda x: (
        -x["_score"],
        _KIND_ORDER.get(x["_row"].get("kind") or "custom", 99),
        # updated_at DESC — string ISO sorts lexicographically.
        -_iso_rank(x["_row"].get("updated_at") or ""),
    ))

    top = scored[: max(1, int(top_k))]
    out: List[Dict[str, Any]] = []
    for entry in top:
        r = entry["_row"]
        out.append({
            "doc_id": r.get("id"),
            "title": r.get("title") or "",
            "kind": r.get("kind") or "custom",
            "snippet": _snippet_for(r.get("content_md") or "", tokens),
            "score": round(float(entry["_score"]), 3),
        })
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "[kb-rag] tenant=%s tokens=%d matches=%d returned=%d "
        "retrieval_ms=%d path=text",
        tenant_id, len(tokens), len(scored), len(out), elapsed_ms,
    )
    return out


def _iso_rank(s: str) -> float:
    """Numeric rank for a lexicographic ISO string — larger means more
    recent. Uses a length-tolerant hash so bad values sort last."""
    if not s:
        return 0.0
    try:
        # Strip non-digit chars and treat the leading YYYYMMDDhhmmss as a number.
        digits = re.sub(r"\D", "", s)[:14]
        return float(digits) if digits else 0.0
    except Exception:                                                    # noqa: BLE001
        return 0.0


def format_kb_context(sources: List[Dict[str, Any]]) -> str:
    """Turn the retrieval output into the Markdown block the LLM sees
    (prepended to the existing system prompt in the chat router)."""
    if not sources:
        return ""
    lines = ["# Reference material from your company's knowledge base",
             "(Cite the doc titles verbatim when quoting.)"]
    for i, s in enumerate(sources, 1):
        lines.append(f"\n## [Doc {i}] {s.get('title') or '(untitled)'}")
        if s.get("kind"):
            lines.append(f"_Kind: {s['kind']}_")
        snippet = s.get("snippet") or ""
        if snippet:
            lines.append(snippet)
        lines.append("---")
    lines.append(
        "\nAnswer the user's question using this material when applicable. "
        "If the material does not answer the question, say so plainly."
    )
    return "\n".join(lines)
