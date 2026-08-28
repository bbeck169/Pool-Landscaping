"""Backlog #iv · Feb-2026 — Unified notification cleanup helpers.

Two-layer defense against duplicate + misrouted outbound notifications:

  * :mod:`dispatch_guard` — insert-then-send idempotency floor
    (compound unique index on ``notification_dispatch_log``).
  * :mod:`deny_list` — strip admin-owned / tenant-owned recipients
    from customer-facing send lists before dispatch.
  * :mod:`scheduler_lease` — Mongo advisory lease so at most one
    process fires a given scheduled tick even when N replicas run
    the scheduler.
"""
