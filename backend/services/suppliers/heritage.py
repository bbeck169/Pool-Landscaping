"""Phase 54e · Feb-2026 — Heritage Pool Plus Playwright connector.

Uses the shared ``PlaywrightScraperBase`` (Phase 54e) — the entire
scrape logic is inherited. This file only pins the slug + display
name + planned phase + selector dict.
"""
from __future__ import annotations

from services.suppliers._scraper_base import PlaywrightScraperBase
from services.suppliers.heritage_selectors import HERITAGE
from services.suppliers.poolcorp import LoginFailedError, LayoutChangedError  # noqa: F401


class HeritageConnector(PlaywrightScraperBase):
    slug = "heritage"
    display_name = "Heritage Pool Plus"
    planned_phase = "54e"
    SELECTORS = HERITAGE


__all__ = ["HeritageConnector", "LoginFailedError", "LayoutChangedError"]
