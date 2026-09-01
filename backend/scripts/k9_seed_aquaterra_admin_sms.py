"""Phase K9 · Feb-2026 — one-shot seed for aquaterra (plofv) admin SMS phone.

Sets ``tenants.admin_sms_notify_to = "+16028874400"`` on the
``aquaterra`` tenant (slug also aliased to ``plofv``).  Dry-run by
default; pass ``--apply`` to persist.  NEVER wired into the boot
seed pipeline — must be invoked explicitly by ops.

    python -m scripts.k9_seed_aquaterra_admin_sms                # dry-run
    python -m scripts.k9_seed_aquaterra_admin_sms --apply         # persist

Idempotent: re-running after apply is a no-op (compares the current
value first).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv


ADMIN_PHONE = "+16028874400"
TENANT_SLUG = "aquaterra"


async def _run(apply: bool) -> int:
    load_dotenv("/app/backend/.env")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    t = await db.tenants.find_one(
        {"$or": [{"slug": TENANT_SLUG},
                 {"slug_aliases": "plofv"}]},
        {"_id": 0, "id": 1, "slug": 1, "name": 1,
         "admin_sms_notify_to": 1, "rc_sms_from_number": 1},
    )
    if not t:
        print(f"[k9-seed] tenant slug={TENANT_SLUG} not found — nothing to do.")
        return 1
    current = t.get("admin_sms_notify_to")
    if current == ADMIN_PHONE:
        print(f"[k9-seed] tenant {t['slug']} already has admin_sms_notify_to={ADMIN_PHONE} — no-op.")
        return 0
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[k9-seed] {mode}  tenant={t['slug']} ({t.get('name')})")
    print(f"[k9-seed]   was:  {current!r}")
    print(f"[k9-seed]   now:  {ADMIN_PHONE!r}")
    print(f"[k9-seed]   rc_sms_from_number: {t.get('rc_sms_from_number')!r}")
    if apply:
        r = await db.tenants.update_one(
            {"id": t["id"]},
            {"$set": {"admin_sms_notify_to": ADMIN_PHONE}},
        )
        print(f"[k9-seed] modified_count={r.modified_count}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Phase K9 seed — set aquaterra tenant admin_sms_notify_to",
    )
    p.add_argument("--apply", action="store_true",
                    help="Persist. Default is a dry-run.")
    args = p.parse_args()
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    sys.exit(main())
