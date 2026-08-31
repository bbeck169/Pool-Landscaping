"""Feb-2026 · Phase F3 · startup namespace.

Hosts prophylactic guardrails that run at process boot. Currently
holds the data-integrity check (``integrity_check.py``); future
guardrails (schema-drift detectors, feature-flag validators, ...)
belong here so the boot pipeline has one obvious home.
"""
