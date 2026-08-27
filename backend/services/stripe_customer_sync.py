"""Feb 2026 · Stripe → CRM customer sync.

BYO-Stripe migration flow: when a tenant onboards from a prior CRM
that used their SAME Stripe account (Direct Charges — NOT a
Homeworks-owned Stripe Connect account), we sync the Stripe.Customer
roster onto the CRM customer roster so cards on file map to the
correct CRM doc and auto-billing continues without re-adding cards.

Design contract:
  * Match rule (ordered fallback):
      1. Stripe.Customer.email (lowercased) exact match to
         CRM.customer.email OR any CRM.customer.emails[].address.
      2. If no email match AND Stripe.Customer.phone present,
         E.164-normalized phone match against CRM.customer.phone
         (mobile primary) OR CRM.customer.mobiles[].number.
      3. Otherwise ``unmatched``.
  * Duplicate CRM emails → ``duplicate_email`` (skip; never guess).
  * Already-attached CRM (``stripe_customer_id`` set) → skip idempotently.
  * ``dry_run`` (default True) never writes to Mongo, never mutates
    Stripe. ``commit`` writes ``$set`` per matched CRM customer.
  * NEVER charges cards. NEVER stores PAN. Only stores ``pm_XXX``
    + card ``last4`` + card ``brand`` for display.
  * Rate limited to 50 concurrent outbound Stripe API calls
    (Stripe's soft limit is 100/sec; keep 2x headroom for the
    payments path running alongside the sync).
  * Audit-logged in ``db.stripe_sync_audit`` — one row per
    attachment / import / skip.

Reused from ``services/payments/stripe_charge.py``:
  * ``_init_api_key()`` — sets ``stripe.api_key`` + api_version per
    ``STRIPE_MODE`` (test/live).
  * ``_to_thread()`` — async-safe wrapper around blocking Stripe SDK.
  * ``_asdict()`` — v15-safe ``StripeObject → dict`` normalizer.
  * ``_UnconfiguredStripeError`` — fail-loud when the key is missing.
  * ``_stripe`` — the module-level SDK reference (respects test stubs).
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from config import db
from services.payments.stripe_charge import (
    _asdict,
    _init_api_key,
    _stripe,
    _to_thread,
    _UnconfiguredStripeError,
)

logger = logging.getLogger("stripe.customer_sync")

# ─── Rate-limit knob ────────────────────────────────────────────────
# Stripe's soft limit is 100 read requests / sec. We cap our
# concurrent Stripe calls at 50 so the payments path (charges,
# refunds, checkout) stays responsive during a big migration sync.
_STRIPE_CONCURRENCY = 50


# ─── Normalizers ────────────────────────────────────────────────────
def _norm_email(v: Optional[str]) -> str:
    return (v or "").strip().lower()


_DIGIT_RE = re.compile(r"\D+")


def _norm_phone(v: Optional[str]) -> str:
    """Reduce to digits then take the last 10 (US convention) so
    ``(602) 555-1234`` and ``+16025551234`` match. Same rule the
    Copilot importer uses — keeps parity across tenants."""
    if not v:
        return ""
    digits = _DIGIT_RE.sub("", str(v))
    return digits[-10:] if len(digits) >= 10 else digits


# ─── CRM roster indexes ─────────────────────────────────────────────
async def _load_crm_indexes(tenant_id: str) -> Tuple[
    Dict[str, List[dict]],
    Dict[str, List[dict]],
    Set[str],
]:
    """Return (email_index, phone_index, already_attached_stripe_ids)
    for the tenant's active customers. Each index maps a normalized
    key → list of matching customer docs (list handles duplicates).
    """
    email_index: Dict[str, List[dict]] = {}
    phone_index: Dict[str, List[dict]] = {}
    attached: Set[str] = set()
    cursor = db.customers.find(
        {"tenant_id": tenant_id, "is_active": {"$ne": False}},
        {
            "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
            "emails": 1, "mobiles": 1, "stripe_customer_id": 1,
        },
    )
    async for c in cursor:
        # Primary email + multi-contact emails.
        for e in [c.get("email")] + [
            m.get("address") for m in (c.get("emails") or [])
            if isinstance(m, dict)
        ]:
            k = _norm_email(e)
            if k:
                email_index.setdefault(k, []).append(c)
        # Primary phone + multi-contact mobiles.
        for p in [c.get("phone")] + [
            m.get("number") for m in (c.get("mobiles") or [])
            if isinstance(m, dict)
        ]:
            k = _norm_phone(p)
            if k:
                phone_index.setdefault(k, []).append(c)
        if c.get("stripe_customer_id"):
            attached.add(c["stripe_customer_id"])
    return email_index, phone_index, attached


# ─── Stripe roster pagination ───────────────────────────────────────
async def _iter_stripe_customers(limit: Optional[int] = None):
    """Yield Stripe customer dicts (with ``invoice_settings`` expanded
    for the default payment method). Uses the SDK's auto-pagination
    over ``stripe.Customer.list``. Stops after ``limit`` customers
    when provided (tests use limit=10 for speed)."""
    _init_api_key()
    yielded = 0
    starting_after: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"limit": 100}
        if starting_after:
            params["starting_after"] = starting_after
        page = await _to_thread(_stripe.Customer.list, **params)
        page = _asdict(page)
        data = page.get("data") or []
        if not data:
            return
        for cust in data:
            yield _asdict(cust)
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        if not page.get("has_more"):
            return
        starting_after = data[-1].get("id")


async def _fetch_default_payment_method(stripe_customer_id: str) -> Optional[dict]:
    """Return ``{id, brand, last4}`` for the customer's default
    payment method, or ``None`` if the customer has no card on file.
    Uses ``Customer.retrieve(expand=[...])`` so we don't need a
    second ``PaymentMethod.retrieve`` call — one round trip per
    matched customer.
    """
    try:
        cust = await _to_thread(
            _stripe.Customer.retrieve,
            stripe_customer_id,
            expand=["invoice_settings.default_payment_method"],
        )
    except Exception as exc:  # Stripe raises many shapes — swallow.
        logger.warning(
            "[stripe_sync] retrieve failed for %s: %s",
            stripe_customer_id, exc,
        )
        return None
    cust = _asdict(cust)
    inv = _asdict(cust.get("invoice_settings")) or {}
    pm = _asdict(inv.get("default_payment_method")) or {}
    if not pm.get("id"):
        return None
    card = _asdict(pm.get("card")) or {}
    return {
        "id": pm["id"],
        "brand": card.get("brand") or "",
        "last4": card.get("last4") or "",
    }


# ─── Main entry: preview + commit share this path ───────────────────
async def sync_stripe_customers(
    *,
    tenant_id: str,
    actor_user_id: str,
    dry_run: bool = True,
    import_unmatched: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Walk the Stripe customer roster, match against the tenant's
    CRM customers, and (when ``dry_run=False``) persist the
    attachments + audit rows. Returns a structured report.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    # Fail-loud on missing Stripe key BEFORE loading indexes so the
    # router can translate to HTTP 400 without side-effects.
    try:
        _init_api_key()
    except _UnconfiguredStripeError as exc:
        raise
    email_index, phone_index, attached = await _load_crm_indexes(tenant_id)
    sem = asyncio.Semaphore(_STRIPE_CONCURRENCY)
    now = datetime.now(timezone.utc)

    # ─── Counters + row lists ───────────────────────────────────────
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "dry_run": bool(dry_run),
        "import_unmatched": bool(import_unmatched),
        "scanned": 0,
        "attachable_count": 0,
        "already_attached_count": 0,
        "duplicate_email_count": 0,
        "unmatched_count": 0,
        "no_email_count": 0,
        "imported_new_count": 0,
        "attachments": [],  # {stripe_customer_id, customer_id, email, name, card}
        "duplicates": [],   # {stripe_customer_id, email, crm_matches: [names]}
        "unmatched": [],    # {stripe_customer_id, email, name}
        "errors": [],       # {stripe_customer_id, reason}
        "generated_at": now.isoformat(),
    }

    async def _process(scust: dict) -> None:
        async with sem:
            await _process_one(scust)

    async def _process_one(scust: dict) -> None:
        report["scanned"] += 1
        scust_id = scust.get("id") or ""
        semail = _norm_email(scust.get("email"))
        sphone = _norm_phone(scust.get("phone"))
        # Idempotency shortcut: if Stripe.id is already attached to
        # SOME CRM customer, skip without a retrieve call.
        if scust_id in attached:
            report["already_attached_count"] += 1
            return
        # No email + no phone → cannot match by identity alone.
        if not semail and not sphone:
            report["no_email_count"] += 1
            return
        # Match by email first, then phone.
        matches: List[dict] = []
        if semail:
            matches = list(email_index.get(semail) or [])
        if not matches and sphone:
            matches = list(phone_index.get(sphone) or [])
        if len(matches) > 1:
            # Multiple CRM rows with same email — never guess.
            report["duplicate_email_count"] += 1
            report["duplicates"].append({
                "stripe_customer_id": scust_id,
                "email": semail or None,
                "phone": sphone or None,
                "crm_match_names": [m.get("name") or "" for m in matches][:10],
            })
            return
        if not matches:
            if not semail:
                report["no_email_count"] += 1
                return
            report["unmatched_count"] += 1
            report["unmatched"].append({
                "stripe_customer_id": scust_id,
                "email": semail,
                "name": scust.get("name") or "",
                "phone": sphone or None,
            })
            return
        crm = matches[0]
        if crm.get("stripe_customer_id"):
            report["already_attached_count"] += 1
            return
        # Fetch card details (only for matched customers to keep
        # API calls proportional to attachments, not total roster).
        card_info = await _fetch_default_payment_method(scust_id)
        report["attachable_count"] += 1
        row: Dict[str, Any] = {
            "stripe_customer_id": scust_id,
            "customer_id": crm.get("id"),
            "customer_name": crm.get("name") or "",
            "email": semail or None,
            "card": card_info,
            "action": "will_attach" if dry_run else "attached",
        }
        report["attachments"].append(row)
        if dry_run:
            return
        # ─── Commit path ────────────────────────────────────────────
        sync_status = "attached" if card_info else "no_card"
        update: Dict[str, Any] = {
            "stripe_customer_id": scust_id,
            "stripe_sync_status": sync_status,
            "stripe_synced_at": now,
        }
        if card_info:
            update["stripe_default_payment_method_id"] = card_info["id"]
            update["stripe_card_brand"] = card_info["brand"]
            update["stripe_card_last4"] = card_info["last4"]
        await db.customers.update_one(
            {"id": crm["id"], "tenant_id": tenant_id},
            {"$set": update},
        )
        await db.stripe_sync_audit.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "customer_id": crm["id"],
            "stripe_customer_id": scust_id,
            "payment_method_id": card_info["id"] if card_info else None,
            "card_last4": card_info["last4"] if card_info else None,
            "card_brand": card_info["brand"] if card_info else None,
            "action": "attached",
            "reason": sync_status,
            "created_at": now,
        })
        # Update local index so a later Stripe customer with the same
        # email doesn't try to double-attach.
        attached.add(scust_id)
        crm["stripe_customer_id"] = scust_id

    async for scust in _iter_stripe_customers(limit=limit):
        await _process(scust)

    # ─── Optional: import unmatched Stripe customers as new CRM rows ─
    if import_unmatched and not dry_run and report["unmatched"]:
        for u in report["unmatched"]:
            new_id = str(uuid.uuid4())
            card_info = await _fetch_default_payment_method(u["stripe_customer_id"])
            doc = {
                "id": new_id,
                "tenant_id": tenant_id,
                "name": u.get("name") or u.get("email") or "Stripe Import",
                "email": u.get("email") or "",
                "phone": u.get("phone") or "",
                "source": "stripe_import",
                "is_active": True,
                "created_at": now,
                "stripe_customer_id": u["stripe_customer_id"],
                "stripe_sync_status": "attached" if card_info else "no_card",
                "stripe_synced_at": now,
            }
            if card_info:
                doc["stripe_default_payment_method_id"] = card_info["id"]
                doc["stripe_card_brand"] = card_info["brand"]
                doc["stripe_card_last4"] = card_info["last4"]
            await db.customers.insert_one(doc)
            await db.stripe_sync_audit.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "customer_id": new_id,
                "stripe_customer_id": u["stripe_customer_id"],
                "payment_method_id": card_info["id"] if card_info else None,
                "card_last4": card_info["last4"] if card_info else None,
                "card_brand": card_info["brand"] if card_info else None,
                "action": "imported",
                "reason": "unmatched_stripe_customer",
                "created_at": now,
            })
            report["imported_new_count"] += 1

    logger.info(
        "[stripe_sync] tenant=%s dry_run=%s scanned=%d attachable=%d "
        "already=%d duplicate=%d unmatched=%d no_email=%d imported_new=%d",
        tenant_id, dry_run, report["scanned"],
        report["attachable_count"], report["already_attached_count"],
        report["duplicate_email_count"], report["unmatched_count"],
        report["no_email_count"], report["imported_new_count"],
    )
    return report
