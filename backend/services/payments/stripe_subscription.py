"""Phase B4 · Feb-2026 — Stripe subscription CRUD service.

Backs the ``/api/subscriptions`` router. Reads AND writes the
``stripe_subscriptions`` mirror ONLY (``db.subscriptions`` is a
read-only Lumino-era legacy artifact — see B3 §E).

Every helper in this module:
  * Filters + writes with an explicit ``tenant_id`` — cross-tenant
    access is silently 404'd upstream, never leaked.
  * Stamps ``metadata.crm_tenant_id`` + ``metadata.crm_customer_id``
    on every Stripe object so future webhook fan-in can resolve
    ownership.
  * Passes a mode-aware ``idempotency_key`` on create so a network
    retry doesn't double-subscribe.

Cache: prices list is memoised for 5 min (in-process, per-worker
best-effort — the fallback fetch is one API call so a colder
worker is fine).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.payments.stripe_charge import (
    _asdict,
    _init_api_key,
    _mode,
    _stripe,
    _to_thread,
    db,
)


logger = logging.getLogger("stripe_subscription")


# ── In-process price cache (5-minute TTL) ────────────────────────
_PRICES_CACHE_TTL_SEC = 300
_prices_cache: Dict[str, Any] = {"ts": 0.0, "rows": None, "mode": ""}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sub_from_stripe(stripe_sub: Any) -> Dict[str, Any]:
    """Flatten a Stripe.Subscription into the canonical mirror shape."""
    d = _asdict(stripe_sub)
    def _epoch(v):
        if not v:
            return None
        try:
            return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            return None
    return {
        "status": d.get("status") or "unknown",
        "current_period_start": _epoch(d.get("current_period_start")),
        "current_period_end": _epoch(d.get("current_period_end")),
        "cancel_at_period_end": bool(d.get("cancel_at_period_end")),
        "canceled_at": _epoch(d.get("canceled_at")),
        "created_at": _epoch(d.get("created")) or _now_iso(),
        "updated_at": _now_iso(),
    }


# ── Price enrichment helpers ─────────────────────────────────────
_PRICE_META_KEYS = (
    "price_id",
    "price_product_name",
    "price_amount_cents",
    "price_currency",
    "price_interval",
    "price_interval_count",
)


def _extract_price_meta(stripe_sub: Any) -> Dict[str, Any]:
    """Pull enriched price fields from a Stripe.Subscription.

    Expects the caller to have passed
    ``expand=["items.data.price.product"]`` so ``product`` is a
    dict, not a bare id. Falls back gracefully when the expand
    wasn't set — leaves ``price_product_name=None`` and lets the
    async backfill fill in the gap later.
    """
    d = _asdict(stripe_sub) if not isinstance(stripe_sub, dict) else stripe_sub
    items = ((d.get("items") or {}).get("data") or [])
    if not items:
        return {}
    price = items[0].get("price") if isinstance(items[0], dict) else None
    if not price:
        return {}
    p = _asdict(price) if not isinstance(price, dict) else price
    recurring = p.get("recurring") or {}
    product = p.get("product")
    prod_name = None
    if isinstance(product, dict):
        prod_name = product.get("name")
    return {
        "price_id": p.get("id"),
        "price_product_name": prod_name,
        "price_amount_cents": p.get("unit_amount"),
        "price_currency": (p.get("currency") or "usd"),
        "price_interval": (recurring.get("interval") if isinstance(recurring, dict) else None),
        "price_interval_count": (
            (recurring.get("interval_count") if isinstance(recurring, dict) else None) or 1
        ),
    }


async def _enrich_price_from_id(price_id: str) -> Dict[str, Any]:
    """Fetch a Stripe Price by id with product expanded — used by
    the webhook handler + the backfill script when the incoming
    payload didn't carry the expanded object."""
    if not price_id:
        return {}
    try:
        _init_api_key()
        p = await _to_thread(_stripe.Price.retrieve, price_id, expand=["product"])
        pd = _asdict(p)
        product = pd.get("product") or {}
        recurring = pd.get("recurring") or {}
        return {
            "price_id": pd.get("id"),
            "price_product_name": product.get("name") if isinstance(product, dict) else None,
            "price_amount_cents": pd.get("unit_amount"),
            "price_currency": (pd.get("currency") or "usd"),
            "price_interval": recurring.get("interval") if isinstance(recurring, dict) else None,
            "price_interval_count": (recurring.get("interval_count") if isinstance(recurring, dict) else None) or 1,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe_subscription] price enrich failed for %s: %s", price_id, exc)
        return {"price_id": price_id}


