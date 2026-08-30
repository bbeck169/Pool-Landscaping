"""Instagram Business publishing adapter — STUB · Feb-2026.

Pending operator setup (paired with Facebook — same Meta app):

    1. Complete every step in the Facebook adapter's checklist
       (Business Verification, App Review, long-lived token).
    2. Convert the target Instagram account to a Business account.
    3. Link the Instagram Business account to the Facebook Page
       whose token you generated in the FB checklist.
    4. Submit the Meta app for Instagram Content Publishing
       review — scope ``instagram_content_publish``.  Usually
       clears alongside the FB review.
    5. Persist the IG User ID + inherit the FB Page Access Token
       on ``db.social_platform_credentials`` (row key = tenant_id
       + ``platform="instagram"``).

Live wiring, when ready: replace :meth:`InstagramAdapter.publish_image`
etc. with the two-step container flow —
``POST /{ig-user-id}/media`` (get container id) then
``POST /{ig-user-id}/media_publish`` (publish container).  This
is different from Facebook's single POST, so keep the multi-step
plumbing scoped to this adapter.

Content-type note: Instagram does NOT accept text-only posts.
:meth:`publish_text` remains a NotImplementedError even after the
gates clear — the caller must provide an image_ref or video_ref.
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: Instagram Business account linked "
    "to a Facebook Page + Meta App Review for "
    "instagram_content_publish. Paired with Facebook — clears "
    "together."
)


class InstagramAdapter(SocialAdapter):
    """Stub adapter — every publish call raises
    :class:`NotImplementedError` until the operator gates above
    are cleared."""

    platform = "instagram"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        # IG requires media — text-only posts are not supported by
        # the platform (even once we're live).
        return {"image", "video"}

    async def publish_image(self, tenant_id: str, text: str,
                                 image_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
