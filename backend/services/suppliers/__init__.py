"""Phase 54a · Feb-2026 — Supplier integration package (skeleton).

Wholesale-pricebook import for Pool360 / SiteOne / Ewing / Heritage
Pool Plus. Phase 54a ships the data model + connector protocol +
credentials plumbing only — the four concrete connectors all raise
``NotImplementedError`` until Phase 54b/c/d/e wire them up.

No network calls, no scraping in 54a.
"""
