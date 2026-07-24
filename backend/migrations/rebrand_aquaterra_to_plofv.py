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

BUSINESS_CARD = {
    "company_name": NEW_TENANT_NAME,
    "tagline": "Your trusted local pool & landscaping pros in Vistancia.",
    "service_area": "Peoria & Vistancia, Arizona",
    "phone": "602-887-4400",
    "email": "brian@plofv.com",
    "website_url": "https://www.poolandlandscapingofvistancia.com/",
}

EMAIL_SENDER = {
    "from_name": NEW_TENANT_NAME,
    "from_email": "noreply@plofv.com",
    "reply_to": "brian@plofv.com",
}

INTERNAL_LEAD_EMAIL = "brian@plofv.com"


async def run() -> Dict[str, Any]:
    """Runs the migration on every boot. Idempotent."""
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
        logger.info("[phase21] aquaterra tenant not found — skipping rebrand migration")
        return report
    report["tenant_found"] = True

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

    # 4. Email sender identity — set if missing / partial.
    current_sender = settings.get("email_sender") or {}
    sender_missing = any(
        current_sender.get(k) != EMAIL_SENDER[k] for k in EMAIL_SENDER
    )
    if sender_missing:
        sets["settings.email_sender"] = EMAIL_SENDER
        report["email_sender_set"] = True

    # 5. Internal lead notification email verify.
    if lead_notif.get("email_to") != INTERNAL_LEAD_EMAIL:
        sets["settings.internal_lead_notifications.email_to"] = INTERNAL_LEAD_EMAIL
        report["internal_lead_email_set"] = True

    # 6. Primary app domain — introduce the field with None default
    #    so the URL builder helper can distinguish "unset" (fall back
    #    to request.base_url) from "set to empty" (also fallback).
    if "primary_app_domain" not in settings:
        sets["settings.primary_app_domain"] = None
        report["primary_app_domain_field_added"] = True

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

    # 7. Refresh the seeded ai_knowledge_base company_profile doc IFF
    #    it still holds the AquaTerra-branded seed content AND was
    #    never edited by a human (``created_by == "system"``). Admin
    #    edits are preserved.
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

    return report
