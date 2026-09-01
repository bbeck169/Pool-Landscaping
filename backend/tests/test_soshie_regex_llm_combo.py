"""Phase H7 · Feb-2026 — Regex + LLM combo pipeline tests."""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict

import pytest

from tests._f7_loop_fixture import run_test


def _reset_env(monkeypatch):
    monkeypatch.delenv("SOSHIE_MODERATION_ENABLED", raising=False)
    monkeypatch.delenv("SOSHIE_REGEX_PREFILTER_ENABLED", raising=False)


def _fake_llm_verdict(decision="approve", reasons=None, risk="low"):
    async def _fake_call(**kw):
        return {"raw": {"decision": decision,
                          "reasons": reasons or [],
                          "risk_level": risk},
                "error": None}
    return _fake_call


async def _tenant_with_credits(db) -> str:
    tid = f"h7-{uuid.uuid4().hex[:8]}"
    await db.tenants.insert_one({
        "id": tid, "slug": tid, "name": "H7 tenant",
        "ai_credits_balance": 9999,
    })
    return tid


async def _cleanup(db, tid: str):
    await db.tenants.delete_one({"id": tid})
    await db.soshie_moderation_results.delete_many(
        {"tenant_id": tid},
    )


def test_h7_regex_high_conf_block_short_circuits_no_llm_call(monkeypatch):
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            r = await lm.moderate_post(
                post_id=f"h7-block-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                # ``guaranteed`` is a high-confidence banned phrase.
                text="We offer guaranteed pool cleaning!",
            )
            assert r["decision"] == "block"
            assert r["model"] == "regex-p1"
            assert r["cost_estimate_usd"] == 0.0
            assert r["regex_short_circuit"] is True
            assert calls["llm"] == 0, "LLM must never be called"
            # Every hit persisted for the H6 counter.
            n = await db.soshie_moderation_results.count_documents({
                "tenant_id": tid, "regex_short_circuit": True,
                "model": "regex-p1",
            })
            assert n == 1
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_regex_low_conf_hit_calls_llm_and_folds_flag(monkeypatch):
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        # LLM says APPROVE but regex-low says the PII pattern
        # matched → combined decision must be FLAG.
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            r = await lm.moderate_post(
                post_id=f"h7-pii-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                text="Contact us at hello@aquaterra.com for details.",
            )
            assert calls["llm"] == 1, "regex-low must fall through to LLM"
            assert r["decision"] == "flag", (
                f"expected regex-low FLAG override; got {r['decision']}"
            )
            # regex_short_circuit stays False since LLM was called.
            assert r["regex_short_circuit"] is False
            # The regex low flag payload is captured on the row.
            assert any(f.get("source") == "email"
                        for f in r["regex_low_flags"])
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_regex_approve_llm_approve_final_approve(monkeypatch):
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm_verdict("approve"),
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            r = await lm.moderate_post(
                post_id=f"h7-ok-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                text="Weekly pool service — sparkling clean water for your family.",
            )
            assert r["decision"] == "approve"
            assert r["model"] == "claude-sonnet-4-5"
            assert r["cost_estimate_usd"] > 0
            assert r["regex_short_circuit"] is False
            assert r["regex_low_flags"] == []
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_regex_approve_llm_block_final_block(monkeypatch):
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm_verdict("block", reasons=["profanity"], risk="high"),
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            # Clean-looking text that the LLM decides to block.
            r = await lm.moderate_post(
                post_id=f"h7-llm-block-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                text="Nothing objectionable here per regex.",
            )
            assert r["decision"] == "block"
            assert r["regex_short_circuit"] is False
            assert r["model"] == "claude-sonnet-4-5"
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_prefilter_env_off_forces_llm_even_on_obvious_blocks(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("SOSHIE_REGEX_PREFILTER_ENABLED", "false")
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            # Would normally short-circuit — env flag off forces
            # the LLM path.
            r = await lm.moderate_post(
                post_id=f"h7-envoff-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                text="We offer guaranteed pool cleaning!",
            )
            assert calls["llm"] == 1, (
                "PREFILTER_ENABLED=false must NOT short-circuit"
            )
            assert r["model"] == "claude-sonnet-4-5"
            assert r["regex_short_circuit"] is False
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_kill_switch_bypasses_both_stages(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("SOSHIE_MODERATION_ENABLED", "false")
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            r = await lm.moderate_post(
                post_id=f"h7-kill-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                # Would BOTH regex-block AND LLM-flag if the
                # switch were on. Kill switch trumps.
                text="We offer guaranteed pool cleaning with cure-all chemistry!",
            )
            assert r["decision"] == "approve"
            assert r["model"] == "kill-switch"
            assert calls["llm"] == 0
            assert r["regex_short_circuit"] is False
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_cache_hit_folds_regex_low_flag_but_never_downgrades_block(
    monkeypatch,
):
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            # First call — seed the cache with an APPROVE for
            # text that carries a regex-low email hit.
            text = "Reach us at hello@aquaterra.com."
            r1 = await lm.moderate_post(
                post_id="h7-cache-1", tenant_id=tid, text=text,
            )
            # The regex-low fold should already have made this
            # a FLAG on the first pass.
            assert r1["decision"] == "flag"
            assert r1["from_cache"] is False
            # Second call with identical text → cache hit path.
            r2 = await lm.moderate_post(
                post_id="h7-cache-2", tenant_id=tid, text=text,
            )
            assert r2["from_cache"] is True
            # Cache row was already flag; combined decision
            # stays flag.
            assert r2["decision"] == "flag"
            assert r2["cost_estimate_usd"] == 0.0
            # LLM was invoked exactly once — on the first call.
            assert calls["llm"] == 1
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_h7_regex_low_hit_does_not_short_circuit(monkeypatch):
    """Explicit lock: PII (low-confidence) must call the LLM."""
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        try:
            r = await lm.moderate_post(
                post_id=f"h7-lowonly-{uuid.uuid4().hex[:6]}",
                tenant_id=tid,
                text="Call us at (555) 123-4567 anytime.",
            )
            assert calls["llm"] == 1, "low-conf must not short-circuit"
            assert r["regex_short_circuit"] is False
            assert any(f.get("source") == "phone"
                        for f in r["regex_low_flags"])
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── Phase I1 · Feb-2026 — autopilot dont_say wire-up ───────────
def test_i1_autopilot_gate_passes_dont_say_from_brand_brain(monkeypatch):
    """End-to-end: seed a tenant's ``brand_brain.dont_say`` list,
    run the autopilot moderation gate against a draft carrying
    one of those phrases, and assert:
      * regex prefilter short-circuits to block
      * LLM is NEVER invoked
      * result row carries ``regex_short_circuit=True``
      * ``regex_high_flags`` includes the tenant's forbidden phrase
    """
    _reset_env(monkeypatch)
    from services.soshie import llm_moderation as lm
    from services.soshie import autopilot_scheduler as sched

    calls = {"llm": 0}

    async def _spy_llm(**kw):
        calls["llm"] += 1
        return {"raw": {"decision": "approve", "reasons": [],
                          "risk_level": "low"}, "error": None}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    async def _go(db):
        tid = await _tenant_with_credits(db)
        await db.brand_brain.insert_one({
            "tenant_id": tid,
            "dont_say": ["magic potion", "snake oil"],
        })
        aid = f"i1-{uuid.uuid4().hex[:8]}"
        # ``_run_moderation_gate`` writes onto the action row so
        # seed one for it to update.
        await db.ai_employee_actions.insert_one({
            "id": aid, "tenant_id": tid, "status": "pending",
            "draft": {"text": "Try our magic potion for spring cleaning!"},
        })
        try:
            outcome = await sched._run_moderation_gate(
                tenant_id=tid,
                action={"id": aid,
                          "draft": {"text": "Try our magic potion for spring cleaning!"}},
                media={"media_url": None},
            )
            # Diverted (block) because the regex prefilter fired.
            assert outcome is not None, "gate must divert on block"
            assert outcome.get("outcome") == "moderation_block"
            # LLM never touched.
            assert calls["llm"] == 0
            # Fingerprint on the moderation row.
            row = await db.soshie_moderation_results.find_one(
                {"tenant_id": tid, "post_id": aid}, {"_id": 0},
            )
            assert row is not None
            assert row["decision"] == "block"
            assert row["regex_short_circuit"] is True
            assert row["model"] == "regex-p1"
            # The forbidden phrase is captured in the flag payload
            # so admins can audit exactly what tripped the gate.
            matches = [f.get("match", "").lower()
                        for f in (row.get("regex_high_flags") or [])]
            assert any("magic potion" in m for m in matches), matches
        finally:
            await _cleanup(db, tid)
            await db.brand_brain.delete_many({"tenant_id": tid})
            await db.ai_employee_actions.delete_many({"id": aid})

    run_test(_go)
