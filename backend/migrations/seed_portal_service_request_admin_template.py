"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — portal service-request
admin notification.

Upserts the canonical ``marketing_templates`` row keyed by
``code="portal_service_request_admin_email"``.  Consumed by
:func:`routers.customer_portal.create_service_request` when it
composes the "New Service Request from <customer>" email routed
to the tenant admin.

PHONE-PURGE invariant
---------------------
The body renders the tenant's configured phone through
``{{TENANT_SERVICE_REQUEST_PHONE}}``.  When the tenant has no
number configured, the caller populates the ctx with an empty
string and the phone line collapses cleanly — never a hardcoded
literal number.

Idempotency contract mirrors ``seed_auth_password_reset_template``:
``$setOnInsert`` upsert, existing rows preserved verbatim.

Run in-session::

    python -m migrations.seed_portal_service_request_admin_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_portal_service_request_admin_template"
TEMPLATE_CODE = "portal_service_request_admin_email"


SUBJECT_DEFAULT = "New Service Request from {{CUSTOMER_NAME}}"

BODY_DEFAULT = (
    '<div style="font-family:-apple-system,\'Inter\',sans-serif;'
    'color:#0F172A;max-width:640px;margin:0 auto;padding:24px;">'
    '<h2 style="margin:0 0 12px;">New Service Request</h2>'
    '<p style="margin:0 0 4px;"><b>Customer:</b> {{CUSTOMER_NAME}}</p>'
    '<p style="margin:0 0 4px;"><b>Email:</b> '
    '<a href="mailto:{{CUSTOMER_EMAIL}}">{{CUSTOMER_EMAIL}}</a></p>'
    '<p style="margin:0 0 4px;"><b>Phone:</b> '
    '<a href="tel:{{CUSTOMER_PHONE}}">{{CUSTOMER_PHONE}}</a></p>'
    '<p style="margin:0 0 4px;"><b>Address:</b> {{PROPERTY_ADDRESS}}</p>'
    '<p style="margin:0 0 4px;"><b>Service:</b> {{SERVICE_TYPE}}</p>'
    '<p style="margin:0 0 4px;"><b>Preferred date:</b> {{PREFERRED_DATE}}</p>'
    '<hr style="border:none;border-top:1px solid #E2E8F0;margin:16px 0;"/>'
    '<div style="white-space:pre-wrap;font-size:15px;line-height:1.5;">'
    '{{REQUEST_DETAILS}}</div>'
    '<p style="margin:20px 0 0;">'
    '<a href="{{VIEW_REQUEST_LINK}}" '
    'style="display:inline-block;background:#0284C7;color:#fff;'
    'padding:10px 16px;border-radius:8px;text-decoration:none;'
    'font-weight:600;">View request</a>'
    '</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "CUSTOMER_NAME", "CUSTOMER_EMAIL", "CUSTOMER_PHONE",
    "PROPERTY_ADDRESS", "SERVICE_TYPE", "PREFERRED_DATE",
    "REQUEST_DETAILS", "VIEW_REQUEST_LINK",
    "TENANT_SERVICE_REQUEST_PHONE",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Portal — Service Request (admin notification)",
        "category": "portal",
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
