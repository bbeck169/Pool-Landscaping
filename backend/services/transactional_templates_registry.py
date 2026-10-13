"""P2 #10a · Feb-2026 — Transactional-template registry.

Single source of truth for the canonical set of system-triggered
("transactional") template slugs. Marketing campaign templates
(admin-authored, sequence-driven) are NOT in this registry — they
live in ``db.marketing_templates`` without a ``code`` field. The
``code`` field presence IS the discriminator (per the P2 #10 audit
Flag 4 decision — zero schema change, matches existing data shape).

Who reads this
──────────────
* ``routers/marketing_templates.py`` — the ``PATCH`` validator mounts
  on ``row.code is not None`` and reads ``REGISTRY[code]
  ["required_tags"]`` to enforce fail-closed merge-tag presence.
* ``GET /marketing/transactional-registry`` (Commit 3) — serves the
  editor's docs panel with per-slug metadata.
* ``services/migrations/seed_transactional_templates_v1.py`` (Commit
  1) — iterates ``TRANSACTIONAL_SLUGS`` to decide what to seed.
* Pytest guardrails — ``test_p2_10a_transactional_registry_and_seed``
  pins the enumeration + required-tag non-emptiness per slug.

Design notes
────────────
* **No default subject / body text here.** Fallbacks live where
  they already live — ``services/customer_welcome_email.py``,
  ``services/quote_notifications.py``, ``services/completion_sms_template.py``,
  ``emailer.py``, etc. The registry is metadata only; duplicating
  fallback copy here would create a maintenance split-brain.
* **Required tags are a hard contract.** The ``PATCH`` validator
  returns 400 ``MISSING_REQUIRED_MERGE_TAGS`` when any listed tag
  is absent from the admin's edited subject+body. Optional tags
  are informational — editor UI renders them in the docs panel but
  does not enforce presence.
* **Enumeration must stay in sync with the already-wired call
  sites.** The 8 slugs below ARE already consumed by
  ``get_template_by_code`` / ``get_template_with_global_fallback``
  in production code paths (see P2 #10 audit Flag 1 for file:line
  attribution). The 3 MVP additions (welcome, decline-email,
  decline-sms) are wired in Commit 2 (``P2 #10b``).
* The 2 slugs flagged for TD-16 (``password_reset_email`` +
  ``portal_chat_admin_notify_sms``) are INCLUDED in the registry
  so the editor shows all admin-overridable templates — the
  "wiring sweep" entry covers migrating their send sites, not
  their presence in the registry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ─── Slug enumeration ────────────────────────────────────────────
# Alphabetical for grep stability. Any addition to this list MUST
# be accompanied by an entry in ``REGISTRY`` below.
TRANSACTIONAL_SLUGS: List[str] = [
    "completion_followup_sms",
    "estimate_reminder_email",
    "invoice_past_due_email",
    "lead_conversion_welcome_email",
    "lead_conversion_welcome_sms",
    "password_reset_email",            # TD-16: send-site still hardcoded
    "portal_chat_admin_notify_sms",    # TD-16: send-site still hardcoded
    "portal_invite_email",
    "quote_decline_admin_email",       # MVP — wired in Commit 2
    "quote_decline_admin_sms",         # MVP — wired in Commit 2
    "welcome_on_first_accept_email",   # MVP — wired in Commit 2
]


REGISTRY: Dict[str, Dict[str, Any]] = {
    "welcome_on_first_accept_email": {
        "channel": "email",
        "required_tags": ["company_name", "customer_first_name", "portal_url"],
        "optional_tags": ["company_phone", "logo_url"],
        "description": (
            "One-off welcome email sent when a customer accepts their "
            "first-ever quote. Gated by "
            "``tenant.welcome_email_on_first_accepted_quote_enabled`` "
            "(default True). Fires from ``services/customer_welcome_email.py``."
        ),
    },
    "quote_decline_admin_email": {
        "channel": "email",
        "required_tags": ["customer_name", "quote_number"],
        "optional_tags": ["decline_reason", "quote_total", "quote_url"],
        "description": (
            "Email notification to tenant admins when a customer "
            "declines a quote. Gated by ``tenant.notify_admin_on_decline`` "
            "(default True). Fires from "
            "``routers/estimate_viewer.py::_notify_admins_email_sms``."
        ),
    },
    "quote_decline_admin_sms": {
        "channel": "sms",
        "required_tags": ["customer_name", "quote_number"],
        "optional_tags": ["decline_reason"],
        "description": (
            "SMS notification to tenant admins when a customer declines "
            "a quote. Same gating + fire path as "
            "``quote_decline_admin_email`` (always paired)."
        ),
    },
    "lead_conversion_welcome_email": {
        "channel": "email",
        "required_tags": ["company_name", "customer_first_name", "portal_url"],
        "optional_tags": ["company_phone"],
        "description": (
            "Welcome email sent when a lead is converted to a customer "
            "(Close-Won pipeline). Already wired through "
            "``get_template_by_code`` in "
            "``services/lead_conversion_notifications.py``."
        ),
    },
    "lead_conversion_welcome_sms": {
        "channel": "sms",
        "required_tags": ["company_name", "customer_first_name"],
        "optional_tags": ["portal_url"],
        "description": (
            "Welcome SMS counterpart to ``lead_conversion_welcome_email``. "
            "Already wired."
        ),
    },
    "completion_followup_sms": {
        "channel": "sms",
        "required_tags": ["company_name", "customer_first_name"],
        "optional_tags": ["review_url"],
        "description": (
            "Service-complete follow-up SMS asking for a review. Already "
            "wired through ``get_template_by_code('job_completion_sms')`` "
            "in ``services/completion_sms_template.py``. **Legacy slug "
            "name on-disk: ``job_completion_sms`` — the registry uses "
            "the business-meaningful ``completion_followup_sms`` alias "
            "for the admin UI; the wire-level code remains "
            "``job_completion_sms`` for backward compat with the "
            "6 existing seeded tenants.**"
        ),
        "legacy_code_alias": "job_completion_sms",
    },
    "invoice_past_due_email": {
        "channel": "email",
        "required_tags": ["customer_name", "invoice_number", "amount_due", "pay_link"],
        "optional_tags": ["days_overdue", "company_name"],
        "description": (
            "Dunning email sent on past-due invoices. Already wired "
            "through ``get_template_with_global_fallback`` at "
            "``emailer.py:665``."
        ),
    },
    "estimate_reminder_email": {
        "channel": "email",
        "required_tags": ["customer_name", "estimate_number", "portal_url"],
        "optional_tags": ["expires_at", "company_name"],
        "description": (
            "Reminder email on open estimates nearing expiry. Already "
            "wired at ``emailer.py:844``."
        ),
    },
    "portal_invite_email": {
        "channel": "email",
        "required_tags": ["customer_first_name", "login_url", "temp_password"],
        "optional_tags": ["company_name"],
        "description": (
            "Email sent when an admin invites a customer to the portal. "
            "Already wired via ``get_template_by_code`` in "
            "``routers/portal_admin.py``."
        ),
    },
    "password_reset_email": {
        "channel": "email",
        "required_tags": ["reset_url", "expires_minutes"],
        "optional_tags": ["company_name"],
        "description": (
            "Password reset email with a one-time magic link. **Send "
            "site still hardcoded in ``routers/auth.py``** — see "
            "TD-16 for migration to ``get_template_by_code``."
        ),
    },
    "portal_chat_admin_notify_sms": {
        "channel": "sms",
        "required_tags": ["customer_name", "chat_url"],
        "optional_tags": ["preview"],
        "description": (
            "SMS to the configured portal-chat admin number when a "
            "customer sends a new portal chat message. **Send site "
            "still hardcoded in "
            "``services/portal_chat_sms_bridge.py``** — see TD-16 "
            "for migration."
        ),
    },
}


def get_slug(code: str) -> Optional[Dict[str, Any]]:
    """Return the registry entry for ``code`` or ``None``. Safe for
    arbitrary string input — the ``PATCH`` validator calls this with
    user-supplied ``code`` values (which come from existing DB rows,
    not request bodies, but defense-in-depth matters)."""
    if not code:
        return None
    return REGISTRY.get(code)


def all_slugs() -> List[Dict[str, Any]]:
    """Return the full registry as a list of ``{code, …}`` dicts,
    sorted alphabetically. Served by the Commit-3 endpoint
    ``GET /marketing/transactional-registry`` for the editor docs
    panel."""
    return [
        {"code": code, **entry}
        for code, entry in sorted(REGISTRY.items())
    ]
