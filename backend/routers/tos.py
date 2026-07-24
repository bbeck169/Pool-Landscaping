"""Feb-2026 · BUG E — global Terms of Service gate.

Endpoints
---------
* ``GET  /api/legal/tos``            — public. Returns the active ToS
  markdown + version. Registered BEFORE the legacy legal-CMS router so
  it wins the ``/legal/tos`` path match.
* ``POST /api/users/me/accept-tos``  — authenticated. Records the
  acceptance on ``users.tos_accepted_at`` + ``tos_version_accepted``.
  Rejects mismatched versions with 409 so the frontend can force a
  reload.

Boot migration
--------------
``run_tos_backfill()`` is called from ``server._background_seed`` on
every cold boot. It grandfathers every existing non-super_admin user
that has NEITHER field set to ``CURRENT_TOS_VERSION`` (idempotent — a
second run with the same version is a no-op). Super admins get their
gate fields explicitly cleared so ``compute_must_accept_tos`` returns
``False`` for them regardless of what the doc previously held.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from config_tos import (
    CURRENT_TOS_VERSION,
    CURRENT_TOS_EFFECTIVE_DATE,
    TOS_MARKDOWN,
    compute_must_accept_tos,
)
from utils import get_current_user, now_iso

router = APIRouter(tags=["Terms of Service"])


class AcceptTosIn(BaseModel):
    version: str


# ── public read ─────────────────────────────────────────────────────
@router.get("/legal/tos")
async def get_active_tos() -> Dict[str, Any]:
    """Public. Returns the active ToS the gate is enforcing."""
    return {
        "version": CURRENT_TOS_VERSION,
        "effective_date": CURRENT_TOS_EFFECTIVE_DATE,
        "markdown": TOS_MARKDOWN,
    }


# ── acceptance ──────────────────────────────────────────────────────
@router.post("/users/me/accept-tos")
async def accept_tos(
    body: AcceptTosIn,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Records the current user's ToS acceptance.

    * Rejects any version other than the active one with **409** so the
      frontend can hard-refresh and re-fetch the markdown.
    * Super admins are exempt — they receive a **200** with an
      ``already_accepted`` sentinel so the client's ordinary flow works
      even if a super admin somehow triggers it.
    * Idempotent: a second call with the same active version is a no-op
      apart from re-stamping ``tos_accepted_at``.
    """
    if body.version != CURRENT_TOS_VERSION:
        raise HTTPException(
            status_code=409,
            detail=f"ToS version mismatch. Server is on {CURRENT_TOS_VERSION!r}, "
                   f"client sent {body.version!r}. Please reload.",
        )

    uid = user.get("id")
    if not uid:
        raise HTTPException(400, "Signed-in user has no id")

    # Super admins are never gated. Return a stable payload so the
    # frontend can drop the modal without a special code path.
    if user.get("role") == "super_admin":
        return {
            "ok": True,
            "must_accept_tos": False,
            "tos_version_accepted": None,
            "tos_accepted_at": None,
            "note": "super_admin is exempt from the ToS gate",
        }

    ts = now_iso()
    await db.users.update_one(
        {"id": uid},
        {"$set": {
            "tos_accepted_at": ts,
            "tos_version_accepted": CURRENT_TOS_VERSION,
        }},
    )

    fresh = await db.users.find_one(
        {"id": uid},
        {"_id": 0, "password_hash": 0},
    ) or {}
    return {
        "ok": True,
        "must_accept_tos": compute_must_accept_tos(fresh),
        "tos_version_accepted": fresh.get("tos_version_accepted"),
        "tos_accepted_at": fresh.get("tos_accepted_at"),
    }


# ── Admin support tool — reset ToS gate for a specific user ─────────
@router.post("/admin/users/{uid}/reset-tos")
async def admin_reset_tos_for_user(
    uid: str,
    actor: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Super-admin support tool. Clears ``tos_accepted_at`` +
    ``tos_version_accepted`` on a target user so the ToS gate re-fires
    on their next request.

    Guards:
      * Only ``super_admin`` may call this — everyone else gets 403.
      * Cannot target a ``super_admin`` (they're exempt from the gate
        so a reset is a no-op AND could lock the owner out of setup
        if verification breaks). Returns **409** with a clear error.
      * Idempotent — calling on a user already missing both fields
        returns ``ok`` without a DB write.
    """
    if actor.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin only")

    target = await db.users.find_one(
        {"id": uid},
        {"_id": 0, "id": 1, "email": 1, "role": 1,
         "tos_accepted_at": 1, "tos_version_accepted": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "super_admin":
        raise HTTPException(
            status_code=409,
            detail="Cannot reset ToS gate on a super_admin (they are exempt).",
        )

    already_clear = (
        target.get("tos_accepted_at") in (None,)
        and target.get("tos_version_accepted") in (None,)
    )
    if already_clear:
        return {
            "ok": True,
            "user_id": uid,
            "email": target.get("email"),
            "was_already_clear": True,
        }

    await db.users.update_one(
        {"id": uid},
        {"$unset": {"tos_accepted_at": "", "tos_version_accepted": ""}},
    )
    logger.info(
        "[tos-reset] super_admin=%s cleared gate for user=%s (%s)",
        actor.get("email"), uid, target.get("email"),
    )
    return {
        "ok": True,
        "user_id": uid,
        "email": target.get("email"),
        "was_already_clear": False,
    }


# ── boot migration ──────────────────────────────────────────────────
async def run_tos_backfill() -> Dict[str, int]:
    """Idempotent grandfathering migration.

    Runs on every cold boot from ``server._background_seed``. Only
    mutates docs whose gate fields disagree with the CURRENT_TOS_VERSION
    expectation for their role, so re-runs are cheap.

    Behaviour:
      * Non-super_admin users missing BOTH ``tos_accepted_at`` and
        ``tos_version_accepted`` are grandfathered to
        ``CURRENT_TOS_VERSION`` so existing preview accounts are not
        walled out by this fix.
      * Super_admin users have both fields explicitly cleared so
        ``compute_must_accept_tos`` returns ``False`` for them, even if
        an earlier stamp is still on the doc.
    """
    ts = now_iso()

    grandfather = await db.users.update_many(
        {
            "role": {"$ne": "super_admin"},
            "tos_accepted_at": {"$exists": False},
            "tos_version_accepted": {"$exists": False},
        },
        {"$set": {
            "tos_accepted_at": ts,
            "tos_version_accepted": CURRENT_TOS_VERSION,
        }},
    )
    n_grandfather = int(getattr(grandfather, "modified_count", 0) or 0)

    exempt = await db.users.update_many(
        {
            "role": "super_admin",
            "$or": [
                {"tos_accepted_at": {"$ne": None}},
                {"tos_version_accepted": {"$ne": None}},
            ],
        },
        {"$set": {
            "tos_accepted_at": None,
            "tos_version_accepted": None,
        }},
    )
    n_exempt = int(getattr(exempt, "modified_count", 0) or 0)

    if n_grandfather or n_exempt:
        logger.info(
            "[tos-backfill] version=%s grandfathered=%s super_admin_cleared=%s",
            CURRENT_TOS_VERSION, n_grandfather, n_exempt,
        )
    return {
        "version": CURRENT_TOS_VERSION,
        "grandfathered": n_grandfather,
        "super_admin_cleared": n_exempt,
    }
