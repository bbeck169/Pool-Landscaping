"""Feb-2026 · TikTok stub adapter tests."""
from __future__ import annotations

import asyncio
import pytest

from services.social.tiktok_adapter import TikTokAdapter


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_check_credentials_returns_pending_gate():
    r = _run(TikTokAdapter().check_credentials("t-any"))
    assert r["ok"] is False
    # Both the invite-only + user-declined-middleman notes surface.
    assert "Content Posting API" in r["detail"]
    assert "INVITE-ONLY" in r["detail"]
    assert "Middleman" in r["detail"] or "middleman" in r["detail"]


def test_publish_video_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(TikTokAdapter().publish_video("t-any", "desc", "vid.mp4"))


def test_publish_text_platform_never_supports_it():
    with pytest.raises(NotImplementedError):
        _run(TikTokAdapter().publish_text("t-any", "hi"))


def test_supported_content_types_video_only():
    types = TikTokAdapter().supported_content_types()
    assert types == {"video"}
