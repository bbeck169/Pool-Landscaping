"""Soshie AI-Employee expansion package · Feb-2026.

Ships alongside the code-review triage completed same-week. Two
sub-modules to start:

* :mod:`services.soshie.seo_context` — pulls a compact, <2 KB
  snapshot of the tenant's SEO Suite state (latest scan, top AEO
  gaps, rank movers, top brand-mention topics, recent keyword
  ideation) so Soshie's outputs are grounded in real signals.
* :mod:`services.soshie.brand_ingest` — shallow crawl of the
  tenant's own website (home + up to 12 internal pages) and
  distills bullets into ``brand_brain.talking_points``. Append-
  only, admin-editable, dedup-safe.
* :mod:`services.soshie.moderation` — regex-only content-safety
  gate (P1). The LLM verdict layer lands in Phase 9.

Non-goals for P1:
    * Real social publishing (WordPress-only in P2).
    * LLM moderation (P9).
    * Any of the P3-P8 platform adapters.
"""
