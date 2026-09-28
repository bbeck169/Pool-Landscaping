"""MTH-A · Feb-2026 — Per-tenant AI rule engine.

Public sub-modules (deliberately tiny — keeps FE + tests + adapters
easy to reason about):

* :mod:`services.tenant_ai_rules.schema`     — action inventory,
  default rules, validation, size guard.
* :mod:`services.tenant_ai_rules.store`      — DB accessors (get /
  save / reset / revert / revisions), lazy-init.
* :mod:`services.tenant_ai_rules.resolver`   — tenant overrides ∪
  platform defaults → ``ResolvedRules`` + ``override_map``.
* :mod:`services.tenant_ai_rules.cache`      — 30-sec in-process
  TTL cache, save-invalidation hooks.
* :mod:`services.tenant_ai_rules.gate`       — ``resolve_ai_send_gate``,
  working-hours + master-switch + per-employee toggle.
* :mod:`services.tenant_ai_rules.indexes`    — index bootstrap.

FE (MTH-B), employee-prompt integration (MTH-C) and
"test-this-rule" flow (MTH-D) are separate phases.
"""
from services.tenant_ai_rules.schema import (
    RULE_CATEGORIES,
    ACTION_INVENTORY,
    EMPLOYEE_KEYS,
    MAX_DOC_SIZE_BYTES,
    MIN_REASON_LEN,
    default_rules_doc,
    validate_category_payload,
)

__all__ = [
    "RULE_CATEGORIES",
    "ACTION_INVENTORY",
    "EMPLOYEE_KEYS",
    "MAX_DOC_SIZE_BYTES",
    "MIN_REASON_LEN",
    "default_rules_doc",
    "validate_category_payload",
]
