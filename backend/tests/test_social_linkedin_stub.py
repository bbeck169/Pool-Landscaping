"""Feb-2026 · LinkedIn stub adapter tests."""
from __future__ import annotations

import asyncio
import pytest

from services.social.linkedin_adapter import LinkedInAdapter


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
    r = _run(LinkedInAdapter().check_credentials("t-any"))
    assert r["ok"] is False
    assert "Marketing Developer Program" in r["detail"]
    assert "2-4 weeks" in r["detail"]


def test_publish_text_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(LinkedInAdapter().publish_text("t-any", "hi"))


def test_publish_image_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(LinkedInAdapter().publish_image("t-any", "hi", "img.png"))


def test_publish_video_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(LinkedInAdapter().publish_video("t-any", "hi", "vid.mp4"))


def test_supported_content_types_full_set():
    types = LinkedInAdapter().supported_content_types()
    assert types == {"text", "link", "image", "video"}
