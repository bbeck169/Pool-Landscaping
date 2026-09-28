"""MTH-A · Feb-2026 — Index bootstrap for the AI rule-engine collections.

Called at server startup (see ``server.py`` — same block as
``ensure_fleet_indexes``).  Idempotent — reruns are no-ops per
PyMongo semantics.

Collections:

* ``tenant_ai_rules``  — unique index on ``tenant_id``.
* ``tenant_ai_rules_revisions`` — non-unique index on
  ``(tenant_id, revision_number desc)`` for the newest-first list
  endpoint.
* ``platform_ai_rule_defaults`` — unique index on ``key`` (the
  singleton sentinel).
"""
from __future__ import annotations

from typing import Any

from pymongo import IndexModel, ASCENDING, DESCENDING


async def ensure_tenant_ai_rules_indexes(db: Any) -> None:
    """Create (or no-op) the three indexes listed above.

    Called via ``asyncio.gather`` at boot alongside the fleet
    indexes; failures are swallowed by the caller so a bad index
    doesn't wedge boot — but the caller ALSO logs the exception so
    ops sees the problem on the health surface.
    """
    await db.tenant_ai_rules.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING)],
            name="tenant_ai_rules_tenant_id_unique",
            unique=True,
            background=True,
        ),
        IndexModel(
            [("last_updated_at", DESCENDING)],
            name="tenant_ai_rules_last_updated_at_bg",
            background=True,
        ),
    ])
    await db.tenant_ai_rules_revisions.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING),
             ("revision_number", DESCENDING)],
            name="tenant_ai_rules_revisions_tenant_rev_bg",
            background=True,
        ),
    ])
    await db.platform_ai_rule_defaults.create_indexes([
        IndexModel(
            [("key", ASCENDING)],
            name="platform_ai_rule_defaults_key_unique",
            unique=True,
            background=True,
        ),
    ])
