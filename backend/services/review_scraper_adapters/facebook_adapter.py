"""Facebook Pages review scraper — Reviews Phase 3.

Facebook Graph API exposes page ratings via
``GET /{page-id}/ratings?fields=rating,review_text,reviewer,created_time``
but requires an app with the ``pages_read_user_content`` permission and
a Page Access Token. Our existing ``routers/social.py`` handles social
post scheduling — it does NOT currently exchange for a Page Access
Token nor persist page IDs for review use.

Rather than build half an OAuth flow that we can't fully test in-
container, we gate the entire adapter behind
``FACEBOOK_INTEGRATION_ENABLED``. When disabled, the adapter returns
``{"status": "disabled"}`` immediately and no HTTP call is made. When
future FB OAuth ships, the same adapter can be extended to fetch real
data — the dispatch surface stays untouched.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Union


def _enabled() -> bool:
    v = (os.environ.get("FACEBOOK_INTEGRATION_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


async def fetch_recent_reviews(tenant_id: str) -> Union[List[Dict[str, Any]], Dict[str, str]]:
    if not _enabled():
        return {
            "status": "disabled",
            "detail": "FACEBOOK_INTEGRATION_ENABLED=false — Page Access "
                       "Token exchange has not shipped in routers/social.py "
                       "yet. Ship the OAuth wiring first, then flip this flag.",
        }
    # OAuth not implemented yet — treat "enabled but not wired" as
    # not_connected so the dispatcher journals the state cleanly
    # without pretending to have called Facebook.
    return {
        "status": "not_connected",
        "detail": "Facebook Page Access Token exchange not yet implemented "
                   "in routers/social.py. See PRD Reviews Phase 3.",
    }
