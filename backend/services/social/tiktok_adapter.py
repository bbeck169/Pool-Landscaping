"""TikTok video-upload adapter — STUB · Feb-2026.

Pending operator setup (HARD BLOCKER — most-friction of the seven
platforms):

    1. Convert the target TikTok account to a Business account.
    2. Create a TikTok for Business Developer app.
    3. Apply for the "Content Posting API" product on the app.
       This is INVITE-ONLY — apps must be reviewed by TikTok's
       partner team.  Anecdotal turnaround is 4-8 weeks; some
       small businesses have been rejected outright without
       actionable feedback.
    4. Once approved, complete OAuth 2.0 as the account owner
       and persist ``client_key``, ``client_secret``, and the
       returned access + refresh tokens on
       ``db.social_platform_credentials`` (row key = tenant_id +
       ``platform="tiktok"``).
    5. Note: rate limits are conservative (default 6 videos/day
       per account).  Direct Post publishes to the public feed;
       "Sandbox" mode drafts to the user's account for manual
       review before posting.

Middleman alternative (NOT recommended per user's Feb-2026
decision — user opted to wait for direct approval):

    * Buffer API                (~$6-100/mo).
    * Hootsuite API             (~$99/mo+).
    * Later API                 (~$25/mo+).

    Each middleman has its own adapter shape (upload video → get
    media_id → schedule post).  If direct approval stalls beyond
    the operator's patience, revisit and wire ONE of the above
    behind this adapter's class — the public shape stays
    identical.

Content note: TikTok's Content Posting API accepts video only.
:meth:`publish_text` / :meth:`publish_image` remain
NotImplementedError even once live (platform limitation).
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: TikTok Content Posting API partner "
    "approval (INVITE-ONLY, 4-8 week turnaround). Middleman "
    "(Buffer/Hootsuite) explicitly declined by user."
)


class TikTokAdapter(SocialAdapter):
    """Stub adapter — video uploads raise
    :class:`NotImplementedError` until TikTok's partner-review
    team approves the app."""

    platform = "tiktok"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        return {"video"}

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
