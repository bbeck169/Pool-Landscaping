"""Feb-2026 · Reddit stub adapter tests."""
from __future__ import annotations

import asyncio
import pytest

from services.social.reddit_adapter import RedditAdapter


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
    r = _run(RedditAdapter().check_credentials("t-any"))
    assert r["ok"] is False
    # Strategy warning surfaced in the pending-gate string.
    assert "karma" in r["detail"]
    assert "subreddit" in r["detail"]
    # LLM moderation dep surfaced.
    assert "Phase 9" in r["detail"] or "LLM moderation" in r["detail"]


def test_publish_text_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(RedditAdapter().publish_text("t-any", "post body"))


def test_publish_image_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        _run(RedditAdapter().publish_image("t-any", "cap", "img.png"))


def test_supported_content_types_text_link_image():
    types = RedditAdapter().supported_content_types()
    assert types == {"text", "link", "image"}
