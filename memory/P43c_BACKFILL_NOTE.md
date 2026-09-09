# Optional backfill — `users.password_updated_at → customers.portal_password_set_at`

**Flagged Feb 2026 · P43c.** Zero-risk historical enrichment for the
Customers list "Portal status" filter.

## Context

The P43c-corrected filter reads two customer-doc signals:
- `portal_password_set_at` — customer chose their own password.
- `last_portal_login_at` — customer signed in at least once.

The first field was **added in the same P43c ship** and is stamped
going forward by both password-reset flow (`_apply_new_password`)
and in-portal change-password (`change_my_password`).

Customers who did a self-serve password reset *before* the P43c
ship have `users.password_updated_at` set (dating from the reset
event) but no `customers.portal_password_set_at`. They still
surface correctly under the corrected filter as long as they've
signed in at least once post-reset (`last_portal_login_at` fires
on every login), which every practical password-reset UX
guarantees. Users who reset but never came back are the only
possible false-negative — a corner case we accept.

## Proposed backfill (opt-in, one-shot, ~5-10 lines)

```python
# app/backend/scripts/backfill_p43c_password_set_at.py
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import dotenv_values

async def main():
    env = dotenv_values("/app/backend/.env")
    db = AsyncIOMotorClient(env["MONGO_URL"])[env["DB_NAME"]]
    cursor = db.users.find(
        {"role": "customer",
          "password_updated_at": {"$exists": True, "$nin": [None, ""]},
          "customer_id": {"$exists": True}},
        {"_id": 0, "customer_id": 1, "tenant_id": 1,
          "password_updated_at": 1},
    )
    n = 0
    async for u in cursor:
        r = await db.customers.update_one(
            {"id": u["customer_id"], "tenant_id": u.get("tenant_id"),
              "$or": [{"portal_password_set_at": {"$exists": False}},
                       {"portal_password_set_at": None},
                       {"portal_password_set_at": ""}]},
            {"$set": {"portal_password_set_at": u["password_updated_at"]}},
        )
        n += r.modified_count
    print(f"backfilled portal_password_set_at on {n} customer rows")

if __name__ == "__main__":
    asyncio.run(main())
```

## Why NOT auto-shipped

Per user directive (Feb 2026): "Do NOT ship it now unless it's
less than 10 lines and zero risk." The script is under 10 lines
of business logic but running it is a data-migration decision that
should be explicit — not folded into an unrelated feature commit.
Run manually with `python scripts/backfill_p43c_password_set_at.py`
inside `/app/backend` when the operator decides it's useful.

## Risk & rollback

- **Read-only over `users`.** No writes to that collection.
- **`customers` writes are idempotent + guarded** by the
  `$or: [not-exists / null / empty]` predicate so a re-run cannot
  overwrite an existing customer-set stamp.
- **Rollback:** `db.customers.updateMany({}, {$unset: {"portal_password_set_at": ""}})` if desired. Reset flow re-stamps on next password change.
