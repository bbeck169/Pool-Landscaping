"""Feb 2026 · Stripe billing history → CRM sync.

Companion to ``services/stripe_customer_sync.py``. BYO-Stripe
migration flow: after the customer sync attaches Stripe.Customer
ids to CRM customers, this service imports the tenant's HISTORICAL
Stripe payments (charges), invoices, and subscriptions so the CRM
has parity with the prior CRM's billing timeline.

Design contract:
  * **Prereq**: the tenant must have at least one CRM customer with
    ``stripe_customer_id`` set. Otherwise every Stripe charge would
    be "unattached" and the import is worthless. Router translates
    to HTTP 400 with a helpful message.
  * **Idempotent** on every entity type — same ``stripe_charge_id`` /
    ``stripe_invoice_id`` / ``stripe_subscription_id`` on a second
    run is skipped (unique index guarantees + pre-write check).
  * **Never charges cards. Never mutates existing CRM records.**
    Only INSERTs into ``db.payments``, ``db.invoices``, and
    ``db.stripe_subscriptions``. Invoices minted here NEVER touch
    ``db.quotes`` (canonical) — they land in the ancillary
    ``db.invoices`` collection (matches the Homeworks importer
    pattern in ``services/homeworks_mcp/active_customers_importer.py``).
  * **Historical only** — no receipt fires, no dashboard-revenue
    recalc side effects, no email/SMS. Every write is silent.
  * **Rate limited** to 50 concurrent Stripe API calls (matches the
    customer sync — see ``_STRIPE_CONCURRENCY``).
  * **Charge → CRM invoice mapping** (ordered fallback):
      1. Stripe.Charge.payment_intent → matches a CRM quote/invoice
         with ``stripe_payment_intent_id`` set.
      2. Stripe.Charge.invoice → matches a Stripe.Invoice we already
         imported this run → whose ``crm_invoice_id`` we resolved.
      3. Amount + created_at within 48h of a CRM paid quote —
         low-precision fallback for tenants with pre-Stripe-metadata
         invoices.
      4. Otherwise "unattached" (parked to the customer, no
         invoice link).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.payments.stripe_charge import (
    _asdict,
    _init_api_key,
    _stripe,
    _to_thread,
    _UnconfiguredStripeError,
)

logger = logging.getLogger("stripe.billing_history_sync")

_STRIPE_CONCURRENCY = 50
_MATCH_WINDOW_HOURS = 48


# ─── Stripe iteration helpers ───────────────────────────────────────
async def _iter_stripe(list_fn, *, cutoff_ts: int,
                         limit_per_page: int = 100,
                         limit_total: Optional[int] = None):
    """Auto-paginate a Stripe ``.list`` endpoint filtered by
    ``created >= cutoff_ts``. Yields dicts. Respects ``limit_total``
    for tests (defaults to unlimited)."""
    yielded = 0
    starting_after: Optional[str] = None
    while True:
        params: Dict[str, Any] = {
            "limit": limit_per_page,
            "created": {"gte": cutoff_ts},
        }
        if starting_after:
            params["starting_after"] = starting_after
        page = _asdict(await _to_thread(list_fn, **params))
        data = page.get("data") or []
        if not data:
            return
        for row in data:
            yield _asdict(row)
            yielded += 1
            if limit_total is not None and yielded >= limit_total:
                return
        if not page.get("has_more"):
            return
        starting_after = data[-1].get("id")


# ─── Main entry ─────────────────────────────────────────────────────
async def sync_stripe_billing_history(
    *,
    tenant_id: str,
    actor_user_id: str,
    dry_run: bool = True,
    months_back: int = 24,
    include_subscriptions: bool = True,
    limit_total: Optional[int] = None,
    preview_sample_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Import Stripe charges + invoices + optionally subscriptions
    into the CRM. Returns a structured report.

    Feb 2026 · When ``dry_run=True`` we cap each entity type at
    ``preview_sample_size`` (default 100 charges + 50 invoices +
    25 subscriptions) so the preview HTTP request stays under the
    proxy 60s timeout on large tenants. The commit path
    (``dry_run=False``) still iterates the full roster.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    _init_api_key()  # fail-loud on missing key

    # ─── Prereq: at least one CRM customer with stripe_customer_id ─
    stripe_id_index: Dict[str, dict] = {}
    async for c in db.customers.find(
        {"tenant_id": tenant_id, "stripe_customer_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "stripe_customer_id": 1, "name": 1},
    ):
        stripe_id_index[c["stripe_customer_id"]] = c
    if not stripe_id_index:
        raise PrereqNotMetError(
            "No CRM customer has stripe_customer_id set. Run "
            "``POST /api/admin/migrations/sync-stripe-customers`` "
            "first — billing history needs the customer mapping.",
        )

    # ─── Time window ────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    cutoff_dt = now - timedelta(days=int(months_back) * 30)
    cutoff_ts = int(cutoff_dt.timestamp())

    # ─── Existing idempotency indexes ───────────────────────────────
    existing_charge_ids = {
        p["stripe_charge_id"]
        async for p in db.payments.find(
            {"tenant_id": tenant_id,
              "stripe_charge_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "stripe_charge_id": 1},
        )
    }
    existing_invoice_ids = {
        i["stripe_invoice_id"]
        async for i in db.invoices.find(
            {"tenant_id": tenant_id,
              "stripe_invoice_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "stripe_invoice_id": 1},
        )
    }
    existing_sub_ids: set = set()
    if include_subscriptions:
        existing_sub_ids = {
            s["stripe_subscription_id"]
            async for s in db.stripe_subscriptions.find(
                {"tenant_id": tenant_id},
                {"_id": 0, "stripe_subscription_id": 1},
            )
        }

    # ─── CRM invoice lookup indexes (for charge → invoice mapping) ─
    quote_by_pi: Dict[str, dict] = {}
    quote_by_amount_date: Dict[str, List[dict]] = {}  # key: cust_id:amount
    async for q in db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "customer_id": 1, "total": 1,
          "created_at": 1, "status": 1, "stripe_payment_intent_id": 1,
          "invoice_number": 1},
    ):
        pi = q.get("stripe_payment_intent_id")
        if pi:
            quote_by_pi[pi] = q
        # Amount-based bucket for low-precision fallback.
        if q.get("customer_id") and q.get("total") is not None:
            k = f"{q['customer_id']}:{q['total']}"
            quote_by_amount_date.setdefault(k, []).append(q)

    # ─── Report skeleton ────────────────────────────────────────────
    # Feb 2026 · When dry_run, cap each entity type at a sample size
    # so the preview HTTP call stays under the proxy 60s timeout.
    # Real commit runs (dry_run=False) always walk the full roster.
    _sample_charges = None
    _sample_invoices = None
    _sample_subs = None
    if dry_run:
        _default = preview_sample_size if preview_sample_size is not None else 100
        _sample_charges = _default
        _sample_invoices = max(1, _default // 2)  # 50 default
        _sample_subs = max(1, _default // 4)      # 25 default

    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "dry_run": bool(dry_run),
        "months_back": int(months_back),
        "include_subscriptions": bool(include_subscriptions),
        "cutoff_date": cutoff_dt.isoformat(),
        # Feb 2026 · preview-cap markers so the FE can render
        # "showing first N" hints when the roster is truncated.
        "preview_sample_size_charges": _sample_charges,
        "preview_sample_size_invoices": _sample_invoices,
        "preview_sample_size_subs": _sample_subs,
        "preview_capped_charges": False,
        "preview_capped_invoices": False,
        "preview_capped_subs": False,
        "matched_charges": 0,
        "unmatched_charges": 0,
        "charge_no_customer": 0,   # Stripe.Charge with no known CRM customer
        "skipped_dup_charges": 0,
        "created_payment_records": 0,
        "created_invoice_records": 0,
        "skipped_dup_invoices": 0,
        "matched_subscriptions": 0,
        "skipped_dup_subs": 0,
        "created_subscription_records": 0,
        "errors": [],
        "generated_at": now.isoformat(),
    }

    # ─── 1) Invoices first (so charge → invoice lookup benefits) ───
    invoice_id_to_crm: Dict[str, str] = {}
    _inv_seen = 0
    async for sinv in _iter_stripe(_stripe.Invoice.list, cutoff_ts=cutoff_ts,
                                     limit_total=limit_total):
        _inv_seen += 1
        if _sample_invoices is not None and _inv_seen > _sample_invoices:
            report["preview_capped_invoices"] = True
            break
        sinv_id = sinv.get("id")
        if not sinv_id:
            continue
        if sinv_id in existing_invoice_ids:
            report["skipped_dup_invoices"] += 1
            # Look up the CRM invoice we already imported for this
            # Stripe invoice so the charge mapping benefits.
            crm_row = await db.invoices.find_one(
                {"tenant_id": tenant_id, "stripe_invoice_id": sinv_id},
                {"_id": 0, "id": 1},
            )
            if crm_row:
                invoice_id_to_crm[sinv_id] = crm_row["id"]
            continue
        crm_cust = stripe_id_index.get(sinv.get("customer") or "")
        if not crm_cust:
            report["charge_no_customer"] += 1  # bucket doubles for invoice-no-customer
            continue
        new_id = uuid.uuid4().hex
        doc = {
            "id": new_id,
            "tenant_id": tenant_id,
            "customer_id": crm_cust["id"],
            "stripe_invoice_id": sinv_id,
            "stripe_customer_id": sinv.get("customer"),
            "stripe_payment_intent_id": sinv.get("payment_intent"),
            "invoice_number": sinv.get("number"),
            "total_cents": sinv.get("total"),
            "amount_paid_cents": sinv.get("amount_paid"),
            "currency": (sinv.get("currency") or "usd").lower(),
            "status": sinv.get("status"),
            "hosted_invoice_url": sinv.get("hosted_invoice_url"),
            "invoice_pdf": sinv.get("invoice_pdf"),
            "created_at": _epoch_to_iso(sinv.get("created")),
            "imported_from": "stripe_history",
            "imported_at": now.isoformat(),
        }
        if not dry_run:
            await db.invoices.insert_one(doc)
        report["created_invoice_records"] += 1
        invoice_id_to_crm[sinv_id] = new_id

    # ─── 2) Charges → payments ─────────────────────────────────────
    _ch_seen = 0
    async for sch in _iter_stripe(_stripe.Charge.list, cutoff_ts=cutoff_ts,
                                    limit_total=limit_total):
        _ch_seen += 1
        if _sample_charges is not None and _ch_seen > _sample_charges:
            report["preview_capped_charges"] = True
            break
        ch_id = sch.get("id")
        if not ch_id:
            continue
        if ch_id in existing_charge_ids:
            report["skipped_dup_charges"] += 1
            continue
        crm_cust = stripe_id_index.get(sch.get("customer") or "")
        if not crm_cust:
            report["charge_no_customer"] += 1
            continue
        # Charge → CRM invoice mapping (ordered fallback).
        crm_invoice_id: Optional[str] = None
        # 1) By payment_intent on canonical quote.
        pi = sch.get("payment_intent")
        if pi and pi in quote_by_pi:
            crm_invoice_id = quote_by_pi[pi]["id"]
        # 2) By Stripe.Invoice we just imported.
        if not crm_invoice_id:
            sinv_id = sch.get("invoice")
            if sinv_id and sinv_id in invoice_id_to_crm:
                crm_invoice_id = invoice_id_to_crm[sinv_id]
        # 3) By amount + created_at within 48h fallback.
        if not crm_invoice_id:
            crm_invoice_id = _match_by_amount_and_date(
                quote_by_amount_date, crm_cust["id"],
                sch.get("amount") or 0, sch.get("created") or 0,
            )
        matched = crm_invoice_id is not None
        pm_card = _asdict(sch.get("payment_method_details")) or {}
        card = _asdict(pm_card.get("card")) or {}
        pay = {
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "customer_id": crm_cust["id"],
            "invoice_id": crm_invoice_id,  # may be None
            "stripe_charge_id": ch_id,
            "stripe_payment_intent_id": pi,
            "stripe_customer_id": sch.get("customer"),
            "amount_cents": sch.get("amount") or 0,
            "currency": (sch.get("currency") or "usd").lower(),
            "card_brand": card.get("brand") or "",
            "card_last4": card.get("last4") or "",
            "status": sch.get("status") or "",
            "refunded": bool(sch.get("refunded")),
            "amount_refunded_cents": sch.get("amount_refunded") or 0,
            "created_at": _epoch_to_iso(sch.get("created")),
            "imported_from": "stripe_history",
            "imported_at": now.isoformat(),
            "matched": bool(matched),
        }
        if not dry_run:
            await db.payments.insert_one(pay)
        if matched:
            report["matched_charges"] += 1
        else:
            report["unmatched_charges"] += 1
        report["created_payment_records"] += 1

    # ─── 3) Subscriptions ──────────────────────────────────────────
    if include_subscriptions:
        try:
            _sub_seen = 0
            async for ssub in _iter_stripe(
                lambda **kw: _stripe.Subscription.list(status="all", **kw),
                cutoff_ts=cutoff_ts, limit_total=limit_total,
            ):
                _sub_seen += 1
                if _sample_subs is not None and _sub_seen > _sample_subs:
                    report["preview_capped_subs"] = True
                    break
                sub_id = ssub.get("id")
                if not sub_id:
                    continue
                if sub_id in existing_sub_ids:
                    report["skipped_dup_subs"] += 1
                    continue
                crm_cust = stripe_id_index.get(ssub.get("customer") or "")
                if not crm_cust:
                    continue
                doc = {
                    "id": uuid.uuid4().hex,
                    "tenant_id": tenant_id,
                    "customer_id": crm_cust["id"],
                    "stripe_subscription_id": sub_id,
                    "stripe_customer_id": ssub.get("customer"),
                    "status": ssub.get("status"),
                    "current_period_start": _epoch_to_iso(
                        ssub.get("current_period_start"),
                    ),
                    "current_period_end": _epoch_to_iso(
                        ssub.get("current_period_end"),
                    ),
                    "cancel_at_period_end": ssub.get("cancel_at_period_end"),
                    "canceled_at": _epoch_to_iso(ssub.get("canceled_at")),
                    "created_at": _epoch_to_iso(ssub.get("created")),
                    "imported_from": "stripe_history",
                    "imported_at": now.isoformat(),
                }
                if not dry_run:
                    await db.stripe_subscriptions.insert_one(doc)
                report["matched_subscriptions"] += 1
                report["created_subscription_records"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({
                "phase": "subscriptions",
                "reason": str(exc)[:200],
            })

    logger.info(
        "[stripe_billing_history] tenant=%s dry_run=%s matched=%d "
        "unmatched=%d no_cust=%d dup_charge=%d inv_new=%d dup_inv=%d "
        "subs_new=%d dup_subs=%d",
        tenant_id, dry_run,
        report["matched_charges"], report["unmatched_charges"],
        report["charge_no_customer"], report["skipped_dup_charges"],
        report["created_invoice_records"], report["skipped_dup_invoices"],
        report["created_subscription_records"], report["skipped_dup_subs"],
    )
    return report


# ─── Helpers ────────────────────────────────────────────────────────
class PrereqNotMetError(RuntimeError):
    """Raised when the billing history sync is invoked before the
    customer sync has attached any Stripe customer to a CRM
    customer. Router translates to HTTP 400."""


def _epoch_to_iso(ts: Any) -> Optional[str]:
    if ts in (None, 0, ""):
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _match_by_amount_and_date(
    index: Dict[str, List[dict]],
    customer_id: str,
    amount_cents: int,
    charge_created_epoch: int,
) -> Optional[str]:
    """Low-precision fallback: match a Stripe charge to the closest
    CRM invoice by (customer_id, total_cents) within ±48h of the
    charge timestamp. Returns the CRM invoice id or ``None``.

    ``total`` on the canonical CRM quote is stored in cents to match
    Stripe. When multiple candidates match, the closest by date wins.
    """
    if not customer_id or amount_cents == 0:
        return None
    key = f"{customer_id}:{amount_cents}"
    candidates = index.get(key) or []
    if not candidates:
        return None
    charge_dt = datetime.fromtimestamp(charge_created_epoch, tz=timezone.utc) \
        if charge_created_epoch else None
    if not charge_dt:
        # No date to compare — take the first candidate (last-write-wins).
        return candidates[0]["id"]
    window = timedelta(hours=_MATCH_WINDOW_HOURS)
    best: Optional[dict] = None
    best_delta: Optional[timedelta] = None
    for q in candidates:
        q_dt = _parse_created(q.get("created_at"))
        if not q_dt:
            continue
        delta = abs(q_dt - charge_dt)
        if delta > window:
            continue
        if best_delta is None or delta < best_delta:
            best = q
            best_delta = delta
    return best["id"] if best else None


def _parse_created(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        # ISO with or without TZ.
        s = str(v).replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
