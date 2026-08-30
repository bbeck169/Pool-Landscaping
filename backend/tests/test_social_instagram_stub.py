"""Feb-2026 · Instagram stub adapter tests."""
from __future__ import annotations

import asyncio
import pytest

from services.social.instagram_adapter import InstagramAdapter


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
    r = _run(InstagramAdapter().check_credentials("t-any"))
    assert r["ok"] is False
    assert "Instagram Business" in r["detail"]
    assert "instagram_content_publish" in r["detail"]


def test_publish_image_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(InstagramAdapter().publish_image("t-any", "cap", "img.png"))


def test_publish_video_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(InstagramAdapter().publish_video("t-any", "cap", "vid.mp4"))


def test_publish_text_unsupported_even_when_live():
    """IG platform requires media — text-only posts are unsupported
    even when we're not stubbed."""
    with pytest.raises(NotImplementedError):
        _run(InstagramAdapter().publish_text("t-any", "hi"))


def test_supported_content_types_no_text_no_link():
    types = InstagramAdapter().supported_content_types()
    assert types == {"image", "video"}
