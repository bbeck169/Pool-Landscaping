"""Phase H5.5 · Feb-2026 — Manual-Only mode contract tests.

Locks in:
    * ``DEFAULT_CADENCE`` flips: Facebook / Instagram / LinkedIn /
      YouTube / TikTok / GBP carry ``manual_only=True``. Reddit
      stays manual_only=True. WordPress stays fully-automated.
    * ``list_for_tenant`` overlays ``manual_only`` from the code
      table onto persisted rows so tenants seeded before H5.5
      surface the current truth.
    * The autopilot scheduler:
        - runs cadence + moderation for manual-only platforms
        - stamps ``status="awaiting_manual"`` on success
        - **never** invokes the wire ``_dispatch_one`` path
    * The stub adapters (Facebook, IG, TikTok, LinkedIn, YouTube,
      Reddit) still raise NotImplementedError on any publish call
      — this is the "fail-loud on accidental future wiring" guard
      called out in the H5.5 brief.
    * ``POST /soshie/moderation/{post_id}/mark-posted`` flips
      ``awaiting_manual`` → ``published_manual`` idempotently and
      writes an audit event.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


# ─── Config-table flips (pure module-level check) ────────────────
def test_h55_default_cadence_flips_six_platforms():
    from services.soshie.autopilot_config import DEFAULT_CADENCE
    for p in ("facebook", "instagram", "linkedin",
              "youtube", "tiktok", "gbp"):
        assert DEFAULT_CADENCE[p].get("manual_only") is True, (
            f"{p} must be manual_only=True after H5.5"
        )
    # Reddit stays manual_only.
    assert DEFAULT_CADENCE["reddit"].get("manual_only") is True
    # WordPress stays fully-automated.
    assert not DEFAULT_CADENCE["wordpress"].get("manual_only")


def test_h55_is_manual_only_helper_reads_code_table_first():
    from services.soshie.autopilot_config import is_manual_only
    # Passed cfg wins when set.
    assert is_manual_only("facebook", {"manual_only": True}) is True
    # Falls back to the code table when cfg is absent — needed for
    # tenants whose persisted rows predate the H5.5 flip.
    assert is_manual_only("facebook", {}) is True
    assert is_manual_only("wordpress", {}) is False
    # Unknown platform → False (defense in depth).
    assert is_manual_only("myspace", {}) is False


# ─── Config-list overlay: persisted row w/o manual_only surfaces True ─
def test_h55_list_for_tenant_overlays_manual_only_on_stale_row():
    from services.soshie.autopilot_config import list_for_tenant

    async def _go(db):
        tid = f"h55-overlay-{uuid.uuid4().hex[:6]}"
        # Simulate a tenant seeded before H5.5: manual_only=False
        # on a platform that H5.5 flipped to True.
        await db.soshie_autopilot_config.insert_one({
            "id": "stale1", "tenant_id": tid, "platform": "facebook",
            "posts_per_day": None, "posts_per_week": 3,
            "manual_only": False, "enabled": True,
            "timezone": "UTC",
        })
        try:
            rows = await list_for_tenant(tid)
            row = next(r for r in rows if r["platform"] == "facebook")
            assert row["manual_only"] is True, (
                "H5.5 overlay must surface manual_only=True even "
                "when the persisted row still says False"
            )
        finally:
            await db.soshie_autopilot_config.delete_many(
                {"tenant_id": tid},
            )

    run_test(_go)


# ─── Adapter stubs still fail-loud on any publish call ────────────
@pytest.mark.parametrize("platform", [
    "facebook", "instagram", "linkedin",
    "youtube", "tiktok", "reddit",
])
def test_h55_stub_adapters_raise_not_implemented_on_publish(platform):
    import importlib
    mod = importlib.import_module(
        f"services.social.{platform}_adapter",
    )
    cls_name = {
        "facebook": "FacebookAdapter",
        "instagram": "InstagramAdapter",
        "linkedin": "LinkedInAdapter",
        "youtube": "YouTubeAdapter",
        "tiktok": "TikTokAdapter",
        "reddit": "RedditAdapter",
    }[platform]
    adapter = getattr(mod, cls_name)()
    import asyncio

    async def _call():
        with pytest.raises(NotImplementedError):
            await adapter.publish_text("t", "hello")
        # publish_image too if the adapter declares it.
        if hasattr(adapter, "publish_image"):
            with pytest.raises(NotImplementedError):
                await adapter.publish_image("t", "hello", "img")

    asyncio.run(_call())


# ─── mark-posted endpoint: idempotent + audit ─────────────────────
def test_h55_mark_posted_flips_status_and_is_idempotent():
    from routers.soshie_moderation import mark_manual_posted

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        tid = tenant["id"]
        admin = await db.users.find_one(
            {"email": "admin@aquaterra.com"},
            {"_id": 0, "id": 1, "role": 1},
        )
        aid = f"h55-mp-{uuid.uuid4().hex[:8]}"
        await db.ai_employee_actions.insert_one({
            "id": aid, "tenant_id": tid,
            "status": "awaiting_manual",
            "manual_only_platform": "facebook",
            "draft": {"text": "hello world"},
        })
        try:
            r1 = await mark_manual_posted(
                post_id=aid, user=admin, tenant={"id": tid},
            )
            assert r1["new_status"] == "published_manual"
            assert r1["already_posted"] is False
            # Idempotent: calling again returns 200 with
            # already_posted=True.
            r2 = await mark_manual_posted(
                post_id=aid, user=admin, tenant={"id": tid},
            )
            assert r2["new_status"] == "published_manual"
            assert r2["already_posted"] is True
            # DB state carries actor + timestamp.
            row = await db.ai_employee_actions.find_one(
                {"id": aid, "tenant_id": tid}, {"_id": 0},
            )
            assert row["status"] == "published_manual"
            assert row["manual_posted_by"] == admin["id"]
            assert row["manual_posted_at"]
            # Audit event written (one row per successful flip;
            # the idempotent second call does NOT write a new
            # audit event because it early-returns before the
            # ``update_one`` path).
            n = await db.audit_events.count_documents({
                "tenant_id": tid,
                "event_type": "soshie_manual_mark_posted",
                "post_id": aid,
            })
            assert n == 1, f"expected exactly 1 audit event, got {n}"
        finally:
            await db.ai_employee_actions.delete_many({"id": aid})
            await db.audit_events.delete_many(
                {"tenant_id": tid, "post_id": aid},
            )

    run_test(_go)


def test_h55_mark_posted_rejects_non_awaiting_manual_states():
    from routers.soshie_moderation import mark_manual_posted

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        tid = tenant["id"]
        admin = await db.users.find_one(
            {"email": "admin@aquaterra.com"},
            {"_id": 0, "id": 1, "role": 1},
        )
        aid = f"h55-mp-bad-{uuid.uuid4().hex[:8]}"
        # A ``rejected`` row must NOT be silently flipped.
        await db.ai_employee_actions.insert_one({
            "id": aid, "tenant_id": tid,
            "status": "rejected",
            "draft": {"text": "hello"},
        })
        try:
            with pytest.raises(HTTPException) as ei:
                await mark_manual_posted(
                    post_id=aid, user=admin, tenant={"id": tid},
                )
            assert ei.value.status_code == 409
        finally:
            await db.ai_employee_actions.delete_many({"id": aid})

    run_test(_go)


# ─── Scheduler wire-dispatch is skipped for manual-only platforms ─
def test_h55_scheduler_stamps_awaiting_manual_and_skips_dispatch(monkeypatch):
    """Locks the core H5.5 contract: when a platform is manual-only,
    the autopilot scheduler runs cadence + moderation but replaces
    the wire dispatch with a status stamp of ``awaiting_manual``.
    ``_dispatch_one`` MUST NOT be invoked."""
    import services.soshie.autopilot_scheduler as sched

    dispatch_calls: list = []
    manual_calls: list = []

    async def _fake_dispatch(**kwargs):
        dispatch_calls.append(kwargs)
        return {"action_id": kwargs["action"]["id"],
                "outcome": "should_not_run"}

    async def _spy_manual(*, tenant_id, action, platform):
        # Delegate to the real implementation so DB state matches,
        # but also record we ran.
        manual_calls.append({"platform": platform,
                                "action_id": action["id"]})
        return await _real_manual(
            tenant_id=tenant_id, action=action, platform=platform,
        )

    _real_manual = sched._mark_manual_ready

    monkeypatch.setattr(sched, "_dispatch_one", _fake_dispatch)
    monkeypatch.setattr(sched, "_mark_manual_ready", _spy_manual)

    async def _go(db):
        tid = f"h55-sched-{uuid.uuid4().hex[:6]}"
        aid = f"h55-act-{uuid.uuid4().hex[:8]}"
        # Enable Facebook autopilot on a fresh tenant.
        await db.soshie_autopilot_config.insert_one({
            "id": "cfg1", "tenant_id": tid, "platform": "facebook",
            "posts_per_day": None, "posts_per_week": 3,
            "manual_only": True, "enabled": True,
            "timezone": "UTC", "last_scheduled_at": None,
        })
        # Global kill switch on.
        await db.tenants.insert_one({
            "id": tid, "slug": tid, "name": "H55 sched",
            "soshie_autopilot_enabled": True,
        })
        # An action ready to be picked up. Must be OLDER than the
        # 24h autopilot window cutoff AND use the ``draft_post``
        # action shape with ``draft.platform`` set for
        # ``_platform_from_action`` to resolve it to Facebook.
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc)
                - timedelta(hours=30)).isoformat()
        await db.ai_employee_actions.insert_one({
            "id": aid, "tenant_id": tid, "employee_key": "soshie",
            "action": "soshie.draft_post", "status": "pending",
            "params": {"platform": "facebook"},
            "draft": {"text": "manual-only proof",
                       "platform": "facebook"},
            "scheduled_at": past, "created_at": past,
        })
        try:
            # Stub out the moderation gate to return "approve" so
            # the row survives to the dispatch/manual-ready branch.
            async def _fake_mod(*, tenant_id, action, media):
                return None
            monkeypatch.setattr(
                sched, "_run_moderation_gate", _fake_mod,
            )
            # Stub _maybe_attach_media so we don't need real assets.
            async def _fake_media(*, tenant_id, action, platform):
                return {"ok": True, "media_url": None,
                        "media_source": None, "brand_score": 0.9}
            monkeypatch.setattr(
                sched, "_maybe_attach_media", _fake_media,
            )
            # Stub credits so we don't defer.
            async def _fake_credits(_):
                return 999.0
            monkeypatch.setattr(
                sched, "_tenant_credit_balance", _fake_credits,
            )
            # Stub cadence to always allow.
            async def _fake_cadence(_tid, _p, _cfg):
                return True
            monkeypatch.setattr(
                sched, "_cadence_ok", _fake_cadence,
            )
            # And run the tick.
            summary = await sched._process_tenant(tid)
            # Wire dispatch must never fire.
            assert not dispatch_calls, (
                f"_dispatch_one invoked for manual-only platform: "
                f"{dispatch_calls}"
            )
            # Manual-ready path fired once.
            assert len(manual_calls) == 1
            assert manual_calls[0]["platform"] == "facebook"
            # DB status flipped.
            row = await db.ai_employee_actions.find_one(
                {"id": aid, "tenant_id": tid}, {"_id": 0},
            )
            assert row["status"] == "awaiting_manual"
            assert row["manual_only_platform"] == "facebook"
            assert row.get("manual_ready_at")
            # Summary reports the outcome.
            outcomes = [
                r.get("outcome") for r in summary["results"]
            ]
            assert "awaiting_manual" in outcomes
        finally:
            await db.ai_employee_actions.delete_many({"id": aid})
            await db.soshie_autopilot_config.delete_many(
                {"tenant_id": tid},
            )
            await db.tenants.delete_one({"id": tid})

    run_test(_go)
