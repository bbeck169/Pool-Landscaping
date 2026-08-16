#!/usr/bin/env python3
"""One-shot admin helper — promote / update a user's role.

Usage::

    cd /app/backend
    python3 -m scripts.promote_user --email brian@plofv.com --role super_admin
    python3 -m scripts.promote_user --email new@x.com --role admin \
        --first-name New --last-name Person --tenant-id <uuid> \
        --temp-password 'password123' --create-if-missing

Behaviour:
  * User exists → update ``role`` + ``active=true`` + ``updated_at``. Password
    left untouched.
  * User missing + ``--create-if-missing`` set → insert a fresh doc using
    the same field shape as ``routers/auth.py`` produces (``password_hash``
    via ``utils.hash_password``, ``must_change_password_on_next_login=True``).
  * User missing + no flag → exit 2 without side effects.

Committable — no secrets baked in, all inputs come from CLI args.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

# Deferred imports so `--help` works without a Mongo connection.
def _late_imports():
    from config import db  # noqa: WPS433
    from utils import hash_password, new_id, now_iso  # noqa: WPS433
    return db, hash_password, new_id, now_iso


def _redact(doc: dict) -> dict:
    """Mask hashes + ``_id`` for safe log output."""
    if not doc:
        return {}
    out = {}
    for k, v in doc.items():
        if k in ("_id",):
            continue
        if k in ("password_hash", "hashed_password", "password"):
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out


async def _resolve_tenant_id(db, hint_email: str | None) -> str | None:
    if hint_email:
        row = await db.users.find_one({"email": hint_email}, {"tenant_id": 1})
        if row and row.get("tenant_id"):
            return row["tenant_id"]
    # Fallback: exactly one tenant in the DB → use it. Otherwise refuse.
    tenants = await db.tenants.find(
        {"active": {"$ne": False}}, {"id": 1, "name": 1},
    ).to_list(length=10)
    if len(tenants) == 1:
        return tenants[0].get("id")
    return None


async def _run(args) -> int:
    db, hash_password, new_id, now_iso = _late_imports()
    email = args.email.strip().lower()

    existing = await db.users.find_one({"email": email})
    if existing:
        prev_role = existing.get("role")
        upd = {
            "role": args.role,
            "active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            # Idempotent auth-counter reset — a promoted super_admin
            # shouldn't be one bad-password-attempt away from a lockout.
            # Password itself is left untouched per guardrail.
            "failed_login_attempts": 0,
            "lockout_until": None,
        }
        await db.users.update_one({"email": email}, {"$set": upd})
        after = await db.users.find_one({"email": email})
        print(json.dumps({
            "case": "A_update",
            "email": email,
            "previous_role": prev_role,
            "new_role": args.role,
            "tenant_id": after.get("tenant_id"),
            "before_redacted": _redact(existing),
            "after_redacted": _redact(after),
        }, indent=2, default=str))
        return 0

    if not args.create_if_missing:
        print(json.dumps({
            "case": "B_missing_no_create",
            "email": email,
            "hint": "pass --create-if-missing to insert a fresh doc",
        }, indent=2))
        return 2

    tenant_id = args.tenant_id or await _resolve_tenant_id(
        db, args.tenant_hint_email,
    )
    if not tenant_id:
        print(json.dumps({
            "case": "B_ambiguous_tenant",
            "email": email,
            "hint": "pass --tenant-id or --tenant-hint-email so the script "
                    "can resolve the tenant unambiguously",
        }, indent=2))
        return 3

    temp_password = args.temp_password
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": new_id(),
        "email": email,
        "first_name": args.first_name or "",
        "last_name": args.last_name or "",
        "name": f"{args.first_name or ''} {args.last_name or ''}".strip() or email,
        "role": args.role,
        "tenant_id": tenant_id,
        "active": True,
        "password_hash": hash_password(temp_password),
        "must_change_password_on_next_login": True,
        "failed_login_attempts": 0,
        "lockout_until": None,
        "auto_clockin_enabled": False,
        "hourly_rate_cents": None,
        "department": None,
        "phone": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(doc)
    after = await db.users.find_one({"email": email})
    print(json.dumps({
        "case": "B_created",
        "email": email,
        "tenant_id": tenant_id,
        "temporary_password": temp_password,
        "after_redacted": _redact(after),
    }, indent=2, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--role", required=True,
                     choices=("customer", "technician", "manager",
                              "admin", "super_admin"))
    ap.add_argument("--first-name", default=None)
    ap.add_argument("--last-name", default=None)
    ap.add_argument("--tenant-id", default=None,
                     help="Tenant to place the user in when creating.")
    ap.add_argument("--tenant-hint-email", default=None,
                     help="Existing user's email — reuse their tenant_id.")
    ap.add_argument("--temp-password", default="password123",
                     help="Only used on create. Default is deliberately "
                          "guessable so the operator can hand it off.")
    ap.add_argument("--create-if-missing", action="store_true")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
