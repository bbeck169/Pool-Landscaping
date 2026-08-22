"""Feb-2026 · P18 — Seed PLOFV tenant lead-alert recipients.

Idempotent — safe to re-run on every boot / manual invocation.

Populates the PLOFV (Pool & Landscaping of Vistancia) tenant with:
  * ``lead_alert_sms_recipients: ["+16028874400"]``
  * ``lead_alert_email_recipients: ["brian@plofv.com"]``

The tenant currently lives under ``slug: "aquaterra"`` (name: "Pool
& Landscaping of Vistancia") — the seed uses ``slug`` to locate the
row so a rename won't misfire.

Idempotency contract: if EITHER recipient list already has a value,
we treat the seed as done and log ``skip`` — no clobbering
customer-configured recipients.  Only when BOTH lists are empty (or
missing entirely) do we write the P18 defaults.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Any

from config import db, logger


PLOFV_SMS_DEFAULTS = ["+16028874400"]
PLOFV_EMAIL_DEFAULTS = ["brian@plofv.com"]
PLOFV_SLUG = "aquaterra"  # tenant name: "Pool & Landscaping of Vistancia"


async def seed_plofv_lead_alerts() -> Dict[str, Any]:
    """Populate PLOFV's ``lead_alert_*`` recipient lists idempotently."""
    tenant = await db.tenants.find_one(
        {"slug": PLOFV_SLUG},
        {"_id": 0, "id": 1, "slug": 1,
          "lead_alert_sms_recipients": 1,
          "lead_alert_email_recipients": 1},
    )
    if not tenant:
        logger.warning(f"[p18-seed] tenant slug={PLOFV_SLUG} not found")
        return {"status": "tenant_missing"}

    existing_sms = tenant.get("lead_alert_sms_recipients") or []
    existing_email = tenant.get("lead_alert_email_recipients") or []
    if existing_sms or existing_email:
        logger.info(
            f"[p18-seed] tenant {tenant['id']} already has recipients "
            f"(sms={len(existing_sms)}, email={len(existing_email)}) — skip"
        )
        return {
            "status": "skipped_already_configured",
            "tenant_id": tenant["id"],
            "sms_count": len(existing_sms),
            "email_count": len(existing_email),
        }

    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {
            "lead_alert_sms_recipients": PLOFV_SMS_DEFAULTS,
            "lead_alert_email_recipients": PLOFV_EMAIL_DEFAULTS,
        }},
    )
    logger.info(
        f"[p18-seed] tenant {tenant['id']} seeded with "
        f"sms={PLOFV_SMS_DEFAULTS}, email={PLOFV_EMAIL_DEFAULTS}"
    )
    return {
        "status": "seeded",
        "tenant_id": tenant["id"],
        "sms_recipients": PLOFV_SMS_DEFAULTS,
        "email_recipients": PLOFV_EMAIL_DEFAULTS,
    }


if __name__ == "__main__":
    print(asyncio.run(seed_plofv_lead_alerts()))
