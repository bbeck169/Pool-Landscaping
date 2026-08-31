"""Phase F3 · Feb-2026 — Soshie LLM Moderation Gate.

Runs BEFORE any autopilot publish so drafts get a conservative,
family-business-tone check against profanity, hate speech, adult
content, medical/legal advice, competitor bashing, misleading
claims, PII, and out-of-pricebook pricing.

Model
-----
Emergent Universal LLM Key → Claude Sonnet (``claude-sonnet-4-5``)
via the existing :mod:`services.llm_provider.call_llm_with_fallback`
pipeline. If the LLM call fails for any reason (timeout, quota,
import, empty JSON) we NEVER auto-approve — the caller receives
``decision="flag"`` with a reason and the post gets queued for
human review.

Idempotency + cost audit
------------------------
Every moderation call is written to ``soshie_moderation_results``
keyed on ``sha256(text + sorted(media_urls))``. A second call with
the same content replays the cached decision without another LLM
round-trip. Cost estimates use a conservative ``$0.003 / 1K input
tokens + $0.015 / 1K output tokens`` Claude Sonnet rate.

Kill switch
-----------
``SOSHIE_MODERATION_ENABLED=false`` in the env → :func:`moderate_post`
short-circuits to ``decision="approve"`` (with reason
``moderation_disabled``) so operators can drop the gate in an
emergency without a redeploy.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


# ─── Constants ────────────────────────────────────────────────────────
COLLECTION = "soshie_moderation_results"
MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-5"
# Conservative Claude-Sonnet public rate (as of Feb 2026). Kept as a
# module constant so ops can grep for the number when accounting the
# monthly LLM burn.
_INPUT_COST_PER_1K = 0.003
_OUTPUT_COST_PER_1K = 0.015
CREDIT_FLOOR = 5  # mirror autopilot_scheduler.CREDIT_FLOOR


SYSTEM_PROMPT = (
    "You are a conservative content-safety reviewer for social posts "
    "authored by a family-run pool + landscaping services business. "
    "Return JSON ONLY (no prose, no markdown) with this exact shape: "
    "{\"decision\": \"approve\" | \"flag\" | \"block\", "
    "\"reasons\": [<short strings>], "
    "\"risk_level\": \"low\" | \"medium\" | \"high\"}.\n\n"
    "Decision rubric:\n"
    "- BLOCK for: profanity, hate speech, adult / NSFW content, medical "
    "or legal advice, competitor bashing, misleading claims (e.g. "
    "'guaranteed', 'cure', 'risk-free'), PII (customer names, "
    "addresses, phone numbers, emails), pricing outside the pricebook.\n"
    "- FLAG for: aggressive or sarcastic tone, unusual claims, "
    "low-confidence assertions, mentions of dangerous chemistry, "
    "anything a family business owner would want to eyeball before it "
    "goes live.\n"
    "- APPROVE for: clean, on-brand pool / landscape / family-business "
    "voice with no risk signals.\n\n"
    "Return AT MOST 4 reasons, each < 60 characters. When in doubt, "
    "prefer FLAG over APPROVE — a human will review flagged posts."
)


# ─── Helpers ──────────────────────────────────────────────────────────
def _content_hash(text: str, media_urls: Optional[List[str]]) -> str:
    m = hashlib.sha256()
    m.update((text or "").encode("utf-8", "replace"))
    for url in sorted(media_urls or []):
        m.update(b"|")
        m.update((url or "").encode("utf-8", "replace"))
    return m.hexdigest()


def _estimate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    ci = (tokens_in / 1000.0) * _INPUT_COST_PER_1K
    co = (tokens_out / 1000.0) * _OUTPUT_COST_PER_1K
    return round(ci + co, 6)


def _kill_switch_disabled() -> bool:
    v = (os.environ.get("SOSHIE_MODERATION_ENABLED") or "").strip().lower()
    return v in ("false", "0", "off", "no")


async def _tenant_credit_balance(tenant_id: str) -> int:
    doc = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "ai_credits_balance": 1},
    ) or {}
    try:
        return int(doc.get("ai_credits_balance") or 0)
    except (TypeError, ValueError):
        return 0


def _sanitize_reasons(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for r in raw[:4]:
        if isinstance(r, str) and r.strip():
            out.append(r.strip()[:120])
    return out


def _sanitize_decision(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if v in ("approve", "flag", "block"):
        return v
    return "flag"


def _sanitize_risk(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if v in ("low", "medium", "high"):
        return v
    return "medium"


async def _store_result(*, tenant_id: str, post_id: str,
                          content_hash: str, decision: str,
                          reasons: List[str], risk_level: str,
                          tokens_in: int, tokens_out: int,
                          cost_estimate_usd: float,
                          model: str,
                          from_cache: bool = False,
                          error: Optional[str] = None) -> Dict[str, Any]:
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "post_id": post_id,
        "hash": content_hash,
        "decision": decision,
        "reasons": reasons,
        "risk_level": risk_level,
        "model": model,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "cost_estimate_usd": float(cost_estimate_usd or 0),
        "from_cache": bool(from_cache),
        "error": error,
        "created_at": now_iso(),
    }
    try:
        await db[COLLECTION].insert_one(doc)
    except Exception as e:  # noqa: BLE001
        logger.warning("[soshie.moderation] result insert failed: %s", e)
    return doc


async def _find_cached(tenant_id: str,
                          content_hash: str) -> Optional[Dict[str, Any]]:
    # A prior *decisive* moderation for the same content (any post_id)
    # in this tenant. We only replay decisions that came from a real
    # LLM call — never a failure-flag; those must retry.
    row = await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "hash": content_hash,
         "error": None},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return row


# ─── Public entrypoint ────────────────────────────────────────────────
async def moderate_post(
    *, post_id: str, tenant_id: str,
    text: str, media_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return ``{status, reasons, model, cost_estimate, from_cache}``.

    ``status`` is one of ``approve`` / ``flag`` / ``block``.
    """
    media_urls = list(media_urls or [])
    content_hash = _content_hash(text, media_urls)

    # ─── Kill switch — S3 emergency escape hatch. ─────────────────────
    if _kill_switch_disabled():
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision="approve",
            reasons=["moderation_disabled"],
            risk_level="low",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model="kill-switch",
        )

    # ─── Cache hit — replay prior decision. ───────────────────────────
    cached = await _find_cached(tenant_id, content_hash)
    if cached and not cached.get("error"):
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision=cached["decision"],
            reasons=list(cached.get("reasons") or []),
            risk_level=cached.get("risk_level") or "low",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=cached.get("model") or MODEL_NAME,
            from_cache=True,
        )

    # ─── Quota gate — over the floor, don't burn LLM calls; flag. ────
    credits = await _tenant_credit_balance(tenant_id)
    if credits < CREDIT_FLOOR:
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision="flag",
            reasons=["quota_exceeded"],
            risk_level="medium",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=MODEL_NAME,
            error="quota_exceeded",
        )

    # ─── Live LLM call. ───────────────────────────────────────────────
    user_text = json.dumps({
        "post_text": text or "",
        "media_urls": media_urls,
    }, ensure_ascii=False)
    try:
        from services.llm_provider import call_llm_with_fallback
        res = await call_llm_with_fallback(
            system_prompt=SYSTEM_PROMPT,
            user_text=user_text,
            provider=MODEL_PROVIDER,
            model=MODEL_NAME,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[soshie.moderation] LLM crash: %s", e)
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision="flag",
            reasons=["moderation_service_unavailable"],
            risk_level="medium",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=MODEL_NAME,
            error=str(e),
        )

    if res.get("error"):
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision="flag",
            reasons=["moderation_service_unavailable"],
            risk_level="medium",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=MODEL_NAME,
            error=str(res.get("error")),
        )
    raw = res.get("raw") or {}
    decision = _sanitize_decision(raw.get("decision"))
    reasons = _sanitize_reasons(raw.get("reasons"))
    risk_level = _sanitize_risk(raw.get("risk_level"))
    # Rough token estimate: 1 token ≈ 4 chars. Good enough for a
    # cost-audit surface — accurate accounting is out of scope for
    # F3 (would require the SDK to surface real usage, which the
    # Emergent wrapper does not yet).
    tokens_in = max(1, (len(SYSTEM_PROMPT) + len(user_text)) // 4)
    tokens_out = max(1, len(json.dumps(raw)) // 4)
    cost = _estimate_cost_usd(tokens_in, tokens_out)
    return await _store_result(
        tenant_id=tenant_id, post_id=post_id,
        content_hash=content_hash,
        decision=decision,
        reasons=reasons,
        risk_level=risk_level,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_estimate_usd=cost,
        model=MODEL_NAME,
    )
