"""Feb-2026 · Phase 21 — Rebrand AquaTerra → Pool & Landscaping of Vistancia.

Idempotent, one-shot migration invoked from ``server._background_seed``
on every cold boot. Second run is a no-op — every step short-circuits
on the "already migrated" state.

Guardrails
----------
* Slug ``aquaterra`` is preserved as the canonical slug for backward
  compatibility with existing links / NFC URLs / hard-coded references.
  A ``slug_aliases: ["plofv"]`` field is added so ``plofv`` also
  resolves (see ``routers/tenants::get_current_tenant`` +
  ``routers/auth::signup``).
* Foreign keys are NOT rewritten — ``_id`` and ``id`` are untouched.
* Demo user emails (``@aquaterra.com``) are LEFT AS-IS — they are
  historical demo credentials the tester + human verification depend
  on. New real users use ``plofv.com`` domains.

Steps
-----
1. Tenant record — ``name`` → "Pool & Landscaping of Vistancia";
   ``slug_aliases`` += ``["plofv"]``.
2. ``settings.business_card`` — fill in every required field
   (idempotent — never overwrites a value that already differs from
   the AquaTerra defaults).
3. ``settings.email_sender`` — set the Vistancia transactional sender
   identity.
4. ``settings.internal_lead_notifications.email_to`` — verify equals
   ``brian@plofv.com``.
5. ``settings.primary_app_domain`` — introduce the field with default
   ``None`` (soft-override picked up by URL builders when non-null).
"""
from __future__ import annotations

from typing import Any, Dict

from config import db, logger
from utils import now_iso


NEW_TENANT_NAME = "Pool & Landscaping of Vistancia"
SLUG_ALIAS = "plofv"

PRIMARY_APP_DOMAIN = "https://app.plofv.com"  # Phase 21 · activation — live once DNS is up

BUSINESS_CARD = {
    "company_name": NEW_TENANT_NAME,
    "tagline": "Your trusted local pool & landscaping pros in Vistancia.",
    "service_area": "Peoria & Vistancia, Arizona",
    "phone": "602-887-4400",
    # Feb-2026 · Customer-facing brand email. User confirmed the
    # ``{{COMPANY_EMAIL}}`` merge tag should render the customer-
    # service alias, not the owner's personal inbox.
    "email": "cs@plofv.com",
    "website_url": "https://www.poolandlandscapingofvistancia.com/",
}

EMAIL_SENDER = {
    "from_name": NEW_TENANT_NAME,
    "from_email": "noreply@plofv.com",
    "reply_to": "brian@plofv.com",
}

INTERNAL_LEAD_EMAIL = "brian@plofv.com"


