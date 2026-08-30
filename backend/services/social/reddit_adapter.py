"""Reddit publishing adapter — STUB · Feb-2026.

Pending operator setup + strategy alignment:

    1. Reddit account owned by the brand.  Recommended maturity
       before automating:
         * Account age ≥ 30 days.
         * Comment karma ≥ 100 across relevant subreddits.
         * No shadowban / suspension history.
       Reddit's anti-spam heuristics ban young low-karma accounts
       posting brand content within hours.  Karma up organically
       before flipping automation on.
    2. Create a Reddit app at https://www.reddit.com/prefs/apps —
       type "script" for owned-account posting.  Note the
       client_id (14-char) and client_secret.
    3. Complete OAuth 2.0 password grant (script apps) OR the
       full 3-legged flow (web apps).  Store the returned
       tokens on ``db.social_platform_credentials`` (row key =
       tenant_id + ``platform="reddit"``).
    4. Curate a subreddit allowlist — each subreddit has its OWN
       rules for self-promo (many require a 1:9 ratio of
       promotional to organic posts).  Store on
       ``db.social_platform_credentials.subreddits[]``.  Ping
       each subreddit's mod team before enabling automated posts
       to avoid a fast ban.
    5. Rate-limit budget: Reddit caps OAuth clients at 60 req/min.
       Post rate is effectively capped by per-subreddit cooldowns
       and account trust.

STRATEGY WARNING (documented in the Feb-2026 audit):
    Automating brand posts to Reddit is a marketing risk, not a
    tech risk.  Even with all technical gates cleared, wrong-
    subreddit posts + wrong-tone content kills the account.
    The moderation gate (Phase 9 LLM verdict) MUST be enabled
    before this adapter goes live.

Live wiring, when ready: use ``praw`` (Python Reddit API
Wrapper) — friendlier than raw HTTP + honors rate limits
automatically.  Add ``praw`` to ``requirements.txt`` at that
time (deliberately NOT added now — no dev dep for a stub).
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: brand Reddit account with adequate "
    "karma + subreddit allowlist + mod-approval per subreddit. "
    "Requires Phase 9 LLM moderation gate to be live before "
    "enabling."
)


class RedditAdapter(SocialAdapter):
    """Stub adapter — every publish call raises
    :class:`NotImplementedError` until the operator gates above
    are cleared AND the LLM moderation layer (P9) ships."""

    platform = "reddit"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        # Reddit supports self posts (text), link posts, and
        # image/gallery posts.  Video via crossposting only.
        return {"text", "link", "image"}

    async def publish_text(self, tenant_id: str, text: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_image(self, tenant_id: str, text: str,
                                 image_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
