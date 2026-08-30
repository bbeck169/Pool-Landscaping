"""Phase 54e · Feb-2026 — Heritage Pool Plus Playwright connector.

Uses the shared ``PlaywrightScraperBase`` (Phase 54e) — the entire
scrape logic is inherited. This file only pins the slug + display
name + planned phase + selector dict.
"""
from __future__ import annotations

from services.suppliers._scraper_base import PlaywrightScraperBase
from services.suppliers.heritage_selectors import HERITAGE
# Phase O4 · Feb-2026 — exception classes now live on ``connector.py``
# so Heritage no longer has to reach into ``poolcorp.py`` just to
# grab them. Re-exported below via ``__all__`` for backward compat.
from services.suppliers.connector import LoginFailedError, LayoutChangedError  # noqa: F401


class HeritageConnector(PlaywrightScraperBase):
    slug = "heritage"
    display_name = "Heritage Pool Plus"
    planned_phase = "54e"
    SELECTORS = HERITAGE
    # Phase 54h-a · Aug-2026 — Cloudflare Turnstile handoff opt-in.
    SUPPORTS_CHALLENGE_HANDOFF = True


__all__ = ["HeritageConnector", "LoginFailedError", "LayoutChangedError"]
