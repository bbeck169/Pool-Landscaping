"""Phase A4 · Feb-2026 · Proactive Intelligence — Renewal Engine.

Producer #4 for the ``intelligence_alerts`` store. Detects
:mod:`routers.warranties` ``warranty_contracts`` whose ``end_date``
is exactly 30 days ahead of the scan's reference date (UTC), and
does two things per match:

1. Emits ONE ``renewal_due`` alert per (agreement, 30d milestone)
   into the A1 bell + full-list page. Dedup key:
   ``renewal_due:agreement:{contract_id}:30d`` — permanent per
   contract, so a same-day re-run is a no-op.
2. Sends a customer-facing renewal email through the existing
   Resend pipeline. The i18n composer key set lives in
   :mod:`services.email_body_i18n` under
   ``email.renewal_proposal.*`` (manual-renewal contracts) and
   ``email.renewal_receipt.*`` (auto-renewal contracts).

Data model — schema audit
-------------------------
No new collection was added. The existing ``warranty_contracts``
collection maintained by Phase 28.1 already tracks every
customer-facing agreement (service plan / maintenance contract /
extended warranty / basic warranty). Fields consumed:

* ``id``, ``tenant_id``, ``customer_id``,
  ``customer_name_snapshot``
* ``plan_id``, ``plan_name_snapshot``, ``plan_kind_snapshot``
* ``end_date`` — ISO-8601 date string (``"2026-03-01"``) or
  full ISO datetime; the scan compares the date portion.
* ``status`` — only ``"active"`` rows are candidates.
* ``price_paid`` — dollars (float); converted to cents in the
  alert ``actor_context`` for symmetry with the A3 churn signal.
* ``renewed_at`` / ``renewal_contract_id`` — presence excludes the
  contract from the scan even if ``status`` hasn't flipped yet.

Auto-renew flag comes from ``warranty_plans.renewal_kind == "auto"``
(joined per-contract via ``plan_id``).

HMAC-signed CTA token
---------------------
Every proposal email carries a customer-portal deep link:

    {APP_PUBLIC_URL}/customer-portal/agreements/{contract_id}/renew?token=<t>

Where ``<t>`` is ``{contract_id}.{exp_epoch}.{sig}`` and ``sig`` is
the first 32 hex chars of ``hmac_sha256(_hmac_key(), f"{contract_id}.{exp_epoch}")``.
Mirrors the ``services/marketing_campaigns.py`` HMAC pattern. TTL
defaults to 60 days (well past the 30-day renewal window) so the
customer has runway to click even from a stale inbox.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL
from services.intelligence.alerts import emit_alert

logger = logging.getLogger("intelligence.renewal_scan")

_MILESTONE_DAYS = 30
_RENEWAL_TOKEN_TTL_DAYS = 60


# ═════════════════════ HMAC-signed CTA token ════════════════════════
def _hmac_key() -> bytes:
    """Return the signing key.  Reuses ``JWT_SECRET`` so the token
    lifecycle is tied to the same secret rotation as every other
    signed artefact in the app."""
    from config import JWT_SECRET
    return JWT_SECRET.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_hmac_key(), payload.encode("utf-8"),
                     hashlib.sha256).hexdigest()[:32]


def sign_renewal_token(contract_id: str,
                          ttl_days: int = _RENEWAL_TOKEN_TTL_DAYS,
                          now: Optional[datetime] = None) -> Tuple[str, int]:
    """Return ``(token, exp_epoch)`` for the given contract.

    Token shape: ``"{contract_id}.{exp_epoch}.{sig}"`` — a single
    string that round-trips through URL query params without
    encoding surprises.  ``exp_epoch`` is a Unix timestamp so
    callers can log / assert on the exact expiration moment.
    """
    ref = (now or datetime.now(timezone.utc))
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    exp = int((ref + timedelta(days=ttl_days)).timestamp())
    payload = f"{contract_id}.{exp}"
    return f"{payload}.{_sign(payload)}", exp


def verify_renewal_token(token: str,
                           now: Optional[datetime] = None,
                           ) -> Optional[str]:
    """Return the ``contract_id`` if the token is valid + unexpired,
    otherwise ``None``. Constant-time signature comparison to
    keep the pattern replay-safe.
    """
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    contract_id, exp_str, sig = parts
    try:
        exp = int(exp_str)
    except ValueError:
        return None
    ref = (now or datetime.now(timezone.utc))
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if exp < int(ref.timestamp()):
        return None
    expected = _sign(f"{contract_id}.{exp}")
    if not hmac.compare_digest(sig, expected):
        return None
    return contract_id


# ═════════════════════ Date helpers ═════════════════════════════════
def _date_only(raw: Any) -> Optional[str]:
    """Return the YYYY-MM-DD portion of an ``end_date`` field,
    tolerating date-only + full-ISO datetime string shapes."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    s = str(raw)
    return s[:10] if len(s) >= 10 else None


