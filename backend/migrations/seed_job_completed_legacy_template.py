"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — job completion (legacy).

Upserts the canonical ``marketing_templates`` row keyed by
``code="job_completed_legacy_email"``.  Consumed by
:func:`emailer.send_completion_email` when a service job is marked
complete.

Coexistence note
----------------
This flow lives ALONGSIDE the door-hanger path
(``door_hanger_job_completed``, shipped in the DOOR-HANGER phase);
both are separate template codes, separate runtime paths, and
their triggers do not collide (per decision (a) in the EMAIL-
MIGRATE brief).  Tenants who want to disable this legacy path can
set ``is_active: False`` on the row without deleting it.

The subject line stays composed via
:func:`services.email_body_i18n.t_email_body` (decision (c) —
i18n subjects preserved).  Non-English recipients keep the
existing i18n body path; the DB body only replaces the English
inner HTML.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_job_completed_legacy_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_job_completed_legacy_template"
TEMPLATE_CODE = "job_completed_legacy_email"


SUBJECT_DEFAULT = "Your {{SERVICE_TYPE}} service is complete"

BODY_DEFAULT = (
    '<div style="max-width:560px;margin:0 auto;'
    'font-family:Arial,sans-serif;color:#1A2B3C;">'
    '<div style="background:#003C5F;padding:24px;'
    'border-radius:12px 12px 0 0;">'
    '<h1 style="color:#fff;margin:0;font-size:20px;">{{COMPANY_NAME}}</h1>'
    '</div>'
    '<div style="border:1px solid #E2E8F0;border-top:none;'
    'border-radius:0 0 12px 12px;padding:24px;">'
    '<h2 style="font-size:18px;margin:0 0 8px;">'
    'Your service is complete ✅</h2>'
    '<p style="font-size:14px;color:#334155;line-height:20px;margin:0 0 4px;">'
    'Hi {{CUSTOMER_NAME}}, we just wrapped up your {{SERVICE_TYPE}} '
    'visit at {{PROPERTY_ADDRESS}}. See the report and photos below.'
    '</p>'
    '<div style="text-align:center;margin:28px 0 8px;">'
    '<a href="{{VIEW_REQUEST_LINK}}" '
    'style="background:#0EA5B7;color:#fff;text-decoration:none;'
    'font-size:15px;font-weight:bold;padding:14px 28px;'
    'border-radius:10px;display:inline-block;">View report</a>'
    '</div>'
    '<p style="font-size:12px;color:#94A3B8;text-align:center;'
    'margin:12px 0 0;">Reply to this email if you have any questions.</p>'
    '</div>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "COMPANY_NAME", "CUSTOMER_NAME", "SERVICE_TYPE",
    "PROPERTY_ADDRESS", "VIEW_REQUEST_LINK",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Job — Completion (legacy customer email)",
        "category": "job",
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
