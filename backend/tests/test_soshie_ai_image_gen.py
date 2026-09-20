"""Phase S1.5 · AM2 — AI image generation tests.

Covers:
* Prompt template pulls brand memory (name, region, service_type,
  scene_description) verbatim into the LLM prompt.
* Aspect ratio per platform matches the S1.5 brief:
    IG=1:1, TikTok=2:3, FB=3:2, GBP=3:2.
* On provider success, image is persisted + logged to
  ``soshie_ai_generated_media``.
* Missing brand memory degrades gracefully (empty fields, no crash).

All tests mock the provider seam at
``services.media_provider.pick_provider`` so no real
nano-banana / Supercool call fires.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = _shared_client()
_db = _shared_db()
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _FakeProvider:
    provider_name = "fake"

    def __init__(self, captured: Dict[str, Any]):
        self._captured = captured

    async def generate(self, **kw):
        self._captured.update(kw)
        return {"provider": "fake",
                "tool_used": "fake-nano-banana",
                "image_urls": ["data:image/png;base64,ZmFrZQ=="]}


def _seed_brand_memory(tid: str) -> None:
    _db.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid,
                    "business_name": "Test Pool Co",
                    "service_area": "Peoria, AZ",
                    "timezone": "America/Phoenix"}},
        upsert=True,
    )
    _db.brand_brain.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "tone": "friendly, professional",
                    "audience": "homeowners",
                    "talking_points": ["clean water", "reliable service"],
                    "brand_voice_snippet": ""}},
        upsert=True,
    )


def _cleanup(tid: str) -> None:
    _db.tenants.delete_many({"id": tid})
    _db.brand_brain.delete_many({"tenant_id": tid})
    _db.brand_brain_ingested_pages.delete_many({"tenant_id": tid})
    _db.soshie_ai_generated_media.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Prompt template pulls brand memory verbatim
# ═════════════════════════════════════════════════════════════════════
def test_build_prompt_includes_brand_memory():
    from services.soshie.ai_image_gen import build_prompt

    brand = {
        "brand_name": "AquaTerra Pool Care",
        "region": "Phoenix, AZ",
        "tone": "warm, expert",
    }
    prompt = build_prompt(
        brand_memory=brand,
        service_type="pool cleaning",
        scene_description="tech skimming leaves out of a backyard pool",
        platform="instagram",
    )
    assert "AquaTerra Pool Care" in prompt
    assert "Phoenix, AZ" in prompt
    assert "pool cleaning" in prompt
    assert "tech skimming leaves" in prompt
    # Guardrails present.
    assert "No text overlays" in prompt
    assert "no watermarks" in prompt


# ═════════════════════════════════════════════════════════════════════
# 2 · Aspect ratio per platform matches the S1.5 brief
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("platform,expected_ratio,expected_px", [
    ("instagram", "1:1",  (1024, 1024)),
    ("tiktok",    "2:3",  (1024, 1536)),
    ("facebook",  "3:2",  (1536, 1024)),
    ("gbp",       "3:2",  (1536, 1024)),
])
def test_platform_aspect_matches_brief(platform, expected_ratio, expected_px):
    from services.soshie.ai_image_gen import PLATFORM_ASPECT, PLATFORM_SIZE_PX

    assert PLATFORM_ASPECT[platform] == expected_ratio
    assert PLATFORM_SIZE_PX[platform] == expected_px


# ═════════════════════════════════════════════════════════════════════
# 3 · generate_brand_image passes the aspect ratio to the provider
# ═════════════════════════════════════════════════════════════════════
def test_generate_brand_image_passes_aspect_and_persists(monkeypatch):
    from services.soshie import ai_image_gen
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    aid = f"TEST-a-{uuid.uuid4().hex[:6]}"
    _seed_brand_memory(tid)

    captured: Dict[str, Any] = {}

    async def _fake_pick(tenant_id: str):
        return _FakeProvider(captured)

    async def _fake_persist(url_or_datauri: str):
        return "img-abc", "/api/objects/generated/media/img-abc.png"

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)

    try:
        res = _run(ai_image_gen.generate_brand_image(
            tenant_id=tid, platform="tiktok",
            prompt_context={"service_type": "pool cleaning",
                             "scene_description": "tech vacuums pool"},
            action_id=aid,
        ))
        # Provider was called with the correct aspect ratio.
        assert captured.get("aspect_ratio") == "2:3", captured
        # Prompt pulled brand fields.
        p = captured.get("prompt", "")
        assert "Test Pool Co" in p
        assert "Peoria, AZ" in p
        assert "pool cleaning" in p
        assert "tech vacuums pool" in p
        # Persisted URL surfaces on the return.
        assert res["url"] == "/api/objects/generated/media/img-abc.png"
        assert res["aspect_ratio"] == "2:3"
        assert res["generated_media_id"] == "img-abc"
        assert res["action_id"] == aid
        # Log row written.
        log = _db.soshie_ai_generated_media.find_one(
            {"tenant_id": tid, "action_id": aid})
        assert log is not None
        assert log["platform"] == "tiktok"
        assert log["aspect_ratio"] == "2:3"
        assert log["storage_url"].endswith("img-abc.png")
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Empty brand memory degrades gracefully
# ═════════════════════════════════════════════════════════════════════
def test_generate_brand_image_no_brand_memory(monkeypatch):
    from services.soshie import ai_image_gen
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    captured: Dict[str, Any] = {}

    async def _fake_pick(tenant_id: str):
        return _FakeProvider(captured)

    async def _fake_persist(url_or_datauri: str):
        return "img-empty", "/api/objects/generated/media/img-empty.png"

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)

    try:
        res = _run(ai_image_gen.generate_brand_image(
            tenant_id=tid, platform="instagram",
            prompt_context={"service_type": ""},
        ))
        # Doesn't crash — prompt uses default fallbacks.
        assert res["url"].endswith("img-empty.png")
        assert res["aspect_ratio"] == "1:1"
        p = captured.get("prompt", "")
        assert "the company" in p or "pool & landscaping" in p
    finally:
        _cleanup(tid)
