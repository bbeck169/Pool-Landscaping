"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — equipment tracker
weekly customer reminder.

Upserts the canonical ``marketing_templates`` row keyed by
``code="equipment_tracker_weekly_reminder_email"``.  Consumed by
:func:`services.equipment_trackers_cron._dispatch_customer_reminders`
when the weekly cron fans out reminders for equipment coming due /
past due for cleaning.

The pre-migration body was a module-level constant
(``_REMINDER_EMAIL_TEMPLATE``) that already used the double-brace
merge-tag syntax — the migration re-hosts it as an editable DB row.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_equipment_tracker_weekly_reminder_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_equipment_tracker_weekly_reminder_template"
TEMPLATE_CODE = "equipment_tracker_weekly_reminder_email"


# Subject stays composed inline (``f"Your {EQUIPMENT_TYPE} cleaning
# is due"``) — the runtime path renders it through
# ``services.marketing.merge_tags.render_template``, so this seed
# subject is used as the informational default.
SUBJECT_DEFAULT = "Your {{EQUIPMENT_TYPE}} cleaning is due"

BODY_DEFAULT = (
    "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
    "<p>Your {{EQUIPMENT_TYPE}} is due for its next cleaning on "
    "<strong>{{EQUIPMENT_DUE_DATE}}</strong> "
    "(last cleaned {{EQUIPMENT_LAST_CLEANED_DATE}}, cadence every "
    "{{EQUIPMENT_INTERVAL_MONTHS}} months).</p>"
    "<p>We'll be in touch to confirm a service date. Reply to this "
    "email if you'd like to schedule right away.</p>"
    "<p>— The {{COMPANY_NAME}} team</p>"
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "CUSTOMER_FIRST_NAME", "EQUIPMENT_TYPE", "EQUIPMENT_DUE_DATE",
    "EQUIPMENT_LAST_CLEANED_DATE", "EQUIPMENT_INTERVAL_MONTHS",
    "COMPANY_NAME",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Equipment — Weekly Reminder (customer)",
        "category": "equipment",
        "channel": "email",
        "kind": "transactional",
        "subject": SUBJECT_DEFAULT,
        "body": BODY_DEFAULT,
        "text_body": TEXT_DEFAULT,
        "merge_tags": MERGE_TAGS,
        "is_system": True,
        "is_default": True,
        "editable": True,
        "created_at": now,
        "updated_at": now,
    }


async def run() -> dict:
    result = await db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE},
        {"$setOnInsert": _seed_row_setoninsert()},
        upsert=True,
    )
    return {"inserted": bool(result.upserted_id), "code": TEMPLATE_CODE}


if __name__ == "__main__":
    summary = asyncio.run(run())
    print(f"[{MIGRATION_NAME}] {summary}")
