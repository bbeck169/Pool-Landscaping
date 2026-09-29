"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — signup email-verify.

Upserts the canonical ``marketing_templates`` row keyed by
``code="signup_verify_code_email"``.  Consumed by
:func:`routers.signup._send_signup_verify_email` when it composes
the "verify your account" email a newly-signed-up tenant admin
receives.

i18n note
---------
The pre-migration path routes through
:func:`services.i18n_notifications.resolve_notification_body` with
``template_key="signup_email_verify"`` (en/es/fr triplet on disk
at ``services/notification_templates/<locale>/signup_email_verify.*``).
The DB body seeded here is used ONLY when the recipient's locale
resolves to ``en`` — non-English sends keep the current i18n path
unchanged (decision (c) in the EMAIL-MIGRATE brief).

Idempotency contract mirrors ``seed_auth_password_reset_template``:
``$setOnInsert`` upsert, existing rows preserved verbatim.

Run in-session::

    python -m migrations.seed_signup_verify_code_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_signup_verify_code_template"
TEMPLATE_CODE = "signup_verify_code_email"


# ═══════════════════════════════════════════════════════════════════
# English default — mirrors ``services/notification_templates/en/
# signup_email_verify.html`` with the single-brace tokens rewritten
# to double-brace merge-tag catalog tokens.
# ═══════════════════════════════════════════════════════════════════
SUBJECT_DEFAULT = "Verify your {{BUSINESS_NAME}} account"

BODY_DEFAULT = (
    '<div style="font-family:system-ui;max-width:600px;margin:0 auto;padding:24px">'
    '<p>Hi {{RECIPIENT_NAME}},</p>'
    '<p>Welcome to {{BUSINESS_NAME}}! Please verify your email address '
    'to activate your account and finish onboarding:</p>'
    '<p><a href="{{VERIFY_CODE}}" '
    'style="display:inline-block;padding:10px 16px;background:#2563EB;'
    'color:#fff;text-decoration:none;border-radius:6px;font-weight:600">'
    'Verify my email</a></p>'
    '<p style="color:#64748B;font-size:13px">'
    'This link expires in {{EXPIRY_LABEL}}. If you did not sign up, '
    'please ignore this email — no action is required.'
    '</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "RECIPIENT_NAME", "BUSINESS_NAME", "VERIFY_CODE", "EXPIRY_LABEL",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Signup — Email Verify Code",
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
