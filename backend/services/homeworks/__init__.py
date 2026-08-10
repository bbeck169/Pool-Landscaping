"""Phase 55 · Aug-2026 — Homeworks (Copilot CRM) importer services.

Everything under this package is one-shot migration code. After the
tenant's initial import lands + is committed, this module can be
retired without impact to the running app.

Sub-modules:
  * ``copilot_scraper`` — EXPERIMENTAL Playwright scraper against
    ``secure.copilotcrm.com``. Selectors are placeholders until the
    live smoke test.
  * ``mapping`` — Homeworks-shape → AquaTerra-shape field mappers
    for customers + properties.
  * ``dedupe`` — email + phone normalization + tenant-scoped
    dedupe engine that classifies each scraped row as
    ``new`` / ``matched`` / ``conflict``.
"""
