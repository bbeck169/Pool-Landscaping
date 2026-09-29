"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — admin-driven password reset.

Upserts the canonical ``marketing_templates`` row keyed by
``code="admin_user_password_reset_email"``.  Consumed by
:func:`routers.admin_users._send_password_reset_email` when it
composes the temp-password email an admin issues to another user.

i18n note
---------
Subjects and body copy for locales OTHER than ``en`` continue to
resolve through :func:`services.email_body_i18n.t_email_body`
(decision (c) in the EMAIL-MIGRATE brief — subjects stay i18n).
The DB body is used ONLY when the recipient's locale is ``en`` and
the row is active — non-English sends keep the current i18n path
unchanged.

Idempotency contract mirrors ``seed_auth_password_reset_template``:
``$setOnInsert`` upsert, existing rows preserved verbatim.

Run in-session::

    python -m migrations.seed_admin_user_password_reset_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_admin_user_password_reset_template"
TEMPLATE_CODE = "admin_user_password_reset_email"


# ═══════════════════════════════════════════════════════════════════
# English-only default subject + body.  The body is the fragment
# ``_password_reset_html`` used to render (pre-migration) with the
# per-render values replaced by merge tags.
# ═══════════════════════════════════════════════════════════════════
SUBJECT_DEFAULT = "Your {{COMPANY_NAME}} password has been reset"

BODY_DEFAULT = (
    '<div style="max-width:520px;margin:0 auto;background:#ffffff;'
    'border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.06);'
    'color:#111827;font-family:system-ui,-apple-system,Segoe UI,'
    'Roboto,Arial,sans-serif">'
    '<h1 style="margin:0 0 12px 0;font-size:20px">Your password has been reset</h1>'
    '<p style="margin:0 0 16px 0;line-height:1.55">'
    'Hi {{RECIPIENT_NAME}}, {{ACTOR_NAME}} at {{COMPANY_NAME}} reset your '
    'password. Use the temporary password below to sign in — you\'ll be asked '
    'to choose a new one immediately.'
    '</p>'
    '<div style="background:#f9fafb;border:1px solid #e5e7eb;'
    'border-radius:8px;padding:14px 16px;margin:0 0 20px 0">'
    '<div style="font-size:12px;color:#6b7280;text-transform:uppercase;'
    'letter-spacing:.4px;margin-bottom:4px">Temporary password</div>'
    '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
    'font-size:15px;font-weight:600">{{TEMP_PASSWORD}}</div>'
    '</div>'
    '<p style="text-align:center;margin:0 0 22px 0">'
    '<a href="{{LOGIN_URL}}" style="background:#0f766e;color:#ffffff;'
    'padding:11px 22px;border-radius:8px;text-decoration:none;'
    'font-weight:600;display:inline-block">Sign in</a>'
    '</p>'
    '<p style="font-size:12px;color:#6b7280;margin:0">'
    "If you didn't expect this reset, contact your administrator right away."
    '</p>'
    '</div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "RECIPIENT_NAME", "ACTOR_NAME", "COMPANY_NAME",
    "TEMP_PASSWORD", "LOGIN_URL",
]


def _seed_row_setoninsert() -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,
        "name": "Auth — Password Reset (admin-driven)",
        "category": "auth",
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
