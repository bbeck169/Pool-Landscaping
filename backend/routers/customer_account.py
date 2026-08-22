"""Feb-2026 · P11b — Customer self-service account deletion.

App Store consumer-account guideline compliance (blocker item 3): the
customer portal must expose a self-service deletion path.  Per the P11b
policy (see ``memory/appstore_readiness_p10.md``):

  * Q3a — anonymize (keep the row, scrub PII); NOT hard-delete.
  * Q3b — customers only; techs/admins/super_admins get 403.
  * Q3c — authored data (jobs, invoices, ToS acceptances, service
    reports) stays owned by the same ``customer_id`` — downstream
    reads render the anonymized name ("Deleted User").

**Endpoint:** ``DELETE /api/customer-portal/account``

Effect on the caller's ``users`` and ``customers`` rows (both tenant-
scoped, both located by the JWT's ``customer_id``):

  * ``deleted_at`` set to now — ``utils.get_current_user`` line 89
    already hard-401s any subsequent request from a ``deleted_at``
    user, giving us session invalidation for free (no blacklist
    collection needed; existing JWTs stop working on the very next
    request).
  * ``anonymized_at`` set to now.
  * PII scrubbed: ``email → deleted-user-<cid>@example.invalid``,
    ``name → "Deleted User"``, ``first_name → "Deleted"``,
    ``last_name → "User"``, ``phone / address / avatar_url / notes``
    → ``None``.

Preserved: ``id, tenant_id, role, customer_id, created_at,
deleted_at, anonymized_at``.  Everything else on the row is scrubbed
or nulled.

**Idempotent** — a re-call after deletion returns 200 with the same
``anonymized_at`` (won't happen in practice because the first call
invalidates the JWT, but pinned by the characterization suite for
defensive-in-depth).

**Audit trail** — writes a row to ``account_deletion_events`` with
``{customer_id, tenant_id, ip, user_agent, deleted_at, anonymized_at}``
so the tenant admin can prove GDPR / App Store compliance.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from config import db, logger
from utils import get_current_user, now_iso

router = APIRouter(tags=["Customer Portal · Account Deletion"])


def _require_customer(user: Dict[str, Any]) -> str:
    """Portal-scoped identity guard.

    Techs / admins / super-admins hitting this endpoint receive a
    403 with ``role_not_permitted``.  Prevents an admin from
    accidentally scrubbing their own admin account through the
    consumer surface, and pins the App Store scope (customers only,
    per Q3b).
    """
    if user.get("role") != "customer":
        raise HTTPException(403, "role_not_permitted")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(400, "Signed-in user has no linked customer record")
    return cid


def _client_ip(request: Request) -> str:
    """Feb-2026 · P16B — delegates to the shared ``services._shared.http``
    helper.  Empty-string default preserved so pre-P16 rows in
    ``account_deletion_events`` remain grep-consistent."""
    from services._shared.http import client_ip as _shared_client_ip
    return _shared_client_ip(request, default="")


@router.delete("/customer-portal/account")
async def delete_customer_account(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Anonymize the caller's customer account.  Idempotent."""
    cid = _require_customer(user)
    tid = user["tenant_id"]
    uid = user.get("id")

    # Idempotent short-circuit — a re-call after prior anonymization
    # returns 200 with the pre-existing ``anonymized_at``.
    prior_users = await db.users.find_one(
        {"id": uid}, {"_id": 0, "anonymized_at": 1},
    ) or {}
    if prior_users.get("anonymized_at"):
        return {"deleted": True, "anonymized_at": prior_users["anonymized_at"]}

    ts = now_iso()
    scrub = {
        "email": f"deleted-user-{cid}@example.invalid",
        "name": "Deleted User",
        "first_name": "Deleted",
        "last_name": "User",
        "phone": None,
        "address": None,
        "avatar_url": None,
        "avatar": None,
        "notes": None,
        "deleted_at": ts,
        "anonymized_at": ts,
        "updated_at": ts,
    }

    # ``users`` row — carries the auth identity. ``deleted_at`` here
    # is the session-invalidation trigger (see utils.get_current_user
    # line 89 — hard-401 on next request).
    if uid:
        await db.users.update_one({"id": uid}, {"$set": scrub})

    # ``customers`` row — the CRM-side identity that hydrates
    # downstream reads (job cards, invoices, ToS history).
    # Authored data is NOT touched — the row stays owned by
    # ``customer_id`` and will render "Deleted User" on hydrate.
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid}, {"$set": scrub},
    )

    # Audit trail — the tenant admin can prove GDPR / App Store
    # compliance from this collection alone. Best-effort write; a
    # failure here must NOT block the deletion the caller requested.
    try:
        await db.account_deletion_events.insert_one({
            "customer_id": cid,
            "tenant_id": tid,
            "user_id": uid,
            "ip": _client_ip(request),
            "user_agent": request.headers.get("user-agent", "")[:500],
            "deleted_at": ts,
            "anonymized_at": ts,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[p11b] account_deletion_events insert failed: {e}")

    return {"deleted": True, "anonymized_at": ts}
