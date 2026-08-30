"""Phase S1.5 · AM2 — Brand-score gate tests.

Covers:
* ``score_brand_consistency`` returns a value in ``[0.0, 1.0]``.
* Score ≥ 0.75 → autopilot's ``_maybe_attach_media`` returns
  ``ok=True`` and does NOT set ``requires_human_approval``.
* Score < 0.75 → returns ``ok=False`` with
  ``requires_human_approval=True`` and blocks autopilot.
* Missing ``EMERGENT_LLM_KEY`` returns the conservative 0.5 stub.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


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
    def __init__(self, captured):
        self._captured = captured

    async def generate(self, **kw):
        self._captured.update(kw)
        return {"provider": "fake", "tool_used": "fake",
                "image_urls": ["data:image/png;base64,ZmFrZQ=="]}


def _seed_brand(tid: str):
    _db.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "business_name": "BrandCo",
                    "service_area": "Peoria, AZ",
                    "timezone": "America/Phoenix",
                    "ai_credits_balance": 500,
                    "ai_credits_plan": "essentials",
                    "ai_credits_monthly_grant": 1000}},
        upsert=True,
    )


def _cleanup(tid: str):
    _db.tenants.delete_many({"id": tid})
    _db.brand_brain.delete_many({"tenant_id": tid})
    _db.soshie_ai_generated_media.delete_many({"tenant_id": tid})
    _db.ai_employee_actions.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · parse_score utility clamps to [0.0, 1.0]
# ═════════════════════════════════════════════════════════════════════
def test_parse_score_clamps_and_normalises():
    from services.soshie.ai_image_gen import _parse_score

    assert _parse_score("0.9") == 0.9
    assert _parse_score("1.0") == 1.0
    assert _parse_score("0.0") == 0.0
    assert _parse_score("") == 0.0
    # 0-100 coerced.
    assert _parse_score("85") == 0.85
    # Out-of-range clamped.
    assert _parse_score("999") == 1.0
    assert _parse_score("nope") == 0.0
    # Whitespace + prose tolerated.
    assert _parse_score("  0.42  ") == 0.42


# ═════════════════════════════════════════════════════════════════════
# 2 · Missing EMERGENT_LLM_KEY returns conservative stub 0.5
# ═════════════════════════════════════════════════════════════════════
def test_score_without_key_returns_stub(monkeypatch):
    from services.soshie import ai_image_gen

    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    score = _run(ai_image_gen.score_brand_consistency(
        image_url="https://ex.test/x.png",
        brand_memory={"brand_name": "Co"},
    ))
    assert score == 0.5


# ═════════════════════════════════════════════════════════════════════
# 3 · Score ≥ threshold → media attach returns ok=True
# ═════════════════════════════════════════════════════════════════════
def test_high_brand_score_auto_publishes(monkeypatch):
    from services.soshie import ai_image_gen
    from services.soshie import autopilot_scheduler as aps
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    aid = f"TEST-a-{uuid.uuid4().hex[:6]}"
    _seed_brand(tid)
    captured: Dict[str, Any] = {}

    async def _fake_pick(tenant_id: str):
        return _FakeProvider(captured)

    async def _fake_persist(url_or_datauri: str):
        return "img-hi", "/api/objects/generated/media/img-hi.png"

    async def _fake_score(**kw):
        return 0.90

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)
    monkeypatch.setattr(ai_image_gen, "score_brand_consistency",
                          _fake_score)
    action = {"id": aid, "tenant_id": tid,
                "params": {"service_type": "pool cleaning"},
                "draft": {}}
    try:
        media = _run(aps._maybe_attach_media(
            tenant_id=tid, action=action, platform="instagram",
        ))
        assert media["ok"] is True
        assert media["media_source"] == "ai_generated"
        assert media["brand_score"] == 0.90
        assert media["requires_human_approval"] is False
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Score < threshold → media attach returns ok=False + requires_human
# ═════════════════════════════════════════════════════════════════════
def test_low_brand_score_blocks_autopilot(monkeypatch):
    from services.soshie import ai_image_gen
    from services.soshie import autopilot_scheduler as aps
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    aid = f"TEST-a-{uuid.uuid4().hex[:6]}"
    _seed_brand(tid)
    captured: Dict[str, Any] = {}

    async def _fake_pick(tenant_id: str):
        return _FakeProvider(captured)

    async def _fake_persist(url_or_datauri: str):
        return "img-lo", "/api/objects/generated/media/img-lo.png"

    async def _fake_score(**kw):
        return 0.40   # below 0.75 threshold

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)
    monkeypatch.setattr(ai_image_gen, "score_brand_consistency",
                          _fake_score)
    action = {"id": aid, "tenant_id": tid,
                "params": {"service_type": "pool cleaning"},
                "draft": {}}
    try:
        media = _run(aps._maybe_attach_media(
            tenant_id=tid, action=action, platform="facebook",
        ))
        assert media["ok"] is False
        assert media["media_source"] == "ai_generated"
        assert media["brand_score"] == 0.40
        assert media["requires_human_approval"] is True
    finally:
        _cleanup(tid)
