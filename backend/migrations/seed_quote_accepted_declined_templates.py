"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — quote accepted/declined
owner emails.

Upserts TWO rows into ``marketing_templates`` — one per event:

* ``quote_accepted_owner_email`` — fires from
  :func:`services.quote_notifications.render_email` when a customer
  accepts a quote / estimate / proposal.
* ``quote_declined_owner_email`` — same helper on the decline path.

Both bodies share the same merge-tag surface
(``QUOTE_HEADLINE`` / ``QUOTE_TOTAL`` / ``QUOTE_LABEL`` /
``QUOTE_SHORT_ID`` / ``QUOTE_ADMIN_LINK`` / ``CUSTOMER_NAME``); only
the leading headline copy differs.  The subject stays composed
inline (the ``[Label #short] Accepted/Declined by <name>``
convention is not tenant-editable per decision (c)).

Idempotency contract mirrors ``seed_auth_password_reset_template``:
``$setOnInsert`` upsert per row, existing rows preserved verbatim.

Run in-session::

    python -m migrations.seed_quote_accepted_declined_templates
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_quote_accepted_declined_templates"

# ─── Body template (shared) ────────────────────────────────────────
# Mirrors the pre-migration ``render_email`` HTML shape verbatim so
# tenants who don't edit the row see the exact same output as before.
_BODY_TEMPLATE = (
    '<div style="font-family:system-ui,sans-serif;font-size:14px">'
    '<p>{{QUOTE_HEADLINE}}</p>'
    '<p><strong>Total:</strong> {{QUOTE_TOTAL}}<br/>'
    '<strong>{{QUOTE_LABEL}}:</strong> #{{QUOTE_SHORT_ID}}<br/>'
    '<strong>Customer:</strong> {{CUSTOMER_NAME}}</p>'
    '<p><a href="{{QUOTE_ADMIN_LINK}}">Open {{QUOTE_LABEL}} in admin →</a></p>'
    '</div>'
)


ACCEPTED_CODE = "quote_accepted_owner_email"
ACCEPTED_SUBJECT = "[{{QUOTE_LABEL}} #{{QUOTE_SHORT_ID}}] Accepted by {{CUSTOMER_NAME}}"
ACCEPTED_BODY = _BODY_TEMPLATE

DECLINED_CODE = "quote_declined_owner_email"
DECLINED_SUBJECT = "[{{QUOTE_LABEL}} #{{QUOTE_SHORT_ID}}] Declined by {{CUSTOMER_NAME}}"
DECLINED_BODY = _BODY_TEMPLATE

TEMPLATE_CODES = (ACCEPTED_CODE, DECLINED_CODE)

MERGE_TAGS = [
    "QUOTE_HEADLINE", "QUOTE_TOTAL", "QUOTE_LABEL",
    "QUOTE_SHORT_ID", "QUOTE_ADMIN_LINK", "CUSTOMER_NAME",
]


def _seed_row(*, code: str, subject: str, body: str,
                 name: str) -> dict:
    now = now_iso()
    return {
        "id": new_id(),
        "code": code,
        "tenant_id": None,
        "name": name,
        "category": "quote",
        "channel": "email",
        "kind": "transactional",
        "subject": subject,
        "body": body,
        "text_body": "",
        "merge_tags": MERGE_TAGS,
        "is_system": True,
        "is_default": True,
        "editable": True,
        "created_at": now,
        "updated_at": now,
    }


async def run() -> dict:
    rows = [
        _seed_row(
            code=ACCEPTED_CODE,
            subject=ACCEPTED_SUBJECT,
            body=ACCEPTED_BODY,
            name="Quote — Accepted (owner notification)",
        ),
        _seed_row(
            code=DECLINED_CODE,
            subject=DECLINED_SUBJECT,
            body=DECLINED_BODY,
            name="Quote — Declined (owner notification)",
        ),
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
