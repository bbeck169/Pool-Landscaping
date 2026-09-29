"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — tenant billing (trial
reminder + dunning / payment-failed).

Upserts TWO rows into ``marketing_templates``:

* ``tenant_billing_trial_reminder_email`` — fires from
  :func:`services.tenant_billing_reminders.run_trial_ending_reminders`
  24h before the trial-end timestamp.
* ``tenant_billing_dunning_email`` — fires from
  :func:`services.tenant_billing_webhooks.handle_tenant_billing_event`
  on Stripe's ``invoice.payment_failed`` webhook.

Both bodies are English defaults — non-English recipients continue
to use the on-disk D5 notification-template triplet
(``services/notification_templates/<locale>/{trial_ending_reminder,
payment_failed}.{subject.txt,html,text.txt}``) per decision (c).

Idempotency contract mirrors ``seed_auth_password_reset_template``.

Run in-session::

    python -m migrations.seed_tenant_billing_templates
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_tenant_billing_templates"


TRIAL_CODE = "tenant_billing_trial_reminder_email"
TRIAL_SUBJECT = "Your {{COMPANY_NAME}} trial ends tomorrow"
TRIAL_BODY = (
    '<div style="font-family:system-ui;max-width:600px;margin:0 auto;padding:24px">'
    '<p>Hi {{ADMIN_NAME}},</p>'
    '<p>Your {{COMPANY_NAME}} free trial ends on '
    '<strong>{{TRIAL_END_LOCAL}}</strong>. Tomorrow we\'ll charge '
    '{{PLAN_AMOUNT}} to the card on file to continue your subscription.</p>'
    "<p>If you'd like to cancel before then, no action is needed on the "
    'card — just cancel here:</p>'
    '<p><a href="{{CANCEL_LINK}}" '
    'style="display:inline-block;padding:10px 16px;background:#DC2626;'
    'color:#fff;text-decoration:none;border-radius:6px;font-weight:600">'
    'Cancel my subscription</a></p>'
    '<p style="color:#64748B;font-size:13px">'
    'Questions? Just reply to this email — we read every message.'
    '</p>'
    '</div>'
)
TRIAL_MERGE_TAGS = [
    "ADMIN_NAME", "COMPANY_NAME", "TRIAL_END_LOCAL",
    "PLAN_AMOUNT", "CANCEL_LINK",
]


DUNNING_CODE = "tenant_billing_dunning_email"
DUNNING_SUBJECT = "Payment failed — update your {{COMPANY_NAME}} card"
DUNNING_BODY = (
    '<div style="font-family:system-ui;max-width:600px;margin:0 auto;padding:24px">'
    '<p>Hi {{ADMIN_NAME}},</p>'
    '<p>We were unable to process your latest {{COMPANY_NAME}} '
    'payment. To keep your account active, please update your card '
    'as soon as possible:</p>'
    '<p><a href="{{UPDATE_CARD_LINK}}" '
    'style="display:inline-block;padding:10px 16px;background:#2563EB;'
    'color:#fff;text-decoration:none;border-radius:6px;font-weight:600">'
    'Update my card</a></p>'
    '<p style="color:#64748B;font-size:13px">'
    "We'll automatically retry the charge over the next few days. "
    'If the card still fails, your account will be paused until a '
    'working card is on file.'
    '</p>'
    '</div>'
)
DUNNING_MERGE_TAGS = [
    "ADMIN_NAME", "COMPANY_NAME", "UPDATE_CARD_LINK",
]

TEMPLATE_CODES = (TRIAL_CODE, DUNNING_CODE)


def _seed_row(*, code: str, subject: str, body: str,
                 name: str, merge_tags: list) -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": code,
        "tenant_id": None,
        "name": name,
        "category": "billing",
        "channel": "email",
        "kind": "transactional",
        "subject": subject,
        "body": body,
        "text_body": "",
        "merge_tags": merge_tags,
        "is_system": True,
        "is_default": True,
        "editable": True,
        "created_at": now,
        "updated_at": now,
    }


async def run() -> dict:
    rows = [
        _seed_row(code=TRIAL_CODE, subject=TRIAL_SUBJECT,
                     body=TRIAL_BODY,
                     name="Billing — Trial Ending Reminder",
                     merge_tags=TRIAL_MERGE_TAGS),
        _seed_row(code=DUNNING_CODE, subject=DUNNING_SUBJECT,
                     body=DUNNING_BODY,
                     name="Billing — Dunning / Payment Failed",
                     merge_tags=DUNNING_MERGE_TAGS),
    ]
    inserted_codes = []
    for row in rows:
        result = await db.marketing_templates.update_one(
            {"code": row["code"]},
            {"$setOnInsert": row},
            upsert=True,
        )
        if result.upserted_id:
            inserted_codes.append(row["code"])
    return {"inserted": inserted_codes, "codes": list(TEMPLATE_CODES)}


if __name__ == "__main__":
    summary = asyncio.run(run())
    print(f"[{MIGRATION_NAME}] {summary}")
