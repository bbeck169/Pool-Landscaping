"""Phase F3 · Feb-2026 — Soshie moderation service tests.

The tests mock ``services.llm_provider.call_llm_with_fallback`` at the
attribute level on the moderation module so no LLM cost is spent.
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed_tenant(db, credits: int = 100) -> str:
    tid = "TEST_F3_" + uuid.uuid4().hex[:8]
    await db.tenants.insert_one({
        "id": tid, "name": "F3 Test Co", "slug": tid.lower(),
        "ai_credits_balance": credits,
    })
    return tid


async def _cleanup(db, tid: str) -> None:
    await db.tenants.delete_many({"id": tid})
    await db.soshie_moderation_results.delete_many({"tenant_id": tid})


def _install_fake_llm(monkey_return):
    """Patch ``services.llm_provider.call_llm_with_fallback`` (the
    symbol imported inside ``moderate_post``)."""
    import services.llm_provider as llm

    calls = {"count": 0, "last_args": None}

    async def _fake(*args, **kwargs):
        calls["count"] += 1
        calls["last_args"] = kwargs or args
        return monkey_return

    original = llm.call_llm_with_fallback
    llm.call_llm_with_fallback = _fake

    def _restore():
        llm.call_llm_with_fallback = original

    return calls, _restore


# ─── 1. approve happy path ─────────────────────────────────────────────
def test_f3_moderate_approve_happy_path():
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db)
        calls, restore = _install_fake_llm({
            "raw": {"decision": "approve", "reasons": [], "risk_level": "low"},
            "provider": "emergent",
        })
        try:
            res = await moderate_post(
                post_id="p-approve", tenant_id=tid,
                text="Beautiful sparkling pool ready for family fun ☀️",
                media_urls=["https://cdn/x.jpg"],
            )
            assert res["decision"] == "approve"
            assert res["from_cache"] is False
            assert calls["count"] == 1
            rows = await db.soshie_moderation_results.find(
                {"tenant_id": tid, "post_id": "p-approve"},
            ).to_list(5)
            assert len(rows) == 1
            assert rows[0]["cost_estimate_usd"] >= 0
        finally:
            restore()
            await _cleanup(db, tid)

    run_test(_go)


# ─── 2. block routing on profanity ────────────────────────────────────
def test_f3_moderate_block_on_profanity():
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db)
        calls, restore = _install_fake_llm({
            "raw": {"decision": "block",
                     "reasons": ["profanity", "hate_speech"],
                     "risk_level": "high"},
            "provider": "emergent",
        })
        try:
            res = await moderate_post(
                post_id="p-block", tenant_id=tid,
                text="[[TEST profanity payload]]",
            )
            assert res["decision"] == "block"
            assert "profanity" in res["reasons"]
        finally:
            restore()
            await _cleanup(db, tid)

    run_test(_go)


# ─── 3. LLM failure → flag, NEVER approve ─────────────────────────────
def test_f3_llm_failure_returns_flag():
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db)
        calls, restore = _install_fake_llm({
            "error": "emergent_timeout", "provider": "emergent",
        })
        try:
            res = await moderate_post(
                post_id="p-fail", tenant_id=tid,
                text="anything",
            )
            assert res["decision"] == "flag"
            assert "moderation_service_unavailable" in res["reasons"]
        finally:
            restore()
            await _cleanup(db, tid)

    run_test(_go)


# ─── 4. cache hit replays without a new LLM call ──────────────────────
def test_f3_cache_hit_replays_prior_decision():
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db)
        calls, restore = _install_fake_llm({
            "raw": {"decision": "approve", "reasons": [], "risk_level": "low"},
            "provider": "emergent",
        })
        try:
            r1 = await moderate_post(
                post_id="p-cache-1", tenant_id=tid,
                text="cache probe text",
                media_urls=["https://cdn/a.jpg"],
            )
            r2 = await moderate_post(
                post_id="p-cache-2", tenant_id=tid,
                text="cache probe text",
                media_urls=["https://cdn/a.jpg"],
            )
            assert r1["decision"] == "approve"
            assert r2["decision"] == "approve"
            assert r2["from_cache"] is True
            assert calls["count"] == 1, (
                f"expected LLM to be called ONCE, got {calls['count']}"
            )
        finally:
            restore()
            await _cleanup(db, tid)

    run_test(_go)


# ─── 5. quota exceeded → flag (never approve) ────────────────────────
def test_f3_quota_exceeded_flags():
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db, credits=0)   # below CREDIT_FLOOR
        calls, restore = _install_fake_llm({
            "raw": {"decision": "approve"},
            "provider": "emergent",
        })
        try:
            res = await moderate_post(
                post_id="p-quota", tenant_id=tid,
                text="probe when out of credits",
            )
            assert res["decision"] == "flag"
            assert "quota_exceeded" in res["reasons"]
            assert calls["count"] == 0, (
                "LLM must NOT be called when tenant is over quota"
            )
        finally:
            restore()
            await _cleanup(db, tid)

    run_test(_go)


# ─── 6. kill switch bypass ───────────────────────────────────────────
def test_f3_kill_switch_bypass_approves():
    import os
    from services.soshie.llm_moderation import moderate_post

    async def _go(db):
        tid = await _seed_tenant(db)
        prev = os.environ.get("SOSHIE_MODERATION_ENABLED")
        os.environ["SOSHIE_MODERATION_ENABLED"] = "false"
        calls, restore = _install_fake_llm({
            "raw": {"decision": "block", "reasons": ["profanity"]},
        })
        try:
            res = await moderate_post(
                post_id="p-kill", tenant_id=tid,
                text="anything at all",
            )
            assert res["decision"] == "approve"
            assert "moderation_disabled" in res["reasons"]
            assert calls["count"] == 0
        finally:
            restore()
            if prev is None:
                os.environ.pop("SOSHIE_MODERATION_ENABLED", None)
            else:
                os.environ["SOSHIE_MODERATION_ENABLED"] = prev
            await _cleanup(db, tid)

    run_test(_go)
