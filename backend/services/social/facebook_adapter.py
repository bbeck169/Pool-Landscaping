"""Facebook Page publishing adapter — STUB · Feb-2026.

Pending operator setup (see the Feb-2026 Soshie AI-Agent Expansion
audit for the full checklist):

    1. Create a Facebook Developer account owning the target FB
       Business.
    2. Complete FB Business Verification (business docs + domain
       verification; D-U-N-S optional).  Typical turnaround
       1-3 business days.
    3. Create a Facebook App tied to the Business.  Enable the
       Graph API product.
    4. Submit for App Review with scopes:
         * ``pages_manage_posts``  (create posts on Page)
         * ``pages_read_engagement`` (read likes/comments back)
         * ``pages_show_list`` (list Pages the token can access)
       App Review typically clears in 1-2 weeks.
    5. Generate a LONG-LIVED Page Access Token for the target
       Page (60-day expiry — refresh flow needed).
    6. Persist the Page ID + long-lived token on
       ``db.social_platform_credentials`` (row key = tenant_id +
       ``platform="facebook"``).

Live wiring, when ready: replace :meth:`FacebookAdapter.publish_text`
etc. with real ``graph.facebook.com/{page-id}/feed`` calls.  The
adapter's public shape does not change — the router does not need
to be re-wired.

Rate limits: ``graph.facebook.com`` defaults to ~200 calls/hour
per user.  Publishing is well within that.
"""
from __future__ import annotations

from typing import Any, Dict, Set

from services.social.base import SocialAdapter


_PENDING_GATE = (
    "Pending operator setup: Facebook Business Verification + "
    "App Review for pages_manage_posts. Contact the operator "
    "before enabling Facebook publishing."
)


class FacebookAdapter(SocialAdapter):
    """Stub adapter — every publish call raises
    :class:`NotImplementedError` until the operator gates above
    are cleared."""

    platform = "facebook"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        return {"ok": False, "detail": _PENDING_GATE}

    def supported_content_types(self) -> Set[str]:
        # Publishable content types once live — kept here so the
        # UI can already render the type toggles correctly.
        return {"text", "link", "image", "video"}

    async def publish_text(self, tenant_id: str, text: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_image(self, tenant_id: str, text: str,
                                 image_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str, **kwargs: Any):
        raise NotImplementedError(_PENDING_GATE)
