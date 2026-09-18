"""Sprint 3c · Feb-2026 — Feature entitlement subsystem.

Public surface:
    * :mod:`registry` — hardcoded feature catalogue + Stripe price
      resolution.
    * :mod:`check`    — ``has_feature(tenant_id, feature_key)``
      access predicate + ``ai_analytics_effective_gate`` for the
      layered org-toggle case.
    * :mod:`stripe_ops` — sandbox-safe Stripe subscription-item
      wrappers.
"""