def _short_date(raw: Any) -> str:
    """Human-facing short date, best-effort."""
    d = _date_only(raw)
    return d or (str(raw) if raw is not None else "")


def _fmt_dollars(cents: int) -> str:
    try:
        v = float(cents) / 100.0
        return f"${v:,.2f}"
    except (TypeError, ValueError):
        return f"${cents}"


# ═════════════════════ Tenant + plan helpers ═════════════════════════
async def _plan_renewal_kind(tenant_id: str,
                                 plan_id: Optional[str]) -> str:
    """Return the plan's ``renewal_kind`` (``auto`` / ``manual`` /
    ``none``).  Falls back to ``manual`` when the plan is missing
    so callers don't crash on legacy contracts pointing at a
    deleted plan."""
    if not plan_id:
        return "manual"
    plan = await db.warranty_plans.find_one(
        {"id": plan_id, "tenant_id": tenant_id},
        {"_id": 0, "renewal_kind": 1},
    )
    return (plan or {}).get("renewal_kind") or "manual"


async def _iter_tenants(explicit: Optional[str]) -> List[Dict[str, Any]]:
    if explicit:
        row = await db.tenants.find_one(
            {"id": explicit}, {"_id": 0, "id": 1, "default_locale": 1},
        )
        return [row] if row else []
    out: List[Dict[str, Any]] = []
    async for t in db.tenants.find(
        {"active": True},
        {"_id": 0, "id": 1, "default_locale": 1},
    ):
        if t.get("id"):
            out.append(t)
    return out


# ═════════════════════ Email dispatch ═══════════════════════════════
async def _send_renewal_email(
    *,
    contract: Dict[str, Any],
    customer: Dict[str, Any],
    tenant:   Dict[str, Any],
    auto_renew: bool,
    now: datetime,
) -> Optional[str]:
    """Send either the manual-renewal proposal or the auto-renewal
    receipt email.  Returns the ``to`` email on a successful
    send / ``None`` when the send was skipped (no recipient,
    Resend key missing, guard blocked).  Never raises — email
    hiccups must not fail the scan loop.
    """
    to = (customer or {}).get("email")
    if not to:
        return None
    if not RESEND_API_KEY:
        logger.info("[renewal-scan] no RESEND_API_KEY — logging mock")
        return None
    try:
        from services.comms_env_guard import guard_outbound
        verdict = guard_outbound(kind="email", to=to)
        if verdict.blocked:
            logger.info(
                "[DRY-RUN] renewal email SKIPPED to=%s contract=%s",
                to, contract.get("id"),
            )
            return None
    except Exception:  # noqa: BLE001
        # Guard import errors must never break the scan.
        pass

    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body

    locale = resolve_email_locale(recipient=customer, tenant=tenant)
    plan_name = (contract.get("plan_name_snapshot")
                  or "maintenance plan")
    price_cents = int(round(
        float(contract.get("price_paid") or 0) * 100))
    monthly = _fmt_dollars(price_cents)
    expires_short = _short_date(contract.get("end_date"))
    first_name = ((customer.get("name") or "").split(" ")[0]
                   or "there")

    token, _exp = sign_renewal_token(contract["id"], now=now)
    cta_url = (f"{APP_PUBLIC_URL}/customer-portal/agreements/"
                f"{contract['id']}/renew?token={token}")

    ns = "renewal_receipt" if auto_renew else "renewal_proposal"
    try:
        subject = t_email_body(
            locale, f"email.{ns}.subject",
            plan_name=plan_name, days_left=_MILESTONE_DAYS,
        )
        intro = t_email_body(
            locale, f"email.{ns}.body_intro",
            customer_first_name=first_name, plan_name=plan_name,
            expires_at_short=expires_short,
        )
        price = t_email_body(
            locale, f"email.{ns}.body_price",
            monthly_amount=monthly, currency="USD",
        )
        cta = t_email_body(locale, f"email.{ns}.body_cta")
        footer = t_email_body(locale, f"email.{ns}.body_footer")
    except KeyError as exc:
        logger.warning(
            "[renewal-scan] i18n key missing: %s", exc)
        return None

    html = (
        f"<p>{intro}</p>"
        f"<p>{price}</p>"
        f'<p><a href="{cta_url}" '
        f'style="display:inline-block;padding:12px 24px;'
        f'background:#0284C7;color:#fff;text-decoration:none;'
        f'border-radius:6px;font-weight:600;">{cta}</a></p>'
        f"<p>{footer}</p>"
    )

    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from":    EMAIL_FROM,
            "to":      to,
            "subject": subject,
            "html":    html,
        })
        return to
    except Exception as exc:  # noqa: BLE001
        logger.warning("[renewal-scan] email send failed: %s", exc)
        return None


