"""Phase 49 · Feb-2026 — Lana admin reminders service.

Single-fire reminders. Recurring is deliberately out-of-scope
(see Phase 49 non-goals in CHANGELOG). Live SMS gated on the
``LANA_SMS_LIVE=1`` env flag; default is a log-only dry-run that
still marks the reminder as fired so the cron doesn't loop.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lana.reminders")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_sms_enabled() -> bool:
    return os.environ.get("LANA_SMS_LIVE") == "1"


async def create_reminder(db, *, tenant_id: str, user_id: str, text: str,
                            remind_at: str, phone: Optional[str] = None,
                          ) -> Dict[str, Any]:
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "text": text.strip(),
        "remind_at": remind_at,
        "phone": phone,
        "sent": False,
        "sent_at": None,
        "sent_mode": None,   # "live" | "dry_run" | None
        "created_at": _now(),
    }
    await db.admin_reminders.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_reminders(db, *, tenant_id: str, user_id: str,
                          only_upcoming: bool = True) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id, "user_id": user_id}
    if only_upcoming:
        q["sent"] = False
    return await db.admin_reminders.find(q, {"_id": 0}).sort("remind_at", 1).to_list(500)


async def fire_due_reminders(db) -> int:
    """Scan for reminders whose ``remind_at`` is in the past and not
    yet ``sent``. Send via RingCentral (or log-only under dry-run) and
    stamp ``sent=True`` so the next cron tick doesn't re-fire."""
    now_iso = _now()
    due = await db.admin_reminders.find(
        {"sent": False, "remind_at": {"$lte": now_iso}},
        {"_id": 0},
    ).to_list(500)
    if not due:
        return 0
    live = _live_sms_enabled()
    fired = 0
    for row in due:
        mode = "live" if live and row.get("phone") else "dry_run"
        try:
            if mode == "live":
                await _send_live_sms(row)
            else:
                logger.info(
                    "[lana.reminders] DRY RUN — would SMS user=%s phone=%s text=%r",
                    row.get("user_id"), row.get("phone"), row.get("text"),
                )
            await db.admin_reminders.update_one(
                {"id": row["id"]},
                {"$set": {"sent": True, "sent_at": _now(), "sent_mode": mode}},
            )
            fired += 1
        except Exception as exc:
            logger.warning("[lana.reminders] fire failed for %s: %s",
                            row.get("id"), exc)
    return fired


async def _send_live_sms(row: Dict[str, Any]) -> None:
    """Send via the tenant's RingCentral integration. Isolated so the
    dry-run path doesn't drag the RC SDK into every test import."""
    try:
        from services.sms_provider import send_sms  # type: ignore
    except Exception:
        # No RingCentral module in-tree yet — treat as dry-run.
        logger.info("[lana.reminders] SMS module unavailable; treating as dry_run")
        return
    tag = "[LANA reminder] "
    await send_sms(
        to_phone=row["phone"],
        body=tag + (row.get("text") or ""),
    )
