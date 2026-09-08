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
MODEL_REGEX_P1 = "regex-p1"
CREDIT_FLOOR = 5  # mirror autopilot_scheduler.CREDIT_FLOOR


def _regex_prefilter_enabled() -> bool:
    """Phase H7 · Feb-2026 — env kill switch for the regex pre-
    filter stage. Defaults to ON; setting
    ``SOSHIE_REGEX_PREFILTER_ENABLED=false`` (or ``0``/``off``/
    ``no``) skips Stage 1 and goes straight to the LLM. Useful
    for A/B testing the combo pipeline vs. LLM-only or for
    troubleshooting a false-positive block."""
    v = (os.environ.get("SOSHIE_REGEX_PREFILTER_ENABLED") or "").strip().lower()
    if v in ("false", "0", "off", "no"):
        return False
    return True


_DECISION_SEVERITY = {"approve": 0, "flag": 1, "block": 2}


def _more_conservative(a: str, b: str) -> str:
    """Return the higher-severity of two decisions. Used by the
    H7 combo pipeline to fold regex + LLM verdicts into one
    final decision — block > flag > approve."""
    return a if _DECISION_SEVERITY.get(a, 0) >= _DECISION_SEVERITY.get(b, 0) else b


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
                          error: Optional[str] = None,
                          regex_short_circuit: bool = False,
                          regex_high_flags: Optional[List[Dict[str, str]]] = None,
                          regex_low_flags: Optional[List[Dict[str, str]]] = None,
                          ) -> Dict[str, Any]:
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
        # Phase H7 · Feb-2026 — regex combo audit fields. Every
        # row carries these so H6's monthly rollup can surface a
        # ``regex_short_circuits`` counter and the cost-savings
        # narrative stays defensible. ``regex_short_circuit=True``
        # means the LLM was NEVER called for this post.
        "regex_short_circuit": bool(regex_short_circuit),
        "regex_high_flags": regex_high_flags or [],
        "regex_low_flags": regex_low_flags or [],
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
    dont_say: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return ``{status, reasons, model, cost_estimate, from_cache}``.

    ``status`` is one of ``approve`` / ``flag`` / ``block``.

    Phase H7 · Feb-2026 — Pipeline order:
        1. Kill-switch (``SOSHIE_MODERATION_ENABLED=false``) → approve
        2. Regex pre-filter (Stage 1, $0):
            - ``high``-confidence hit → short-circuit BLOCK, LLM
              never invoked. ``regex_short_circuit=True`` written.
            - ``low``-confidence hit → keep the low-confidence
              flag payload; fall through to LLM; combine.
            - clean → fall through to LLM.
        3. Cache lookup (F3) — deterministic replay of a prior
           LLM verdict for identical content. Cached result IS
           NOT combined with regex-low flags (the cached row
           already carried its own snapshot).
        4. Credit-floor gate — if under CREDIT_FLOOR, flag with
           ``quota_exceeded``.
        5. Live LLM call, then fold regex-low flags via
           :func:`_more_conservative` so a regex-low ``flag`` +
           LLM ``approve`` still lands as ``flag``.
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

    # ─── Phase H7 · Stage 1: regex prefilter ($0 fast-path). ─────────
    regex_high: List[Dict[str, str]] = []
    regex_low: List[Dict[str, str]] = []
    if _regex_prefilter_enabled():
        from services.soshie.moderation import prefilter as _regex_prefilter
        pre, regex_high, regex_low = _regex_prefilter(
            text or "", dont_say=dont_say,
        )
        if pre == "block":
            # Definitive block — LLM is not consulted. Reasons
            # are compact stringified source|match pairs so the
            # audit surface stays readable.
            reasons = [
                f"{f.get('source', 'regex')}:{f.get('match', '')[:40]}"
                for f in regex_high[:4]
            ]
            return await _store_result(
                tenant_id=tenant_id, post_id=post_id,
                content_hash=content_hash,
                decision="block",
                reasons=reasons or ["regex_policy_block"],
                risk_level="high",
                tokens_in=0, tokens_out=0,
                cost_estimate_usd=0.0,
                model=MODEL_REGEX_P1,
                regex_short_circuit=True,
                regex_high_flags=regex_high,
                regex_low_flags=regex_low,
            )
        # ``pre`` is now either ``flag`` (regex-low hits) or
        # ``approve``. Either way we fall through to the cache
        # + LLM stages; the regex-low flags will be folded into
        # the final decision below.

    # ─── Cache hit — replay prior decision. ───────────────────────────
    cached = await _find_cached(tenant_id, content_hash)
    if cached and not cached.get("error"):
        # Fold in any regex-low flags — if the cached decision was
        # ``approve`` but we now have a regex-low hit that wasn't
        # present when we first cached (e.g. dont_say list grew),
        # bump to ``flag``. Never downgrade a cached ``block``.
        combined = _more_conservative(
            cached["decision"],
            "flag" if regex_low else "approve",
        )
        cached_reasons = list(cached.get("reasons") or [])
        if regex_low and combined != cached["decision"]:
            cached_reasons = (cached_reasons + [
                f"{f.get('source','regex')}:{f.get('match','')[:40]}"
                for f in regex_low[:2]
            ])[:4]
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision=combined,
            reasons=cached_reasons,
            risk_level=cached.get("risk_level") or "low",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=cached.get("model") or MODEL_NAME,
            from_cache=True,
            regex_high_flags=regex_high,
            regex_low_flags=regex_low,
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
            regex_high_flags=regex_high,
            regex_low_flags=regex_low,
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
            tenant_id=tenant_id,
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
            regex_high_flags=regex_high,
            regex_low_flags=regex_low,
        )

    # Phase I1.7.e · chunk 2.c · Feb-2026 — moderation is a scheduled
    # / autopilot gate, NOT a transactional HTTP endpoint. When the
    # tenant BYO monthly AI cap is exceeded we MUST NOT raise HTTP 429
    # (there's no HTTP caller). Instead, log ``skipped_cap_exceeded``
    # into the audit row and return ``decision="flag"`` so the post
    # is queued for human review — the safest failure mode when the
    # LLM is unavailable.
    from services.ai.cap_http import is_ai_cap_exceeded
    if is_ai_cap_exceeded(res):
        logger.info(
            "[soshie.moderation] skipped_cap_exceeded tenant=%s post=%s",
            tenant_id, post_id,
        )
        return await _store_result(
            tenant_id=tenant_id, post_id=post_id,
            content_hash=content_hash,
            decision="flag",
            reasons=["skipped_cap_exceeded"],
            risk_level="medium",
            tokens_in=0, tokens_out=0,
            cost_estimate_usd=0.0,
            model=MODEL_NAME,
            error="skipped_cap_exceeded",
            regex_high_flags=regex_high,
            regex_low_flags=regex_low,
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
            regex_high_flags=regex_high,
            regex_low_flags=regex_low,
        )
    raw = res.get("raw") or {}
    decision = _sanitize_decision(raw.get("decision"))
    reasons = _sanitize_reasons(raw.get("reasons"))
    risk_level = _sanitize_risk(raw.get("risk_level"))
    # Phase H7 · Combine LLM verdict with regex-low signal. The
    # LLM sees the full text so it *should* catch a PII-looking
    # substring, but folding in the regex-low signal is
    # defense-in-depth: never lets a low-confidence hit slip
    # past when the LLM approves. ``block`` from either side
    # dominates; ``flag`` from either side dominates ``approve``.
    if regex_low:
        combined = _more_conservative(decision, "flag")
        if combined != decision:
            reasons = (reasons + [
                f"{f.get('source','regex')}:{f.get('match','')[:40]}"
                for f in regex_low[:2]
            ])[:4]
        decision = combined
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
        regex_high_flags=regex_high,
        regex_low_flags=regex_low,
    )
