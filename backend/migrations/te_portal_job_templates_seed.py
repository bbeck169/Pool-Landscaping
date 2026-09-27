"""TE-portal-job · Feb-2026 — Seed system defaults for the two new
transactional template categories:

* ``portal_invite_email`` — customer portal invite (email).
* ``job_completion_sms``  — service completion SMS (customer-facing).

Idempotent — inserts one row per (tenant, code) pair only when the
row is missing. NEVER overwrites an existing row (system or
user-edited). Matches the P30 add-card refresh migration style:

* Runs on boot under ``server.py::_run_structural_migration`` with
  ``must_succeed=False`` — a Mongo hiccup logs a WARN and boot
  continues.
* Exposes ``seed_for_tenant(tenant_id)`` so pytest can invoke it
  against a synthetic tenant.
* Exposes ``run()`` for the full-tenant sweep.

Body/subject strings are captured VERBATIM from the current
hardcoded strings at the two call sites:

* ``routers/portal_admin.py::_try_send_reset_email`` inline HTML +
  ``subject = "Your customer portal login"``.
* ``services/notification_templates/en/completion_sms.sms.txt``.

Any change here MUST be paired with a change in the fallback
constants living next to the call sites so DB and hardcoded fallback
never drift. Callers render via
``services.marketing.merge_tags.render_template`` (double-brace
``{{TOKEN}}`` syntax, catalog- and flat-key-aware) as of the Feb-
2026 portal-invite merge-tags fix.  Historical rows that were
seeded BEFORE this migration ship with single-brace placeholders
and are rewritten by
``services/migrations/portal_invite_placeholder_rebrace_v1.py`` on
the next boot so the swap is compat-safe.  See the ``variables``
allowlist on each doc for the accepted keys.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

import config
from utils import new_id, now_iso


MIGRATION_NAME = "te_portal_job_templates_seed"


# ══════════════════════════════════════════════════════════════════
# Canonical defaults — SINGLE source of truth. Byte-identical to the
# hardcoded strings living at the call sites.
# ══════════════════════════════════════════════════════════════════

# ── portal_invite_email ────────────────────────────────────────
PORTAL_INVITE_EMAIL_SUBJECT = "Your customer portal login"
# Double-brace merge-tag placeholders — resolved at send time by
# ``services.marketing.merge_tags.render_template`` (which handles
# both the catalog resolvers like ``{{COMPANY_NAME}}`` /
# ``{{COMPANY_PHONE}}`` AND the flat-key overrides ``{{NAME}}`` /
# ``{{TO}}`` / ``{{TEMP_PASSWORD}}`` / ``{{LOGIN_URL}}`` populated
# inline by the send path).  Historical rows shipped with single-
# brace placeholders and are rewritten by
# ``services/migrations/portal_invite_placeholder_rebrace_v1.py``
# on the first boot after the portal-invite merge-tags fix landed.
PORTAL_INVITE_EMAIL_BODY_HTML = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}<br>"
    "<strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)
PORTAL_INVITE_EMAIL_VARIABLES = ["name", "to", "temp_password", "login_url"]

# ── job_completion_sms ─────────────────────────────────────────
# Byte-identical to
# ``backend/services/notification_templates/en/completion_sms.sms.txt``.
JOB_COMPLETION_SMS_BODY = (
    "Hi {first_name}, your {job_title} with {business_name} is "
    "complete! View your full report and photos here: {portal_link}"
)
JOB_COMPLETION_SMS_VARIABLES = [
    "first_name", "job_title", "business_name", "portal_link",
]


def _portal_invite_email_doc(tenant_id: str) -> Dict[str, Any]:
    now = now_iso()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "code": "portal_invite_email",
        "name": "Portal Invite — Email",
        "channel": "email",
        "category": "portal_invite",
        "kind": "transactional",
        "subject": PORTAL_INVITE_EMAIL_SUBJECT,
        "body": PORTAL_INVITE_EMAIL_BODY_HTML,
        "variables": PORTAL_INVITE_EMAIL_VARIABLES,
        "is_system": True,
        "is_editable": True,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _job_completion_sms_doc(tenant_id: str) -> Dict[str, Any]:
    now = now_iso()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "code": "job_completion_sms",
        "name": "Job Completion — SMS",
        "channel": "sms",
        "category": "job_completion",
        "kind": "transactional",
        "subject": None,
        "body": JOB_COMPLETION_SMS_BODY,
        "variables": JOB_COMPLETION_SMS_VARIABLES,
        "is_system": True,
        "is_editable": True,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


async def _ensure_for_tenant(
    tenant_id: str,
    code: str,
    doc_factory: Callable[[str], Dict[str, Any]],
) -> bool:
    """Return True if a new row was inserted; False when it already
    existed OR when ``tenant_id`` is falsy."""
    if not tenant_id:
        return False
    existing = await config.db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": code}, {"_id": 0, "id": 1},
    )
    if existing:
        return False
    await config.db.marketing_templates.insert_one(doc_factory(tenant_id))
    return True


async def seed_for_tenant(tenant_id: str) -> Dict[str, bool]:
    """Seed BOTH templates for a single tenant. Idempotent.

    Returns::

        {
            "portal_invite_email": <inserted?>,
            "job_completion_sms":  <inserted?>,
        }
    """
    return {
        "portal_invite_email": await _ensure_for_tenant(
            tenant_id, "portal_invite_email", _portal_invite_email_doc,
        ),
        "job_completion_sms": await _ensure_for_tenant(
            tenant_id, "job_completion_sms", _job_completion_sms_doc,
        ),
    }


async def run() -> Dict[str, Any]:
    """Iterate every tenant. Insert missing rows for both codes.
    Idempotent — reruns are no-ops for already-seeded tenants.

    Returns a summary dict for the P21 structural-migration logger.
    """
    tenants_scanned = 0
    portal_invite_seeded = 0
    job_completion_seeded = 0
    async for t in config.db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        if not tid:
            continue
        tenants_scanned += 1
        try:
            res = await seed_for_tenant(tid)
        except Exception as exc:  # noqa: BLE001
            config.logger.warning(
                "[te-portal-job] seed failed for tenant=%s: %s", tid, exc,
            )
            continue
        if res["portal_invite_email"]:
            portal_invite_seeded += 1
        if res["job_completion_sms"]:
            job_completion_seeded += 1
        config.logger.info(
            "[te-portal-job] tenant %s: portal_invite_email=%s "
            "job_completion_sms=%s", tid,
            "seeded" if res["portal_invite_email"] else "already present",
            "seeded" if res["job_completion_sms"] else "already present",
        )
    config.logger.info(
        "[te-portal-job] seed complete — tenants_scanned=%s "
        "portal_invite_seeded=%s job_completion_seeded=%s",
        tenants_scanned, portal_invite_seeded, job_completion_seeded,
    )
    return {
        "tenants_scanned": tenants_scanned,
        "portal_invite_seeded": portal_invite_seeded,
        "job_completion_seeded": job_completion_seeded,
    }