def _apply_tenant_config_updates(
    tenant: Dict[str, Any], report: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the ``$set`` patch that rebrands tenant metadata +
    settings. Split out from ``run()`` (Batch 2 · complexity refactor)
    so the config-vs-DB concerns are isolated. Mutates ``report`` in
    place with per-field booleans + lists."""
    sets: Dict[str, Any] = {}
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    lead_notif = settings.get("internal_lead_notifications") or {}

    # 1. Tenant name.
    if tenant.get("name") != NEW_TENANT_NAME:
        sets["name"] = NEW_TENANT_NAME
        report["name_changed"] = True

    # 2. Slug aliases (list-safe — union without duplicates).
    aliases = list(tenant.get("slug_aliases") or [])
    if SLUG_ALIAS not in aliases:
        aliases.append(SLUG_ALIAS)
        sets["slug_aliases"] = aliases
        report["slug_alias_added"] = True

    # 3. Business card — add MISSING fields only. Never overwrite an
    #    admin-authored value.
    added_card = []
    for k, v in BUSINESS_CARD.items():
        if not card.get(k):
            sets[f"settings.business_card.{k}"] = v
            added_card.append(k)
    if added_card:
        report["business_card_fields_added"] = added_card

    # 3b. Business card — one-off upgrade of the known-legacy email
    # value. Prior versions of this migration seeded
    # ``brian@plofv.com`` into the customer-facing brand email; user
    # has since confirmed the ``{{COMPANY_EMAIL}}`` merge tag should
    # render the customer-service alias. Idempotent — once flipped
    # the branch never fires again. Admin-authored values (anything
    # other than the exact legacy string) are preserved.
    if card.get("email") == "brian@plofv.com":
        sets["settings.business_card.email"] = BUSINESS_CARD["email"]
        report["business_card_email_upgraded_from_legacy"] = True

    # 4. Email sender identity — set if missing / partial.
    current_sender = settings.get("email_sender") or {}
    sender_missing = any(
        current_sender.get(k) != EMAIL_SENDER[k] for k in EMAIL_SENDER
    )
    if sender_missing:
        sets["settings.email_sender"] = EMAIL_SENDER
        report["email_sender_set"] = True

    # 5. Internal lead notification email.
    if lead_notif.get("email_to") != INTERNAL_LEAD_EMAIL:
        sets["settings.internal_lead_notifications.email_to"] = INTERNAL_LEAD_EMAIL
        report["internal_lead_email_set"] = True

    # 6. Primary app domain — set only when currently unset.
    if "primary_app_domain" not in settings \
            or settings.get("primary_app_domain") is None:
        sets["settings.primary_app_domain"] = PRIMARY_APP_DOMAIN
        report["primary_app_domain_field_added"] = True

    return sets


async def _refresh_ai_knowledge_base_seed(
    tenant: Dict[str, Any], report: Dict[str, Any],
) -> None:
    """Rewrite the seeded ``ai_knowledge_base`` company_profile doc iff
    it still carries the AquaTerra-branded seed AND was never edited
    by a human. Admin edits are preserved. Split out from ``run()``
    for the same reason as ``_apply_tenant_config_updates``."""
    kb_updates = await db.ai_knowledge_base.update_many(
        {
            "tenant_id": tenant["id"],
            "kind": "company_profile",
            "created_by": "system",
            "content_md": {"$regex": "^# AquaTerra"},
        },
        {"$set": {
            "title": "Pool & Landscaping of Vistancia — Company Profile",
            "content_md": (
                "# Pool & Landscaping of Vistancia\n\n"
                "We service the greater Peoria & Vistancia, Arizona area.\n\n"
                "**Services:** recurring pool maintenance, salt cell + filter cleaning, "
                "one-off repairs, landscaping crews.\n\n"
                "**Brand voice:** friendly, direct, no fluff. Never quote prices without "
                "admin approval. Techs never see prices.\n\n"
                "**Escalation:** for billing questions route to admin; for scheduling "
                "changes offer earliest available."
            ),
            "updated_at": now_iso(),
        }},
    )
    report["ai_knowledge_base_profiles_rebranded"] = int(
        getattr(kb_updates, "modified_count", 0) or 0
    )
    if report["ai_knowledge_base_profiles_rebranded"]:
        logger.info(
            "[phase21] refreshed %s ai_knowledge_base company_profile row(s)",
            report["ai_knowledge_base_profiles_rebranded"],
        )


async def run() -> Dict[str, Any]:
    """Runs the migration on every boot. Idempotent.

    Orchestrates two extracted helpers (Batch 2 · complexity refactor):
      * ``_apply_tenant_config_updates`` — tenant metadata + settings
      * ``_refresh_ai_knowledge_base_seed`` — company_profile refresh
    """
    report: Dict[str, Any] = {
        "tenant_found": False,
        "name_changed": False,
        "slug_alias_added": False,
        "business_card_fields_added": [],
        "email_sender_set": False,
        "internal_lead_email_set": False,
        "primary_app_domain_field_added": False,
    }

    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        logger.info(
            "[phase21] aquaterra tenant not found — skipping rebrand migration")
        return report
    report["tenant_found"] = True

    sets = _apply_tenant_config_updates(tenant, report)

    if sets:
        sets["updated_at"] = now_iso()
        sets["rebrand_phase21_applied_at"] = now_iso()
        await db.tenants.update_one({"id": tenant["id"]}, {"$set": sets})
        logger.info(
            "[phase21] rebrand applied — tenant=%s changes=%s",
            tenant["id"], sorted(list(sets.keys())),
        )
    else:
        logger.info("[phase21] rebrand already applied — no changes")

    await _refresh_ai_knowledge_base_seed(tenant, report)
    return report
