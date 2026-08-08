"""Phase 53a · Feb-2026 — Finance services.

Contains EBIT computation + editable snapshot helpers. Kept as a
dedicated package because the CFO / profit-report codepaths already
own domain-specific aggregations and mixing "editable EBIT" into
either would blur ownership.
"""
