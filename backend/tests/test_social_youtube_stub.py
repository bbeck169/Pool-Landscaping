"""Feb-2026 · YouTube stub adapter tests."""
from __future__ import annotations

import asyncio
import pytest

from services.social.youtube_adapter import YouTubeAdapter


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
    r = _run(YouTubeAdapter().check_credentials("t-any"))
    assert r["ok"] is False
    assert "GCP project" in r["detail"]
    assert "OAuth refresh token" in r["detail"]
    # Quota constraint surfaced.
    assert "6 uploads/day" in r["detail"]


def test_publish_video_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(YouTubeAdapter().publish_video("t-any", "desc", "vid.mp4"))


def test_publish_text_platform_never_supports_it():
    # YouTube only accepts video — text is unsupported by the
    # platform, not just by the stub.  Default base-class
    # NotImplementedError is what we expect.
    with pytest.raises(NotImplementedError):
        _run(YouTubeAdapter().publish_text("t-any", "hi"))


def test_publish_image_platform_never_supports_it():
    with pytest.raises(NotImplementedError):
        _run(YouTubeAdapter().publish_image("t-any", "hi", "img.png"))


def test_supported_content_types_video_only():
    types = YouTubeAdapter().supported_content_types()
    assert types == {"video"}
