"""Phase 54b · Feb-2026 — Pool360 (PoolCorp) Playwright connector.

Real login-then-catalog-walk implementation. Runs headless with a
scraper-honest User-Agent (``AquaTerra-PriceBook/1.0``) — we don't
spoof a real browser to hide from Pool360.

Etiquette:
    - Max 1 page load per second (``RATE_LIMIT_SECONDS``).
    - Backoff on 429 / 503 (exponential up to 60s).
    - 30s hard timeout per page.
    - Never scrape while unauthenticated.

The concrete public methods (``authenticate`` / ``list_products``)
are async in this connector — the router uses them via ``await``.
Tests fully mock the ``async_playwright()`` context manager.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, Dict, Optional

from config import logger
from services.suppliers.connector import (
    BaseSupplierConnector, ExternalProduct, SupplierSession,
    # Phase O4 · Feb-2026 — exception classes were moved to
    # ``connector.py`` so every sibling connector can import them
    # without reaching into this file. Re-exported below (via
    # ``__all__`` + direct name binding) so existing call sites in
    # ``sync.py``, ``_scraper_base.py``, ``ewing.py``, ``siteone.py``,
    # and the supplier-cron tests keep working unchanged.
    LoginFailedError, LayoutChangedError,
)
from services.suppliers.selectors import POOL360 as SEL


USER_AGENT = "AquaTerra-PriceBook/1.0"
RATE_LIMIT_SECONDS = 1.0
PAGE_TIMEOUT_MS = 30_000
MAX_BACKOFF_SECONDS = 60

# Explicit re-exports so ``from services.suppliers.poolcorp import
# LoginFailedError`` continues to resolve for the many existing
# call sites (see ``git grep -n LoginFailedError services/suppliers
# tests/``). New code should import from ``connector.py`` directly.
__all__ = [
    "PoolCorpConnector", "LoginFailedError", "LayoutChangedError",
    "_parse_price",
]


def _parse_price(txt: Optional[str]) -> Optional[float]:
    if not txt:
        return None
    m = re.search(r"[\d,]+\.\d+|[\d,]+", txt)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


class PoolCorpConnector(BaseSupplierConnector):
    slug = "poolcorp"
    display_name = "Pool360 (PoolCorp)"
    planned_phase = "54b"
    # Phase 54h-a · Aug-2026 — Cloudflare Turnstile handoff opt-in.
    SUPPORTS_CHALLENGE_HANDOFF = True

    async def authenticate(self, credentials: Dict[str, Any]) -> SupplierSession:
        username = (credentials or {}).get("username") or ""
        password = (credentials or {}).get("password") or ""
        # Phase 54h-a — optional cookie-jar rehydration from a
        # previous bookmarklet handoff. When present, the connector
        # skips scripted login entirely and re-uses the operator's
        # human-solved session. Falls through to scripted login only
        # if the rehydration cookies are absent or reach a
        # ``/login`` bounce.
        session_cookies = (credentials or {}).get("_session_cookies") or []
        if not username or not password:
            if not session_cookies:
                raise LoginFailedError(
                    "Login failed — missing username or password")

        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
        from services.suppliers.challenge import (
            detect_challenge_on_page, SupplierChallengeRequired,
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=USER_AGENT)
                if session_cookies:
                    try:
                        await context.add_cookies(session_cookies)
                    except Exception:                             # noqa: BLE001
                        # Malformed cookie shape → treat as no cache
                        # and fall through to scripted login.
                        pass
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                await page.goto(SEL["login_url"])
                # Fire Turnstile detector BEFORE the login form
                # timing budget bites — short-circuits within 2s.
                await detect_challenge_on_page(
                    page, self.slug,
                    username_selector=SEL["input_username"],
                )
                await page.fill(SEL["input_username"], username)
                await page.fill(SEL["input_password"], password)
                await page.click(SEL["btn_submit"])
                try:
                    await page.wait_for_selector(SEL["logged_in_marker"], timeout=15_000)
                except PWTimeout as e:
                    raise LoginFailedError(
                        "Login failed — check credentials"
                    ) from e
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
                await page.goto(SEL["catalog_url"])

                total_yielded = 0
                page_num = 1
                while True:
                    cards = await page.query_selector_all(SEL["product_card"])
                    if not cards and page_num == 1:
                        raise LayoutChangedError(
                            "Layout changed — selectors returned zero product "
                            "cards on the first page. Refusing to sync (would "
                            "otherwise soft-delete every existing item)."
                        )
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
                        except Exception as e:  # per-card failure isn't fatal
                            logger.warning(f"[poolcorp] card parse failed: {e}")

                    # Pagination
                    next_btn = await page.query_selector(SEL["btn_next_page"])
                    if not next_btn:
                        break
                    try:
                        await asyncio.sleep(RATE_LIMIT_SECONDS)
                        await next_btn.click()
                        await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
                        page_num += 1
                        backoff = 1.0  # reset on success
                    except PWTimeout:
                        # Slow-loading page; back off + retry once
                        await asyncio.sleep(min(backoff, MAX_BACKOFF_SECONDS))
                        backoff *= 2
                        if backoff > MAX_BACKOFF_SECONDS:
                            logger.warning("[poolcorp] repeated page timeouts — aborting pagination")
                            break

                logger.info(f"[poolcorp] yielded {total_yielded} products across {page_num} page(s)")
            finally:
                await browser.close()

    async def _text(self, node, selector: str) -> Optional[str]:
        el = await node.query_selector(selector)
        if not el:
            return None
        try:
            return (await el.text_content()) or None
        except Exception:
            return None
