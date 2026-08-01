"""Phase 18 · Per-Tech Inventory Alerts + Real-time / Daily Low-Stock Fan-out.

Scope (locked by user 2026-08-01 decision matrix):
  * Auto-seed 8 core pool chemicals into ``db.inventory_items`` with
    ``is_seeded_chemical=True``, ``sku="P18-<slug>"``,
    ``department="pool"``, and ``reorder_point=10``.
    – Idempotent: only NEW inserts on subsequent runs. Existing tuned
      ``reorder_point`` values are NEVER overwritten. Rows that already
      exist by name are patched in-place to attach ``sku`` +
      ``is_seeded_chemical`` + ``department`` (but not the threshold).
  * Real-time hook: called from
    ``routers/inventory.decrement_from_service_report()`` after every
    decrement. Any item whose ``current_qty`` crosses at-or-below the
    reorder_point fans out ONCE per 24h dedup window
    (``inventory_items.low_stock_notified_at``) through THREE channels
    simultaneously:
        1) in-app bell (``db.notifications`` via ``services.notifications.emit``)
        2) Slack (per-tenant ``inventory_alert_settings.slack_webhook_url``,
           falls back to env ``INVENTORY_SLACK_WEBHOOK_URL``)
        3) Email (Resend via ``services.notifications.emit`` — same fan-out)
  * Daily cron at ``INVENTORY_CRON_HOUR_UTC`` (default 06:00 UTC —
    offset from Phase 5b 07:00, Phase 5c 08:00, Phase 7 hourly:05,
    Phase 8 hourly:10, Phase 17 03:00). Scans every tenant, emits for
    any low-stock SKU that hasn't been notified in the last 24h.
  * Quiet hours: if the tenant has ``quiet_hours_utc`` set on
    ``inventory_alert_settings`` and the current UTC hour falls within
    the window, the fan-out is deferred to the next cron tick (real-
    time hooks respect it too).
  * Nullable thresholds: rows with ``reorder_point is None`` are
    NEVER alerted on. Rows with ``reorder_point <= 0`` remain valid
    (0-threshold = "alert only when fully out").

Cost data is NEVER referenced here — this module is thresholds-only.
The cost report lives in ``routers/inventory_reports.py``.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from config import db, logger
from utils import new_id, now_iso


# ══════════════════════════════════════════════════════════════════
# Seed catalog — 8 core pool chemicals per user decision.
# ══════════════════════════════════════════════════════════════════
SEEDED_CHEMICALS: List[Dict[str, Any]] = [
    {"slug": "liquid_chlorine",  "name": "Liquid Chlorine",   "unit": "gal",  "department": "pool"},
    {"slug": "chlorine_tabs",    "name": "Chlorine Tablets",  "unit": "tabs", "department": "pool"},
    {"slug": "muriatic_acid",    "name": "Muriatic Acid",     "unit": "gal",  "department": "pool"},
    {"slug": "shock",            "name": "Cal-Hypo Shock",    "unit": "lbs",  "department": "pool"},
    {"slug": "soda_ash",         "name": "Soda Ash",          "unit": "lbs",  "department": "pool"},
    {"slug": "cyanuric_acid",    "name": "Cyanuric Acid",     "unit": "lbs",  "department": "pool"},
    {"slug": "pool_salt",        "name": "Pool Salt",         "unit": "lbs",  "department": "pool"},
    {"slug": "algaecide",        "name": "Algaecide",         "unit": "gal",  "department": "pool"},
]

DEFAULT_REORDER_POINT = 10.0
DEDUP_WINDOW_HOURS = 24


# ══════════════════════════════════════════════════════════════════
# Seed logic
# ══════════════════════════════════════════════════════════════════
async def seed_chemicals_for_tenant(tenant_id: str) -> Dict[str, int]:
    """Idempotent per-tenant seed.

    Behaviour per user decision 2026-08-01:
      * If an inventory row already exists with matching ``sku`` OR the
        chemical name (case-insensitive), we PATCH it to attach
        ``sku=P18-<slug>``, ``is_seeded_chemical=True``,
        ``department=pool``. We do NOT touch its
        ``reorder_point`` (respecting admin-tuned thresholds).
      * If no matching row exists, INSERT a fresh row with
        ``reorder_point=10`` and ``current_qty=0``.
    """
    inserted = 0
    patched = 0
    for chem in SEEDED_CHEMICALS:
        sku = f"P18-{chem['slug']}"
        existing = await db.inventory_items.find_one(
            {"tenant_id": tenant_id,
             "$or": [
                 {"sku": sku},
                 {"is_seeded_chemical": True, "sku": sku},
                 # Case-insensitive name match — catches Phase 23 _STARTER
                 # rows that pre-exist without an sku.
                 {"name": {"$regex": f"^{_escape_regex(chem['name'])}$",
                           "$options": "i"}},
             ]},
            {"_id": 0, "id": 1, "reorder_point": 1, "sku": 1,
             "is_seeded_chemical": 1, "department": 1},
        )
        if existing:
            update: Dict[str, Any] = {"updated_at": now_iso()}
            if not existing.get("is_seeded_chemical"):
                update["is_seeded_chemical"] = True
            if not existing.get("sku"):
                update["sku"] = sku
            if not existing.get("department"):
                update["department"] = chem["department"]
            if len(update) > 1:
                await db.inventory_items.update_one(
                    {"id": existing["id"], "tenant_id": tenant_id},
                    {"$set": update},
                )
                patched += 1
            continue

        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": chem["name"],
            "category": "chemical",
            "unit": chem["unit"],
            "sku": sku,
            "current_qty": 0.0,
            "reorder_point": DEFAULT_REORDER_POINT,
            "reorder_qty": DEFAULT_REORDER_POINT,
            "unit_cost": 0.0,
            "supplier": "",
            "location": "",
            "notes": "",
            "is_seeded_chemical": True,
            "department": chem["department"],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        try:
            await db.inventory_items.insert_one(doc)
            inserted += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[inventory_alerts] seed skip {sku}: {e}")
    return {"inserted": inserted, "patched": patched}


async def seed_chemicals_all_tenants() -> Dict[str, Any]:
    total_inserted = 0
    total_patched = 0
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(5000)
    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        r = await seed_chemicals_for_tenant(tid)
        total_inserted += r["inserted"]
        total_patched += r["patched"]
    return {"tenants": len(tenants), "inserted": total_inserted,
            "patched": total_patched}


def _escape_regex(s: str) -> str:
    import re
    return re.escape(s)


# ══════════════════════════════════════════════════════════════════
# Threshold + quiet hours + dedup helpers
# ══════════════════════════════════════════════════════════════════
def should_alert(item: Dict[str, Any]) -> bool:
    """Return True iff the item is at-or-below its reorder_point AND
    ``reorder_point`` is not None. Null thresholds are opt-out (per
    user decision — do NOT alert on null)."""
    rp = item.get("reorder_point")
    if rp is None:
        return False
    try:
        cur = float(item.get("current_qty") or 0)
        rp_val = float(rp)
    except (TypeError, ValueError):
        return False
    return cur <= rp_val


def _is_in_dedup_window(item: Dict[str, Any]) -> bool:
    last = item.get("low_stock_notified_at")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return False
    now = datetime.now(timezone.utc)
    return (now - last_dt) < timedelta(hours=DEDUP_WINDOW_HOURS)


async def _is_in_quiet_hours(tenant_id: str) -> bool:
    settings = await db.inventory_alert_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "quiet_hours_utc": 1},
    ) or {}
    qh = settings.get("quiet_hours_utc")
    if not qh or not isinstance(qh, dict):
        return False
    start = qh.get("start_hour")
    end = qh.get("end_hour")
    if start is None or end is None:
        return False
    try:
        start = int(start) % 24
        end = int(end) % 24
    except (TypeError, ValueError):
        return False
    hour = datetime.now(timezone.utc).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # wraps midnight (e.g. 22 → 06)
    return hour >= start or hour < end


# ══════════════════════════════════════════════════════════════════
# Slack helper — plain webhook POST, injectable for tests.
# ══════════════════════════════════════════════════════════════════
async def _default_slack_post(webhook_url: str,
                              payload: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(webhook_url, json=payload)
        return {"ok": 200 <= r.status_code < 300, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:180]}


def _build_slack_payload(tenant_name: str,
                         items: List[Dict[str, Any]]) -> Dict[str, Any]:
    lines = [f"*⚠️ Low-stock alert · {tenant_name}*",
             f"{len(items)} SKU{'s' if len(items) != 1 else ''} at or below reorder point:"]
    for it in items[:15]:
        cur = it.get("current_qty", 0)
        rp = it.get("reorder_point", 0)
        oos = " · *OUT OF STOCK*" if float(cur or 0) <= 0 else ""
        lines.append(f"• *{it.get('name')}* — {cur} {it.get('unit') or ''} "
                     f"(reorder at {rp}){oos}")
    if len(items) > 15:
        lines.append(f"…and {len(items) - 15} more")
    return {"text": "\n".join(lines)}


# ══════════════════════════════════════════════════════════════════
# Core notify — real-time + cron entry points share this.
# ══════════════════════════════════════════════════════════════════
async def check_and_notify_low_stock(
    tenant_id: str,
    item_ids: Optional[Iterable[str]] = None,
    *,
    source: str = "real_time",
    slack_post=_default_slack_post,
    force: bool = False,
) -> Dict[str, Any]:
    """Scan low-stock items and fan out to all three channels once
    per 24h dedup window.

    Args:
        tenant_id: tenant scope.
        item_ids: restrict scan to these ``inventory_items.id`` values.
            When ``None``, all items in the tenant are scanned.
        source: audit tag written into the notification ``source_ref``.
        slack_post: injectable Slack webhook POST (test hook).
        force: if True, skip the 24h dedup window (used by admin
            "resend now" workflow — not exposed via UI yet).

    Returns a summary dict.
    """
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "id": 1, "name": 1, "business_name": 1},
    ) or {}
    tenant_name = tenant.get("name") or tenant.get("business_name") or "Business"

    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if item_ids:
        ids = [i for i in item_ids if i]
        if not ids:
            return {"scanned": 0, "notified": 0, "deferred_quiet_hours": False}
        q["id"] = {"$in": ids}
    rows = await db.inventory_items.find(q, {"_id": 0}).to_list(5000)

    low = [r for r in rows if should_alert(r)]
    if not low:
        return {"scanned": len(rows), "notified": 0, "deferred_quiet_hours": False}

    quiet = await _is_in_quiet_hours(tenant_id)
    if quiet and source == "real_time":
        # Defer to daily cron — real-time hook never wakes techs up at 3am.
        return {"scanned": len(rows), "notified": 0,
                "deferred_quiet_hours": True, "low_stock_count": len(low)}

    # Apply dedup (unless forced or cron in quiet-hours re-scan mode).
    to_notify = low if force else [r for r in low if not _is_in_dedup_window(r)]
    if not to_notify:
        return {"scanned": len(rows), "notified": 0,
                "deferred_quiet_hours": False, "deduped": len(low)}

    # ── 1) Bell + Email fan-out via unified notifications engine.
    #    Emits to every admin/owner/super_admin in the tenant. Per-user
    #    channel prefs (email/push/bell) are honoured downstream by
    #    ``services.notifications.emit()``.
    try:
        from services.notifications import enqueue_for_tenant_admins
        titles = ", ".join(x.get("name") or "?" for x in to_notify[:5])
        more = f" (+{len(to_notify) - 5} more)" if len(to_notify) > 5 else ""
        body_lines = []
        for r in to_notify[:10]:
            body_lines.append(
                f"• {r.get('name')} — {r.get('current_qty')} "
                f"{r.get('unit') or ''} (reorder at {r.get('reorder_point')})"
            )
        await enqueue_for_tenant_admins(
            tenant_id=tenant_id,
            kind="inventory_low_stock",
            title=f"Low stock: {titles}{more}",
            body="\n".join(body_lines) or "Items below reorder point.",
            href="/admin/inventory",
            priority="high",
            source_ref={"kind": "inventory_low_stock",
                        "source": source,
                        "item_ids": [r["id"] for r in to_notify]},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[inventory_alerts] bell/email fan-out failed: {e}")

    # ── 2) Slack fan-out.
    settings = await db.inventory_alert_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "slack_webhook_url": 1},
    ) or {}
    slack_url = settings.get("slack_webhook_url") or \
        os.environ.get("INVENTORY_SLACK_WEBHOOK_URL") or ""
    slack_status: Dict[str, Any] = {"sent": False}
    if slack_url:
        payload = _build_slack_payload(tenant_name, to_notify)
        r = await slack_post(slack_url, payload)
        slack_status = {"sent": bool(r.get("ok")),
                        "status": r.get("status"),
                        "error": r.get("error")}
    else:
        slack_status = {"sent": False, "error": "slack_not_configured"}

    # ── 3) Stamp dedup window on notified rows.
    stamp = now_iso()
    await db.inventory_items.update_many(
        {"tenant_id": tenant_id,
         "id": {"$in": [r["id"] for r in to_notify]}},
        {"$set": {"low_stock_notified_at": stamp}},
    )

    # ── 4) Audit trail row for reporting.
    await db.inventory_alert_events.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "source": source,
        "item_ids": [r["id"] for r in to_notify],
        "item_names": [r.get("name") for r in to_notify],
        "slack_sent": slack_status.get("sent"),
        "slack_error": slack_status.get("error"),
        "created_at": stamp,
    })

    return {
        "scanned": len(rows),
        "notified": len(to_notify),
        "deferred_quiet_hours": False,
        "slack": slack_status,
        "notified_item_ids": [r["id"] for r in to_notify],
    }


# ══════════════════════════════════════════════════════════════════
# Cron entry — daily digest across all tenants.
# ══════════════════════════════════════════════════════════════════
async def run_daily_low_stock_scan() -> Dict[str, Any]:
    """Called by APScheduler at ``INVENTORY_CRON_HOUR_UTC`` (default 6)."""
    tenants = await db.tenants.find(
        {"active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(5000)
    total = {"tenants": len(tenants), "notified": 0, "deferred": 0}
    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        try:
            r = await check_and_notify_low_stock(tid, source="cron")
            total["notified"] += int(r.get("notified") or 0)
            if r.get("deferred_quiet_hours"):
                total["deferred"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[inventory_alerts] cron tenant {tid} failed: {e}")
    logger.info(f"[inventory_alerts] daily scan complete: {total}")
    return total
