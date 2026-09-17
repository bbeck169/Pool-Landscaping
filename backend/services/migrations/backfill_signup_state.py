"""Feb-2026 · Business Signup SP1 — backfill migration.

Every tenant that predates self-serve signup (i.e. every tenant
missing the ``email_verified`` field) is stamped as verified with
onboarding complete so the frontend guards (SP2) never trap an
existing admin inside the wizard.

Idempotent — the migration selects on ``email_verified NOT EXISTS``.
A second run finds nothing to update and returns
``{"matched": 0, "modified": 0}``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger("backfill_signup_state")


async def run_backfill_signup_state(db: Any) -> Dict[str, int]:
    """Backfill ``email_verified`` + ``onboarding_completed_at`` +
    ``onboarding_step`` on every pre-signup tenant."""
    now_iso = datetime.now(timezone.utc).isoformat()
    query = {"email_verified": {"$exists": False}}
    update = {
        "$set": {
            "email_verified":          True,
            "email_verified_at":       now_iso,
            "onboarding_step":         5,   # 5 == complete
            "onboarding_completed_at": now_iso,
            "backfilled_signup_state_at": now_iso,
        }
    }
    result = await db.tenants.update_many(query, update)
    logger.info(
        "[backfill_signup_state] matched=%s modified=%s",
        result.matched_count, result.modified_count,
    )
    return {
        "matched":  result.matched_count,
        "modified": result.modified_count,
    }
