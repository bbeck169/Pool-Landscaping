"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — estimate reminder.

Upserts the canonical ``marketing_templates`` row keyed by
``code="estimate_reminder_email"``.  Consumed by
:func:`emailer.send_estimate_reminder_email` (estimate/quote-only
refusal guard preserved).

Fundamentally different from the invoice reminder — no "balance"
copy, CTA lands on the magic-link viewer.  Non-English recipients
keep the D6 i18n path unchanged (decision (c)).

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_estimate_reminder_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_estimate_reminder_template"
TEMPLATE_CODE = "estimate_reminder_email"


SUBJECT_DEFAULT = "Your estimate from {{COMPANY_NAME}} is waiting"

BODY_DEFAULT = (
    '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
    '<h2>{{ESTIMATE_NUMBER}} is ready for review</h2>'
    '<p>Hi {{CUSTOMER_NAME}},</p>'
    '<p>Your estimate from {{COMPANY_NAME}} totalling '
    '<b>${{ESTIMATE_TOTAL}}</b> is ready to review. Please open it '
    'to approve, request changes, or decline. This link is valid '
    'until <b>{{ESTIMATE_EXPIRES}}</b>.</p>'
    '<p><a href="{{ACCEPT_LINK}}" '
    'style="background:#0891b2;color:#fff;padding:12px 20px;'
    'border-radius:8px;text-decoration:none;display:inline-block;'
    'font-weight:600;">Review estimate</a></p>'
    '<p style="color:#64748b;font-size:12px;margin-top:24px;">'
    'Reply to this email if you have any questions — we read every '
    'message.</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "CUSTOMER_NAME", "COMPANY_NAME", "ESTIMATE_NUMBER",
    "ESTIMATE_TOTAL", "ESTIMATE_EXPIRES", "ACCEPT_LINK",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Estimate — Review Reminder",
        "category": "finance",
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