def format_plan_label(row: Dict[str, Any]) -> str:
    """Render ``Pool Pro — $9.99/month`` (or fallbacks). Pure
    string formatting — used by the router response layer + the
    frontend as a fallback if the field is server-provided."""
    if not isinstance(row, dict):
        return ""
    name = row.get("price_product_name") or "Custom plan"
    amount_cents = row.get("price_amount_cents")
    currency = (row.get("price_currency") or "usd").upper()
    interval = row.get("price_interval")
    interval_count = int(row.get("price_interval_count") or 1)
    if amount_cents is None:
        return name
    dollars = float(amount_cents) / 100.0
    # Format the money — drop trailing .00 for readability.
    money = f"${dollars:,.2f}"
    if money.endswith(".00"):
        money = money[:-3]
    if currency != "USD":
        money = f"{money} {currency}"
    if not interval:
        return f"{name} — {money}"
    if interval_count == 1:
        return f"{name} — {money}/{interval}"
    return f"{name} — {money} every {interval_count} {interval}s"


async def _ensure_stripe_customer(
    *, tenant_id: str, customer_id: str,
) -> Dict[str, Any]:
    """Return the CRM customer doc, creating a Stripe Customer if
    the CRM row lacks a ``stripe_customer_id``. Mirrors the pattern
    used in ``stripe_charge._create_fresh_stripe_customer``."""
    _init_api_key()
    row = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not row:
        raise ValueError("customer_not_found")
    if row.get("stripe_customer_id"):
        return row
    stripe_cust = await _to_thread(
        _stripe.Customer.create,
        email=row.get("email") or None,
        name=row.get("name") or None,
        metadata={
            "crm_customer_id": customer_id,
            "crm_tenant_id": tenant_id,
            "stripe_mode": _mode(),
        },
        idempotency_key=f"cust_create:{_mode()}:{tenant_id}:{customer_id}",
    )
    new_id = _asdict(stripe_cust).get("id") or stripe_cust["id"]
    await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {"stripe_customer_id": new_id}},
    )
    row["stripe_customer_id"] = new_id
    return row


async def create_subscription(
    *,
    tenant_id: str,
    customer_id: str,
    price_id: str,
    quantity: int = 1,
    payment_method_id: Optional[str] = None,
    trial_days: int = 0,
    cancel_at_period_end: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    idempotency_suffix: Optional[str] = None,
) -> Dict[str, Any]:
    """Create + mirror a Stripe subscription."""
    _init_api_key()
    cust = await _ensure_stripe_customer(tenant_id=tenant_id, customer_id=customer_id)
    stripe_customer_id = cust["stripe_customer_id"]

    # Set default PM if the caller supplied one.
    if payment_method_id:
        await _to_thread(
            _stripe.Customer.modify,
            stripe_customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

    sub_meta = {
        "crm_tenant_id": tenant_id,
        "crm_customer_id": customer_id,
        "stripe_mode": _mode(),
    }
    if isinstance(metadata, dict):
        # Caller-supplied metadata layered on top but reserved keys stay ours.
        for k, v in metadata.items():
            if k in ("crm_tenant_id", "crm_customer_id", "stripe_mode"):
                continue
            sub_meta[k] = v

    idem = (
        f"create_sub:{_mode()}:{tenant_id}:{customer_id}:{price_id}"
        + (f":{idempotency_suffix}" if idempotency_suffix else "")
    )

    kwargs: Dict[str, Any] = {
        "customer": stripe_customer_id,
        "items": [{"price": price_id, "quantity": int(quantity or 1)}],
        "metadata": sub_meta,
        "cancel_at_period_end": bool(cancel_at_period_end),
        "idempotency_key": idem,
        # Feb-2026 · price enrichment — expand so the response
        # carries the product name + amount + interval and the
        # mirror row can be populated without an extra API call.
        "expand": ["items.data.price.product"],
    }
    if trial_days and int(trial_days) > 0:
        kwargs["trial_period_days"] = int(trial_days)

    stripe_sub = await _to_thread(_stripe.Subscription.create, **kwargs)
    sub_dict = _asdict(stripe_sub)
    sub_id = sub_dict.get("id")
    if not sub_id:
        raise ValueError("stripe_subscription_id_missing")

    # Immediate mirror upsert so the UI doesn't wait for the webhook.
    now = _now_iso()
    set_doc = _sub_from_stripe(stripe_sub)
    set_doc["webhook_source"] = "app_create"
    # Feb-2026 · price enrichment — pull enriched price/product
    # fields out of the expanded Stripe response.
    price_meta = _extract_price_meta(stripe_sub)
    # ``created_at`` is `$setOnInsert`-only (first-write wins for
    # the creation timestamp). Pop from ``set_doc`` so we don't
    # write the same path under both ``$setOnInsert`` and ``$set``.
    created_at_val = set_doc.pop("created_at", None) or now
    insert_doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "stripe_subscription_id": sub_id,
        "stripe_customer_id": stripe_customer_id,
        "created_at": created_at_val,
    }
    set_payload = {
        **set_doc,
        "price_id": price_id,
        "quantity": int(quantity or 1),
        **price_meta,
    }
    await db.stripe_subscriptions.update_one(
        {"stripe_subscription_id": sub_id},
        {"$setOnInsert": insert_doc,
         "$set": set_payload},
        upsert=True,
    )
    mirror = await _fetch_mirror(tenant_id=tenant_id, sub_id=sub_id)
    return mirror or {**insert_doc, **set_doc,
                       "formatted_plan_label": format_plan_label({**insert_doc, **set_payload})}


