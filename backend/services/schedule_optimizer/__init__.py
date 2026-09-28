"""SO-A · Feb-2026 — AI Schedule Optimizer service package.

Split modules:
    ``detour``   — per-tech route + insertion cost math (no I/O).
    ``origin``   — tech-origin cascade (GPS ping → first job → warn).
    ``persona``  — DISPATCH plain-English synthesis + tone shaping.
    ``endpoint`` — top-level orchestrator called by the router.
"""
