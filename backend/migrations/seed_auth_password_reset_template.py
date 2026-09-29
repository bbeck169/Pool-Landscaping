"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — auth self-serve password reset.

Upserts the canonical ``marketing_templates`` row keyed by
``code="auth_password_reset_email"``.  When
:func:`routers.auth.forgot_password` composes the reset email, it
looks up this row first (via
:func:`services.marketing_template_lookup.get_template_with_global_fallback`)
and renders the ``body`` / ``subject`` through
:func:`services.marketing.merge_tags.render_template` — meaning a
tenant that clones + edits the row via the marketing-templates UI
overrides the hard-coded fallback in ``_password_reset_email_html``.

Idempotency contract
--------------------
* First run inserts the row via ``$setOnInsert``.
* Second and subsequent runs are a no-op — an existing row is
  detected by ``code`` alone and its ``body`` / ``subject`` are
  preserved verbatim (a tenant may have edited them via the UI,
  and this migration is not permitted to clobber their work).

Run in-session::

    python -m migrations.seed_auth_password_reset_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_auth_password_reset_template"
TEMPLATE_CODE = "auth_password_reset_email"


# ═══════════════════════════════════════════════════════════════════
# Default subject + HTML body.  Body carries the same inline styling
# the pre-migration ``_password_reset_email_html`` emitted; the only
# change is that per-render values are now ``{{MERGE_TAG}}``
# placeholders rendered through
# ``services.marketing.merge_tags.render_template``.
# ═══════════════════════════════════════════════════════════════════
SUBJECT_DEFAULT = "Reset your password"

BODY_DEFAULT = (
    '<div style="font-family:-apple-system,\'Inter\',sans-serif;'
    'color:#0F172A;max-width:560px;margin:0 auto;padding:24px;">'
    '<h2 style="margin:0 0 12px;">Reset your password</h2>'
    '<p style="margin:0 0 12px;font-size:15px;line-height:1.55;">'
    'Hi {{RECIPIENT_NAME}},</p>'
    '<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">'
    'We received a request to reset your {{COMPANY_NAME}} '
    'portal password. Click the button below to choose a new one.</p>'
    '<p style="margin:24px 0;">'
    '<a href="{{RESET_LINK}}" '
    'style="display:inline-block;background:#0284C7;color:#fff;'
    'padding:12px 22px;border-radius:10px;text-decoration:none;'
    'font-weight:600;">Reset password</a></p>'
    '<p style="margin:0 0 8px;font-size:13px;color:#475569;">'
    "This link expires in {{EXPIRY_LABEL}}. If you didn't "
    "request this reset you can safely ignore this email — your "
    "password won't change.</p>"
    '<p style="margin:16px 0 0;font-size:12px;color:#94A3B8;'
    'word-break:break-all;">'
    'Or copy this link into your browser:<br/>'
    '<a href="{{RESET_LINK}}" style="color:#475569;">{{RESET_LINK}}</a>'
    '</p></div>'
)

TEXT_DEFAULT = ""

MERGE_TAGS = [
    "RECIPIENT_NAME", "COMPANY_NAME", "RESET_LINK", "EXPIRY_LABEL",
]


def _seed_row_setoninsert() -> dict:
    """Return the ``$setOnInsert`` payload — the shape a fresh row
    gets on first insert.  Uses a computed ``created_at`` / new id
    on each call so a fresh insert on a fresh DB reflects the run
    time.
    """
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,          # global default
        "name": "Auth — Password Reset (self-serve)",
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
    """Upsert the auth-password-reset default row idempotently.

    Returns ``{"inserted": bool, "code": str}`` — suitable for the
    P21 structural-migration logger.
    """
    result = await db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE},
        {"$setOnInsert": _seed_row_setoninsert()},
        upsert=True,
    )
    return {"inserted": bool(result.upserted_id), "code": TEMPLATE_CODE}


if __name__ == "__main__":
    summary = asyncio.run(run())
    print(f"[{MIGRATION_NAME}] {summary}")