async def _fetch_mirror(*, tenant_id: str, sub_id: str) -> Optional[Dict[str, Any]]:
    row = await db.stripe_subscriptions.find_one(
        {"tenant_id": tenant_id, "stripe_subscription_id": sub_id},
        {"_id": 0},
    )
    if row is not None:
        # Feb-2026 · price enrichment — stamp the humanised label
        # so every response carries a display-ready plan string.
        row["formatted_plan_label"] = format_plan_label(row)
    return row


async def update_subscription(
    *,
    tenant_id: str,
    sub_id: str,
    price_id: Optional[str] = None,
    quantity: Optional[int] = None,
    cancel_at_period_end: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Modify a subscription. Returns None if the mirror row is
    missing for this tenant (caller should raise 404)."""
    _init_api_key()
    mirror = await _fetch_mirror(tenant_id=tenant_id, sub_id=sub_id)
    if not mirror:
        return None

    kwargs: Dict[str, Any] = {}
    if price_id or quantity is not None:
        # Retrieve current item id to modify in place (single-item
        # subscriptions — the common case).
        current = await _to_thread(_stripe.Subscription.retrieve, sub_id)
        cd = _asdict(current)
        items = ((cd.get("items") or {}).get("data") or [])
        if not items:
            raise ValueError("subscription_has_no_items")
        first_item_id = items[0].get("id")
        item_patch: Dict[str, Any] = {"id": first_item_id}
        if price_id:
            item_patch["price"] = price_id
        if quantity is not None:
            item_patch["quantity"] = int(quantity)
        kwargs["items"] = [item_patch]

    if cancel_at_period_end is not None:
        kwargs["cancel_at_period_end"] = bool(cancel_at_period_end)

    if isinstance(metadata, dict) and metadata:
        # Preserve reserved keys.
        reserved = ("crm_tenant_id", "crm_customer_id", "stripe_mode")
        merged = {k: v for k, v in metadata.items() if k not in reserved}
        merged.update({
            "crm_tenant_id": tenant_id,
            "crm_customer_id": mirror.get("customer_id") or "",
            "stripe_mode": _mode(),
        })
        kwargs["metadata"] = merged

    # Feb-2026 · price enrichment — always expand so a price
    # change surfaces the new product name / amount / interval in
    # the response and we can refresh the mirror without another
    # API round trip.
    kwargs["expand"] = ["items.data.price.product"]

    stripe_sub = await _to_thread(_stripe.Subscription.modify, sub_id, **kwargs)
    set_doc = _sub_from_stripe(stripe_sub)
    set_doc.pop("created_at", None)  # first-write wins
    set_doc["webhook_source"] = "app_update"
    if price_id:
        set_doc["price_id"] = price_id
    if quantity is not None:
        set_doc["quantity"] = int(quantity)
    # Refresh enriched price fields when price changes (or on every
    # modify — the payload is already expanded so it's free).
    price_meta = _extract_price_meta(stripe_sub)
    if price_meta:
        set_doc.update(price_meta)
    await db.stripe_subscriptions.update_one(
        {"stripe_subscription_id": sub_id, "tenant_id": tenant_id},
        {"$set": set_doc},
    )
    return await _fetch_mirror(tenant_id=tenant_id, sub_id=sub_id)


async def cancel_subscription(
    *,
    tenant_id: str,
    sub_id: str,
    immediate: bool = False,
) -> Optional[Dict[str, Any]]:
    """Cancel at period end (default) or immediately. Returns None
    on cross-tenant / missing row."""
    _init_api_key()
    mirror = await _fetch_mirror(tenant_id=tenant_id, sub_id=sub_id)
    if not mirror:
        return None

    if immediate:
        stripe_sub = await _to_thread(_stripe.Subscription.delete, sub_id)
    else:
        stripe_sub = await _to_thread(
            _stripe.Subscription.modify, sub_id,
            cancel_at_period_end=True,
        )
    set_doc = _sub_from_stripe(stripe_sub)
    set_doc.pop("created_at", None)  # first-write wins
    set_doc["webhook_source"] = "app_cancel_immediate" if immediate else "app_cancel_period_end"
    await db.stripe_subscriptions.update_one(
        {"stripe_subscription_id": sub_id, "tenant_id": tenant_id},
        {"$set": set_doc},
    )
    return await _fetch_mirror(tenant_id=tenant_id, sub_id=sub_id)


async def list_subscriptions(
    *,
    tenant_id: str,
    customer_id: Optional[str] = None,
    status: str = "all",
    limit: int = 50,
    skip: int = 0,
) -> Dict[str, Any]:
    """List mirror rows filtered by tenant + optional customer/status."""
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        q["customer_id"] = customer_id
    if status and status != "all":
        q["status"] = status
    total = await db.stripe_subscriptions.count_documents(q)
    cursor = (
        db.stripe_subscriptions.find(q, {"_id": 0})
        .sort("created_at", -1)
        .skip(int(skip)).limit(int(limit))
    )
    rows = [r async for r in cursor]
    # Feb-2026 · price enrichment — stamp the pre-computed label so
    # the client renders the humanised copy without duplicating
    # the formatter. Falls back gracefully for rows that haven't
    # been backfilled yet (label uses whatever fields are present).
    for r in rows:
        r["formatted_plan_label"] = format_plan_label(r)
    return {"total": total, "rows": rows}


async def list_prices() -> List[Dict[str, Any]]:
    """Return active Stripe prices (with product expanded).

    Cached in-process for 5 minutes per Stripe mode.
    """
    _init_api_key()
    mode = _mode()
    now = time.time()
    if (
        _prices_cache["rows"] is not None
        and _prices_cache["mode"] == mode
        and (now - _prices_cache["ts"]) < _PRICES_CACHE_TTL_SEC
    ):
        return _prices_cache["rows"]

    stripe_prices = await _to_thread(
        _stripe.Price.list,
        active=True, limit=100, expand=["data.product"],
    )
    data = _asdict(stripe_prices).get("data") or []
    rows: List[Dict[str, Any]] = []
    for p in data:
        pd = _asdict(p) if hasattr(p, "get") is False else p
        product = pd.get("product") or {}
        prod_name = (
            product.get("name") if isinstance(product, dict) else None
        ) or ""
        rows.append({
            "id": pd.get("id"),
            "unit_amount": pd.get("unit_amount"),
            "currency": pd.get("currency"),
            "recurring": pd.get("recurring"),
            "nickname": pd.get("nickname"),
            "product_id": (product.get("id") if isinstance(product, dict) else product),
            "product_name": prod_name,
        })
    _prices_cache.update({"rows": rows, "ts": now, "mode": mode})
    return rows


def invalidate_prices_cache() -> None:
    """Test helper — clear the in-process price cache."""
    _prices_cache.update({"rows": None, "ts": 0.0, "mode": ""})
