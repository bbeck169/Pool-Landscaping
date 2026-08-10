"""Phase 54d · Feb-2026 — Ewing Irrigation Playwright connector.

Same guardrails as Pool360 (54b) + SiteOne (54c):

* Headless Chromium, UA ``AquaTerra-PriceBook/1.0``.
* Max 1 page load per second.
* Exponential backoff on 429 / 503 up to 60 s.
* 30 s hard timeout per page.
* Never scrape while unauthenticated.
* Zero-item first-page response raises ``LayoutChangedError`` — the
  sync aborts rather than soft-deleting every existing item.

Reuses ``LoginFailedError`` / ``LayoutChangedError`` from ``poolcorp``
and ``_next_backoff`` / ``RATE_LIMIT_HTTP_STATUSES`` from ``siteone``
(both are single-source-of-truth in their respective modules — this
connector is a straight mirror).
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, Optional

from config import logger
from services.suppliers.connector import (
    BaseSupplierConnector, ExternalProduct, SupplierSession,
)
from services.suppliers.poolcorp import (
    LoginFailedError, LayoutChangedError, _parse_price,
)
from services.suppliers.siteone import (
    _next_backoff, RATE_LIMIT_HTTP_STATUSES, MAX_BACKOFF_SECONDS,
)
from services.suppliers.ewing_selectors import EWING as SEL


USER_AGENT = "AquaTerra-PriceBook/1.0"
RATE_LIMIT_SECONDS = 1.0
PAGE_TIMEOUT_MS = 30_000


class EwingConnector(BaseSupplierConnector):
    slug = "ewing"
    display_name = "Ewing Irrigation"
    planned_phase = "54d"
    # Phase 54h-a · Aug-2026 — Ewing stays on scripted flow. No
    # Turnstile handoff for this supplier.
    SUPPORTS_CHALLENGE_HANDOFF = False

    async def authenticate(self, credentials: Dict[str, Any]) -> SupplierSession:
        username = (credentials or {}).get("username") or ""
        password = (credentials or {}).get("password") or ""
        if not username or not password:
            raise LoginFailedError(
                "Login failed — missing username or password")

        from playwright.async_api import async_playwright, TimeoutError as PWTimeout

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=USER_AGENT)
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                await page.goto(SEL["login_url"])
                await page.fill(SEL["input_username"], username)
                await page.fill(SEL["input_password"], password)
                await page.click(SEL["btn_submit"])
                try:
                    await page.wait_for_selector(
                        SEL["logged_in_marker"], timeout=15_000)
                except PWTimeout as e:
                    raise LoginFailedError(
                        "Login failed — check credentials") from e
                cookies = await context.cookies()
                return SupplierSession(
                    supplier_slug=self.slug,
                    credentials_ref="",
                    extra={"cookies": cookies},
                )
            finally:
                await browser.close()

    async def list_products(  # type: ignore[override]
        self,
        session: SupplierSession,
        since: Optional[str] = None,
    ) -> AsyncIterator[ExternalProduct]:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout

        cookies = (session.extra or {}).get("cookies") or []
        backoff = 1.0

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=USER_AGENT)
                if cookies:
                    await context.add_cookies(cookies)
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)

                await self._goto_with_backoff(page, SEL["catalog_url"])

                total_yielded = 0
                page_num = 1
                while True:
                    cards = await page.query_selector_all(SEL["product_card"])
                    if not cards and page_num == 1:
                        raise LayoutChangedError(
                            "Layout changed — selectors returned zero product "
                            "cards on the first page. Refusing to sync "
                            "(would otherwise soft-delete every existing item).")
                    if not cards:
                        break

                    for card in cards:
                        try:
                            sku_text = await self._text(card, SEL["field_sku"])
                            if not sku_text:
                                continue
                            yield ExternalProduct(
                                sku=sku_text.strip(),
                                name=(await self._text(card, SEL["field_name"])) or sku_text,
                                cost=_parse_price(await self._text(card, SEL["field_cost"])),
                                msrp=_parse_price(await self._text(card, SEL["field_msrp"])),
                                category=await self._text(card, SEL["field_category"]),
                                uom=await self._text(card, SEL["field_uom"]),
                                description=await self._text(card, SEL["field_description"]),
                                raw={"page": page_num},
                            )
                            total_yielded += 1
                        except Exception as e:
                            logger.warning(f"[ewing] card parse failed: {e}")

                    next_btn = await page.query_selector(SEL["btn_next_page"])
                    if not next_btn:
                        break
                    try:
                        await asyncio.sleep(RATE_LIMIT_SECONDS)
                        await next_btn.click()
                        await page.wait_for_load_state(
                            "networkidle", timeout=PAGE_TIMEOUT_MS)
                        page_num += 1
                        backoff = 1.0
                    except PWTimeout:
                        await asyncio.sleep(min(backoff, MAX_BACKOFF_SECONDS))
                        backoff = _next_backoff(backoff)
                        if backoff >= MAX_BACKOFF_SECONDS:
                            logger.warning(
                                "[ewing] repeated page timeouts — "
                                "aborting pagination")
                            break

                logger.info(
                    f"[ewing] yielded {total_yielded} products across "
                    f"{page_num} page(s)")
            finally:
                await browser.close()

    async def _goto_with_backoff(self, page, url: str) -> None:
        """Rate-limit-aware navigation. See siteone.py for rationale."""
        backoff = 1.0
        attempts = 0
        while True:
            attempts += 1
            resp = await page.goto(url)
            status = getattr(resp, "status", 200) if resp is not None else 200
            if status not in RATE_LIMIT_HTTP_STATUSES:
                return
            if backoff >= MAX_BACKOFF_SECONDS:
                logger.warning(
                    f"[ewing] rate-limited on {url} after {attempts} "
                    f"attempt(s) — giving up (status={status})")
                return
            logger.info(
                f"[ewing] rate-limited (status={status}); sleeping "
                f"{backoff:.1f}s before retry {attempts + 1}")
            await asyncio.sleep(backoff)
            backoff = _next_backoff(backoff)

    async def _text(self, node, selector: str) -> Optional[str]:
        el = await node.query_selector(selector)
        if not el:
            return None
        try:
            return (await el.text_content()) or None
        except Exception:
            return None


__all__ = [
    "EwingConnector",
    "LoginFailedError",
    "LayoutChangedError",
    "RATE_LIMIT_HTTP_STATUSES",
    "MAX_BACKOFF_SECONDS",
]
