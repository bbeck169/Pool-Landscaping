"""Phase 54h-a · Aug-2026 — Turnstile challenge detection.

Runs immediately after ``page.goto(login_url)`` on every connector
that opts into the handoff flow (``SUPPORTS_CHALLENGE_HANDOFF = True``).
Detects a Cloudflare Turnstile / captcha wall via THREE signals so
we short-circuit before wasting the login-page 30s timeout:

  1. ``page.url`` contains ``challenges.cloudflare.com``.
  2. DOM includes ``iframe[src*="challenges.cloudflare.com"]``,
     ``.cf-turnstile``, or ``[data-sitekey]``.
  3. The username input isn't visible within 2s (scripted login can't
     even reach the form).

On detection, ``SupplierChallengeRequired`` is raised — NOT
log-and-swallowed. The router at ``POST /test-connection`` maps
this exception into a friendly ``{ok: false, challenge_required:
true, challenge_id, supplier_slug, ttl_hint_minutes: 30}`` payload
the frontend uses to open the handoff modal in 54h-b.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


class SupplierChallengeRequired(Exception):
    """Signals the login page is fronted by a human-required
    Turnstile / captcha and the operator must complete it in their
    own browser (bookmarklet flow, Phase 54h-b)."""

    def __init__(
        self,
        supplier_slug: str,
        challenge_url: str,
        screenshot_url: Optional[str] = None,
    ):
        super().__init__(
            f"Supplier '{supplier_slug}' login is behind a "
            "Turnstile challenge — human handoff required.",
        )
        self.supplier_slug = supplier_slug
        self.challenge_url = challenge_url
        self.screenshot_url = screenshot_url
        self.challenge_id = uuid.uuid4().hex


_CHALLENGE_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    ".cf-turnstile",
    "[data-sitekey]",
)


async def detect_challenge_on_page(
    page: Any,
    supplier_slug: str,
    username_selector: Optional[str] = None,
    visibility_cap_ms: int = 2_000,
) -> None:
    """Inspect ``page`` for a Turnstile challenge. Raise
    ``SupplierChallengeRequired`` on any positive signal.

    Kept operator-callable + fully async so it works inside every
    connector's existing ``async with async_playwright()`` block.

    ``page`` is intentionally typed as ``Any`` — Playwright's
    ``Page`` type isn't importable at module scope without pulling
    the whole runtime in for test envs that stub Playwright.
    """
    # Signal 1: URL redirect to the challenge host.
    url = ""
    try:
        url = getattr(page, "url", "") or ""
    except Exception:                                             # noqa: BLE001
        url = ""
    if "challenges.cloudflare.com" in url:
        raise SupplierChallengeRequired(supplier_slug, url)

    # Signal 2: challenge DOM markers.
    for sel in _CHALLENGE_SELECTORS:
        try:
            el = await page.query_selector(sel)
        except Exception:                                         # noqa: BLE001
            el = None
        if el:
            raise SupplierChallengeRequired(supplier_slug, url or sel)

    # Signal 3: username input isn't visible fast enough → login form
    # was replaced by a challenge shell. Bounded so a slow-but-honest
    # login page (heritage on a bad day) doesn't false-positive.
    if username_selector:
        try:
            await page.wait_for_selector(
                username_selector, state="visible",
                timeout=visibility_cap_ms,
            )
        except Exception:                                         # noqa: BLE001
            raise SupplierChallengeRequired(supplier_slug, url or username_selector)
