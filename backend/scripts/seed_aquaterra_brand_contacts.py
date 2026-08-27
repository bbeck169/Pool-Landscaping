"""Feb-2026 · One-shot seed — AquaTerra brand contact fields.

Populates the AquaTerra tenant's admin-editable Business Card fields
with real values so ``{{COMPANY_EMAIL}}`` / ``{{COMPANY_PHONE}}`` /
``{{COMPANY_WEBSITE}}`` resolve to the user's actual brand data at
send time.

Idempotent + guarded:
* Only touches the AquaTerra tenant (slug=aquaterra, alias=plofv).
* Skips fields that are already populated with a non-placeholder value.
* Leaves EVERY other tenant untouched.

Usage::

    python -m scripts.seed_aquaterra_brand_contacts

Safe to re-run.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional

from config import db, logger


AQUATERRA_TARGETS: Dict[str, str] = {
    "email": "cs@plofv.com",
    "phone": "602-887-4400",
    "website_url": "www.poolandlandscapingofvistancia.com",
}

# Values that count as "empty enough to overwrite". Anything else is
# treated as a real admin-set value and is preserved.
_PLACEHOLDER_MARKERS: Dict[str, set] = {
    "email": {"", "support@aquaterra.com", "contact@example.com"},
    "phone": {
        "", "+1 (623) 555-0100", "+1 (555) 555-0100",
        "(623) 555-0100", "(555) 555-0100", "623-555-0100",
    },
    "website_url": {
        "", "https://aquaterra.example.com",
        "https://example.com", "example.com",
    },
}


def _should_overwrite(existing: Optional[str], field: str) -> bool:
    if existing in (None, ""):
        return True
    return existing in _PLACEHOLDER_MARKERS.get(field, set())


async def seed_aquaterra_brand_contacts() -> Dict[str, Any]:
    tenant = await db.tenants.find_one(
        {"$or": [{"slug": "aquaterra"}, {"slug_aliases": "plofv"}]},
        {"_id": 0},
    )
    if not tenant:
        logger.warning("[seed_aquaterra_brand] no aquaterra tenant found — skipping")
        return {"ok": False, "reason": "aquaterra_tenant_missing"}

    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}

    updates: Dict[str, str] = {}
    skipped: Dict[str, str] = {}
    conflicts: Dict[str, Dict[str, str]] = {}
    for field, target in AQUATERRA_TARGETS.items():
        existing = card.get(field)
        if _should_overwrite(existing, field):
            updates[f"settings.business_card.{field}"] = target
        else:
            if existing != target:
                conflicts[field] = {"existing": existing, "requested": target}
                logger.warning(
                    f"[seed_aquaterra_brand] {field} already set to "
                    f"{existing!r} — requested {target!r} preserved as-is "
                    "(pass explicit override to change)"
                )
            skipped[field] = existing

    if not updates:
        logger.info(
            "[seed_aquaterra_brand] all fields already populated — "
            "no update needed"
        )
        return {"ok": True, "tenant_id": tenant["id"],
                 "updated": {}, "skipped": skipped,
                 "conflicts": conflicts}

    await db.tenants.update_one({"id": tenant["id"]}, {"$set": updates})
    logger.info(
        f"[seed_aquaterra_brand] updated tenant {tenant['id']} — "
        f"fields={list(updates.keys())}"
    )
    return {"ok": True, "tenant_id": tenant["id"],
             "updated": updates, "skipped": skipped,
             "conflicts": conflicts}


def _main() -> int:
    result = asyncio.get_event_loop().run_until_complete(
        seed_aquaterra_brand_contacts()
    )
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main())
