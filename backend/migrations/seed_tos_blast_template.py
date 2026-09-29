"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — ToS blast.

Upserts the canonical ``marketing_templates`` row keyed by
``code="tos_blast_email"``.  Consumed by
:func:`routers.tos_multi._blast_one_customer` when an admin
publishes an updated Terms of Service document and the async blast
job fans out per-customer email notifications.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_tos_blast_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_tos_blast_template"
TEMPLATE_CODE = "tos_blast_email"


SUBJECT_DEFAULT = "Updated Terms of Service from {{COMPANY_NAME}}"

BODY_DEFAULT = (
    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="100%" style="border-collapse:collapse;'
    'background:#F1F5F9;">'
    '<tr><td align="center" style="padding:24px 12px;">'
    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="640" style="border-collapse:collapse;'
    'max-width:640px;font-family:Inter,Arial,sans-serif;color:#0F172A;">'
    '<tr><td>'

    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="100%" style="border-collapse:collapse;'
    'background:#1f2937;color:#FFFFFF;border-radius:12px;'
    'margin:0 0 16px 0;">'
    '<tr><td style="padding:24px;">'
    '<div style="font-size:12px;letter-spacing:0.08em;'
    'text-transform:uppercase;opacity:0.85;">Updated terms</div>'
    '<div style="font-size:20px;font-weight:700;margin-top:4px;">'
    '{{COMPANY_NAME}}</div>'
    '</td></tr></table>'

    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="100%" style="border-collapse:collapse;'
    'background:#FFFFFF;border:1px solid #E2E8F0;'
    'border-radius:12px;margin:0 0 16px 0;">'
    '<tr><td style="padding:20px;">'
    '<p style="margin:0 0 8px;font-size:15px;">Hi {{RECIPIENT_NAME}},</p>'
    '<p style="margin:0 0 16px;font-size:14px;color:#334155;'
    'line-height:1.5;">'
    "We've updated our Terms of Service for {{SERVICE_LABEL}} "
    "customers. Version {{TOS_VERSION}} takes effect "
    "{{EFFECTIVE_DATE}}. Please review and accept the updated "
    "terms at your next portal visit — this email is for your "
    "records; the portal will prompt you when you sign in."
    '</p>'
    '<div style="text-align:center;margin:8px 0 4px;">'
    '<a href="{{TOS_URL}}" '
    'style="display:inline-block;background:#1f2937;color:#FFFFFF;'
    'padding:12px 24px;border-radius:8px;text-decoration:none;'
    'font-weight:600;font-size:14px;">Review Updated Terms</a>'
    '</div>'
    '</td></tr></table>'

    '<p style="font-size:13px;color:#334155;margin-top:24px;'
    'text-align:center;">We appreciate your business<br/>'
    '<b>{{COMPANY_NAME}}</b><br/>{{COMPANY_PHONE}}</p>'
    '</td></tr></table></td></tr></table>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "COMPANY_NAME", "RECIPIENT_NAME", "SERVICE_LABEL",
    "TOS_VERSION", "EFFECTIVE_DATE", "TOS_URL", "COMPANY_PHONE",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "TOS — Update Blast",
        "category": "legal",
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
