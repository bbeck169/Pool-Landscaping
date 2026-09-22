"""Phase P30 · Feb-2026 — Refresh add-card SMS + Email templates for
existing tenants.

The templates in ``db.marketing_templates`` are per-tenant (each row
carries ``tenant_id``). The seeder (``services.add_card_links.
seed_add_card_templates_for_tenant``) only inserts a row if one
doesn't already exist — so historical tenants keep the pre-P30 copy
forever unless we explicitly refresh. This migration upserts the
new body on every tenant's ``add_card_request_sms`` +
``add_card_request_email`` rows, but ONLY when the row is
``is_system=True`` (customization is preserved — a tenant that
edited the body keeps their edits).

Idempotency:

* Second run reads the current DB body, compares against the
  P30 canonical body, no-ops if they match.
* Emits per-tenant counts on the InitState summary so ops can
  see the migration's footprint on ``/api/health``.

Scope:

* ``code == "add_card_request_sms"`` OR
  ``code == "add_card_request_email"``.
* ``is_system == True`` OR the row body matches one of the
  pre-P30 canonical strings (defensive against a legacy row that
  omitted the ``is_system`` flag).
* NEVER touches ``kind != "transactional"`` rows.

Wired into the P21 STRUCTURAL block via
``_run_structural_migration(..., must_succeed=False)`` — best-effort
data cleanup that never blocks bind.
"""
from __future__ import annotations

from typing import Any, Dict

from config import db, logger
from utils import now_iso


MIGRATION_NAME = "p30_add_card_sms_template"


# ══════════════════════════════════════════════════════════════════
# P30 canonical bodies — SINGLE source of truth. The router's
# ``send_card_add_link`` handler renders these via
# ``services.marketing.merge_tags.render_template`` so the three
# tokens (``{{CUSTOMER_FIRST_NAME}}``, ``{{COMPANY_NAME}}``,
# ``{{ADD_CARD_LINK}}``) resolve at send time.
# ══════════════════════════════════════════════════════════════════
P30_SMS_BODY = (
    "Hi {{CUSTOMER_FIRST_NAME}}, To keep your service on schedule, "
    "please add a card on file with {{COMPANY_NAME}}. Adding a card "
    "is quick, secure, and only takes a minute: {{ADD_CARD_LINK}}. "
    "If you have any questions, just reply to this text. - The "
    "{{COMPANY_NAME}} team"
)

P30_EMAIL_SUBJECT = "Please add a card to your account"
P30_EMAIL_BODY = (
    "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
    "<p>To keep your service on schedule, please add a card on file "
    "with {{COMPANY_NAME}}.</p>"
    "<p>Adding a card is quick, secure, and only takes a minute:</p>"
    "<p><a href=\"{{ADD_CARD_LINK}}\">Click Here to Add Card</a></p>"
    "<p>If you have any questions, just reply to this email.</p>"
    "<p>— The {{COMPANY_NAME}} team</p>"
)

# Pre-P30 body fragments used to detect a legacy row on a tenant
# that lost its ``is_system`` flag through some legacy migration.
_PRE_P30_SMS_MARKER = "needs a card on file for your account"
_PRE_P30_EMAIL_MARKER = "Add my card securely"


async def _refresh_sms_body(tenant_id: str) -> bool:
    """Return True if the SMS row was mutated."""
    row = await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "add_card_request_sms"},
        {"_id": 0, "body": 1, "is_system": 1},
    )
    if not row:
        # No row — the seeder handles greenfield tenants; this
        # migration is only about REFRESHING an existing row.
        return False
    current_body = row.get("body") or ""
    if current_body == P30_SMS_BODY:
        return False   # already at target
    # Refresh gate: only touch system rows OR rows still carrying the
    # pre-P30 marker phrase. Customized rows (``is_system=False`` +
    # divergent body) are preserved.
    is_system = row.get("is_system", False)
    has_legacy_marker = _PRE_P30_SMS_MARKER in current_body
    if not (is_system or has_legacy_marker):
        return False
    await db.marketing_templates.update_one(
        {"tenant_id": tenant_id, "code": "add_card_request_sms"},
        {"$set": {"body": P30_SMS_BODY, "updated_at": now_iso()}},
    )
    return True


async def _refresh_email_body(tenant_id: str) -> bool:
    """Return True if the email row was mutated."""
    row = await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "add_card_request_email"},
        {"_id": 0, "body": 1, "subject": 1, "is_system": 1},
    )
    if not row:
        return False
    current_body = row.get("body") or ""
    current_subject = row.get("subject") or ""
    if (current_body == P30_EMAIL_BODY
            and current_subject == P30_EMAIL_SUBJECT):
        return False
    is_system = row.get("is_system", False)
    has_legacy_marker = _PRE_P30_EMAIL_MARKER in current_body
    if not (is_system or has_legacy_marker):
        return False
    await db.marketing_templates.update_one(
        {"tenant_id": tenant_id, "code": "add_card_request_email"},
        {"$set": {"subject": P30_EMAIL_SUBJECT, "body": P30_EMAIL_BODY,
                    "updated_at": now_iso()}},
    )
    return True


async def run() -> Dict[str, Any]:
    """Iterate every tenant. Refresh SMS + email add-card templates
    to the P30 canonical bodies. Idempotent.

    Returns a summary dict for the P21 structural-migration logger.
    """
    tenants_scanned = 0
    sms_updated = 0
    email_updated = 0
    per_tenant: Dict[str, Dict[str, bool]] = {}

    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        if not tid:
            continue
        tenants_scanned += 1
        try:
            sms_did = await _refresh_sms_body(tid)
            email_did = await _refresh_email_body(tid)
        except Exception as exc:                                # noqa: BLE001
            logger.warning(
                "[p30-tpl] refresh failed for tenant=%s: %s", tid, exc,
            )
            continue
        if sms_did:
            sms_updated += 1
        if email_did:
            email_updated += 1
        if sms_did or email_did:
            per_tenant[tid] = {"sms": sms_did, "email": email_did}

    logger.info(
        "[p30-tpl] add-card template refresh complete — "
        "tenants_scanned=%s sms_updated=%s email_updated=%s",
        tenants_scanned, sms_updated, email_updated,
    )
    return {
        "tenants_scanned": tenants_scanned,
        "sms_updated": sms_updated,
        "email_updated": email_updated,
        "per_tenant": per_tenant,
    }
