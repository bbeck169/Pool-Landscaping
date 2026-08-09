"""Phase 54e · Feb-2026 — ePoolSupply Playwright connector.

Uses the shared ``PlaywrightScraperBase`` (Phase 54e) — see
``heritage.py`` for the same pattern.
"""
from __future__ import annotations

from services.suppliers._scraper_base import PlaywrightScraperBase
from services.suppliers.epoolsupply_selectors import EPOOLSUPPLY
from services.suppliers.poolcorp import LoginFailedError, LayoutChangedError  # noqa: F401


class EPoolSupplyConnector(PlaywrightScraperBase):
    slug = "epoolsupply"
    display_name = "ePoolSupply"
    planned_phase = "54e"
    SELECTORS = EPOOLSUPPLY


__all__ = ["EPoolSupplyConnector", "LoginFailedError", "LayoutChangedError"]