# ═════════════════════ Scan core ═════════════════════════════════════
async def _scan_one_tenant(
    tenant: Dict[str, Any], now: datetime,
) -> Dict[str, int]:
    tid = tenant["id"]
    target_date = (now + timedelta(days=_MILESTONE_DAYS)).date().isoformat()

    scanned = alerts_emitted = alerts_deduped = 0
    emails_sent = auto_receipts_sent = 0

    cursor = db.warranty_contracts.find(
        {"tenant_id": tid, "status": "active"},
        {"_id": 0},
    )
    async for contract in cursor:
        end_iso = _date_only(contract.get("end_date"))
        if end_iso != target_date:
            continue
        # ``renewed_at`` or ``renewal_contract_id`` set means the
        # contract already got renewed — skip belt-and-braces even
        # though ``status`` should have flipped to "renewed" too.
        if contract.get("renewed_at") or contract.get("renewal_contract_id"):
            continue
        scanned += 1

        cid = contract.get("customer_id")
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tid}, {"_id": 0}) or {}
        renewal_kind = await _plan_renewal_kind(
            tid, contract.get("plan_id"))
        auto_renew = (renewal_kind == "auto")

        price_cents = int(round(
            float(contract.get("price_paid") or 0) * 100))
        expires_short = _short_date(contract.get("end_date"))
        plan_name = (contract.get("plan_name_snapshot")
                      or "maintenance plan")
        cname = (contract.get("customer_name_snapshot")
                  or cust.get("name") or cid)

        if auto_renew:
            title = (f"Renewal due: {cname} — {plan_name} "
                     f"(auto-renew)")
            body = (f"Auto-renews on {expires_short}. "
                    f"Confirmation will be sent.")
        else:
            title = f"Renewal due: {cname} — {plan_name}"
            body = (f"Agreement expires {expires_short} "
                    f"({_MILESTONE_DAYS} days). "
                    f"Renewal proposal emailed.")

        # Fire the email FIRST so ``email_sent_to`` lands in the
        # actor_context even on the first-ever insert. Emails are
        # dedup'd via the alert itself — if the alert was already
        # emitted a re-scan lands in the ``duplicate_key`` branch
        # of emit_alert and this coro returns early with no send.
        # (See dedup check below.)
        alert_key = f"renewal_due:agreement:{contract['id']}:30d"
        existing = await db.intelligence_alerts.find_one(
            {"tenant_id": tid, "alert_key": alert_key},
            {"_id": 1},
        )
        if existing:
            alerts_deduped += 1
            continue

        email_sent_to = await _send_renewal_email(
            contract=contract, customer=cust, tenant=tenant,
            auto_renew=auto_renew, now=now,
        )
        if email_sent_to:
            if auto_renew:
                auto_receipts_sent += 1
            else:
                emails_sent += 1

        actor_context = {
            "agreement_id":         contract["id"],
            "plan_id":              contract.get("plan_id"),
            "plan_name":            plan_name,
            "plan_kind":            contract.get("plan_kind_snapshot"),
            "monthly_amount_cents": price_cents,
            "expires_at":           contract.get("end_date"),
            "expires_at_short":     expires_short,
            "days_left":            _MILESTONE_DAYS,
            "auto_renew":           auto_renew,
            "email_sent_to":        email_sent_to,
        }
        inserted, _doc = await emit_alert(
            tid,
            category="renewal_due",
            severity="recommended",
            alert_key=alert_key,
            title=title,
            body=body,
            customer_id=cid,
            job_id=None,
            actor_context=actor_context,
        )
        if inserted:
            alerts_emitted += 1
        else:
            # Race: another worker inserted between our probe and
            # the emit. Count as dedup for accounting.
            alerts_deduped += 1

    return {
        "scanned_agreements":       scanned,
        "alerts_emitted":           alerts_emitted,
        "alerts_deduped":           alerts_deduped,
        "emails_sent":              emails_sent,
        "auto_renew_receipts_sent": auto_receipts_sent,
    }


