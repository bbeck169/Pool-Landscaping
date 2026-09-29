"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — lead thank-you auto-reply
(out-of-state).

Upserts the canonical ``marketing_templates`` row keyed by
``code="lead_thank_you_reply_email"``.  Consumed by
:func:`services.leads_side_effects._fire_customer_reject_reply`
when it composes the "Thanks for reaching out — unfortunately we
don't currently service your area" auto-reply email a lead
receives after landing on an out-of-state address.

The pre-migration builder was hardcoded to
``"Pool & Landscaping of Vistancia"``; the seed body uses
``{{COMPANY_NAME}}`` so the auto-reply signs off correctly for
any tenant.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_lead_thank_you_reply_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_lead_thank_you_reply_template"
TEMPLATE_CODE = "lead_thank_you_reply_email"


SUBJECT_DEFAULT = "Thanks for reaching out"

BODY_DEFAULT = (
    '<div style="font-family:-apple-system,\'Inter\',sans-serif;'
    'color:#0F172A;max-width:560px;margin:0 auto;padding:24px;'
    'line-height:1.55;">'
    '<p>Hi {{RECIPIENT_NAME}},</p>'
    '<p>Thanks for reaching out — unfortunately we don\'t currently '
    "service your area ({{REJECT_STATE}}). We'll keep your info on "
    'file if that changes.</p>'
    '<p>— {{COMPANY_NAME}} Team</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "RECIPIENT_NAME", "REJECT_STATE", "COMPANY_NAME",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Lead — Thank-you Reply (out-of-state)",
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
