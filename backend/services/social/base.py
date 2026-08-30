"""Social publishing adapter contract · Feb-2026.

Every platform adapter — live or stub — implements the same
``SocialAdapter`` shape so the ``POST /soshie/publish`` fan-out
can iterate over a list of platform keys without caring which are
live vs pending.

Contract:

* :meth:`check_credentials` — ``{ok: bool, detail: str}``. NEVER
  raises. A missing key or expired token returns ``ok=False`` with
  a plain-English detail the UI can render as a toast/badge.
* :meth:`publish_text` / :meth:`publish_image` / :meth:`publish_video`
  — publish one post. Returns ``{platform_post_id, url, status}``.
  Live adapters raise ``PublishError`` on failure.  Stub adapters
  raise ``NotImplementedError`` — the router catches both cleanly
  and records the failure in ``social_posts``.
* :meth:`supported_content_types` — set of ``{"text", "image",
  "video", "link"}`` the platform can accept.  Callers use this
  to render the connect grid or grey out content-type toggles.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Set


class PublishError(Exception):
    """Raised by adapters when a publish attempt fails after
    credentials + payload validation passed.  Carries a status
    code + human-readable detail the router surfaces to the
    frontend."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class SocialAdapter(ABC):
    """Base class every platform adapter implements.

    Subclass responsibilities:
        * Set :attr:`platform` (e.g. ``"facebook"``).
        * Implement :meth:`check_credentials` — must NEVER raise.
        * Implement whichever ``publish_*`` methods the platform
          supports; raise :class:`PublishError` on failure OR
          :class:`NotImplementedError` if the adapter is a stub.
        * Return the set of supported content types from
          :meth:`supported_content_types`.
    """

    #: e.g. ``"facebook"``, ``"wordpress"`` — used as the primary key
    #: on ``social_platform_credentials`` and ``social_posts`` rows.
    platform: str = "abstract"

    @abstractmethod
    async def check_credentials(self, tenant_id: str) -> Dict[str, Any]:
        """Return ``{"ok": bool, "detail": str}``.  MUST NOT raise."""
        raise NotImplementedError

    async def publish_text(self, tenant_id: str, text: str, *,
                                link: Optional[str] = None,
                                **kwargs: Any) -> Dict[str, Any]:
        """Publish a text-only post.  Default: unsupported."""
        raise NotImplementedError(
            f"{self.platform} adapter does not support text posts",
        )

    async def publish_image(self, tenant_id: str, text: str,
                                 image_ref: str,
                                 **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.platform} adapter does not support image posts",
        )

    async def publish_video(self, tenant_id: str, text: str,
                                 video_ref: str,
                                 **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.platform} adapter does not support video posts",
        )

    def supported_content_types(self) -> Set[str]:
        """Return the ``{"text", "image", "video", "link"}`` subset
        the platform accepts.  Default: empty (stub)."""
        return set()
