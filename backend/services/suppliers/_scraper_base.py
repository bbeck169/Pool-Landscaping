"""Phase 54e · Feb-2026 — Shared Playwright scraper base.

Extracted to eliminate the copy-paste-per-supplier pattern introduced
by Phases 54b/c/d. Heritage + ePoolSupply (both 54e) subclass this
directly. Older connectors (poolcorp / siteone / ewing) keep their
own implementations — no behaviour change for those wire-ups, no
risk to their green test suites.

Subclass contract:

    class MyConnector(PlaywrightScraperBase):
        slug          = "myslug"
        display_name  = "My Display Name"
        planned_phase = "54e"
        SELECTORS     = MY_SELECTOR_DICT  # dict from _selectors.py

The base implements ``authenticate`` + ``list_products`` + rate-limit
navigation. Fields the subclass MAY override:
    * ``USER_AGENT`` (default AquaTerra-PriceBook/1.0)
    * ``RATE_LIMIT_SECONDS`` (default 1.0)
    * ``PAGE_TIMEOUT_MS`` (default 30_000)
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


class PlaywrightScraperBase(BaseSupplierConnector):
    USER_AGENT = "AquaTerra-PriceBook/1.0"
    RATE_LIMIT_SECONDS = 1.0
    PAGE_TIMEOUT_MS = 30_000
    SELECTORS: Dict[str, str] = {}

    async def authenticate(self, credentials: Dict[str, Any]) -> SupplierSession:
        username = (credentials or {}).get("username") or ""
        password = (credentials or {}).get("password") or ""
        if not username or not password:
            raise LoginFailedError(
                "Login failed — missing username or password")

        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
        sel = self.SELECTORS

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=self.USER_AGENT)
                page = await context.new_page()
                page.set_default_timeout(self.PAGE_TIMEOUT_MS)
                await page.goto(sel["login_url"])
                await page.fill(sel["input_username"], username)
                await page.fill(sel["input_password"], password)
                await page.click(sel["btn_submit"])
                try:
                    await page.wait_for_selector(
                        sel["logged_in_marker"], timeout=15_000)
                except PWTimeout as e:
                    raise LoginFailedError(
                        "Login failed — check credentials") from e
                cookies = await context.cookies()
                return SupplierSession(
                    supplier_slug=self.slug, credentials_ref="",
                    extra={"cookies": cookies})
            finally:
                await browser.close()

    async def list_products(  # type: ignore[override]
        self, session: SupplierSession, since: Optional[str] = None,
    ) -> AsyncIterator[ExternalProduct]:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
        sel = self.SELECTORS
        cookies = (session.extra or {}).get("cookies") or []
        backoff = 1.0

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=self.USER_AGENT)
                if cookies:
                    await context.add_cookies(cookies)
                page = await context.new_page()
                page.set_default_timeout(self.PAGE_TIMEOUT_MS)
                await self._goto_with_backoff(page, sel["catalog_url"])

                total_yielded = 0
                page_num = 1
                while True:
                    cards = await page.query_selector_all(sel["product_card"])
                    if not cards and page_num == 1:
                        raise LayoutChangedError(
                            "Layout changed — selectors returned zero product "
                            "cards on the first page. Refusing to sync "
                            "(would otherwise soft-delete every existing item).")
                    if not cards:
                        break

                    for card in cards:
                        try:
                            sku_text = await self._text(card, sel["field_sku"])
                            if not sku_text:
                                continue
                            yield ExternalProduct(
                                sku=sku_text.strip(),
                                name=(await self._text(card, sel["field_name"])) or sku_text,
                                cost=_parse_price(await self._text(card, sel["field_cost"])),
                                msrp=_parse_price(await self._text(card, sel["field_msrp"])),
                                category=await self._text(card, sel["field_category"]),
                                uom=await self._text(card, sel["field_uom"]),
                                description=await self._text(card, sel["field_description"]),
                                raw={"page": page_num})
                            total_yielded += 1
                        except Exception as e:
                            logger.warning(f"[{self.slug}] card parse failed: {e}")

                    next_btn = await page.query_selector(sel["btn_next_page"])
                    if not next_btn:
                        break
                    try:
                        await asyncio.sleep(self.RATE_LIMIT_SECONDS)
                        await next_btn.click()
                        await page.wait_for_load_state(
                            "networkidle", timeout=self.PAGE_TIMEOUT_MS)
                        page_num += 1
                        backoff = 1.0
                    except PWTimeout:
                        await asyncio.sleep(min(backoff, MAX_BACKOFF_SECONDS))
                        backoff = _next_backoff(backoff)
                        if backoff >= MAX_BACKOFF_SECONDS:
                            logger.warning(
                                f"[{self.slug}] repeated page timeouts — "
                                f"aborting pagination")
                            break

                logger.info(
                    f"[{self.slug}] yielded {total_yielded} products across "
                    f"{page_num} page(s)")
            finally:
                await browser.close()

    async def _goto_with_backoff(self, page, url: str) -> None:
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
                    f"[{self.slug}] rate-limited on {url} after {attempts} "
                    f"attempt(s) — giving up (status={status})")
                return
            logger.info(
                f"[{self.slug}] rate-limited (status={status}); sleeping "
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
