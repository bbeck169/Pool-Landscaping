#!/usr/bin/env python3
"""Demo-convenience script · Reset all seeded demo-user passwords to
``password123`` and clear their lockout state.

This is the counterpart to ``rotate_demo_passwords.py``. Use this when you
want the classic ``password123`` demo experience back (pod-owner-friendly,
tester-friendly, cross-suite pytest compatible). The rotation script is
still available when you want strong random tokens for a security review.

**This does NOT change any security gate.**

- ``SEED_DEMO_USERS`` stays wherever the operator set it (``0`` in prod,
  ``1`` in dev/preview).
- Every SEC-* hardening (tenant scoping, audit logging, deactivation
  enforcement, CORS allowlist, JWT strict-mode, signature size cap, digest
  recipient allowlist) is untouched — this script only writes new bcrypt
  hashes to five specific rows in ``db.users`` and rewrites
  ``/app/memory/test_credentials.md``.

Never runs on boot. Explicit invocation only.

    cd /app/backend && python3 scripts/reset_demo_passwords_to_default.py
"""
from __future__ import annotations
import asyncio, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from utils import hash_password  # noqa: E402

DEFAULT_PW = "password123"

DEMO_EMAILS = [
    ("super@aquaterra.com",    "super_admin"),
    ("admin@aquaterra.com",    "admin"),
    ("mike@aquaterra.com",     "pool_tech"),
    ("carlos@aquaterra.com",   "landscape_tech"),
    ("customer@aquaterra.com", "customer"),
]

CREDS_PATH = Path("/app/memory/test_credentials.md")


async def _reset() -> list[tuple[str, str, bool]]:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    hashed = hash_password(DEFAULT_PW)
    out: list[tuple[str, str, bool]] = []
    for email, role_hint in DEMO_EMAILS:
        existing = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "role": 1})
        if not existing:
            out.append((email, role_hint, False))
            continue
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {
                "password_hash": hashed,
                "failed_login_attempts": 0,
                "lockout_until": None,
                "active": True,
            }},
        )
        out.append((email, existing.get("role") or role_hint, True))
    client.close()
    return out


def _write_credentials(rows: list[tuple[str, str, bool]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Test Credentials — Pool & Landscaping of Vistancia",
        "",
        f"> Reset to password123 by reset_demo_passwords_to_default.py on {now} (demo mode)",
        "",
        "## Auth mechanism",
        "- POST `/api/auth/login` with `{email, password}` returns `{access_token, user}`.",
        "- Tokens are Bearer JWTs — send `Authorization: Bearer <token>` on every subsequent call.",
        "- Demo mode: all seeded accounts share the plaintext `password123`. Rotate with `scripts/rotate_demo_passwords.py` for a security review.",
        "",
        "## Accounts",
    ]
    for email, role, ok in rows:
        if ok:
            lines.append(f"- **{role}** · `{email}` · `password123`")
        else:
            lines.append(f"- **{role}** · `{email}` · _(user row not present; skipped)_")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Landscape techs carry `role: \"technician\"` + `department: \"landscaping\"` and are required to")
    lines.append("  finalize their onboarding checklist before route assignment.")
    lines.append("- Emergent LLM key, Resend API key, Stripe test/live keys are in `/app/backend/.env`.")
    lines.append("- `SEED_DEMO_USERS` gate is unchanged — production still refuses to seed these demo users.")
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = asyncio.run(_reset())
    _write_credentials(rows)
    ok_count = sum(1 for r in rows if r[2])
    print(f"Reset {ok_count} / {len(rows)} demo accounts to '{DEFAULT_PW}'.")
    for email, role, ok in rows:
        marker = "OK " if ok else "SKP"
        print(f"  [{marker}] {role:16s} {email}")
    print(f"Credentials file rewritten: {CREDS_PATH}")


if __name__ == "__main__":
    main()
