"""YouTube video-upload adapter — STUB · Feb-2026.

Pending operator setup:

    1. Have a YouTube channel owned by the brand (Business
       preferred so custom-thumbnail features are available).
    2. Create a Google Cloud project.  Enable "YouTube Data
       API v3" on the project.
    3. Create an OAuth 2.0 Client ID (Desktop or Web).
    4. Complete OAuth 2.0 as the channel owner and capture the
       ``refresh_token`` — access tokens expire hourly, the
       refresh token is what we persist.
    5. Persist ``client_id``, ``client_secret``, ``refresh_token``,
       and ``channel_id`` on ``db.social_platform_credentials``
       (row key = tenant_id + ``platform="youtube"``).

Quota note (critical):
    * YouTube's default per-project quota is 10,000 units/day.
    * A single video upload costs ~1600 units.
    * Effective ceiling: ~6 uploads/day per GCP project.
    * If more capacity is required, submit a Quota Increase
      Request via the GCP console — Google reviews these and
      typically approves for legitimate business use.

Content note: YouTube requires a REAL video file for every
upload.  Shorts are just short videos with vertical aspect
ratio and ``#Shorts`` in the title/description — same API.
:meth:`publish_text` and :meth:`publish_image` will always
raise :class:`NotImplementedError` (platform limitation, not
a stub concern).

Live wiring, when ready: use the resumable upload flow via
``https://www.googleapis.com/upload/youtube/v3/videos`` with
``?uploadType=resumable`` — session URL first, chunked PUT after.
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: GCP project + YouTube Data API v3 + "
    "OAuth refresh token from channel owner. Quota-locked to "
    "~6 uploads/day per project by default."
)


class YouTubeAdapter(SocialAdapter):
    """Stub adapter — video uploads raise
    :class:`NotImplementedError` until the operator gates above
    are cleared."""

    platform = "youtube"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        # YouTube only accepts video — text/image are not
        # supported by the platform.
        return {"video"}

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
