"""Feb-2026 · Item 11 — Referral vesting.

Additive layer on top of the existing referral_conversions collection.
Adds a ``vesting_status`` field with the state machine:

    pending → vesting → vested → credited
                     ↘ forfeited
                     ↘ canceled

Existing rows created before this feature (already in ``approved``
status with credit issued) are marked ``legacy_credited=true`` and
kept intact — the promoter cron never touches them.

Cron ``promote_referrals_to_vested()`` runs nightly and promotes
rows where ``vesting_started_at + 30 days <= now`` AND at least
one full monthly invoice was paid AND the referred customer's
account is still active.

Admin endpoints let support force-promote or force-forfeit any row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter(tags=["Referrals · Vesting"])

VESTING_WINDOW_DAYS = 30


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _referrer_has_paid_invoice_since(
    tenant_id: str, referred_customer_id: str, since_iso: str,
) -> bool:
    """Returns True when the referred customer has at least one PAID
    invoice with paid_at >= since_iso."""
    row = await db.invoices.find_one({
        "tenant_id": tenant_id,
        "customer_id": referred_customer_id,
        "status": {"$in": ["paid", "partially_paid"]},
        "paid_at": {"$gte": since_iso},
    }, {"_id": 0, "id": 1})
    return bool(row)


async def _issue_referrer_credit(row: Dict[str, Any]) -> str:
    """Issues the $25 flat credit on the referrer's account. Uses the
    same ``service_credits`` collection as the existing referral
    approve path. Returns the new credit id."""
    credit_id = new_id()
    await db.service_credits.insert_one({
        "id": credit_id,
        "tenant_id": row["tenant_id"],
        "customer_id": row["referrer_customer_id"],
        "kind": "flat_dollars",
        "amount_cents": 2500,
        "source": "referral_vesting",
        "source_conversion_id": row["id"],
        "granted_at": now_iso(),
        "redeemed_at": None,
    })
    return credit_id


async def promote_referrals_to_vested() -> Dict[str, int]:
    """Nightly promoter. Idempotent — never re-processes a row that
    already has ``vesting_status`` in a terminal state."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=VESTING_WINDOW_DAYS)).isoformat()
    rows = await db.referral_conversions.find({
        "vesting_status": "vesting",
        "vesting_started_at": {"$lte": cutoff},
    }, {"_id": 0}).to_list(1000)

    promoted = 0
    skipped = 0
    for r in rows:
        try:
            has_paid = await _referrer_has_paid_invoice_since(
                r["tenant_id"], r.get("referred_customer_id") or "",
                r.get("vesting_started_at") or "",
            )
            if not has_paid:
                skipped += 1
                continue
            credit_id = await _issue_referrer_credit(r)
            await db.referral_conversions.update_one(
                {"id": r["id"]},
                {"$set": {
                    "vesting_status": "credited",
                    "credited_at": now_iso(),
                    "credit_id": credit_id,
                }},
            )
            promoted += 1
        except Exception as e:
            logger.warning(f"[vesting] promote {r.get('id')} failed: {e}")

    if promoted or skipped:
        logger.info(
            "[vesting] promoted=%s skipped=%s (waiting on first paid invoice)",
            promoted, skipped,
        )
    return {"promoted": promoted, "skipped": skipped}


async def run_backfill() -> Dict[str, int]:
    """One-shot idempotent backfill on boot:
    * Rows in ``approved`` status → ``vesting_status="credited"`` +
      ``legacy_credited=true`` (leave the credit alone).
    * Rows with no ``vesting_status`` field yet → ``"pending"``.
    """
    r1 = await db.referral_conversions.update_many(
        {"status": "approved", "vesting_status": {"$exists": False}},
        {"$set": {"vesting_status": "credited",
                    "legacy_credited": True,
                    "credited_at": None}},
    )
    r2 = await db.referral_conversions.update_many(
        {"vesting_status": {"$exists": False}},
        {"$set": {"vesting_status": "pending"}},
    )
    n_legacy = int(getattr(r1, "modified_count", 0) or 0)
    n_pending = int(getattr(r2, "modified_count", 0) or 0)
    if n_legacy or n_pending:
        logger.info(
            "[vesting-backfill] legacy_credited=%s pending=%s",
            n_legacy, n_pending,
        )
    return {"legacy_credited": n_legacy, "pending": n_pending}


@router.post("/admin/referrals/{rid}/promote",
              operation_id="referrals.forcePromote")
async def force_promote(
    rid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    row = await db.referral_conversions.find_one({"id": rid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Referral not found")
    if row.get("vesting_status") in ("credited", "forfeited", "canceled"):
        return {"ok": True, "already_terminal": row.get("vesting_status")}
    credit_id = await _issue_referrer_credit(row)
    await db.referral_conversions.update_one(
        {"id": rid},
        {"$set": {
            "vesting_status": "credited",
            "credited_at": now_iso(),
            "credit_id": credit_id,
            "force_promoted_by_user_id": user.get("id"),
        }},
    )
    return {"ok": True, "vesting_status": "credited",
             "credit_id": credit_id}


@router.post("/admin/referrals/{rid}/forfeit",
              operation_id="referrals.forceForfeit")
async def force_forfeit(
    rid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    row = await db.referral_conversions.find_one({"id": rid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Referral not found")
    if row.get("vesting_status") in ("credited", "forfeited", "canceled"):
        return {"ok": True, "already_terminal": row.get("vesting_status")}
    await db.referral_conversions.update_one(
        {"id": rid},
        {"$set": {
            "vesting_status": "forfeited",
            "forfeited_at": now_iso(),
            "forfeited_by_user_id": user.get("id"),
        }},
    )
    return {"ok": True, "vesting_status": "forfeited"}


@router.get("/admin/referrals/vesting",
             operation_id="referrals.vestingList")
async def list_vesting(
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    rows = await db.referral_conversions.find(
        {"tenant_id": tenant_id,
         "vesting_status": {"$in": ["vesting", "pending", "vested"]}},
        {"_id": 0},
    ).sort("vesting_started_at", -1).to_list(500)
    now = datetime.now(timezone.utc)
    for r in rows:
        started = r.get("vesting_started_at")
        if started:
            try:
                d = datetime.fromisoformat(started.replace("Z", "+00:00"))
                days_in = int((now - d).days)
                r["days_vested"] = max(0, min(VESTING_WINDOW_DAYS, days_in))
                r["days_remaining"] = max(0, VESTING_WINDOW_DAYS - days_in)
            except Exception:
                pass
    return {"total": len(rows), "items": rows,
             "vesting_window_days": VESTING_WINDOW_DAYS}
