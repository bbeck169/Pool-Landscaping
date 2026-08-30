"""Google Business Profile (GBP) publisher adapter · Feb-2026.

Wraps the already-live end-to-end GBP integration in
``routers/gbp.py`` — OAuth 2.0 flow + refresh-token cycle +
``_do_publish_post`` against ``mybusiness.googleapis.com/v4``.

This adapter is NOT a stub.  The code path is fully wired.  What
gates a live publish is per-tenant OAuth completion — the OAuth
credentials + refresh token are stored on ``db.gbp_settings``
(singleton doc for now; a tenant-scoped variant is Phase-later
work).  ``check_credentials`` reports the tri-state cleanly:

    * ok=True  — client_id + refresh_token stamped → publish will succeed.
    * ok=False — client_id missing → operator hasn't saved OAuth
                 config yet (Settings → GBP → paste client_id/secret).
    * ok=False — client_id present but no access/refresh_token →
                 operator has NOT clicked "Connect Google" yet
                 (click Connect on the GBP settings page).

Operator setup (one-time per instance):

    1. Create a Google Cloud project + enable the Business
       Profile APIs (``mybusinessaccountmanagement``,
       ``mybusinessbusinessinformation``, ``mybusiness``).
    2. Create an OAuth 2.0 Client ID (Web application).
    3. Add ``{public_url}/api/gbp/callback`` as an authorized
       redirect URI.
    4. Save the client_id + client_secret via ``PUT /gbp/settings``
       (Settings → GBP → paste creds).
    5. Click Connect Google → complete OAuth → refresh token
       persists on ``db.gbp_settings.tokens``.
    6. First location discovery happens on-demand (``_first_location``).

Live-publish flow (same as ``auto_gbp_from_article``):

    1. Refresh access token if expired.
    2. Discover the tenant's Google Business Location if not
       cached (``accounts/*/locations`` v1 API).
    3. POST ``localPosts`` v4 with summary + optional CTA link.

Content model:

    * ``publish_text(text, link=None, cta_action="LEARN_MORE")``
      → single localPost.  Text is capped by GBP at 1,500 chars.
    * ``publish_image`` — not yet implemented on the router side
      (media upload flow is different).  Deferred to a future pass.
    * ``publish_video``  — same deferral.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

from config import db, logger
from services.social.base import PublishError, SocialAdapter


class GBPAdapter(SocialAdapter):
    """Google Business Profile publisher.  Delegates to the
    already-wired ``routers.gbp`` helpers."""

    platform = "gbp"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        # NOTE: current gbp_settings collection is singleton-scoped
        # (id="config" / id="tokens") — tenant_id isn't yet a key
        # on the row.  When we tenant-scope GBP, add the filter
        # here.  Kept intentionally instance-scoped for now.
        cfg = await db.gbp_settings.find_one({"id": "config"},
                                                 {"_id": 0})
        tok = await db.gbp_settings.find_one({"id": "tokens"},
                                                 {"_id": 0})
        if not cfg or not cfg.get("client_id"):
            return {
                "ok": False,
                "detail": ("Google Business Profile not configured. "
                             "Save your OAuth Client ID + Secret via "
                             "Settings → GBP → paste credentials."),
            }
        if not tok or not tok.get("access_token") \
                or not tok.get("refresh_token"):
            return {
                "ok": False,
                "detail": ("Google Business Profile credentials saved "
                             "but not connected. Click Connect Google on "
                             "the GBP settings page to complete OAuth."),
            }
        return {
            "ok": True,
            "detail": "Connected — GBP publisher ready.",
        }

    def supported_content_types(self) -> Set[str]:
        # localPosts accept text + optional CTA link.  Media
        # (image/video) requires the separate media-upload flow
        # which is deferred.
        return {"text", "link"}

    async def publish_text(self, tenant_id: str, text: str, *,
                                link: Optional[str] = None,
                                cta_action: str = "LEARN_MORE",
                                title: Optional[str] = None,
                                status: Optional[str] = None,
                                article_id: Optional[str] = None,
                                **kwargs: Any) -> Dict[str, Any]:
        # Lazy imports so the router doesn't pull GBP internals at
        # import time.
        from routers.gbp import (
            _access_token, _first_location, _do_publish_post,
        )
        from fastapi import HTTPException

        # Guardrail: GBP caps summaries at 1,500 chars.  Trim
        # deterministically so the caller sees a predictable
        # result rather than a 400 from Google.
        summary = (text or "").strip()
        if len(summary) > 1500:
            summary = summary[:1497].rstrip() + "…"

        try:
            token = await _access_token()
        except HTTPException as e:
            # ``_access_token`` raises 400 when config is missing.
            raise PublishError(400,
                                 f"GBP OAuth not ready: {e.detail}") from e
        except Exception as e:                                    # noqa: BLE001
            raise PublishError(500, f"GBP token refresh failed: {e}") from e

        try:
            location = await _first_location(token)
        except Exception as e:                                    # noqa: BLE001
            raise PublishError(
                500, f"GBP location lookup failed: {e}") from e
        if not location:
            raise PublishError(
                400,
                "GBP account has no locations — link your Google "
                "Business Page to this Google account first.")

        try:
            res = await _do_publish_post(token, location, summary,
                                              link, cta_action)
        except HTTPException as e:
            raise PublishError(e.status_code, str(e.detail)) from e
        except Exception as e:                                    # noqa: BLE001
            logger.exception("[gbp_adapter] publish crash: %s", e)
            raise PublishError(500, f"GBP publish crashed: {e}") from e

        # ``_do_publish_post`` returns the raw Google localPost
        # payload.  Extract the id + searchUrl for our contract.
        name = res.get("name") or ""
        search_url = res.get("searchUrl") or ""
        return {
            "platform_post_id": name,
            "url": search_url,
            "status": "published",
            "raw": {k: res.get(k) for k in ("name", "createTime",
                                                "updateTime", "state")},
        }
