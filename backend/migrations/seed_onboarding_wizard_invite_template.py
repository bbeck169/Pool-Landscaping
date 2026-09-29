"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — signup onboarding wizard invite.

Upserts the canonical ``marketing_templates`` row keyed by
``code="onboarding_wizard_invite_email"``.  Consumed by
:func:`routers.signup_onboarding_wizard._send_team_invite_signup_email`
when it composes the "you've been invited to join" email a new
tenant sends to teammates during the step-3 wizard.

i18n note
---------
The pre-migration path routes through
:func:`services.i18n_notifications.resolve_notification_body` with
``template_key="team_invite_signup"`` (en/es/fr triplet on disk
at ``services/notification_templates/<locale>/team_invite_signup.*``).
The DB body seeded here is used ONLY when the recipient's locale
resolves to ``en`` — non-English sends keep the current i18n path
unchanged (decision (c) in the EMAIL-MIGRATE brief).

Idempotency contract mirrors ``seed_auth_password_reset_template``:
``$setOnInsert`` upsert, existing rows preserved verbatim.

Run in-session::

    python -m migrations.seed_onboarding_wizard_invite_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_onboarding_wizard_invite_template"
TEMPLATE_CODE = "onboarding_wizard_invite_email"


# ═══════════════════════════════════════════════════════════════════
# English default — mirrors ``services/notification_templates/en/
# team_invite_signup.html`` with the single-brace tokens rewritten
# to double-brace merge-tag catalog tokens.
# ═══════════════════════════════════════════════════════════════════
SUBJECT_DEFAULT = (
    "You're invited to join {{BUSINESS_NAME}} on "
    "Pool & Landscaping CRM"
)

BODY_DEFAULT = (
    '<div style="font-family:system-ui;max-width:600px;margin:0 auto;padding:24px">'
    '<p>Hi,</p>'
    '<p>{{ACTOR_NAME}} at <strong>{{BUSINESS_NAME}}</strong> invited you to '
    'join their team as {{ROLE}}.</p>'
    '<p><a href="{{ONBOARDING_LINK}}" '
    'style="display:inline-block;padding:10px 16px;background:#0F766E;'
    'color:#fff;text-decoration:none;border-radius:6px;font-weight:600">'
    'Accept invite &amp; sign in</a></p>'
    "<p style=\"color:#64748B;font-size:13px\">"
    "If you didn't expect this invite, ignore this email — no action is required."
    "</p>"
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "ACTOR_NAME", "BUSINESS_NAME", "ROLE",
    "ONBOARDING_LINK", "RECIPIENT_EMAIL",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Signup — Onboarding Wizard Invite",
        "category": "signup",
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
