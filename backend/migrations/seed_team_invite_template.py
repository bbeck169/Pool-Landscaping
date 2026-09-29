"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — team invite.

Upserts the canonical ``marketing_templates`` row keyed by
``code="team_invite_email"``.  Consumed by
:func:`routers.team._send_team_invite_email` when an admin adds a
new team member and issues them a temporary password.

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_team_invite_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_team_invite_template"
TEMPLATE_CODE = "team_invite_email"


SUBJECT_DEFAULT = "Welcome to {{COMPANY_NAME}} — you've been added to the team"

BODY_DEFAULT = (
    '<!doctype html>'
    '<html><body style="font-family:system-ui,-apple-system,Segoe UI,'
    'Roboto,Arial,sans-serif;background:#f4f6f8;padding:24px 0;'
    'margin:0;color:#111827">'
    '<div style="max-width:520px;margin:0 auto;background:#ffffff;'
    'border-radius:12px;padding:28px 30px;'
    'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
    '<h1 style="margin:0 0 12px 0;font-size:20px">'
    'Welcome to {{COMPANY_NAME}}, {{INVITEE_NAME}} 👋</h1>'
    '<p style="margin:0 0 16px 0;line-height:1.55">'
    "{{INVITER_NAME}} added you to the team. You can sign in now "
    "with the temporary credentials below — you'll be asked to "
    'change your password on first login.</p>'
    '<div style="background:#f9fafb;border:1px solid #e5e7eb;'
    'border-radius:8px;padding:14px 16px;margin:0 0 20px 0">'
    '<div style="font-size:12px;color:#6b7280;text-transform:uppercase;'
    'letter-spacing:.4px;margin-bottom:4px">Temporary password</div>'
    '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
    'font-size:15px;font-weight:600">{{TEMP_PASSWORD}}</div>'
    '</div>'
    '<p style="text-align:center;margin:0 0 22px 0">'
    '<a href="{{ACCEPT_INVITE_LINK}}" '
    'style="background:#0f766e;color:#ffffff;padding:11px 22px;'
    'border-radius:8px;text-decoration:none;font-weight:600;'
    'display:inline-block">Sign in to the platform</a>'
    '</p>'
    '<p style="font-size:12px;color:#6b7280;margin:0">'
    "If you weren't expecting this invite, ignore this email or "
    'reply to let us know.</p>'
    '</div>'
    '</body></html>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "COMPANY_NAME", "INVITEE_NAME", "INVITER_NAME",
    "TEMP_PASSWORD", "ACCEPT_INVITE_LINK",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Team — Invite (new member)",
        "category": "team",
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
