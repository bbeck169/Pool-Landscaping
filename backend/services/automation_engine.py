"""Communications Phase 3 · in-process automation engine (Feb 2026).

Zero-infra event bus that wires ``automation_rules`` (Phase 1) to real
domain events. Fanout is synchronous; delayed rules go through the
existing ``apscheduler`` instance. Every dispatch is journalled to
``automation_engine_events`` with a 24-hour TTL dedup key.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from config import db

logger = logging.getLogger(__name__)
_DEDUP_TTL_SECONDS = 24 * 60 * 60

# ── in-memory rule cache — {(tenant_id, trigger_event): [rule_doc, …]} ─
_RULES_INDEX: Dict[tuple, List[dict]] = {}
_INDEXED_ONCE = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


async def _ensure_indexes() -> None:
    try:
        await db.automation_engine_events.create_index(
            "dedup_key", unique=True, sparse=True,
        )
        await db.automation_engine_events.create_index(
            "fired_at_dt", expireAfterSeconds=_DEDUP_TTL_SECONDS,
        )
        await db.automation_engine_events.create_index(
            [("tenant_id", 1), ("fired_at", -1)],
        )
        await db.automation_engine_events.create_index(
            [("tenant_id", 1), ("automation_code", 1), ("fired_at", -1)],
        )
    except Exception as e:
        logger.warning(f"[automation_engine] index setup partial: {e}")


async def re_index_rules(tenant_id: Optional[str] = None) -> int:
    """Reload the in-memory index of active rules. Called at startup and
    from the automations CRUD endpoints after every write.

    System rules (``tenant_id=None`` + ``is_system=True``) are stored
    under the ``(None, trigger)`` key so ``emit()`` can fan them out to
    every tenant that has activated them.
    """
    global _RULES_INDEX, _INDEXED_ONCE
    if tenant_id:
        # Drop only the target tenant's slice (leave system slice intact).
        for k in [k for k in _RULES_INDEX if k[0] == tenant_id]:
            _RULES_INDEX.pop(k, None)
        q: Dict[str, Any] = {"active": True, "tenant_id": tenant_id}
        total = 0
        async for r in db.automation_rules.find(q, {"_id": 0}):
            key = (r.get("tenant_id"), r.get("trigger_event"))
            _RULES_INDEX.setdefault(key, []).append(r)
            total += 1
        return total

    # Full rebuild.
    _RULES_INDEX = {}
    q = {"active": True}
    total = 0
    async for r in db.automation_rules.find(q, {"_id": 0}):
        key = (r.get("tenant_id"), r.get("trigger_event"))
        _RULES_INDEX.setdefault(key, []).append(r)
        total += 1
    _INDEXED_ONCE = True
    return total


def _conditions_match(conditions: Optional[dict], payload: dict) -> bool:
    """Flat-key equality/contains match. Keys use dotted paths;
    condition value is either a scalar (exact match) or a dict
    ``{"contains": "..."}`` (substring match on stringified payload
    value). Missing conditions ≡ always-match.
    """
    if not conditions:
        return True
    for path, expected in conditions.items():
        parts = path.split(".")
        cur: Any = payload
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                cur = None
                break
        if isinstance(expected, dict) and "contains" in expected:
            if expected["contains"] not in str(cur or ""):
                return False
        else:
            if cur != expected:
                return False
    return True


async def _fire_rule(rule: dict, payload: dict, tenant_id: str,
                      entity_kind: str, entity_id: str,
                      customer_id: Optional[str]) -> str:
    """Dispatch a single rule. Returns the event status."""
    dedup_key = f"{tenant_id}::{rule['code']}::{entity_kind}::{entity_id}"
    now_dt = _now()
    event_doc = {
        "id": f"evt_{now_dt.timestamp():.6f}",
        "tenant_id": tenant_id,
        "automation_code": rule["code"],
        "trigger_event": rule["trigger_event"],
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "customer_id": customer_id,
        "communication_send_id": None,
        "error": None,
        "dedup_key": dedup_key,
        "fired_at": _iso(),
        "fired_at_dt": now_dt,
    }

    # Dedup — same rule + same entity within 24h skips.
    exists = await db.automation_engine_events.find_one(
        {"dedup_key": dedup_key}, {"_id": 1},
    )
    if exists:
        event_doc["status"] = "skipped_deduped"
        event_doc.pop("dedup_key", None)
        await db.automation_engine_events.insert_one(event_doc)
        return "skipped_deduped"

    if not _conditions_match(rule.get("trigger_conditions"), payload):
        event_doc["status"] = "skipped_conditions_not_met"
        event_doc.pop("dedup_key", None)
        await db.automation_engine_events.insert_one(event_doc)
        return "skipped_conditions_not_met"

    if not customer_id:
        event_doc["status"] = "skipped_no_customer"
        event_doc.pop("dedup_key", None)
        await db.automation_engine_events.insert_one(event_doc)
        return "skipped_no_customer"

    # Dispatch via the automation-engine entry point in the comms
    # router. Import locally to avoid a circular services↔routers graph.
    try:
        from routers.comms import deliver_one_by_ids
        send_row = await deliver_one_by_ids(
            tenant_id=tenant_id,
            template_code=rule["template_code"],
            channel=rule.get("channel") or "email",
            recipient_id=customer_id,
            extras=payload,
            automation_code=rule["code"],
        )
        if not send_row:
            event_doc["status"] = "failed"
            event_doc["error"] = "delivery helper returned None (missing template or customer)"
            await db.automation_engine_events.insert_one(event_doc)
            return "failed"
        event_doc["communication_send_id"] = send_row.get("id")
        event_doc["status"] = "sent" if send_row.get("status") in ("sent", "mocked") else "failed"
        if event_doc["status"] == "failed":
            event_doc["error"] = send_row.get("error") or "delivery status not sent"
        # Keep dedup_key on failure so a broken template/provider does
        # not re-fire the same rule for the same entity every request
        # inside the 24h TTL window. Admins can manually re-fire via
        # ``POST /comms/automations/{code}/test-fire``.
        await db.automation_engine_events.insert_one(event_doc)
        # Bump last_fired_at / fire_count on the rule doc.
        await db.automation_rules.update_one(
            {"code": rule["code"], "tenant_id": rule.get("tenant_id")},
            {"$set": {"last_fired_at": _iso()},
             "$inc": {"fire_count": 1}},
        )
        return event_doc["status"]
    except Exception as e:
        logger.exception(f"[automation_engine] dispatch failed: {e}")
        event_doc["status"] = "failed"
        event_doc["error"] = str(e)[:400]
        event_doc.pop("dedup_key", None)
        try:
            await db.automation_engine_events.insert_one(event_doc)
        except Exception:
            pass
        return "failed"


async def emit(trigger_event: str, payload: dict, tenant_id: str,
                entity_kind: str = "", entity_id: str = "",
                customer_id: Optional[str] = None) -> List[str]:
    """Fanout a domain event to every matching active rule for the
    tenant. Returns per-rule status strings for observability. Never
    raises — hooks in domain code must not become failure points.
    """
    global _INDEXED_ONCE
    try:
        if not _INDEXED_ONCE:
            await _ensure_indexes()
            await re_index_rules()
        # Tenant-owned rules + activated system rules (tenant_id=None).
        tenant_rules = list(_RULES_INDEX.get((tenant_id, trigger_event), []))
        system_rules = list(_RULES_INDEX.get((None, trigger_event), []))
        rules = tenant_rules + system_rules
        if not rules:
            return []
        outcomes: List[str] = []
        for r in rules:
            delay = int(r.get("send_delay_minutes") or 0)
            if delay > 0:
                # Schedule via apscheduler if available; else fire now.
                try:
                    from services import scheduler as _sched  # optional
                    _sched.schedule_once(
                        _fire_rule, delay_seconds=delay * 60,
                        args=[r, payload, tenant_id, entity_kind,
                              entity_id, customer_id],
                    )
                    outcomes.append("scheduled")
                    continue
                except Exception:
                    pass
            outcomes.append(
                await _fire_rule(r, payload, tenant_id, entity_kind,
                                  entity_id, customer_id),
            )
        return outcomes
    except Exception as e:
        logger.warning(f"[automation_engine.emit] {trigger_event} failed: {e}")
        return []


# ═════════════════════════════════════════════════════════════════════
# Daily sweeps — invoice.overdue / customer.birthday / customer.anniversary
# ═════════════════════════════════════════════════════════════════════

async def sweep_invoice_overdue() -> int:
    """Emit ``invoice.overdue`` for every unpaid invoice past due_date.

    Invoices live in the ``quotes`` collection (``doc_type='invoice'``);
    an invoice is overdue when ``payment_status`` is not ``paid`` and
    ``due_date`` (ISO YYYY-MM-DD) is strictly before today's UTC date.
    """
    today = _now().date().isoformat()
    n = 0
    async for inv in db.quotes.find(
        {"doc_type": "invoice",
         "payment_status": {"$ne": "paid"},
         "due_date": {"$lt": today}},
        {"_id": 0},
    ):
        await emit(
            "invoice.overdue",
            {"invoice": inv, "customer": {"id": inv.get("customer_id")}},
            tenant_id=inv.get("tenant_id") or "",
            entity_kind="invoice", entity_id=inv.get("id") or "",
            customer_id=inv.get("customer_id"),
        )
        n += 1
    return n


async def _sweep_date_field(trigger: str, field: str) -> int:
    today = _now()
    mm_dd = f"{today.month:02d}-{today.day:02d}"
    n = 0
    async for c in db.customers.find({field: {"$exists": True, "$ne": None}},
                                       {"_id": 0}):
        raw = str(c.get(field) or "")
        # accepts "YYYY-MM-DD" and "MM-DD" and "MM/DD/YYYY"
        norm = raw.replace("/", "-")
        parts = norm.split("-")
        m = d = None
        if len(parts) >= 3 and len(parts[0]) == 4:  # YYYY-MM-DD
            m, d = parts[1], parts[2][:2]
        elif len(parts) >= 3:                        # MM-DD-YYYY
            m, d = parts[0], parts[1]
        elif len(parts) == 2:
            m, d = parts[0], parts[1]
        if not m or not d:
            continue
        if f"{int(m):02d}-{int(d):02d}" != mm_dd:
            continue
        await emit(
            trigger, {"customer": c}, tenant_id=c.get("tenant_id") or "",
            entity_kind="customer", entity_id=c.get("id") or "",
            customer_id=c.get("id"),
        )
        n += 1
    return n


async def sweep_customer_birthday() -> int:
    return await _sweep_date_field("customer.birthday", "birthday")


async def sweep_customer_anniversary() -> int:
    return await _sweep_date_field("customer.anniversary", "customer_since")


def register_daily_sweeps(scheduler) -> None:
    """Attach the three daily sweeps to the existing apscheduler
    instance. No-op if scheduler is None."""
    if scheduler is None:
        return
    from apscheduler.triggers.cron import CronTrigger

    # Feb-2026 · P1 asyncio-in-thread fix.
    #
    # The prior ``_wrap`` returned a sync ``_runner`` that called
    # ``asyncio.get_event_loop()``. APScheduler's ``AsyncIOScheduler``
    # invokes sync callables on a worker thread with no event loop →
    # ``RuntimeError: There is no current event loop in thread``. Hand
    # the coroutine functions to the scheduler directly instead; it
    # awaits them on its own loop. Mirrors the Phase-49 pattern in
    # ``reminder_cron.py`` and the review_scraper remediation.

    try:
        scheduler.add_job(sweep_invoice_overdue,
                           CronTrigger(hour=9, minute=0),
                           id="automation.invoice_overdue",
                           replace_existing=True)
        scheduler.add_job(sweep_customer_birthday,
                           CronTrigger(hour=8, minute=0),
                           id="automation.customer_birthday",
                           replace_existing=True)
        scheduler.add_job(sweep_customer_anniversary,
                           CronTrigger(hour=8, minute=5),
                           id="automation.customer_anniversary",
                           replace_existing=True)
        logger.info("[automation_engine] daily sweeps registered "
                    "(invoice.overdue, customer.birthday, customer.anniversary)")
    except Exception as e:
        logger.warning(f"[automation_engine] scheduler registration failed: {e}")
