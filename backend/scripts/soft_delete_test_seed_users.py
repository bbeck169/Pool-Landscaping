#!/usr/bin/env python3
"""Feb-2026 · Data hygiene — soft-delete test-seed users.

Removes test-seed noise from the team roster / assignee dropdowns.
Idempotent. Reversible (soft delete only — sets ``active=false`` +
``soft_deleted_at`` + reason fields; no hard-delete, no cascade).

Detection patterns (email at ``@aquaterra.com`` or ``@plofv.com``):
  - ``tech-*`` · ``gps_*_tech`` · ``smoke_*`` · ``*_smoke_*`` infix
  - ``deact_*`` · ``test_*`` · ``qa_*`` · ``e2e_*`` · ``*_test`` suffix
  - ``g<N><letter>-*`` / ``g<N><letter>_*`` seed patterns
  - Name-based fallback: ``test | smoke | debug | dbg | qa``

Whitelist (NEVER soft-deleted):
  - ``super@aquaterra.com`` · ``admin@aquaterra.com`` ·
    ``manager@aquaterra.com`` · ``landscaper@aquaterra.com`` ·
    ``customer@aquaterra.com`` · ``brian@plofv.com``
  - Any ``super_admin`` role
  - Any external-domain email
  - Any user with a recent 2026 login timestamp (ambiguous — flagged
    for manual review, never auto-deleted)

Usage::
    # Dry-run — enumerate only, no writes:
    python3 -m scripts.soft_delete_test_seed_users \\
        --tenant-id 3814833a-dd0d-4bd9-90ea-351c24924649 --dry-run

    # Execute:
    python3 -m scripts.soft_delete_test_seed_users \\
        --tenant-id 3814833a-dd0d-4bd9-90ea-351c24924649 --confirm
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


WHITELIST_EMAILS = {
    "super@aquaterra.com", "admin@aquaterra.com", "manager@aquaterra.com",
    "landscaper@aquaterra.com", "customer@aquaterra.com",
    "brian@plofv.com",
}

PATTERNS = [
    (re.compile(r"^tech-.*@aquaterra\.com$", re.I), "tech-* prefix"),
    (re.compile(r"^gps_.*_tech@aquaterra\.com$", re.I), "gps_*_tech pattern"),
    (re.compile(r"^smoke_.*@aquaterra\.com$", re.I), "smoke_* prefix"),
    (re.compile(r".*_smoke_.*@aquaterra\.com$", re.I), "*_smoke_* infix"),
    (re.compile(r"^deact_.*@aquaterra\.com$", re.I), "deact_* prefix"),
    (re.compile(r"^test_.*@aquaterra\.com$", re.I), "test_* prefix"),
    (re.compile(r"^qa_.*@aquaterra\.com$", re.I), "qa_* prefix"),
    (re.compile(r"^e2e_.*@aquaterra\.com$", re.I), "e2e_* prefix"),
    (re.compile(r".*_test@aquaterra\.com$", re.I), "*_test suffix"),
    (re.compile(r"^g\d[a-z]-.*@aquaterra\.com$", re.I),
       "g<N><letter>-* seed pattern"),
    (re.compile(r"^g\d[a-z]_.*@aquaterra\.com$", re.I),
       "g<N><letter>_* seed pattern"),
]
NAME_PATTERNS = [re.compile(r"\b(test|smoke|debug|dbg|qa)\b", re.I)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _enumerate(db, tenant_id: str) -> Dict[str, List[Dict[str, Any]]]:
    candidates: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    async for u in db.users.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "name": 1,
         "first_name": 1, "last_name": 1, "active": 1,
         "last_login_at": 1, "soft_deleted_at": 1},
    ):
        email = (u.get("email") or "").lower()
        if not email:
            continue
        # Skip already soft-deleted (idempotency).
        if u.get("soft_deleted_at"):
            continue
        # Whitelist gates.
        if email in WHITELIST_EMAILS:
            continue
        if u.get("role") == "super_admin":
            continue
        if not (email.endswith("@aquaterra.com")
                 or email.endswith("@plofv.com")):
            continue
        matched_reason = None
        for pat, reason in PATTERNS:
            if pat.match(email):
                matched_reason = reason
                break
        if not matched_reason:
            name_bits = " ".join([u.get("name") or "",
                                    u.get("first_name") or "",
                                    u.get("last_name") or ""])
            for pat in NAME_PATTERNS:
                if pat.search(name_bits):
                    matched_reason = f"name-match:{pat.pattern}"
                    break
        if not matched_reason:
            continue
        # Ambiguity check — recent 2026 login timestamp = manual review.
        last_login = u.get("last_login_at")
        rec = {
            "id": u.get("id"),
            "email": u.get("email"),
            "role": u.get("role"),
            "reason": matched_reason,
        }
        if last_login and isinstance(last_login, str) and "2026" in last_login:
            rec["last_login_at"] = last_login
            ambiguous.append(rec)
        else:
            candidates.append(rec)
    return {"candidates": candidates, "ambiguous": ambiguous}


async def _soft_delete(db, tenant_id: str,
                        candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    now = _now_iso()
    ids = [c["id"] for c in candidates if c.get("id")]
    if not ids:
        return {"soft_deleted": 0, "audit_logged": 0, "failed": []}

    # Bulk update — one round-trip.
    upd = await db.users.update_many(
        {"id": {"$in": ids}, "tenant_id": tenant_id},
        {"$set": {
            "active": False,
            "soft_deleted_at": now,
            "soft_deleted_by": "data_hygiene_cleanup",
            "soft_delete_reason": "test_seed_cleanup",
            "updated_at": now,
        }},
    )

    # One audit-log entry per soft-delete.
    audit_rows = [{
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "event": "user.soft_delete",
        "actor": "data_hygiene_cleanup",
        "reason": "test_seed_cleanup",
        "target_user_id": c["id"],
        "target_email": c["email"],
        "target_role": c.get("role"),
        "match_reason": c.get("reason"),
        "created_at": now,
    } for c in candidates if c.get("id")]

    audit_logged = 0
    try:
        r = await db.audit_logs.insert_many(audit_rows, ordered=False)
        audit_logged = len(r.inserted_ids)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] audit_logs insert_many partial failure: {e}")

    return {
        "soft_deleted": int(upd.modified_count),
        "matched": int(upd.matched_count),
        "audit_logged": audit_logged,
        "failed": [],
    }


async def _run(tenant_id: str, *, dry_run: bool) -> Dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient
    import os
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        db = client[os.environ["DB_NAME"]]
        enum_res = await _enumerate(db, tenant_id)
        report: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "at": _now_iso(),
            "dry_run": dry_run,
            "candidate_count": len(enum_res["candidates"]),
            "ambiguous_count": len(enum_res["ambiguous"]),
            "candidate_emails": [c["email"] for c in enum_res["candidates"]],
            "ambiguous_emails": [c["email"] for c in enum_res["ambiguous"]],
        }
        if not dry_run and enum_res["candidates"]:
            del_res = await _soft_delete(
                db, tenant_id, enum_res["candidates"])
            report["execution"] = del_res
        return report
    finally:
        client.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant-id", required=True)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                       help="Enumerate only; do not write.")
    grp.add_argument("--confirm", action="store_true",
                       help="Actually perform the soft-delete.")
    args = ap.parse_args()

    report = asyncio.run(_run(
        args.tenant_id, dry_run=args.dry_run))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
