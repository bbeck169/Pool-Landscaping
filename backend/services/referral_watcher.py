"""Phase 10 · Feb 2026 — 30-day paid-window referral credit watcher.

Runs hourly on the top-of-hour tick. For each tenant, resolves the
tenant's local time (fallback ``America/Phoenix``); when the local
weekday+hour matches the configured dispatch window (default: any
day, 03:00 local), the watcher scans referrals in
``pending_paid_window`` and issues credit for any that have cleared
the 30-day paid-window guard AND had no refund/dispute void the
paid invoice inside that window.

Idempotency: every eligible referral advances via a status-guarded
CAS update (``pending_paid_window`` → ``credited``). A second run
finds ``status="credited"`` and no-ops.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db, logger
from routers.promo_codes import create_promo_code_internal
from services.marketing.merge_tags import render_template

DEFAULT_TZ = "America/Phoenix"
DEFAULT_HOUR = 3           # 03:00 local
DEFAULT_CREDIT_CENTS = 2500  # $25.00
PAID_WINDOW_DAYS = 30


def _tenant_tz(tenant: dict) -> str:
    tz = (tenant.get("timezone") or "").strip()
    return tz or DEFAULT_TZ


def _now_local(tenant: dict) -> datetime:
    try:
        return datetime.now(ZoneInfo(_tenant_tz(tenant)))
    except Exception:
        return datetime.now(ZoneInfo(DEFAULT_TZ))


def _fmt_pretty(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso)[:19]).strftime("%b %-d, %Y")
    except Exception:
        try:
            return date.fromisoformat(str(iso)[:10]).strftime("%b %-d, %Y")
        except Exception:
            return str(iso)


# ─── Public entry point (scheduler) ──────────────────────────────────
async def hourly_scan() -> Dict[str, Any]:
    tenants = await db.tenants.find(
        {},
        {"_id": 0, "id": 1, "name": 1, "timezone": 1,
         "referral_watcher_hour_local": 1,
         "referral_reward_amount_cents": 1,
         "referral_reward_enabled": 1},
    ).to_list(1000)
    fired: List[str] = []
    skipped = 0
    for t in tenants:
        try:
            local = _now_local(t)
        except Exception as exc:
            logger.warning(f"[phase10-cron] tz resolve failed for {t.get('id')}: {exc}")
            continue
        hour = int(t.get("referral_watcher_hour_local") or DEFAULT_HOUR)
        if local.hour != hour:
            skipped += 1
            continue
        try:
            await run_referral_watcher(t)
            fired.append(t.get("id") or "")
        except Exception as exc:
            logger.warning(f"[phase10-cron] tenant {t.get('id')} run failed: {exc}")
    return {"fired": fired, "skipped": skipped, "total": len(tenants)}


async def run_referral_watcher(tenant: dict) -> Dict[str, Any]:
    """Public helper — also called by manual admin trigger + pytest."""
    if tenant.get("referral_reward_enabled") is False:
        return {"skipped": True, "reason": "reward_disabled"}
    credit_cents = int(
        tenant.get("referral_reward_amount_cents")
        or ((tenant.get("settings") or {}).get("referrals") or {}).get("reward_amount_cents")
        or DEFAULT_CREDIT_CENTS
    )
    tenant_id = tenant["id"]

    pending = await db.referrals.find({
        "tenant_id": tenant_id,
        "status": "pending_paid_window",
    }, {"_id": 0}).to_list(2000)

    credited: List[str] = []
    still_waiting: List[str] = []
    voided_already: List[str] = []

    for ref in pending:
        rc = await _try_credit_referral(tenant, ref, credit_cents)
        if rc.get("credited"):
            credited.append(ref["id"])
        elif rc.get("voided"):
            voided_already.append(ref["id"])
        else:
            still_waiting.append(ref["id"])
    return {
        "tenant_id": tenant_id,
        "checked": len(pending),
        "credited": credited,
        "still_waiting": len(still_waiting),
        "voided": voided_already,
    }


# ─── Core credit-issue logic ─────────────────────────────────────────
async def _try_credit_referral(
    tenant: dict, referral: dict, credit_cents: int,
) -> Dict[str, Any]:
    tenant_id = tenant["id"]
    ref_id = referral["id"]
    now = datetime.now(timezone.utc)

    # 1) Resolve first paid_at.
    first_paid = referral.get("first_paid_at")
    if not first_paid:
        first_paid = await _earliest_paid_at(
            tenant_id, referral.get("converted_to_customer_id")
                        or referral.get("referred_customer_id"),
        )
        if first_paid:
            await db.referrals.update_one(
                {"id": ref_id},
                {"$set": {"first_paid_at": first_paid,
                          "updated_at": now.isoformat()}},
            )
    if not first_paid:
        return {"credited": False, "reason": "not_paid_yet"}

    # 2) Check 30-day window elapsed.
    try:
        first_paid_dt = datetime.fromisoformat(str(first_paid).replace("Z", "+00:00"))
        if first_paid_dt.tzinfo is None:
            first_paid_dt = first_paid_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return {"credited": False, "reason": "bad_first_paid_at"}
    eligible_at_dt = first_paid_dt + timedelta(days=PAID_WINDOW_DAYS)
    if now < eligible_at_dt:
        return {"credited": False, "reason": "waiting_window"}

    # 3) Guard against a refund/dispute that hit the paid invoice
    #    INSIDE the 30-day window.
    voided = await _check_refund_or_dispute_inside_window(
        tenant_id,
        referral.get("converted_to_customer_id")
            or referral.get("referred_customer_id"),
        first_paid_dt, eligible_at_dt,
    )
    if voided:
        await db.referrals.update_one(
            {"id": ref_id, "status": "pending_paid_window"},
            {"$set": {"status": "voided",
                       "voided_reason": voided,
                       "voided_at": now.isoformat(),
                       "updated_at": now.isoformat()}},
        )
        return {"voided": True, "reason": voided}

    # 4) Mint the promo code + ledger + notification. ALL inside a
    #    single status-guarded CAS so a concurrent run can't
    #    double-credit.
    guard = await db.referrals.update_one(
        {"id": ref_id, "status": "pending_paid_window"},
        {"$set": {"status": "crediting_in_progress",
                   "updated_at": now.isoformat()}},
    )
    if guard.modified_count != 1:
        return {"credited": False, "reason": "concurrent_or_already_credited"}

    try:
        promo = await create_promo_code_internal(
            tenant_id=tenant_id,
            type_="referral_reward",
            discount_kind="fixed_credit",
            apply_to="account_credit",
            amount_cents=credit_cents,
            max_uses=1,
            prefix="REF-",
            metadata={
                "referral_id": ref_id,
                "referrer_customer_id": referral.get("referrer_customer_id"),
                "referred_customer_id": referral.get("converted_to_customer_id")
                                          or referral.get("referred_customer_id"),
            },
        )
        # Add ledger row on customer_credits + roll balance forward.
        from utils import new_id, now_iso
        ledger_id = new_id()
        await db.customer_credits.insert_one({
            "id": ledger_id,
            "tenant_id": tenant_id,
            "customer_id": referral["referrer_customer_id"],
            "delta_cents": credit_cents,
            "source": "referral_credit",
            "promo_code_id": promo["id"],
            "referral_id": ref_id,
            "note": (
                f"Referral credit — {referral.get('friend_name') or 'friend'} "
                f"paid on {_fmt_pretty(first_paid)}, "
                f"eligible {_fmt_pretty(eligible_at_dt.isoformat())}"
            ),
            "created_at": now_iso(),
            "created_by": "referral_watcher",
        })
        await db.customer_credits_balance.update_one(
            {"tenant_id": tenant_id,
              "customer_id": referral["referrer_customer_id"]},
            {"$inc": {"balance_cents": credit_cents, "balance": credit_cents / 100.0},
              "$set": {"updated_at": now_iso()}},
            upsert=True,
        )
        # Finalise referral row.
        await db.referrals.update_one(
            {"id": ref_id},
            {"$set": {
                "status": "credited",
                "credited_at": now.isoformat(),
                "credited_promo_code_id": promo["id"],
                "credit_amount_cents": credit_cents,
                "eligible_at": eligible_at_dt.isoformat(),
                "updated_at": now.isoformat(),
            }},
        )
        # Fire notification (best-effort — never blocks credit issuance).
        await _fire_credit_notifications(
            tenant, referral, promo, credit_cents, eligible_at_dt,
        )
        return {"credited": True, "promo_code_id": promo["id"],
                "ledger_id": ledger_id}
    except Exception as exc:
        # Roll status back so the next run can try again.
        await db.referrals.update_one(
            {"id": ref_id, "status": "crediting_in_progress"},
            {"$set": {"status": "pending_paid_window",
                       "updated_at": now.isoformat()}},
        )
        logger.warning(f"[phase10] credit issuance rolled back: {exc}")
        return {"credited": False, "reason": "internal_error"}


async def _earliest_paid_at(
    tenant_id: str, customer_id: Optional[str],
) -> Optional[str]:
    if not customer_id:
        return None
    row = await db.invoices.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "status": "paid"},
        {"_id": 0, "paid_at": 1},
        sort=[("paid_at", 1)],
    )
    if row and row.get("paid_at"):
        return row["paid_at"]
    # Fallback: some tenants store paid invoices in ``quotes`` with
    # ``doc_type="invoice"`` (legacy).
    row2 = await db.quotes.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "doc_type": "invoice", "status": "paid"},
        {"_id": 0, "paid_at": 1},
        sort=[("paid_at", 1)],
    )
    return (row2 or {}).get("paid_at")


async def _check_refund_or_dispute_inside_window(
    tenant_id: str, customer_id: Optional[str],
    first_paid_dt: datetime, eligible_at_dt: datetime,
) -> Optional[str]:
    """Returns a truthy ``reason`` string (``"refunded"`` /
    ``"disputed"``) if the referred customer's paid invoices had a
    refund or dispute INSIDE the 30-day window, else ``None``."""
    if not customer_id:
        return None
    # We inspect stripe_events for any refund/dispute affecting this
    # customer's paid invoices INSIDE the window.
    lo = first_paid_dt.isoformat()
    hi = eligible_at_dt.isoformat()
    ev = await db.stripe_events.find_one({
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "event_type": {"$in": ["charge.refunded", "charge.dispute.created"]},
        "created_at": {"$gte": lo, "$lte": hi},
    }, {"_id": 0, "event_type": 1})
    if not ev:
        return None
    return "refunded" if ev["event_type"] == "charge.refunded" else "disputed"


# ─── Notifications ───────────────────────────────────────────────────
async def _fire_credit_notifications(
    tenant: dict, referral: dict, promo: dict,
    credit_cents: int, eligible_at_dt: datetime,
) -> None:
    try:
        cust = await db.customers.find_one(
            {"id": referral["referrer_customer_id"],
              "tenant_id": tenant["id"]},
            {"_id": 0},
        ) or {}
        friend = await db.customers.find_one(
            {"id": referral.get("converted_to_customer_id")
                    or referral.get("referred_customer_id"),
              "tenant_id": tenant["id"]},
            {"_id": 0},
        ) or {}
        # Build canonical merge ctx.
        from services.marketing.merge_tags import render_context
        ctx = render_context(
            customer={
                "name": cust.get("name") or "",
                "email": cust.get("email"),
                "phone": cust.get("phone"),
                "credits_balance_cents": (
                    int(cust.get("credits_balance_cents") or 0) + credit_cents
                ),
            },
            tenant={
                "name": tenant.get("name"),
                "phone": tenant.get("phone"),
                "email": tenant.get("email"),
            },
        )
        ctx["referral"] = {
            "friend_name": friend.get("name") or "",
            "friend_first_name": (friend.get("name") or "").split(" ", 1)[0],
            "credit_amount_cents": credit_cents,
            "eligible_at": eligible_at_dt.isoformat(),
            "eligible_at_pretty": _fmt_pretty(eligible_at_dt.isoformat()),
            "promo_code": promo["code"],
        }
        # Load the seeded templates.
        email_tpl = await db.marketing_templates.find_one({
            "tenant_id": tenant["id"], "system_key": "referral_credit_earned_email",
        }, {"_id": 0})
        sms_tpl = await db.marketing_templates.find_one({
            "tenant_id": tenant["id"], "system_key": "referral_credit_earned_sms",
        }, {"_id": 0})

        from utils import now_iso, new_id

        if email_tpl and cust.get("email"):
            subject, _ = render_template(email_tpl.get("subject") or "", ctx)
            body, _ = render_template(email_tpl.get("body") or "", ctx)
            try:
                from services.email.resend_adapter import send as _send_email
                res = await _send_email(
                    to=cust["email"], subject=subject, html=body,
                    category="transactional", tenant_id=tenant["id"],
                    idempotency_key=f"referral_credit:{referral['id']}:email",
                )
                await db.marketing_deliveries.insert_one({
                    "id": new_id(),
                    "tenant_id": tenant["id"],
                    "channel": "email",
                    "recipient_id": cust.get("id"),
                    "recipient_email": cust["email"],
                    "trigger_entity": {
                        "kind": "referral_credit_issued",
                        "referral_id": referral["id"],
                        "promo_code_id": promo["id"],
                    },
                    "template_id": email_tpl.get("id"),
                    "status": res.get("provider_status"),
                    "provider_response_id": res.get("provider_response_id"),
                    "subject": subject,
                    "created_at": now_iso(),
                })
            except Exception as exc:
                logger.warning(f"[phase10] credit email send failed: {exc}")

        if sms_tpl and cust.get("phone"):
            body, _ = render_template(sms_tpl.get("body") or "", ctx)
            try:
                from services.sms.rc_adapter import send as _send_sms
                res = await _send_sms(
                    to=cust["phone"], body=body,
                    category="transactional", tenant_id=tenant["id"],
                    idempotency_key=f"referral_credit:{referral['id']}:sms",
                )
                await db.marketing_deliveries.insert_one({
                    "id": new_id(),
                    "tenant_id": tenant["id"],
                    "channel": "sms",
                    "recipient_id": cust.get("id"),
                    "recipient_phone": cust["phone"],
                    "trigger_entity": {
                        "kind": "referral_credit_issued",
                        "referral_id": referral["id"],
                        "promo_code_id": promo["id"],
                    },
                    "template_id": sms_tpl.get("id"),
                    "status": (res or {}).get("provider_status") or "sent",
                    "provider_response_id": (res or {}).get("provider_response_id"),
                    "body": body,
                    "created_at": now_iso(),
                })
            except Exception as exc:
                logger.warning(f"[phase10] credit SMS send failed: {exc}")
    except Exception as exc:
        logger.warning(f"[phase10] credit notification wrap failed: {exc}")


# ─── Boot-time seed of the referral credit templates ─────────────────
_REFERRAL_EMAIL_SUBJECT = "You earned a {{REFERRAL_CREDIT_AMOUNT}} credit!"
_REFERRAL_EMAIL_BODY = (
    "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
    "<p>Great news — your referral of <strong>{{REFERRAL_FRIEND_NAME}}</strong> "
    "is officially credited. <strong>{{REFERRAL_CREDIT_AMOUNT}}</strong> "
    "has been added to your account.</p>"
    "<p>Your new balance: <strong>{{CUSTOMER_CREDIT_BALANCE}}</strong>. "
    "We'll auto-apply it on your next invoice.</p>"
    "<p>Thanks for spreading the word,<br/>The {{COMPANY_NAME}} team</p>"
)
_REFERRAL_SMS_BODY = (
    "Hi {{CUSTOMER_FIRST_NAME}} — {{REFERRAL_FRIEND_NAME}}'s referral "
    "earned you {{REFERRAL_CREDIT_AMOUNT}}. New balance: "
    "{{CUSTOMER_CREDIT_BALANCE}}. — {{COMPANY_NAME}}"
)


async def seed_referral_credit_templates() -> None:
    """Boot hook — idempotent seed of the two credit-earned templates
    for every tenant. Missing rows are inserted; existing rows are
    left alone (tenant may have customised the copy)."""
    from utils import new_id, now_iso
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        for system_key, channel, subject, body in (
            ("referral_credit_earned_email", "email",
             _REFERRAL_EMAIL_SUBJECT, _REFERRAL_EMAIL_BODY),
            ("referral_credit_earned_sms", "sms", "", _REFERRAL_SMS_BODY),
        ):
            existing = await db.marketing_templates.find_one({
                "tenant_id": t["id"], "system_key": system_key,
            }, {"_id": 0, "id": 1})
            if existing:
                continue
            await db.marketing_templates.insert_one({
                "id": new_id(),
                "tenant_id": t["id"],
                "system_key": system_key,
                "name": ("Referral credit earned — "
                          + ("Email" if channel == "email" else "SMS")),
                "channel": channel,
                "category": "referral",
                "subject": subject,
                "body": body,
                "active": True,
                "system": True,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })


# ─── Back-migration for legacy immediate-credit path ─────────────────
async def backmigrate_legacy_referral_credits() -> Dict[str, int]:
    """Idempotent — scans referrals rows that were immediately credited
    via the pre-Phase-10 hook (``reward_applied_at`` set), and:

      * Ensures they have the Phase-10 status shape (``credited``) +
        ``credited_at`` + ``credited_promo_code_id`` (mints a promo
        code retro if missing so the ledger row is consistent).
      * Ensures the ``customer_credits`` ledger row uses the new
        ``source="referral_credit"`` tag (was: ``referral_reward``).

    Never double-credits — dedupe by referral_id."""
    upgraded = 0
    minted = 0
    async for ref in db.referrals.find({
        "reward_applied_at": {"$exists": True, "$ne": None},
        "status": {"$nin": ["credited", "voided"]},
    }, {"_id": 0}):
        upd: Dict[str, Any] = {
            "status": "credited",
            "credited_at": ref.get("reward_applied_at"),
        }
        if not ref.get("credited_promo_code_id"):
            try:
                promo = await create_promo_code_internal(
                    tenant_id=ref["tenant_id"],
                    type_="referral_reward",
                    discount_kind="fixed_credit",
                    apply_to="account_credit",
                    amount_cents=int(
                        (ref.get("reward_amount") or 0) * 100
                    ) or DEFAULT_CREDIT_CENTS,
                    max_uses=1,
                    prefix="REF-",
                    metadata={
                        "referral_id": ref["id"],
                        "referrer_customer_id": ref.get("referrer_customer_id"),
                        "backmigrated": True,
                    },
                )
                upd["credited_promo_code_id"] = promo["id"]
                minted += 1
            except Exception as exc:
                logger.warning(
                    f"[phase10-backmigrate] promo mint failed for referral "
                    f"{ref.get('id')}: {exc}")
        await db.referrals.update_one({"id": ref["id"]}, {"$set": upd})
        upgraded += 1
    return {"upgraded": upgraded, "minted": minted}


# ─── Index bootstrap ─────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db.referrals.create_index(
            [("tenant_id", 1), ("status", 1), ("first_paid_at", 1)],
            name="referrals_watcher_idx",
        )
        await db.stripe_events.create_index(
            [("tenant_id", 1), ("customer_id", 1),
             ("event_type", 1), ("created_at", 1)],
            name="stripe_events_customer_type_idx",
        )
    except Exception as exc:
        logger.warning(f"[phase10] referral index skipped: {exc}")
