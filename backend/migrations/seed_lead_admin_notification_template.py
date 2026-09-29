"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — canonical lead-admin
notification (LD2 invoice-style template).

Upserts the canonical ``marketing_templates`` row keyed by
``code="lead_admin_notification_email"``.  Consumed by
:func:`services.lead_admin_notifications.dispatch_admin_lead_email`.

Passthrough-migration strategy
------------------------------
The pre-migration builder ``_compose_email_html`` composes a highly
dynamic HTML template — a full-width brand-color header with the
tenant's palette, structured data sections that hide when their
rows are empty, and a CTA button styled with the tenant's accent
colour.  Migrating every fragment to an independent merge tag
would double the maintenance surface without adding tenant-editing
value.

Instead, the seed body defaults to a single ``{{LEAD_ADMIN_INNER_HTML}}``
passthrough — the Python builder still runs and stashes its output
into ``ctx["lead_admin_inner_html"]``.  Tenants who want additional
chrome (e.g. a compliance footer, an intake-form-specific banner)
can edit the DB row body to wrap ``{{LEAD_ADMIN_INNER_HTML}}`` in
that chrome.  The pre-rendered inner HTML plus the tenant's chrome
compose the final outbound email.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_lead_admin_notification_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_lead_admin_notification_template"
TEMPLATE_CODE = "lead_admin_notification_email"


# ``dispatch_admin_lead_email`` composes the subject inline via
# ``_compose_subject`` — the seed subject is informational only, the
# runtime path continues to build the LD2 subject shape.
SUBJECT_DEFAULT = "New lead — {{LEAD_NAME}}"

BODY_DEFAULT = "{{LEAD_ADMIN_INNER_HTML}}"

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "LEAD_ADMIN_INNER_HTML", "LEAD_NAME", "COMPANY_NAME",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Lead — Admin Notification (LD2 canonical)",
        "category": "lead",
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
