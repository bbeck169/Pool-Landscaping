"""Social publishing adapters · Feb-2026.

One module per platform, all implementing :class:`SocialAdapter`
(see :mod:`services.social.base`).  Registration for every
supported platform lives in the :data:`PLATFORMS` registry below —
:func:`get_adapter` lazily imports the concrete class on demand so
a missing platform (e.g. TikTok Content Posting API blocked
pending partner approval) doesn't break the ``POST /soshie/publish``
fan-out.

Platform status matrix (Feb-2026 · P2 ship + follow-up stubs + GBP)::

    wordpress   ✓ LIVE — real publisher wired via services.social.wordpress_adapter
    gbp         ~ CODE-LIVE, OAuth pending — real publisher wired via
                  services.social.gbp_adapter. Awaiting per-tenant OAuth
                  connect (Settings → GBP → Connect Google).
    facebook    ✗ stub  — awaiting FB Business Verification + App Review
    instagram   ✗ stub  — paired with facebook, same gate
    linkedin    ✗ stub  — awaiting Marketing Developer Program approval
    youtube     ✗ stub  — awaiting GCP OAuth + refresh token; quota-locked
    reddit      ✗ stub  — awaiting brand account karma + subreddit approvals
    tiktok      ✗ stub  — awaiting Content Posting API partner approval (4-8 wks)

    x (Twitter) ✗ EXPLICITLY DROPPED per user decision — $100/mo paid tier
                  not approved. Do NOT re-add without a fresh green-light.
"""
from __future__ import annotations

import importlib
from typing import Dict, List, Optional, Tuple

from services.social.base import SocialAdapter


# Order-sensitive — the ``POST /soshie/publish`` fan-out iterates
# in insertion order so wordpress + gbp (the two live-code
# adapters) run first.  This is helpful for debugging: if WP + GBP
# publish and a stub raises NotImplementedError, the live rows are
# already on the response.
PLATFORMS: Dict[str, Tuple[str, str]] = {
    "wordpress": ("services.social.wordpress_adapter", "WordPressAdapter"),
    "gbp":       ("services.social.gbp_adapter",       "GBPAdapter"),
    "facebook":  ("services.social.facebook_adapter",  "FacebookAdapter"),
    "instagram": ("services.social.instagram_adapter", "InstagramAdapter"),
    "linkedin":  ("services.social.linkedin_adapter",  "LinkedInAdapter"),
    "youtube":   ("services.social.youtube_adapter",   "YouTubeAdapter"),
    "reddit":    ("services.social.reddit_adapter",    "RedditAdapter"),
    "tiktok":    ("services.social.tiktok_adapter",    "TikTokAdapter"),
    # DO NOT ADD "x" — explicitly dropped per Feb-2026 user decision.
}


_INSTANCES: Dict[str, SocialAdapter] = {}


def get_adapter(platform: str) -> Optional[SocialAdapter]:
    """Return a cached adapter instance for the platform, or None
    when the platform name is unknown.  Lazy import — a missing
    stub file surfaces as an ImportError logged by the caller."""
    name = (platform or "").strip().lower()
    if name not in PLATFORMS:
        return None
    if name not in _INSTANCES:
        module_path, class_name = PLATFORMS[name]
        mod = importlib.import_module(module_path)
        _INSTANCES[name] = getattr(mod, class_name)()
    return _INSTANCES[name]


def list_platforms() -> List[str]:
    """Return the ordered list of registered platform keys.  Used
    by ``GET /soshie/platforms`` to render the connect grid."""
    return list(PLATFORMS.keys())


__all__ = ["PLATFORMS", "get_adapter", "list_platforms", "SocialAdapter"]
