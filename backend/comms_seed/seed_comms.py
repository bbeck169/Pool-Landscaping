"""Communications Subsystem · Phase 1 — Seed the 6 email + 4 SMS + 5
automation system rows into MongoDB.

Idempotent — safe to run on every startup. Runs from
``server.py::_background_seed()`` and uses ``upsert``-style writes so
existing custom fields aren't clobbered.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db, logger
from services.comm_tokens import extract_tokens

from comms_seed.system_data import (
    SYSTEM_EMAIL_TEMPLATES, SYSTEM_SMS_TEMPLATES, SYSTEM_AUTOMATION_RULES, now_iso,
)


async def _upsert_email_template(t: Dict[str, Any]) -> str:
    doc = {
        "tenant_id": None,
        "code": t["code"],
        "name": t["name"],
        "description": t.get("description") or "",
        "subject": t["subject"],
        "blocks_json": t["blocks_json"],
        "is_system": True,
        "is_customer_facing": True,
        "version": 1,
        "updated_at": now_iso(),
    }
    existing = await db.email_templates.find_one(
        {"code": t["code"], "is_system": True, "tenant_id": None}, {"_id": 1})
    if existing:
        await db.email_templates.update_one(
            {"_id": existing["_id"]},
            {"$set": doc})
        return "updated"
    doc["created_at"] = doc["updated_at"]
    await db.email_templates.insert_one(doc)
    return "inserted"


async def _upsert_sms_template(t: Dict[str, Any]) -> str:
    doc = {
        "tenant_id": None,
        "code": t["code"],
        "name": t["name"],
        "body": t["body"],
        "mms_image_url": t.get("mms_image_url"),
        "tokens_referenced": extract_tokens(t["body"]),
        "is_system": True,
        "version": 1,
        "updated_at": now_iso(),
    }
    existing = await db.sms_templates.find_one(
        {"code": t["code"], "is_system": True, "tenant_id": None}, {"_id": 1})
    if existing:
        await db.sms_templates.update_one({"_id": existing["_id"]}, {"$set": doc})
        return "updated"
    doc["created_at"] = doc["updated_at"]
    await db.sms_templates.insert_one(doc)
    return "inserted"


async def _upsert_automation_rule(r: Dict[str, Any]) -> str:
    doc = {
        "tenant_id": None,
        "code": r["code"],
        "name": r["name"],
        "description": r.get("description") or "",
        "trigger_event": r["trigger_event"],
        "trigger_conditions": r.get("trigger_conditions") or {},
        "channel": r["channel"],
        "template_code": r["template_code"],
        "send_delay_minutes": int(r.get("send_delay_minutes") or 0),
        "active": False,       # seeded off so nothing fires accidentally
        "is_system": True,
        "updated_at": now_iso(),
    }
    existing = await db.automation_rules.find_one(
        {"code": r["code"], "is_system": True, "tenant_id": None}, {"_id": 1})
    if existing:
        # Preserve caller-set `active` and `fire_count`/`last_fired_at`.
        await db.automation_rules.update_one(
            {"_id": existing["_id"]},
            {"$set": {k: v for k, v in doc.items() if k not in ("active",)}})
        return "updated"
    doc["created_at"] = doc["updated_at"]
    doc["fire_count"] = 0
    doc["last_fired_at"] = None
    await db.automation_rules.insert_one(doc)
    return "inserted"


async def _ensure_indexes() -> None:
    try:
        await db.email_templates.create_index([("tenant_id", 1), ("code", 1)], unique=True)
        await db.sms_templates.create_index([("tenant_id", 1), ("code", 1)], unique=True)
        await db.automation_rules.create_index([("tenant_id", 1), ("trigger_event", 1), ("active", 1)])
        await db.communication_sends.create_index([("tenant_id", 1), ("status", 1), ("queued_at", 1)])
        await db.communication_sends.create_index([("tenant_id", 1), ("recipient_id", 1), ("sent_at", -1)])
        await db.communication_opt_outs.create_index(
            [("tenant_id", 1), ("contact_email", 1), ("channel", 1)], unique=True, sparse=True)
        await db.communication_opt_outs.create_index(
            [("tenant_id", 1), ("contact_phone", 1), ("channel", 1)], unique=True, sparse=True)
    except Exception as e:
        logger.warning(f"comms_seed: index creation partially failed: {e}")


async def seed_comms() -> Dict[str, int]:
    """Idempotent seed. Returns counts of each collection after run."""
    await _ensure_indexes()

    inserted_email = updated_email = 0
    for t in SYSTEM_EMAIL_TEMPLATES:
        r = await _upsert_email_template(t)
        if r == "inserted":
            inserted_email += 1
        else:
            updated_email += 1

    inserted_sms = updated_sms = 0
    for t in SYSTEM_SMS_TEMPLATES:
        r = await _upsert_sms_template(t)
        if r == "inserted":
            inserted_sms += 1
        else:
            updated_sms += 1

    inserted_auto = updated_auto = 0
    for r in SYSTEM_AUTOMATION_RULES:
        rr = await _upsert_automation_rule(r)
        if rr == "inserted":
            inserted_auto += 1
        else:
            updated_auto += 1

    logger.info(
        "seed_comms: email={ins}+{upd}={total_e}  sms={sins}+{supd}={total_s}  "
        "automations={ains}+{aupd}={total_a}".format(
            ins=inserted_email, upd=updated_email,
            total_e=inserted_email + updated_email,
            sins=inserted_sms, supd=updated_sms,
            total_s=inserted_sms + updated_sms,
            ains=inserted_auto, aupd=updated_auto,
            total_a=inserted_auto + updated_auto))

    return {
        "email_templates_total": inserted_email + updated_email,
        "email_templates_inserted": inserted_email,
        "sms_templates_total": inserted_sms + updated_sms,
        "sms_templates_inserted": inserted_sms,
        "automation_rules_total": inserted_auto + updated_auto,
        "automation_rules_inserted": inserted_auto,
    }


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    print(asyncio.run(seed_comms()))
