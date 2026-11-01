"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — invoice reminder (dunning).

Upserts the canonical ``marketing_templates`` row keyed by
``code="invoice_reminder_email"``.  Consumed by
:func:`emailer.send_invoice_reminder_email` (invoice-only refusal
guard preserved — this path never fires for estimate/quote docs).

The pre-migration builder ``_reminder_html`` already routes body
copy through the D6 ``t_email_body`` catalog for locales other than
English; the DB body seeded here is used ONLY when the recipient's
locale resolves to ``en``.  Non-English recipients continue to see
the i18n copy unchanged (decision (c)).

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_invoice_reminder_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_invoice_reminder_template"
TEMPLATE_CODE = "invoice_reminder_email"


SUBJECT_DEFAULT = "Payment reminder — Invoice {{INVOICE_NUMBER}}"

BODY_DEFAULT = (
    '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
    '<h2>Friendly reminder</h2>'
    '<p>Hi {{CUSTOMER_NAME}},</p>'
    '<p>Invoice <b>{{INVOICE_NUMBER}}</b> has an outstanding '
    'balance of <b>${{INVOICE_BALANCE}}</b> due '
    '{{INVOICE_DUE_DATE}}.</p>'
    '<p><a href="{{PAY_LINK}}" '
    'style="background:#DC2626;color:#fff;padding:12px 20px;'
    'border-radius:8px;text-decoration:none;display:inline-block;'
    'font-size:22px;font-weight:700;">View Invoice</a></p>'
    '<p>Thanks — the {{COMPANY_NAME}} team</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "CUSTOMER_NAME", "INVOICE_NUMBER", "INVOICE_BALANCE",
    "INVOICE_DUE_DATE", "DAYS_OVERDUE", "PAY_LINK", "COMPANY_NAME",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Invoice — Payment Reminder",
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