async def run_renewal_scan(
    tenant_id: Optional[str] = None,
    now:       Optional[datetime] = None,
) -> Dict[str, Any]:
    """Run the 30-day renewal scan for one or all active tenants."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    tenants = await _iter_tenants(tenant_id)
    aggregate: Dict[str, Any] = {
        "tenant_id":              tenant_id,
        "scanned_agreements":     0,
        "alerts_emitted":         0,
        "alerts_deduped":         0,
        "emails_sent":            0,
        "auto_renew_receipts_sent": 0,
        "by_tenant":              {},
    }
    for t in tenants:
        summary = await _scan_one_tenant(t, ref)
        for k in ("scanned_agreements", "alerts_emitted",
                   "alerts_deduped", "emails_sent",
                   "auto_renew_receipts_sent"):
            aggregate[k] += summary[k]
        aggregate["by_tenant"][t["id"]] = summary
    if tenant_id and tenant_id in aggregate["by_tenant"]:
        aggregate.update(aggregate["by_tenant"][tenant_id])
        aggregate["by_tenant"] = {
            tenant_id: aggregate["by_tenant"][tenant_id],
        }
    return aggregate


async def run_renewal_scan_all_tenants() -> Dict[str, Any]:
    """APScheduler entry point."""
    try:
        result = await run_renewal_scan(tenant_id=None)
        logger.info(
            "[renewal-scan] scanned=%d emitted=%d deduped=%d "
            "emails=%d auto_receipts=%d tenants=%d",
            result["scanned_agreements"], result["alerts_emitted"],
            result["alerts_deduped"], result["emails_sent"],
            result["auto_renew_receipts_sent"],
            len(result["by_tenant"]),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("[renewal-scan] failed: %s", exc)
        return {"error": str(exc)}


# ═════════════════════ Resend helper (used by the "Resend renewal
# email" admin button) ════════════════════════════════════════════════
async def resend_renewal_email_for_contract(
    tenant_id: str, contract_id: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Manual resend of the renewal email for a specific contract.

    Callable from the admin UI's "Resend renewal email" row action.
    Does NOT re-emit the alert (dedup would eat it anyway) — this
    is email-only. Returns a small status dict for the UI toast.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    contract = await db.warranty_contracts.find_one(
        {"id": contract_id, "tenant_id": tenant_id}, {"_id": 0})
    if not contract:
        return {"ok": False, "reason": "contract_not_found"}
    if contract.get("status") != "active":
        return {"ok": False, "reason": "contract_inactive"}
    cust = await db.customers.find_one(
        {"id": contract.get("customer_id"),
         "tenant_id": tenant_id}, {"_id": 0}) or {}
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0}) or {}
    renewal_kind = await _plan_renewal_kind(
        tenant_id, contract.get("plan_id"))
    to = await _send_renewal_email(
        contract=contract, customer=cust, tenant=tenant,
        auto_renew=(renewal_kind == "auto"), now=ref,
    )
    return {"ok": bool(to), "sent_to": to,
            "auto_renew": renewal_kind == "auto"}
