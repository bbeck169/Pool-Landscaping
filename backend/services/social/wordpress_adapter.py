"""WordPress publisher adapter · Feb-2026 · P2.

Thin wrapper around the already-live ``_publish_to_wp`` helper in
``routers/seo.py``.  We deliberately DO NOT duplicate the httpx
POST logic — the seo router owns the canonical WP publish path
(including the auto-GBP hook + article status stamp).  This
adapter simply reshapes the input/output so it fits the
:class:`SocialAdapter` contract.

Operator setup already complete for this preview environment:
    * ``.env`` has ``WORDPRESS_URL``, ``WORDPRESS_USERNAME``,
      ``WORDPRESS_APP_PASSWORD``.
    * Target site: ``www.poolandlandscapingofvistancia.com``.
    * Auto-publish flag: ``WORDPRESS_AUTO_PUBLISH=false``
      (Soshie always drafts, admins publish).

Because the seo router's ``_publish_to_wp`` requires a
``seo_articles`` row shape, this adapter accepts either
``article_id`` (existing row) OR raw text — for raw text we
insert a minimal ephemeral ``seo_articles`` row so the existing
publisher stays the single source of truth.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Set

from config import db, logger
from utils import new_id, now_iso
from services.social.base import SocialAdapter, PublishError


class WordPressAdapter(SocialAdapter):
    """Publishes to the tenant's connected WordPress site via
    the existing seo-router ``_publish_to_wp`` helper."""

    platform = "wordpress"

    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        # Reuse the seo-router's settings-loader — accounts for
        # both the per-tenant ``seo_settings`` row AND the env
        # fallback.  Never raises.
        try:
            from routers.seo import _get_wp_settings
            s = await _get_wp_settings(tenant_id)
        except Exception as e:                                    # noqa: BLE001
            logger.warning("[wp_adapter] settings load failed: %s", e)
            return {"ok": False,
                     "detail": f"Could not load WordPress settings: {e}"}
        if not s:
            return {"ok": False,
                     "detail": "WordPress is not configured for this "
                                 "tenant. Set WORDPRESS_URL / _USERNAME / "
                                 "_APP_PASSWORD in the env or connect it "
                                 "from the SEO Suite → Connect tab."}
        missing = [k for k in ("url", "username", "app_password")
                    if not s.get(k)]
        if missing:
            return {"ok": False,
                     "detail": (
                         "WordPress config incomplete — missing: "
                         + ", ".join(missing))}
        return {"ok": True,
                 "detail": f"Connected to {s['url']} as {s['username']}"}

    def supported_content_types(self) -> Set[str]:
        # WP posts are HTML — text, links, images (via HTML), no
        # native video primitive on the REST API side.
        return {"text", "link", "image"}

    async def publish_text(self, tenant_id: str, text: str, *,
                                link: Optional[str] = None,
                                title: Optional[str] = None,
                                status: str = "draft",
                                article_id: Optional[str] = None,
                                **kwargs: Any) -> Dict[str, Any]:
        """Publish (or draft) a WordPress post.

        Two entry paths:

        * ``article_id`` — publishes an existing ``seo_articles``
          row.  Reuses whatever the article's editor produced.
        * raw ``text``   — writes a minimal ephemeral ``seo_articles``
          row so the canonical publisher can consume it, then
          publishes.  The ephemeral row survives (visible in the
          SEO Suite → Articles list) so admins can edit + republish
          without re-drafting.
        """
        from routers.seo import _publish_to_wp, WpError

        if article_id:
            art = await db.seo_articles.find_one(
                {"id": article_id, "tenant_id": tenant_id}, {"_id": 0})
            if not art:
                raise PublishError(
                    404, f"seo_articles/{article_id} not found")
        else:
            # Ephemeral-but-persistent bootstrap row so the existing
            # publisher can consume + stamp the WP result on it.
            art_id = new_id()
            title_val = (title or "").strip() or (text[:80] or "Untitled")
            art = {
                "id": art_id,
                "tenant_id": tenant_id,
                "title": title_val,
                "slug": _slugify(title_val),
                "outline": [],
                "body_html": _wrap_text_as_html(text, link=link),
                "meta_description": (text[:150]).strip(),
                "faqs": [],
                "status": "draft",
                "source": "soshie",
                "created_at": now_iso(),
            }
            await db.seo_articles.insert_one(dict(art))

        # Normalize status — ``_publish_to_wp`` accepts only
        # "draft" or "publish".
        wp_status = "publish" if status == "publish" else "draft"
        try:
            res = await _publish_to_wp(art, wp_status)
        except WpError as e:
            raise PublishError(e.status, e.detail) from e
        except Exception as e:                                    # noqa: BLE001
            raise PublishError(
                500, f"WordPress publisher raised: {e}") from e
        return {
            "platform_post_id": str(res.get("wp_post_id") or ""),
            "url": res.get("link") or "",
            "status": res.get("wp_status") or wp_status,
            "article_id": art["id"],
        }


def _slugify(s: str) -> str:
    """Very small slugifier — matches the SEO router's pattern
    without importing it (module boundary hygiene)."""
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")[:80] or "post"


def _wrap_text_as_html(text: str, *, link: Optional[str]) -> str:
    """Convert a raw Soshie-drafted string into WP-ready HTML.
    Paragraph-splits on blank lines and appends an optional CTA
    link at the tail."""
    paras = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    body = "".join(f"<p>{p}</p>\n" for p in paras) or f"<p>{text}</p>"
    if link:
        body += (f'\n<p><a href="{link}" '
                    f'rel="noopener">Read more →</a></p>\n')
    return body
