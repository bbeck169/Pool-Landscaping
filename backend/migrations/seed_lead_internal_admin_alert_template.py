"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — internal lead-created
admin alert.

Upserts the canonical ``marketing_templates`` row keyed by
``code="lead_internal_admin_alert_email"``.  Consumed by
:func:`services.leads_side_effects._fire_internal_notification`
when a lead lands and the tenant admin/dispatcher needs to be
paged.

The pre-migration builder in
:func:`services.leads_side_effects._compose_internal` emitted a
plain-text body with newline-separated ``key: value`` lines.  The
seeded HTML body mirrors that shape — one ``<div>`` per field —
so it renders cleanly in email clients and still degrades to
readable plain text.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_lead_internal_admin_alert_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_lead_internal_admin_alert_template"
TEMPLATE_CODE = "lead_internal_admin_alert_email"


# Subject stays parametric — the caller passes ``lead_subject_prefix``
# ("[New lead] " or "[REJECTED] ") + the lead's ``name`` in the ctx
# so the composed subject reads e.g. ``"[New lead] Jane Doe"``.
SUBJECT_DEFAULT = "{{LEAD_SUBJECT_PREFIX}}{{LEAD_NAME}}"

BODY_DEFAULT = (
    '<div style="font-family:-apple-system,\'Inter\',sans-serif;'
    'color:#0F172A;max-width:560px;margin:0 auto;padding:24px;'
    'line-height:1.5;">'
    '<div>{{LEAD_REJECT_HEADER}}</div>'
    '<div><b>Name:</b> {{LEAD_NAME}}</div>'
    '<div><b>Phone:</b> {{LEAD_PHONE}}</div>'
    '<div><b>Email:</b> {{LEAD_EMAIL}}</div>'
    '<div><b>Address:</b> {{PROPERTY_ADDRESS}}</div>'
    '<div><b>Message:</b> {{LEAD_MESSAGE}}</div>'
    '<div><b>Source:</b> {{LEAD_SOURCE}}</div>'
    '<div><b>When:</b> {{LEAD_TIME_LABEL}}</div>'
    '<div style="margin-top:12px;">'
    '<a href="{{LEAD_LINK}}" '
    'style="display:inline-block;background:#0284C7;color:#fff;'
    'padding:8px 14px;border-radius:6px;text-decoration:none;'
    'font-weight:600;">Open lead</a>'
    '</div>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "LEAD_REJECT_HEADER", "LEAD_NAME", "LEAD_PHONE", "LEAD_EMAIL",
    "PROPERTY_ADDRESS", "LEAD_MESSAGE", "LEAD_SOURCE",
    "LEAD_TIME_LABEL", "LEAD_LINK",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Lead — Internal Admin Alert",
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
