"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — lead-to-customer welcome.

Upserts the canonical ``marketing_templates`` row keyed by
``code="lead_conversion_welcome_email"``.  Consumed by
:func:`services.lead_conversion_notifications._send_welcome_email`
when an admin converts a lead into a customer.

BUGFIX
------
The pre-migration builder hardcoded
``"Pool & Landscaping of Vistancia"`` in both the subject line AND
the body copy — plus a hardcoded phone number ``+1 (602) 887-4400``
in the footer line.  The seeded body replaces both with the
``{{COMPANY_NAME}}`` and ``{{COMPANY_PHONE}}`` merge tags so
non-plofv tenants sign off correctly and no hardcoded phone leaks
survive.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_lead_conversion_welcome_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_lead_conversion_welcome_template"
TEMPLATE_CODE = "lead_conversion_welcome_email"


SUBJECT_DEFAULT = "Welcome to {{COMPANY_NAME}} — your account is ready"

BODY_DEFAULT = (
    '<div style="font-family:sans-serif;max-width:560px;margin:auto">'
    '<h2>Welcome aboard, {{CUSTOMER_NAME}}!</h2>'
    '<p>Thanks for choosing <b>{{COMPANY_NAME}}</b>. '
    "We've set up your account and one of our team will reach out "
    'shortly to schedule your first service.</p>'
    '<h3>What happens next</h3>'
    '<ul>'
    "<li>We'll call or text you within one business day to confirm "
    'a start date.</li>'
    "<li>You'll receive service reports, invoices, and appointment "
    'reminders here.</li>'
    '<li>Refer a neighbor and you both save $55 on your next '
    'service.</li>'
    '</ul>'
    '<p><a href="{{PORTAL_LINK}}" '
    'style="background:#0891b2;color:#fff;padding:12px 20px;'
    'border-radius:8px;text-decoration:none;display:inline-block">'
    'Open your customer portal</a></p>'
    '<p style="color:#666;font-size:12px">'
    'You are receiving this because you requested service from us. '
    'Reply to this email or call <b>{{COMPANY_PHONE}}</b> anytime.'
    '</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "CUSTOMER_NAME", "COMPANY_NAME", "PORTAL_LINK", "COMPANY_PHONE",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Lead — Conversion Welcome (customer)",
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
