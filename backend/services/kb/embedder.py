"""KB IH-A · Feb-2026 — embedder shim.

Emergent's ``emergentintegrations.llm.chat.LlmChat`` provides
chat completions but does NOT expose an embeddings surface
(verified via ``dir(LlmChat)`` — no ``embed`` or
``embeddings`` method).  Per user brief: "add the tiniest
wrapper — do not pull a new heavy dep. If truly unavailable,
raise a clear error, do NOT fall back to random vectors."

This module provides a minimal ``embed_texts()`` function that
uses the ``openai`` SDK (already lazily imported by
``services/llm_provider.py``, so no new dep) with the Emergent
LLM key.  When the runtime call fails, ``EmbeddingUnavailable``
is raised — the KB indexer catches it and marks
``index_status='error'`` on the KB doc.

Tests inject a fake embedder via the ``embedder`` kwarg on
``kb_indexer.index_document`` and NEVER hit this module.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Protocol

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# Model + config
# ═════════════════════════════════════════════════════════════
EMBEDDING_MODEL = "text-embedding-3-small"   # 1536 dims
EMBEDDING_DIM = 1536
_TIMEOUT_SECONDS = 30


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding call cannot be completed.

    Never falls back to random vectors — per user brief §
    "no random-vector fallbacks".  Callers set
    ``index_status='error'`` with the exception's message.
    """


class Embedder(Protocol):
    """Injectable embedder protocol.  Tests pass a fake that
    returns deterministic vectors from a hash of text so the
    indexer's contract can be verified without hitting OpenAI.
    """

    async def __call__(self, texts: List[str]) -> List[List[float]]:
        ...


# ═════════════════════════════════════════════════════════════
# Real embedder — Emergent key + OpenAI SDK path
# ═════════════════════════════════════════════════════════════
async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch of strings using ``text-embedding-3-small``.

    Attempts the OpenAI SDK with the Emergent LLM key first
    (the Emergent proxy routes OpenAI-compatible calls
    through their endpoint).  Falls back to a real OpenAI key
    when set as an env var.

    Raises ``EmbeddingUnavailable`` on any failure with a
    legible message — the indexer captures this and marks
    ``index_status='error'`` on the KB doc.
    """
    if not texts:
        return []

    key = os.environ.get("EMERGENT_LLM_KEY", "").strip()
    fallback_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and not fallback_key:
        raise EmbeddingUnavailable(
            "no_llm_key: neither EMERGENT_LLM_KEY nor OPENAI_API_KEY set"
        )

    try:
        from openai import OpenAI  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        raise EmbeddingUnavailable(
            f"openai_import_failed: {exc}"
        ) from exc

    last_err: Exception | None = None
    for candidate in (key, fallback_key):
        if not candidate:
            continue
        try:
            client = OpenAI(api_key=candidate, timeout=_TIMEOUT_SECONDS)
            resp = await asyncio.to_thread(
                client.embeddings.create,
                model=EMBEDDING_MODEL,
                input=texts,
            )
            vectors = [item.embedding for item in resp.data]
            if any(len(v) != EMBEDDING_DIM for v in vectors):
                raise EmbeddingUnavailable(
                    f"unexpected_dim: expected {EMBEDDING_DIM}"
                )
            return vectors
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[kb.embedder] embedding attempt failed key=%s… err=%s",
                (candidate or "")[:12], exc,
            )
            last_err = exc
            continue

    raise EmbeddingUnavailable(
        f"embedding_call_failed: {last_err}"
    )
