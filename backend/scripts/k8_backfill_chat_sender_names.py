"""Phase K8 · Feb-2026 — One-shot backfill for portal chat sender_name drift.

Motivation
----------
Prior to K8 the portal chat write path (backend/routers/portal_chats.py
lines 171 + 256 pre-fix) stamped ``sender_name`` from
``users.name`` on the sender's User row.  When the User row's ``name``
field went stale (portal-activation flows, admin seed drift, an old
customer-account re-link), the bubble carried the wrong name for
every message that user ever posted.  Reported case: Brian Beckman
was seeing his own outgoing bubbles rendered as "Jennifer Carson".

The K8 fix corrects the WRITE path so all NEW messages carry the
customer's authoritative name — but existing rows in
``db.portal_chat_messages`` still carry the drifted names.  This
script rewrites those rows in-place.

Safety
------
- Read-only unless invoked with ``--apply``. Default mode is a dry
  run that prints exactly what would change (and how many rows are
  already correct / already stale).
- Tenant-scoped: pass ``--tenant-id <UUID>`` to constrain the
  backfill.  Omit to run across every tenant on the pod.
- Idempotent: only rewrites rows where the newly-resolved name
  differs from the currently-stored ``sender_name``.
- NEVER touches ``sender_role == "admin"`` messages — the fix
  intentionally leaves admin/staff bubbles reading ``users.name``.
- Does not auto-run on boot.  Must be invoked explicitly:
      python -m scripts.k8_backfill_chat_sender_names --apply
- Prints a per-message audit line so ops can diff before/after.

Do NOT run against production without confirmation from the tenant
owner.  A single admin can re-run this any time — it's idempotent —
so there's no urgency to fire it blindly.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv


def _load_env() -> None:
    load_dotenv("/app/backend/.env")


async def _resolve_sender_name(
    db, tenant_id: str, sender_id: str,
) -> Optional[str]:
    """Re-derive the customer's canonical name.

    Mirrors backend/routers/portal_chats.py::_resolve_sender_name for
    the ``role == "customer"`` branch — the only branch the backfill
    touches.  Returns ``None`` when the sender user row or its linked
    customer row can't be resolved (leave the message untouched).
    """
    user = await db.users.find_one(
        {"id": sender_id},
        {"_id": 0, "name": 1, "email": 1, "role": 1,
         "customer_id": 1, "tenant_id": 1},
    )
    if not user:
        return None
    if (user.get("role") or "").lower() != "customer":
        # Not a customer bubble — leave admin/staff rows alone.
        return None
    cid = user.get("customer_id")
    if not cid:
        return None
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1,
         "last_name": 1, "full_name": 1},
    ) or {}
    name = (cust.get("name") or "").strip()
    if name:
        return name
    first = (cust.get("first_name") or "").strip()
    last = (cust.get("last_name") or "").strip()
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    full = (cust.get("full_name") or "").strip()
    if full:
        return full
    email = (user.get("email") or "").strip()
    if "@" in email:
        local = email.split("@", 1)[0]
        if local:
            return local
    return "Customer"


async def _run(tenant_id: Optional[str], apply: bool) -> Dict[str, int]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    query: Dict[str, Any] = {"sender_role": "customer"}
    if tenant_id:
        query["tenant_id"] = tenant_id

    total = 0
    ok = 0
    drift = 0
    rewrote = 0
    skipped = 0
    async for m in db.portal_chat_messages.find(
        query,
        {"_id": 0, "id": 1, "tenant_id": 1, "chat_id": 1,
         "sender_id": 1, "sender_name": 1, "created_at": 1},
    ):
        total += 1
        current = (m.get("sender_name") or "").strip()
        expected = await _resolve_sender_name(
            db, m["tenant_id"], m.get("sender_id") or "",
        )
        if expected is None:
            skipped += 1
            continue
        if current == expected:
            ok += 1
            continue
        drift += 1
        prefix = "[apply]" if apply else "[dry-run]"
        print(
            f"{prefix} msg={m['id']} chat={m.get('chat_id')} "
            f"created={m.get('created_at')}  "
            f"was={current!r}  ->  now={expected!r}"
        )
        if apply:
            r = await db.portal_chat_messages.update_one(
                {"id": m["id"]},
                {"$set": {"sender_name": expected}},
            )
            if r.modified_count == 1:
                rewrote += 1

    print()
    print("──────────── K8 backfill summary ────────────")
    print(f"  tenant_id     : {tenant_id or '(all)'}")
    print(f"  mode          : {'APPLY' if apply else 'DRY-RUN'}")
    print(f"  scanned       : {total}")
    print(f"  already correct: {ok}")
    print(f"  drift found   : {drift}")
    print(f"  skipped (no user/customer link): {skipped}")
    print(f"  rewritten     : {rewrote}")
    print("─────────────────────────────────────────────")

    return {
        "scanned": total, "ok": ok, "drift": drift,
        "skipped": skipped, "rewrote": rewrote,
    }


def main() -> int:
    _load_env()
    p = argparse.ArgumentParser(
        description="Phase K8 · Feb-2026 — backfill portal_chat_messages.sender_name",
    )
    p.add_argument(
        "--tenant-id", default=None,
        help="Restrict to a single tenant. Omit to sweep every tenant.",
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Persist the rewrites. Default is a dry-run — nothing is written.",
    )
    args = p.parse_args()
    asyncio.run(_run(args.tenant_id, args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
