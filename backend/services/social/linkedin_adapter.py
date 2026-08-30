"""LinkedIn Company Page publishing adapter — STUB · Feb-2026.

Pending operator setup:

    1. Create a LinkedIn Developer app owned by the target
       Company Page's admin account.
    2. Apply to the LinkedIn Marketing Developer Program (LMDP).
       Approval typically clears in 2-4 weeks.  LMDP approval
       is REQUIRED for the ``w_organization_social`` scope
       that lets us post as the Company Page.
    3. Configure the app's OAuth 2.0 redirect URI to point at
       ``{public_url}/api/soshie/platforms/linkedin/callback``.
    4. Complete 3-legged OAuth as an admin of the Company Page.
       Store the returned access + refresh tokens on
       ``db.social_platform_credentials`` (row key = tenant_id +
       ``platform="linkedin"``).
    5. Capture the Company Page URN (``urn:li:organization:{id}``)
       from the ``/v2/organizationAcls`` endpoint after OAuth.

Live wiring, when ready: replace :meth:`LinkedInAdapter.publish_text`
etc. with a POST to ``https://api.linkedin.com/v2/ugcPosts`` (or
``/rest/posts`` on the newer versioned API — check LinkedIn docs
at the time of implementation).  The ``author`` field takes the
Company Page URN captured above.
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: LinkedIn Marketing Developer Program "
    "approval + Company Page admin OAuth. Typical approval "
    "timeline: 2-4 weeks."
)


class LinkedInAdapter(SocialAdapter):
    """Stub adapter — every publish call raises
    :class:`NotImplementedError` until the operator gates above
    are cleared."""

    platform = "linkedin"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        # LinkedIn supports the widest set — kept here so the UI's
        # content-type toggles render correctly pre-approval.
        return {"text", "link", "image", "video"}

    async def publish_text(self, tenant_id: str, text: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_image(self, tenant_id: str, text: str,
                                 image_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
