"""Phase 12B · Feb 2026 — Stripe ↔ Customers cross-reference sync.

Ensures the CRM's ``customers.has_card_on_file`` derived state reflects
reality on Stripe:

* Backfill: link CRM customers to Stripe customers (via
  ``stripe_customer_id`` when present, or an exact-single email match
  when not) + refresh the cached card display fields.
* Ongoing: the ``payment_method.attached / .detached`` and
  ``customer.updated`` webhooks call ``sync_customer_from_stripe`` so
  state stays honest without a nightly cron.

Cached display fields (masked, non-secret only):
    customer.card_brand         # "visa", "mastercard", …
    customer.card_last4         # "4242"
    customer.card_exp_month     # 8
    customer.card_exp_year      # 2028
    customer.stripe_default_payment_method_id
    customer.saved_payment_methods_count

We NEVER store PANs, CVCs, or Stripe fingerprints. All state flows via
the Stripe API — no raw card data ever touches our DB.

The two admin-triggered entry points are ``run_stripe_customer_sync``
(real writes, ``dry_run=False``) and its ``dry_run=True`` sibling. Both
produce an identical report shape; only the persistence bit differs.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import now_iso


# ─── Stripe helpers ──────────────────────────────────────────────────
def _stripe():
    from services.stripe_client import get_stripe
    return get_stripe()


def _stripe_retry(fn, *args, attempts: int = 4, base_delay: float = 0.4,
                    **kwargs):
    """Small retry wrapper around Stripe API calls. Backs off on 429
    (RateLimitError) and network errors. Non-retryable errors surface
    immediately."""
    import stripe as _stripe_mod
    last_exc = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except _stripe_mod.error.RateLimitError as exc:
            last_exc = exc
            time.sleep(base_delay * (2 ** i))
        except _stripe_mod.error.APIConnectionError as exc:
            last_exc = exc
            time.sleep(base_delay * (2 ** i))
    if last_exc:
        raise last_exc


def _pm_card_display(pm: Any) -> Dict[str, Any]:
    """Extract the masked, non-secret display fields from a Stripe
    PaymentMethod. Never returns fingerprints or PAN-derived data."""
    card = None
    try:
        card = pm.card if hasattr(pm, "card") else (pm or {}).get("card")
    except Exception:
        card = None
    if not card:
        return {}
    if hasattr(card, "brand"):
        brand = card.brand
        last4 = card.last4
        em = card.exp_month
        ey = card.exp_year
    else:
        brand = card.get("brand")
        last4 = card.get("last4")
        em = card.get("exp_month")
        ey = card.get("exp_year")
    return {
        "card_brand": brand or None,
        "card_last4": last4 or None,
        "card_exp_month": int(em) if em else None,
        "card_exp_year": int(ey) if ey else None,
    }


def _default_pm_id_from_stripe_customer(sc: Any) -> Optional[str]:
    try:
        settings = sc.invoice_settings if hasattr(sc, "invoice_settings") \
            else (sc or {}).get("invoice_settings") or {}
        if hasattr(settings, "default_payment_method"):
            return settings.default_payment_method
        return settings.get("default_payment_method")
    except Exception:
        return None


# ─── Per-customer sync (shared by backfill + webhooks) ───────────────
async def sync_customer_from_stripe(customer: dict, *,
                                      dry_run: bool = False,
                                      stripe_customer_id: Optional[str] = None,
                                      ) -> Dict[str, Any]:
    """Refresh ``has_card_on_file`` + display fields for a single
    customer against Stripe. If ``stripe_customer_id`` is not passed,
    read it from ``customer.stripe_customer_id``.

    Returns a summary dict with:
      ``customer_id``, ``stripe_customer_id``, ``pm_count``,
      ``changed`` (bool), ``update_set`` (dict of fields that would/
      did change).

    Idempotent — a second call with unchanged Stripe state returns
    ``changed=False`` and issues zero writes.
    """
    sid = stripe_customer_id or customer.get("stripe_customer_id")
    if not sid:
        return {"customer_id": customer.get("id"),
                "stripe_customer_id": None,
                "pm_count": 0, "changed": False, "update_set": {}}
    stripe = _stripe()
    pms = _stripe_retry(stripe.PaymentMethod.list,
                          customer=sid, type="card", limit=100)
    data = list((pms or {}).get("data") if isinstance(pms, dict)
                else getattr(pms, "data", []) or [])
    pm_count = len(data)

    # Determine which PM to use for the display cache — prefer the
    # customer's Stripe-side default; fall back to the first listed PM.
    default_pm = None
    try:
        sc = _stripe_retry(stripe.Customer.retrieve, sid)
        default_pm_id = _default_pm_id_from_stripe_customer(sc)
        if default_pm_id:
            for pm in data:
                pid = pm.id if hasattr(pm, "id") else pm.get("id")
                if pid == default_pm_id:
                    default_pm = pm
                    break
    except Exception:
        default_pm_id = None
    if not default_pm and data:
        default_pm = data[0]
        default_pm_id = default_pm.id if hasattr(default_pm, "id") \
            else default_pm.get("id")

    display = _pm_card_display(default_pm) if default_pm else {
        "card_brand": None, "card_last4": None,
        "card_exp_month": None, "card_exp_year": None,
    }

    update_set: Dict[str, Any] = {
        "saved_payment_methods_count": pm_count,
        "stripe_default_payment_method_id": default_pm_id if pm_count else None,
        **display,
    }
    # Detect actual change vs the persisted doc so we can be a proper
    # no-op on the 2nd run.
    changed = any(customer.get(k) != v for k, v in update_set.items())
    if changed and not dry_run:
        update_set["updated_at"] = now_iso()
        await db.customers.update_one(
            {"id": customer["id"], "tenant_id": customer["tenant_id"]},
            {"$set": update_set},
        )
    return {
        "customer_id": customer.get("id"),
        "stripe_customer_id": sid,
        "pm_count": pm_count,
        "changed": changed,
        "update_set": update_set,
    }


# ─── Tenant-wide backfill ────────────────────────────────────────────
async def _match_stripe_customer_by_email(email: str) -> List[Any]:
    stripe = _stripe()
    resp = _stripe_retry(stripe.Customer.list, email=email, limit=3)
    return list((resp or {}).get("data") if isinstance(resp, dict)
                else getattr(resp, "data", []) or [])


async def run_stripe_customer_sync(tenant_id: str, *,
                                     dry_run: bool = False) -> Dict[str, Any]:
    """Cross-reference every CRM customer under ``tenant_id`` against
    Stripe. See module docstring for semantics.

    Returns a report dict with the following keys (past-tense on a
    real run, would_* on a dry run):

        tenant_id, dry_run, examined,
        linked / would_link                 [{customer_id, stripe_customer_id, email}]
        updated_card_flag / would_update_card_flag  [{customer_id, pm_count, brand, last4}]
        ambiguous_matches                   [{customer_id, email, stripe_ids:[...]}]
        skipped_no_contact                  int
        no_op                               int   (already in sync)
    """
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "dry_run": bool(dry_run),
        "examined": 0,
        "linked" if not dry_run else "would_link": [],
        ("updated_card_flag" if not dry_run
          else "would_update_card_flag"): [],
        "ambiguous_matches": [],
        "skipped_no_contact": 0,
        "no_op": 0,
        "started_at": now_iso(),
    }

    cursor = db.customers.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    )
    linked_key = "linked" if not dry_run else "would_link"
    upd_key = "updated_card_flag" if not dry_run else "would_update_card_flag"

    async for c in cursor:
        report["examined"] += 1
        sid = c.get("stripe_customer_id")
        email = (c.get("email") or "").strip().lower()

        if not sid and not email:
            report["skipped_no_contact"] += 1
            continue

        # Auto-link by email when no stripe_customer_id.
        if not sid:
            try:
                matches = await _match_stripe_customer_by_email(email)
            except Exception as exc:
                logger.warning(f"[phase12b] email lookup failed for "
                                f"{c.get('id')}: {exc}")
                continue
            if len(matches) == 0:
                continue
            if len(matches) > 1:
                report["ambiguous_matches"].append({
                    "customer_id": c["id"],
                    "customer_name": c.get("name"),
                    "email": email,
                    "stripe_ids": [
                        (m.id if hasattr(m, "id") else m.get("id"))
                        for m in matches
                    ],
                })
                continue
            m = matches[0]
            sid = m.id if hasattr(m, "id") else m.get("id")
            if not dry_run:
                await db.customers.update_one(
                    {"id": c["id"], "tenant_id": tenant_id},
                    {"$set": {"stripe_customer_id": sid,
                                "updated_at": now_iso()}},
                )
            report[linked_key].append({
                "customer_id": c["id"],
                "stripe_customer_id": sid,
                "email": email,
            })
            c["stripe_customer_id"] = sid  # so the following sync step sees it

        try:
            sync_res = await sync_customer_from_stripe(
                c, dry_run=dry_run, stripe_customer_id=sid,
            )
        except Exception as exc:
            logger.warning(f"[phase12b] pm sync failed for "
                            f"{c.get('id')}: {exc}")
            continue

        if sync_res["changed"]:
            us = sync_res["update_set"]
            report[upd_key].append({
                "customer_id": c["id"],
                "pm_count": sync_res["pm_count"],
                "brand": us.get("card_brand"),
                "last4": us.get("card_last4"),
                "exp_month": us.get("card_exp_month"),
                "exp_year": us.get("card_exp_year"),
            })
        else:
            report["no_op"] += 1

    # Persist last-sync stamp on the tenant (real runs only).
    if not dry_run:
        await db.tenants.update_one(
            {"id": tenant_id},
            {"$set": {"stripe_sync_last_run_at": now_iso()}},
        )
    report["finished_at"] = now_iso()
    return report


# ─── Ambiguous-match resolver ────────────────────────────────────────
async def link_customer_to_stripe(*, tenant_id: str,
                                    customer_id: str,
                                    stripe_customer_id: str) -> Dict[str, Any]:
    """Admin manually resolves an ambiguous email match. Verifies:
      * The Stripe customer exists.
      * Its email matches the CRM customer's email (case-insensitive).
    Then persists the linkage + immediately syncs card state.

    Raises HTTPException(400, ...) on any validation failure.
    """
    from fastapi import HTTPException  # local import to keep this
                                        # service module framework-agnostic
                                        # elsewhere.
    stripe = _stripe()
    crm = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not crm:
        raise HTTPException(404, "Customer not found")
    try:
        sc = _stripe_retry(stripe.Customer.retrieve, stripe_customer_id)
    except Exception:
        raise HTTPException(400, "stripe_customer_id not found on Stripe")
    stripe_email = (getattr(sc, "email", "") or "").lower()
    crm_email = (crm.get("email") or "").lower()
    if not crm_email:
        raise HTTPException(400, "CRM customer has no email to compare")
    if stripe_email != crm_email:
        raise HTTPException(
            400,
            f"email mismatch — CRM has {crm_email}, Stripe has {stripe_email}",
        )
    await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {"stripe_customer_id": stripe_customer_id,
                    "updated_at": now_iso()}},
    )
    crm["stripe_customer_id"] = stripe_customer_id
    sync = await sync_customer_from_stripe(crm)
    return {
        "ok": True,
        "customer_id": customer_id,
        "stripe_customer_id": stripe_customer_id,
        "sync": sync,
    }
